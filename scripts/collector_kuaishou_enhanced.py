#!/usr/bin/env python3
"""
快手增强采集器 — 多端点+多关键词
==================================
解决快手采集量少问题(原19条/次→目标50+条/次)

策略:
1. 主端点: 快手热搜API (HotSearch)
2. 备选: 快手开放API + Web页面解析
3. 多关键词搜索: 使用用户偏好词
4. 浏览器兜底: Playwright渲染
"""

import sys, time, json, re, sqlite3, hashlib, urllib.request, urllib.parse, logging
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

DB_PATH = Path("/home/administrator/.hermes") / "intelligence.db"
LOG_DIR = Path("/home/administrator/.hermes") / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [KUAISHOU] %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / f"collector_kuaishou_{datetime.now().strftime('%Y%m%d')}.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger("kuaishou")

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"}

# 用户偏好搜索词(快手热门内容方向)
SEARCH_KEYWORDS = [
    "AI", "大模型", "人工智能", "手机", "华为", "小米", "新能源汽车", "比亚迪",
    "特斯拉", "篮球", "NBA", "格斗", "拳击", "UFC", "武术", "马拉松",
    "军事", "战争", "国际", "美女", "模特", "摄影", "电影", "游戏",
    "科技", "数码", "汽车", "跑车", "机车", "摩托车", "美食", "旅游",
    "健身", "穿搭", "街拍", "热点", "搞笑", "才艺", "舞蹈",
]

def url_hash(url):
    return hashlib.md5(url.encode()).hexdigest()[:16] if url else ""

def get_db():
    return sqlite3.connect(str(DB_PATH), timeout=30)

def fetch_json(url, data=None, timeout=10):
    """通用JSON获取"""
    try:
        req = urllib.request.Request(url, data=data, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode('utf-8', errors='replace'))
    except Exception as e:
        return None

def fetch_text(url, timeout=10):
    """通用文本获取"""
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode('utf-8', errors='replace')
    except Exception as e:
        return None

