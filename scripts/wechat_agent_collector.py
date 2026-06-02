#!/usr/bin/env python3
"""
微信公众号文章采集器 — 使用 agent-browser 浏览器自动化采集搜狗微信搜索结果
====================================================================

通过 agent-browser 浏览器自动化工具（headless Chromium），访问搜狗微信搜索
(https://weixin.sogou.com/)，使用 25 个关键词搜索公众号文章，
提取标题、URL、发布时间、摘要，直接写入 intelligence.db。

技术方案：
  1. subprocess 调用 agent-browser CLI 命令链式操作
  2. 先访问搜狗微信首页获取 Cookie，再用搜索 URL 获取结果
  3. 用 JS console 执行提取逻辑，解析 JSON 结果
  4. 调用 is_collect_filtered() 进行黑名单过滤
  5. 写入 raw_intelligence 表（platform='sogou_wechat', source_type='browser'）

使用方式：
  python3 ~/.hermes/scripts/wechat_agent_collector.py

已知限制：
  - 搜狗微信有反爬验证码（CAPTCHA），首次使用大概率会遇到
  - 解决方案：使用 --profile 参数指定 Chrome 用户数据目录以持久化 Cookie
  - 建议先用带 UI 的浏览器手动访问一次 https://weixin.sogou.com/ 完成验证
  - 之后使用 --profile 指向该浏览器用户数据目录即可自动复用 Cookie

环境变量：
  AGENT_BROWSER_PATH    - agent-browser 二进制路径（默认自动检测）
  AGENT_BROWSER_PROFILE - Chrome profile 路径，用于持久化 Cookie 绕过验证码
                          （例如：/home/user/.config/chromium/Default）
  DEBUG                 - 设为 1 可输出更多调试信息

输出：
  - 标准输出显示进度和结果
  - 采集到的文章写入 ~/.hermes/intelligence.db 的 raw_intelligence 表
  - 遇到验证码时会在 /tmp/sogou_captcha_*.png 保存截图
"""

import subprocess
import sys
import os
import re
import time
import json
import hashlib
from datetime import datetime
from pathlib import Path
from urllib.parse import quote, urlparse, urlunparse

# ─── 路径配置 ─────────────────────────────────────────────────────

HERMES_HOME = Path("/home/administrator/.hermes")
AGENT_BROWSER_PATH = os.environ.get(
    "AGENT_BROWSER_PATH",
    str(HERMES_HOME / "hermes-agent/node_modules/agent-browser/bin/agent-browser-linux-x64")
)
DB_PATH = HERMES_HOME / "intelligence.db"
DEBUG = os.environ.get("DEBUG", "0") == "1"

# ─── 25 个搜索关键词（覆盖格林主人方向） ───────────────────────────

SEARCH_KEYWORDS = [
    "AI大模型", "ChatGPT", "新能源汽车", "特斯拉", "比亚迪",
    "手机评测", "iPhone", "华为手机", "小米", "芯片",
    "UFC", "格斗", "NBA", "军事", "国防",
    "中美关系", "摄影技巧", "人像摄影", "Rust", "编程",
    "开源项目", "GitHub", "机器人", "太空探索", "SpaceX",
]


# ─── 工具函数 ─────────────────────────────────────────────────────

def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def debug(msg):
    if DEBUG:
        log(f"DEBUG: {msg}")


def url_hash(url):
    return hashlib.sha256(url.encode()).hexdigest()[:32]


# ─── agent-browser 执行封装 ──────────────────────────────────────

