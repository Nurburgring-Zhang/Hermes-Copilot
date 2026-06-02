#!/usr/bin/env python3
"""
微信公众号采集器 v3 — 独立Playwright扫码+API采集
==================================================
不依赖wechat-mp-mcp包，直接通过微信公众号后台API采集。

流程:
  1. Playwright打开 mp.weixin.qq.com 扫码登录
  2. 获取cookie + token
  3. 使用公众号后台 searchbiz + appmsg API 采集文章

格林主人最高指令：
  采高质量公众号文章，必须稳定50+条/次
"""

import json, re, time, hashlib, urllib.request, sys, os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import List, Dict, Optional, Tuple

HERMES = Path("/home/administrator/.hermes")
DB_PATH = HERMES / "intelligence.db"
COOKIE_FILE = HERMES / "scripts" / "collectors" / "wechat-mp-mcp" / "mp_cookies.json"
LOG_FILE = HERMES / "logs" / "wechat_mp_direct.log"
TZ = timezone(timedelta(hours=8))

def log(msg):
    ts = datetime.now(TZ).strftime("%H:%M:%S")
    line = f"[{ts}] [WXv3] {msg}"
    print(line)
    LOG_FILE.parent.mkdir(exist_ok=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")

# ========== 格林主人偏好公众号 ==========
ACCOUNTS = [
    # AI/大模型
    "机器之心", "量子位", "新智元", "36氪", "虎嗅APP",
    "DeepTech深科技", "硅星人", "AI科技评论", "极客公园",
    "爱范儿", "品玩", "钛媒体", "雷锋网",
    # 技术/开发者
    "InfoQ", "CSDN", "OSC开源社区", "前端之巅",
    "阿里技术", "腾讯技术", "美团技术团队", "字节跳动技术团队",
    # 军事/国际
    "局座召忠", "观察者网", "环球网", "参考消息",
    # 汽车
    "电动星球", "42号车库", "汽车之家",
    # 财经/商业
    "晚点LatePost", "财经网", "第一财经",
]

# ========== 搜索关键词 ==========
SEARCH_KEYWORDS = [
    "AI", "大模型", "人工智能", "ChatGPT", "OpenAI", 
    "科技", "芯片", "华为", "特斯拉",
    "新能源汽车", "自动驾驶", "机器人",
    "军事", "国际", "手机",
]


def playwright_login() -> Optional[Dict]:
    """使用Playwright打开微信公众平台扫码登录，返回cookies"""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        log("❌ 需要playwright: pip install playwright && playwright install chromium")
        return None

    login_url = "https://mp.weixin.qq.com/"
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)  # 需要有显示器的环境
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0"
        )
        page = context.new_page()
        page.goto(login_url)
        
        log("📱 请在打开的浏览器中扫码登录微信公众平台")
        log("⏳ 等待登录...最长5分钟")
        
        try:
            page.wait_for_url("https://mp.weixin.qq.com/cgi-bin/home*", timeout=300000)
        except:
            log("❌ 登录超时")
            browser.close()
            return None
        
        log("✅ 登录成功!")
        time.sleep(2)
        
        # 获取cookies
        cookies = context.cookies()
        browser.close()
        
        # 提取关键cookie
        cookie_dict = {}
        for c in cookies:
            cookie_dict[c['name']] = c['value']
        
        # 构建cookie字符串
        cookie_str = "; ".join([f"{k}={v}" for k, v in cookie_dict.items()])
        
        # 从页面获取token
        token = ""
        page.goto("https://mp.weixin.qq.com/cgi-bin/home")
        content = page.content()
        token_match = re.search(r'token=(\d+)', content)
        if token_match:
            token = token_match.group(1)
        
        result = {
            "cookies": cookie_str,
            "token": token,
            "cookie_dict": cookie_dict,
            "timestamp": datetime.now(TZ).isoformat(),
        }
        
        # 保存到文件
        COOKIE_FILE.parent.mkdir(parents=True, exist_ok=True)
        COOKIE_FILE.write_text(json.dumps(result, ensure_ascii=False, indent=2))
        log(f"💾 Cookies已保存到 {COOKIE_FILE}")
        
        return result


def load_cookies() -> Optional[Dict]:
    """从文件加载已保存的cookie"""
    if COOKIE_FILE.exists():
        try:
            data = json.loads(COOKIE_FILE.read_text())
            ts = datetime.fromisoformat(data.get("timestamp", "2000-01-01"))
            hours = (datetime.now(TZ) - ts).total_seconds() / 3600
            if hours > 2:
                log(f"⚠️ Cookies已过期({hours:.0f}小时前)，需要重新扫码")
                return None
            log(f"✅ 加载已保存的Cookies ({hours:.1f}小时前)")
            return data
        except:
            return None
    return None


def fetch_mp_api(url, cookie_data: Dict) -> Optional[str]:
    """带认证的微信公众平台API请求"""
    cookies = cookie_data.get("cookies", "")
    token = cookie_data.get("token", "")
    
    if token and "token=" not in url:
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}token={token}"
    
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0",
        "Cookie": cookies,
        "Referer": "https://mp.weixin.qq.com/",
    })
    
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        log(f"API请求失败: {e}")
        return None


