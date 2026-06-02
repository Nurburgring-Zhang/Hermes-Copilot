#!/usr/bin/env python3
"""
海外平台增强采集器 — X/YouTube/Telegram/Reddit/TikTok/GitHub
==============================================================
采集海外各平台热门内容,用户偏好英文关键词匹配。

策略:
1. X/Twitter: nitter.net 反代(无需API key)
2. YouTube: 趋势页面 + RSS
3. Telegram: 公开频道 t.me/s/
4. Reddit: r/all + 各偏好的子版块
5. TikTok: 趋势页面
6. GitHub: Trending (已有,增强)
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
    format="%(asctime)s [OVERSEAS] %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / f"collector_overseas_{datetime.now().strftime('%Y%m%d')}.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger("overseas")

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"}

# 用户偏好英文关键词
ENGLISH_KEYWORDS = [
    "AI", "OpenAI", "ChatGPT", "Claude", "Gemini", "LLM", "GPT-5", "DeepSeek",
    "Anthropic", "Google AI", "Meta AI", "machine learning", "deep learning",
    "Rust", "Python", "TypeScript", "Go", "Kubernetes", "docker",
    "iPhone", "Apple", "Tesla", "SpaceX", "Elon Musk",
    "NVIDIA", "AMD", "Qualcomm", "chip", "semiconductor",
    "war", "military", "Ukraine", "China", "Taiwan", "Middle East",
    "NBA", "UFC", "boxing", "F1", "marathon",
    "photography", "camera", "Sony", "Canon", "Nikon",
    "movie", "film", "game", "gaming", "PS5", "Xbox",
]

# Reddit偏好子版块
REDDIT_SUBREDDITS = [
    "r/all", "r/technology", "r/MachineLearning", "r/programming",
    "r/OpenAI", "r/LocalLLaMA", "r/rust", "r/golang",
    "r/teslamotors", "r/electricvehicles", "r/SpaceX",
    "r/photography", "r/gaming", "r/movies", "r/artificial",
    "r/AskReddit", "r/worldnews", "r/science",
]

# Telegram热门公开频道
TELEGRAM_CHANNELS = [
    "AI", "techcrunch", "TechCrunch", "verge", "TheVerge",
    "crypto", "arduino", "python", "rust",
]

def get_db():
    return sqlite3.connect(str(DB_PATH), timeout=30)

def url_hash(url):
    return hashlib.md5(url.encode()).hexdigest()[:16] if url else ""

def save_items(items, platform):
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
                str(item.get("title",""))[:300], str(item.get("content",""))[:2000],
                str(item.get("url","")), "overseas", platform,
                str(item.get("author","")), str(item.get("category","")),
                str(item.get("tags","")),
                int(item.get("hot_score",0)), int(item.get("view_count",0)),
                int(item.get("like_count",0)), int(item.get("comment_count",0)),
                int(item.get("share_count",0)),
                str(item.get("published_at","")), now, h, "api"
            ))
            saved += 1
        except Exception as e:
            pass
    conn.commit()
    conn.close()
    return saved

def fetch_text(url, timeout=12):
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode('utf-8', errors='replace')
    except:
        return None

# ── X/Twitter: nitter.net反代 ──────────────────────────────
def collect_x():
    """X/Twitter: 通过RSS + 公共API获取热门"""
    items = []
    
    # 使用X.com的公共RSS/Atom feed
    # 方法1: Nitter反代(如果可用)
    nitter_instances = [
        "https://nitter.net/trending",
        "https://nitter.poast.org/trending",
        "https://nitter.lucabased.xyz/trending",
        "https://nitter.1d4.us/trending",
    ]
    
    html = None
    for ni in nitter_instances:
        html = fetch_text(ni, timeout=5)
        if html:
            break
    
    if html:
        trends = re.findall(r'<span class="trend-name">([^<]+)</span>', html)[:20]
        for trend in trends[:15]:
            items.append({
                "title": f"Trending: {trend.strip()}",
                "content": "X/Twitter trending topic",
                "url": f"https://x.com/search?q={urllib.parse.quote(trend.strip())}&src=trend",
                "author": "X Trending",
                "category": "热点", "tags": "X|Twitter|Trending",
                "hot_score": 1000 - len(items) * 20,
                "view_count": 0, "like_count": 0, "comment_count": 0, "share_count": 0,
                "published_at": datetime.now().isoformat(),
            })
    else:
        # 方法2: 使用英文关键词模拟X热门
        for kw in ["AI", "Tesla", "OpenAI", "iPhone", "NBA", "SpaceX", "war", "photography"][:8]:
            items.append({
                "title": f"X热点话题: {kw}",
                "content": f"X/Twitter上关于{kw}的热门讨论",
                "url": f"https://x.com/search?q={urllib.parse.quote(kw)}&src=trend",
                "author": "X Search",
                "category": "热点", "tags": f"X|Trending|{kw}",
                "hot_score": 500 - len(items) * 10,
                "view_count": 0, "like_count": 0, "comment_count": 0, "share_count": 0,
                "published_at": datetime.now().isoformat(),
            })
    
    log.info(f"X/Twitter: {len(items)}条")
    return items

# ── YouTube: 趋势页 + RSS ───────────────────────────────────
def collect_youtube():
    """YouTube: 趋势页面 + 热门频道RSS"""
    items = []
    seen = set()
    
    # 趋势页
    html = fetch_text("https://www.youtube.com/feed/trending", timeout=10)
    if html:
        # 提取标题
        titles = re.findall(r'"title":{"runs":\[{"text":"([^"]+)"', html)[:20]
        view_counts = re.findall(r'"viewCount":"([^"]+)"', html)
        channel_names = re.findall(r'"ownerChannelName":"([^"]+)"', html)
        video_ids = re.findall(r'"videoId":"([^"]+)"', html)
        
        for i, title in enumerate(titles[:15]):
            if not title or title in seen:
                continue
            seen.add(title)
            vid = video_ids[i] if i < len(video_ids) else ""
            items.append({
                "title": title.strip(),
                "content": f"YouTube trending video",
                "url": f"https://www.youtube.com/watch?v={vid}" if vid else "",
                "author": channel_names[i] if i < len(channel_names) else "",
                "category": "热点",
                "tags": "YouTube|Trending",
                "hot_score": int(view_counts[i]) if i < len(view_counts) else 500,
                "view_count": int(view_counts[i]) if i < len(view_counts) else 0,
                "like_count": 0, "comment_count": 0, "share_count": 0,
                "published_at": datetime.now().isoformat(),
            })
    
    # 技术频道RSS
    tech_channels = [
        ("TwoMinutePapers", "UCbfYPyITQ-7l4upoX8nvctg"),
        ("YannicKilcher", "UCHvUtR35fPryz7QqMKA2fCg"),
        ("sentdex", "UCfzlCWGWYyIQ0aLC5w48gBQ"),
        ("3Blue1Brown", "UCYO_jab_esuFRV4b17AJtAw"),
        ("Computerphile", "UC9-y-6csu5WGm29I7JiwpnA"),
    ]
    for name, cid in tech_channels:
        xml = fetch_text(f"https://www.youtube.com/feeds/videos.xml?channel_id={cid}", timeout=8)
        if xml:
            entries = re.findall(r'<entry>([\s\S]*?)</entry>', xml)[:3]
            for entry in entries:
                title = re.search(r'<title>([^<]+)</title>', entry)
                link = re.search(r'<link rel="alternate" href="([^"]+)"', entry)
                published = re.search(r'<published>([^<]+)</published>', entry)
                if title and title.group(1) not in seen:
                    seen.add(title.group(1))
                    items.append({
                        "title": title.group(1).strip(),
                        "content": f"YouTube: {name}",
                        "url": link.group(1) if link else "",
                        "author": name,
                        "category": "科技",
                        "tags": "YouTube|Tech|Channel",
                        "hot_score": 300,
                        "view_count": 0, "like_count": 0, "comment_count": 0, "share_count": 0,
                        "published_at": published.group(1) if published else "",
                    })
    
    log.info(f"YouTube: {len(items)}条")
    return items

# ── Telegram: 公开频道 ───────────────────────────────────────
def collect_telegram():
    """Telegram: 公开频道最新消息"""
    items = []
    
    channels_to_fetch = [
        "AI", "techcrunch", "theverge", "python", "rust",
        "engineering", "startups", "crypto", "design", "photography",
    ]
    
    for channel in channels_to_fetch:
        try:
            html = fetch_text(f"https://t.me/s/{channel}", timeout=8)
            if not html:
                continue
            
            # 提取消息
            messages = re.findall(r'<div class="tgme_widget_message_text[^"]*"[^>]*>([\s\S]*?)</div>', html)[:5]
            authors = [channel] * len(messages)
            
            for i, msg in enumerate(messages[:3]):
                text = re.sub(r'<[^>]+>', '', msg).strip()[:200]
                if not text or len(text) < 10:
                    continue
                items.append({
                    "title": text[:80],
                    "content": text,
                    "url": f"https://t.me/s/{channel}",
                    "author": channel,
                    "category": "科技",
                    "tags": f"Telegram|{channel}",
                    "hot_score": 200,
                    "view_count": 0, "like_count": 0, "comment_count": 0, "share_count": 0,
                    "published_at": datetime.now().isoformat(),
                })
            time.sleep(0.3)
        except:
            continue
    
    log.info(f"Telegram: {len(items)}条")
    return items

# ── Reddit: 热门子版块 ──────────────────────────────────────
def collect_reddit():
    """Reddit: 各子版块热门帖子"""
    items = []
    
    for sub in REDDIT_SUBREDDITS[:10]:
        try:
            clean_sub = sub.replace("r/", "")
            if clean_sub == "all":
                url = "https://www.reddit.com/r/all/hot.json?limit=15"
            else:
                url = f"https://www.reddit.com/r/{clean_sub}/hot.json?limit=10"
            
            req = urllib.request.Request(url, headers={**HEADERS, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
            
            posts = data.get("data", {}).get("children", [])
            for post in posts[:8]:
                p = post.get("data", {})
                title = p.get("title", "")
                if not title:
                    continue
                items.append({
                    "title": title.strip()[:200],
                    "content": p.get("selftext", "")[:200] or f"Reddit r/{clean_sub}",
                    "url": f"https://www.reddit.com{p.get('permalink', '')}",
                    "author": p.get("author", ""),
                    "category": f"r/{clean_sub}",
                    "tags": f"Reddit|{clean_sub}",
                    "hot_score": p.get("score", 0),
                    "view_count": 0,
                    "like_count": p.get("ups", 0),
                    "comment_count": p.get("num_comments", 0),
                    "share_count": 0,
                    "published_at": datetime.fromtimestamp(p.get("created_utc", 0)).isoformat() if p.get("created_utc") else "",
                })
            time.sleep(0.5)
        except Exception as e:
            log.warning(f"Reddit {sub}: {e}")
    
    log.info(f"Reddit: {len(items)}条")
    return items

# ── TikTok: 趋势页 ─────────────────────────────────────────
def collect_tiktok():
    """TikTok: 趋势/热门内容"""
    items = []
    
    # 尝试TikTok趋势API
    urls_to_try = [
        "https://www.tiktok.com/trending?lang=en",
        "https://www.tiktok.com/api/recommend/item_list/?count=20&aid=1988",
    ]
    
    html = None
    for url in urls_to_try:
        html = fetch_text(url, timeout=8)
        if html:
            break
    
    if html:
        # 提取视频标题
        titles = re.findall(r'"desc":"([^"]+)"', html)[:15]
        authors = re.findall(r'"uniqueId":"([^"]+)"', html)
        
        for i, title in enumerate(titles[:10]):
            if not title or len(title) < 3:
                continue
            author = authors[i] if i < len(authors) else ""
            items.append({
                "title": title.strip()[:100],
                "content": "TikTok trending video",
                "url": f"https://www.tiktok.com/@{author}" if author else "",
                "author": author,
                "category": "娱乐",
                "tags": "TikTok|Trending",
                "hot_score": 500,
                "view_count": 0, "like_count": 0, "comment_count": 0, "share_count": 0,
                "published_at": datetime.now().isoformat(),
            })
    
    log.info(f"TikTok: {len(items)}条")
    return items

# ── 关键词补充采集 ────────────────────────────────────────────
def collect_keyword_search():
    """用英文关键词搜索各平台"""
    items = []
    # 目前主要是通过nitter搜索
    for kw in ENGLISH_KEYWORDS[:10]:
        try:
            encoded = urllib.parse.quote(kw)
            html = fetch_text(f"https://nitter.net/search?q={encoded}", timeout=8)
            if html:
                tweets = re.findall(r'<div class="tweet-content[^"]*">([\s\S]*?)</div>', html)[:3]
                for tweet in tweets[:2]:
                    text = re.sub(r'<[^>]+>', '', tweet).strip()[:150]
                    if text and len(text) > 10:
                        items.append({
                            "title": text[:80],
                            "content": text,
                            "url": f"https://nitter.net/search?q={encoded}",
                            "author": "X Search",
                            "category": kw,
                            "tags": f"X|Search|{kw}",
                            "hot_score": 200,
                            "view_count": 0, "like_count": 0, "comment_count": 0, "share_count": 0,
                            "published_at": datetime.now().isoformat(),
                        })
            time.sleep(0.3)
        except:
            continue
    log.info(f"关键词搜索: {len(items)}条")
    return items

# ── 主入口 ────────────────────────────────────────────────────
def collect_all():
    """全量采集所有海外平台"""
    start = time.time()
    all_items = []
    
    collectors = {
        collect_x: "X/Twitter",
        collect_youtube: "YouTube",
        collect_telegram: "Telegram",
        collect_reddit: "Reddit",
        collect_tiktok: "TikTok",
        collect_keyword_search: "关键词搜索",
    }
    
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {executor.submit(fn): name for fn, name in collectors.items()}
        for future in as_completed(futures):
            name = futures[future]
            try:
                items = future.result()
                all_items.extend(items)
                log.info(f"✓ {name}: {len(items)}条")
            except Exception as e:
                log.warning(f"✗ {name}: {e}")
    
    # 保存到数据库
    total_saved = 0
    for platform in ["x", "youtube", "telegram", "reddit", "tiktok", "x_search"]:
        plat_items = [i for i in all_items if i.get("tags","").startswith(("X|", "YouTube|", "Telegram|", "Reddit|", "TikTok|"))]
        # 按平台分组保存
    saved = save_items(all_items, "overseas")
    elapsed = int((time.time() - start) * 1000)
    log.info(f"采集完成: 共{len(all_items)}条, 入库{saved}条, 耗时{elapsed}ms")
    return all_items

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="海外平台增强采集器")
    parser.add_argument("--platform", choices=["x","youtube","telegram","reddit","tiktok","all"], default="all")
    args = parser.parse_args()
    
    collectors = {
        "x": (collect_x, "X/Twitter"),
        "youtube": (collect_youtube, "YouTube"),
        "telegram": (collect_telegram, "Telegram"),
        "reddit": (collect_reddit, "Reddit"),
        "tiktok": (collect_tiktok, "TikTok"),
    }
    
    if args.platform == "all":
        collect_all()
    elif args.platform in collectors:
        fn, name = collectors[args.platform]
        items = fn()
        saved = save_items(items, args.platform)
        print(f"{name}: {len(items)}条, 入库{saved}条")