def ab(args, timeout=30, retries=1):
    """
    运行 agent-browser 命令，返回 (stdout, returncode)
    支持自动重试
    """
    cmd = [AGENT_BROWSER_PATH]

    profile_path = os.environ.get("AGENT_BROWSER_PROFILE")
    if profile_path:
        cmd.extend(["--profile", profile_path])

    cmd.extend(args)

    env = {**os.environ, "AGENT_BROWSER_JSON": "1"}

    for attempt in range(retries + 1):
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True,
                timeout=timeout, env=env
            )
            if result.returncode == 0:
                return result.stdout, 0
            # 非零返回时检查是否是有意义的错误
            stderr = result.stderr or ""
            if "Missing X server" in stderr or "platform failed to initialize" in stderr:
                debug(f"X server issue detected")
            return result.stdout, result.returncode
        except subprocess.TimeoutExpired:
            if attempt < retries:
                debug(f"timeout, retry {attempt+1}/{retries}")
                time.sleep(1)
                continue
            debug(f"timeout after {retries} retries")
            return "", -1
        except FileNotFoundError:
            log(f"  agent-browser not found at {AGENT_BROWSER_PATH}")
            return "", -2
        except Exception as e:
            debug(f"agent-browser error: {e}")
            return "", -3
    return "", -1


# ─── DB 操作 ──────────────────────────────────────────────────────