def search_account(account_name: str, cookie_data: Dict) -> List[Dict]:
    """
    搜索公众号并获取文章列表
    使用微信公众平台后台的searchbiz和appmsg API
    """
    articles = []
    
    # 步骤1: 搜索公众号获取fakeid
    search_url = (
        f"https://mp.weixin.qq.com/cgi-bin/searchbiz?"
        f"action=search_biz&begin=0&count=5&query={urllib.request.quote(account_name)}"
    )
    
    resp = fetch_mp_api(search_url, cookie_data)
    if not resp:
        return articles
    
    try:
        data = json.loads(resp)
        biz_list = data.get("list", [])
        if not biz_list:
            log(f"  未找到公众号: {account_name}")
            return articles
        
        fakeid = biz_list[0].get("fakeid", "")
        nickname = biz_list[0].get("nickname", "")
        log(f"  找到: {nickname} (fakeid={fakeid[:10]}...)")
        
        # 步骤2: 获取该公众号的文章
        article_url = (
            f"https://mp.weixin.qq.com/cgi-bin/appmsg?"
            f"action=list_ex&begin=0&count=10&fakeid={fakeid}&type=9"
        )
        
        resp2 = fetch_mp_api(article_url, cookie_data)
        if not resp2:
            return articles
        
        data2 = json.loads(resp2)
        article_list = data2.get("app_msg_list", [])
        
        for art in article_list:
            articles.append({
                "title": art.get("title", ""),
                "content": art.get("digest", ""),
                "url": art.get("link", ""),
                "author": nickname,
                "published_at": datetime.fromtimestamp(art.get("create_time", 0)).strftime("%Y-%m-%d %H:%M:%S"),
                "source_type": "wechat_mp_api",
                "hot_score": art.get("total_view_count", 0) or 0,
                "platform": "wechat_mp",
                "source": "sogou_wechat",
            })
        
        log(f"  → 获取 {len(article_list)} 篇文章")
        
    except Exception as e:
        log(f"  解析失败 {account_name}: {e}")
    
    return articles


def save_articles(articles: List[Dict]) -> Tuple[int, int]:
    """保存到数据库"""
    import sqlite3
    
    if not articles:
        return 0, 0
    
    db = sqlite3.connect(str(DB_PATH))
    saved = 0
    total = len(articles)
    
    for art in articles:
        if not art.get("url") or not art.get("title"):
            continue
        
        url_hash = hashlib.md5(art["url"].encode()).hexdigest()
        exists = db.execute(
            "SELECT 1 FROM raw_intelligence WHERE url_hash=?", (url_hash,)
        ).fetchone()
        
        if exists:
            continue
        
        now = datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")
        try:
            db.execute("""
                INSERT INTO raw_intelligence 
                (title, content, url, source, platform, author, collected_at, published_at,
                 hot_score, source_type, url_hash)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                art.get("title", "")[:200],
                (art.get("content", "") or "")[:2000],
                art.get("url", "")[:500],
                art.get("source", "sogou_wechat"),
                art.get("platform", "wechat_mp"),
                art.get("author", "")[:50],
                now,
                art.get("published_at", now),
                art.get("hot_score", 0),
                art.get("source_type", "wechat_mp_api"),
                url_hash,
            ))
            saved += 1
        except:
            continue
    
    db.commit()
    db.close()
    return saved, total


def collect_wechat_mp_articles():
    """
    主采集函数：自动扫码登录(如需) + 采集30个公众号文章
    """
    log("=" * 60)
    log("🚀 微信公众号采集器 v3 启动")
    log("=" * 60)
    
    # 尝试加载已有cookie
    cookie_data = load_cookies()
    
    if not cookie_data:
        log("🔑 需要扫码登录微信公众平台")
        cookie_data = playwright_login()
        if not cookie_data:
            log("❌ 无法登录，采集终止")
            return 0, 0, 0
    
    total_articles = 0
    total_saved = 0
    total_accounts = 0
    
    for acc in ACCOUNTS:
        articles = search_account(acc, cookie_data)
        if articles:
            saved, total = save_articles(articles)
            total_saved += saved
            total_articles += total
            total_accounts += 1
        
        time.sleep(1.5)  # API限速，避免被封
    
    log(f"✅ 采集完成: {total_accounts}个公众号, {total_articles}条, 新保存{total_saved}条")
    return total_saved, total_articles, total_accounts


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="微信公众平台独立采集器")
    parser.add_argument("--login", action="store_true", help="仅扫码登录")
    parser.add_argument("--force-login", action="store_true", help="强制重新扫码登录")
    args = parser.parse_args()
    
    if args.force_login:
        COOKIE_FILE.unlink(missing_ok=True)
        collect_wechat_mp_articles()
    elif args.login:
        playwright_login()
    else:
        collect_wechat_mp_articles()