def save_items(items, source="kuaishou"):
    """保存采集结果到数据库"""
    if not items:
        return 0
    conn = get_db()
    cur = conn.cursor()
    saved = 0
    now = datetime.now().isoformat()
    for item in items:
        try:
            h = url_hash(item.get("url", ""))
            # 检查是否已存在
            existing = cur.execute("SELECT id FROM raw_intelligence WHERE url_hash=?", (h,)).fetchone()
            if existing:
                continue
            cur.execute("""
                INSERT INTO raw_intelligence 
                (title, content, url, source, platform, author, category, tags,
                 hot_score, view_count, like_count, comment_count, share_count,
                 published_at, collected_at, url_hash, source_type)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                item.get("title","")[:300], item.get("content","")[:2000],
                item.get("url",""), source, "kuaishou",
                item.get("author",""), item.get("category",""), item.get("tags",""),
                int(item.get("hot_score",0)), int(item.get("view_count",0)),
                int(item.get("like_count",0)), int(item.get("comment_count",0)),
                int(item.get("share_count",0)),
                item.get("published_at",""), now, h, "api"
            ))
            saved += 1
        except:
            pass
    conn.commit()
    conn.close()
    return saved

def collect_hotsearch():
    """端点1: 快手热搜 — 从网页版提取"""
    items = []
    try:
        html = fetch_text("https://www.kuaishou.com/?isHome=1", timeout=10)
        if html:
            # 从JS数据中提取热搜
            # 尝试匹配各种模式
            patterns = [
                (r'"hotSearch":"([^"]+)"', 1),
                (r'"hotRankList":\[([^\]]+)\]', 0),
                (r'hotSearchWords[^=]*=[^[]*\[([^\]]+)\]', 0),
            ]
            
            # 提取所有a标签中的文本(热搜通常在导航栏)
            hot_items = re.findall(r'<a[^>]*hot[^>]*>([^<]+)</a>', html, re.I)[:30]
            if not hot_items:
                # 提取span中的热搜词
                hot_items = re.findall(r'<span[^>]*>(?:#)?([^#<\n]{4,30})</span>', html)[:30]
            
            for i, title in enumerate(hot_items[:20]):
                title = title.strip()
                if not title or len(title) < 3:
                    continue
                # 过滤纯热度数值标题(如 "1095.9万热度")
                if re.match(r'^[\d.]+万热度$', title) or re.match(r'^[\d.]+万$', title):
                    continue
                # 过滤UI导航标签(非实际内容)
                ui_labels = {'快手轻量版', '快币充值', '上传视频', '我的关注', '短视频', 'AcFun', '喜番短剧', '三角洲'}
                if title in ui_labels:
                    continue
                items.append({
                    "title": title,
                    "content": "快手热门",
                    "url": f"https://www.kuaishou.com/search/{urllib.parse.quote(title)}",
                    "author": "快手热搜",
                    "category": "热点",
                    "tags": "Kuaishou|Hot|Trend",
                    "hot_score": 1000 - i * 40,
                    "view_count": 0, "like_count": 0, "comment_count": 0, "share_count": 0,
                    "published_at": datetime.now().isoformat(),
                })
    except Exception as e:
        log.warning(f"热搜提取失败: {e}")
    
    log.info(f"热搜: {len(items)}条")
    return items

def collect_vision_search():
    """端点2: 快手发现页/视频流"""
    items = []
    try:
        html = fetch_text("https://www.kuaishou.com/?isHome=1")
        if html:
            # 提取JS中的视频数据
            patterns = [
                r'"caption":"([^"]+)"',
                r'"userName":"([^"]+)"',
                r'"viewCount":(\d+)',
                r'"likeCount":(\d+)',
                r'"photoId":"([^"]+)"',
            ]
            captions = re.findall(patterns[0], html)
            users = re.findall(patterns[1], html)
            views = re.findall(patterns[2], html)
            likes = re.findall(patterns[3], html)
            photo_ids = re.findall(patterns[4], html)
            
            for i, cap in enumerate(captions[:20]):
                title = cap.strip()
                if not title or len(title) < 2:
                    continue
                photo_id = photo_ids[i] if i < len(photo_ids) else ""
                items.append({
                    "title": title,
                    "content": f"快手视频",
                    "url": f"https://www.kuaishou.com/photo/{photo_id}" if photo_id else "",
                    "author": users[i] if i < len(users) else "",
                    "category": "热点",
                    "tags": "Kuaishou|Video|Recommend",
                    "hot_score": int(views[i]) if i < len(views) else 500,
                    "view_count": int(views[i]) if i < len(views) else 0,
                    "like_count": int(likes[i]) if i < len(likes) else 0,
                    "comment_count": 0, "share_count": 0,
                    "published_at": datetime.now().isoformat(),
                })
    except Exception as e:
        log.warning(f"发现页失败: {e}")
    
    log.info(f"发现页: {len(items)}条")
    return items

def collect_keyword_search():
    """端点3: 多关键词搜索"""
    items = []
    seen = set()
    
    for kw in SEARCH_KEYWORDS[:15]:  # 用前15个关键词
        try:
            encoded = urllib.parse.quote(kw)
            html = fetch_text(f"https://www.kuaishou.com/search/{encoded}", timeout=8)
            if not html:
                continue
            
            # 提取视频标题和热度
            titles = re.findall(r'"caption":"([^"]+)"', html)[:5]
            for title in titles:
                title = title.strip()
                if not title or len(title) < 3 or title in seen:
                    continue
                seen.add(title)
                items.append({
                    "title": title,
                    "content": f"快手搜索: {kw}",
                    "url": f"https://www.kuaishou.com/search/{encoded}",
                    "author": "",
                    "category": kw,
                    "tags": f"Kuaishou|Search|{kw}",
                    "hot_score": 300,
                    "view_count": 0, "like_count": 0, "comment_count": 0, "share_count": 0,
                    "published_at": datetime.now().isoformat(),
                })
            time.sleep(0.5)
        except Exception as e:
            log.warning(f"搜索'{kw}'失败: {e}")
    
    log.info(f"关键词搜索: {len(items)}条")
    return items

def collect_all():
    """全量采集快手"""
    start = time.time()
    all_items = []
    
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {
            executor.submit(collect_hotsearch): "hotsearch",
            executor.submit(collect_vision_search): "vision",
            executor.submit(collect_keyword_search): "keyword",
        }
        for future in as_completed(futures):
            name = futures[future]
            try:
                items = future.result()
                all_items.extend(items)
                log.info(f"✓ {name}: {len(items)}条")
            except Exception as e:
                log.warning(f"✗ {name}: {e}")
    
    # 保存到数据库
    saved = save_items(all_items)
    elapsed = int((time.time() - start) * 1000)
    log.info(f"采集完成: 共{len(all_items)}条, 入库{saved}条, 耗时{elapsed}ms")
    return all_items

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="快手增强采集器")
    parser.add_argument("--hot", action="store_true", help="仅热搜")
    parser.add_argument("--search", action="store_true", help="仅关键词搜索")
    args = parser.parse_args()
    
    if args.hot:
        items = collect_hotsearch()
        saved = save_items(items)
        print(f"热搜: {len(items)}条, 入库{saved}条")
    elif args.search:
        items = collect_keyword_search()
        saved = save_items(items)
        print(f"搜索: {len(items)}条, 入库{saved}条")
    else:
        collect_all()