def insert_raw_item(item):
    """写入 raw_intelligence 表"""
    if not item.get('url') or not item.get('title'):
        return False
    import sqlite3
    url_h = url_hash(item['url'])
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    try:
        db = sqlite3.connect(str(DB_PATH), timeout=30)
        db.execute("""
            INSERT OR IGNORE INTO raw_intelligence 
            (title, content, url, source, platform, author, author_id,
             category, tags, hot_score,
             view_count, like_count, collect_count, comment_count, share_count,
             published_at, collected_at, url_hash, source_type, raw_data)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            item.get('title', ''),
            item.get('content', ''),
            item.get('url', ''),
            item.get('source', 'sogou_wechat'),
            item.get('platform', 'sogou_wechat'),
            item.get('author', ''),
            item.get('author_id', ''),
            item.get('category', ''),
            item.get('tags', ''),
            float(item.get('hot_score', 0)),
            int(item.get('view_count', 0)),
            int(item.get('like_count', 0)),
            int(item.get('collect_count', 0)),
            int(item.get('comment_count', 0)),
            int(item.get('share_count', 0)),
            item.get('published_at', now),
            now,
            url_h,
            item.get('source_type', 'browser'),
            item.get('raw_data', ''),
        ))
        db.commit()
        new = db.total_changes > 0
        db.close()
        return new
    except Exception as e:
        debug(f"DB insert error: {e}")
        return False


def get_filter_cache():
    """加载黑名单关键词缓存（来自 spam_filter_keywords 表）"""
    import sqlite3
    try:
        db = sqlite3.connect(str(DB_PATH), timeout=10)
        rows = db.execute("""
            SELECT keyword FROM spam_filter_keywords 
            WHERE is_active = 1 AND severity >= 3
        """).fetchall()
        db.close()
        return [r[0].lower() for r in rows]
    except Exception:
        return []


def is_collect_filtered(title, content):
    """
    采集时黑名单过滤 — 与 unified_collector_v5.py 的 is_collect_filtered 一致
    命中任意 active 黑名单关键词直接丢弃不进库
    """
    _cache = get_filter_cache()
    if not title and not content:
        return False
    text = (title + " " + (content or "")[:500]).lower()
    for kw in _cache:
        if kw in text:
            return True
    return False


# ─── JavaScript 提取逻辑 ─────────────────────────────────────────

def make_extract_js():
    """生成用于提取搜狗微信搜索结果的 JavaScript 代码"""
    return r"""
(() => {
    const results = [];
    const selectors = ['.wx-rb', '.news-box', '.results .wx-rb', '.result-brief'];

    let items = [];
    for (const sel of selectors) {
        const found = document.querySelectorAll(sel);
        if (found.length > 0) { items = Array.from(found); break; }
    }

    // 备选：通过 mp.weixin.qq.com 链接找结果容器
    if (items.length === 0) {
        const links = document.querySelectorAll('a[href*="mp.weixin.qq.com"]');
        const seen = new Set();
        for (const a of links) {
            let p = a.closest('li, .wx-rb, [class*="result"]');
            if (!p) p = a.parentElement;
            if (p && !seen.has(p)) { seen.add(p); items.push(p); if (items.length >= 3) break; }
        }
    }

    for (const item of items) {
        const titleEl = item.querySelector('h3 a, .tit a, .title a, .txt a, h3, .tit');
        if (!titleEl) continue;
        const title = (titleEl.textContent || titleEl.innerText || '').trim();
        let url = titleEl.tagName === 'A' ? (titleEl.href || '') : '';
        if (!url || !url.startsWith('http')) {
            const linkEl = item.querySelector('a[href*="mp.weixin.qq.com"]') || item.querySelector('a[href*="weixin.sogou.com"]');
            url = linkEl ? linkEl.href : '';
        }
        if (!title || !url) continue;

        const descEl = item.querySelector('.summary, .des, .txt-info, .s-p, p');
        const summary = descEl ? (descEl.textContent || descEl.innerText || '').trim() : '';

        const timeEl = item.querySelector('.time, .date, .s2, [class*="time"], [class*="date"]');
        const pubTime = timeEl ? (timeEl.textContent || timeEl.innerText || '').trim() : '';

        const accountEl = item.querySelector('.account, .source, .name, .s-p');
        const account = accountEl ? (accountEl.textContent || accountEl.innerText || '').trim() : '';

        results.push({
            title: title.replace(/\s+/g, ' ').slice(0, 200),
            url: url,
            summary: summary.replace(/\s+/g, ' ').slice(0, 500),
            pub_time: pubTime,
            account: account
        });
    }

    return JSON.stringify(results);
})()
"""


# ─── 搜狗微信搜索结果采集 ─────────────────────────────────────────

def is_captcha_page(text):
    """检测页面是否被验证码拦截"""
    markers = ["验证码", "VerifyCode", "请输入验证", "请依次点击"]
    return any(m in text for m in markers)


def is_empty_results(text):
    """检测是否为空结果页"""
    markers = ["没有搜索到", "搜索结果为空", "没有找到"]
    return any(m in text for m in markers)


def extract_json_from_console(output):
    """
    从 agent-browser console 命令输出中提取 JSON
    console 返回的是逐行文本，JSON 在最后一行
    """
    output = output.strip()
    if not output:
        return None

    # 从最后一行开始找 JSON
    lines = output.split('\n')
    for line in reversed(lines):
        line = line.strip()
        if line.startswith('['):
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue
    return None


def search_with_agent_browser(keyword):
    """
    使用 agent-browser 执行一次搜索并提取结果

    流程：
      1. 先打开 weixin.sogou.com 首页（建立 session，获取 Cookie）
      2. 再导航到搜索 URL（type=2 表示文章搜索）
      3. 检测验证码、空结果
      4. 用 JS 提取结果
      5. 返回结果列表
    """
    items = []
    encoded_kw = quote(keyword)
    search_url = f"https://weixin.sogou.com/weixin?type=2&query={encoded_kw}"

    # Step 1: 打开首页建立 session
    debug(f"  Opening sogou weixin homepage...")
    stdout, rc = ab(["open", "https://weixin.sogou.com/"], timeout=15)
    if rc != 0:
        # 可能已经在一个页面了，直接导航到搜索
        debug(f"  open failed (rc={rc}), trying direct navigation...")
        stdout, rc = ab(["open", search_url], timeout=15)
        if rc != 0:
            log(f"  Failed to open browser (rc={rc})")
            return items
    else:
        # 首页打开成功，等渲染
        time.sleep(1.5)

        # Step 2: 导航到搜索 URL
        debug(f"  Navigating to search URL...")
        stdout, rc = ab(["open", search_url], timeout=15)
        if rc != 0:
            log(f"  Failed to navigate to search (rc={rc})")
            return items

    # 等结果页加载
    time.sleep(3)

    # Step 3: 检查页面
    stdout, rc = ab(["snapshot", "-i"], timeout=10)
    if rc != 0:
        log(f"  Failed to get page snapshot")
        return items

    if is_captcha_page(stdout):
        log(f"  ⚠ CAPTCHA blocked — sogou anti-spider triggered")
        try:
            ab(["screenshot", f"/tmp/sogou_captcha_{keyword[:6]}.png"], timeout=5)
        except Exception:
            pass
        return items

    if is_empty_results(stdout):
        debug(f"  Empty results page")
        return items

    # Step 4: JS 提取
    js = make_extract_js()
    stdout, rc = ab(["console", js], timeout=10)
    if rc != 0:
        debug(f"  console eval failed (rc={rc})")
        return items

    # Step 5: 解析 JSON
    parsed = extract_json_from_console(stdout)
    if parsed and isinstance(parsed, list):
        for r in parsed[:3]:
            title = (r.get('title') or '').strip()
            url = (r.get('url') or '').strip()
            if not title or not url:
                continue
            # 修复相对 URL
            if url.startswith('//'):
                url = 'https:' + url
            elif url.startswith('/'):
                url = 'https://weixin.sogou.com' + url
            items.append({
                'title': title,
                'url': url,
                'content': (r.get('summary') or '').strip(),
                'published_at': (r.get('pub_time') or '').strip(),
                'author': (r.get('account') or '').strip(),
            })

    return items


def search_with_http(keyword):
    """
    HTTP 直连备用方案
    通过 urllib 直接请求搜狗微信搜索结果页，用正则解析 HTML
    """
    import urllib.request
    import http.cookiejar

    items = []
    encoded_kw = quote(keyword)
    url = f"https://weixin.sogou.com/weixin?type=2&query={encoded_kw}"

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Referer": "https://weixin.sogou.com/",
    }

    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode('utf-8', errors='replace')
    except Exception as e:
        debug(f"HTTP request failed: {e}")
        return items

    if is_captcha_page(html):
        debug(f"CAPTCHA in HTTP as well")
        return items

    # 解析 wx-rb 区块
    blocks = re.findall(
        r'<div class="wx-rb[^"]*"[^>]*>(.*?)</div>\s*</div>\s*</li>',
        html, re.DOTALL
    )
    if not blocks:
        blocks = re.findall(
            r'<div class="[^"]*wx-rb[^"]*"[^>]*>(.*?)</div>\s*</li>',
            html, re.DOTALL
        )

    for block in blocks[:6]:
        # 标题 + URL
        m = re.search(
            r'<a[^>]*href="(https?://mp\.weixin\.qq\.com[^"]*)"[^>]*>(.*?)</a>',
            block, re.DOTALL
        )
        if not m:
            m = re.search(
                r'<h3[^>]*>.*?<a[^>]*href="([^"]*)"[^>]*>(.*?)</a>',
                block, re.DOTALL
            )
        if not m:
            continue
        url_val = m.group(1)
        title = re.sub(r'<[^>]+>', '', m.group(2)).strip()
        if not title or not url_val:
            continue

        # 摘要
        sm = re.search(
            r'class="[^"]*(?:summary|des|txt-info)[^"]*"[^>]*>(.*?)</p>',
            block, re.DOTALL
        )
        summary = re.sub(r'<[^>]+>', '', sm.group(1)).strip() if sm else ''

        # 时间
        tm = re.search(
            r'class="[^"]*(?:time|date|s2)[^"]*"[^>]*>(.*?)</',
            block, re.DOTALL
        )
        pub_time = re.sub(r'<[^>]+>', '', tm.group(1)).strip() if tm else ''

        # 公众号
        am = re.search(
            r'class="[^"]*(?:account|source|name)[^"]*"[^>]*>\s*(.*?)</',
            block, re.DOTALL
        )
        account = re.sub(r'<[^>]+>', '', am.group(1)).strip() if am else ''

        items.append({
            'title': title[:200],
            'url': url_val,
            'content': summary[:500],
            'published_at': pub_time,
            'author': account,
        })
        if len(items) >= 3:
            break

    return items


def collect_keyword(keyword):
    """
    对一个关键词的完整采集流程

    策略：
      1. 先用 agent-browser 浏览器方式采集（可能绕过验证码）
      2. 如果失败则用 HTTP 直连方式
    """
    items = search_with_agent_browser(keyword)

    if not items:
        debug(f"  agent-browser gave 0 results, trying HTTP...")
        items = search_with_http(keyword)

    return items


# ─── 主流程 ───────────────────────────────────────────────────────

def main():
    log("=" * 60)
    log("微信公众号文章采集器 — v1.0")
    log(f"    agent-browser: {AGENT_BROWSER_PATH}")
    log(f"    DB: {DB_PATH}")
    log(f"    关键词: {len(SEARCH_KEYWORDS)} 个")
    log(f"    DEBUG: {'ON' if DEBUG else 'OFF'}")
    profile = os.environ.get("AGENT_BROWSER_PROFILE")
    if profile:
        log(f"    Profile: {profile}")
    log("=" * 60)

    # 1. 检查 agent-browser
    path = Path(AGENT_BROWSER_PATH)
    if not path.exists():
        log(f"ERROR: agent-browser 未找到!")
        log(f"请确认: {AGENT_BROWSER_PATH}")
        log(f"或设置 AGENT_BROWSER_PATH 环境变量指向正确的路径")
        sys.exit(1)
    log(f"✓ agent-browser 就绪")

    # 2. 检查 DB
    import sqlite3
    try:
        db = sqlite3.connect(str(DB_PATH), timeout=10)
        count = db.execute("SELECT COUNT(*) FROM raw_intelligence").fetchone()[0]
        db.close()
        log(f"✓ DB 就绪 (当前 {count} 条记录): {DB_PATH}")
    except Exception as e:
        log(f"ERROR: DB 访问失败: {e}")
        sys.exit(1)

    # 3. 预加载黑名单缓存
    cache = get_filter_cache()
    log(f"✓ 黑名单过滤加载: {len(cache)} 条关键词")

    # 4. 逐个采集
    total_new = 0
    total_found = 0
    kw_with_data = 0

    for i, keyword in enumerate(SEARCH_KEYWORDS):
        log(f"")
        log(f"[{i+1}/{len(SEARCH_KEYWORDS)}] 搜索: \"{keyword}\"")

        try:
            items = collect_keyword(keyword)
        except Exception as e:
            log(f"  ERROR: {e}")
            import traceback
            debug(traceback.format_exc())
            items = []

        # 过滤 + 入库
        kw_new = 0
        for item in items:
            if is_collect_filtered(item.get('title', ''), item.get('content', '')):
                log(f"    🚫 过滤: {item['title'][:40]}")
                continue
            if insert_raw_item(item):
                kw_new += 1
            else:
                debug(f"  - 已存在: {item['title'][:40]}")

        if items:
            kw_with_data += 1

        total_found += len(items)
        total_new += kw_new
        log(f"    💾 入库 {kw_new}/{len(items)} 条")

        # 控制频率：每2个关键词间隔2秒
        if (i + 1) % 2 == 0 and i < len(SEARCH_KEYWORDS) - 1:
            log(f"  ⏱ 等待 2 秒...")
            time.sleep(2)

    # 5. 汇总
    log("")
    log("=" * 60)
    log("📊 采集完成")
    log(f"   关键词总数:     {len(SEARCH_KEYWORDS)}")
    log(f"   有数据的关键词: {kw_with_data}")
    log(f"   总采集条目:     {total_found}")
    log(f"   新增入库:       {total_new}")
    log("=" * 60)


if __name__ == "__main__":
    main()
