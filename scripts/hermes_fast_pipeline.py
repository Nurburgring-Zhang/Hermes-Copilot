#!/usr/bin/env python3
"""
Hermes 快速情报管线 (--fast mode)
采集 -> 清洗 -> 评估 -> 存储 (无推送)
并行采集关键平台,精简高效
"""
import urllib.request
import json
import time
import sqlite3
import re
import os
import sys
from datetime import datetime, timedelta
from html import unescape
from concurrent.futures import ThreadPoolExecutor, as_completed

DB_PATH = os.path.expanduser("~/.hermes/intelligence.db")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/html, */*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=OFF")
    conn.execute("PRAGMA cache_size=-8000")
    return conn

# ============================================================
# 采集函数
# ============================================================
def fetch_bilibili_ranking(rid=0):
    items = []
    region_names = {0: "全站", 36: "科技", 4: "游戏", 223: "汽车", 160: "生活", 21: "运动"}
    region_name = region_names.get(rid, str(rid))
    url = f"https://api.bilibili.com/x/web-interface/ranking/v2?rid={rid}&type=all"
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode('utf-8'))
        for item in data.get('data', {}).get('list', []):
            stat = item.get('stat', {})
            title = unescape(item.get('title', ''))
            if len(title) < 5:
                continue
            pub_time = item.get('pubdate', 0)
            items.append({
                "title": title, "content": item.get('desc', ''),
                "url": f"https://www.bilibili.com/video/{item.get('bvid', '')}",
                "platform": "bilibili", "source": f"B站-{region_name}",
                "author": item.get('owner', {}).get('name', ''),
                "author_id": str(item.get('owner', {}).get('mid', '')),
                "category": item.get('tname', region_name),
                "hot_score": float(stat.get('view', 0)),
                "view_count": stat.get('view', 0),
                "like_count": stat.get('like', 0),
                "collect_count": stat.get('favorite', 0),
                "comment_count": stat.get('reply', 0),
                "share_count": stat.get('share', 0),
                "published_at": datetime.fromtimestamp(pub_time).isoformat() if pub_time else None,
                "raw_data": json.dumps(item, ensure_ascii=False)
            })
    except Exception:
        pass
    return items

def fetch_weibo_hot():
    items = []
    try:
        req = urllib.request.Request("https://weibo.com/ajax/side/hotSearch", headers=HEADERS)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode('utf-8'))
        for item in data.get('data', {}).get('realtime', []):
            title = unescape(item.get('note', ''))
            if len(title) < 5:
                continue
            items.append({
                "title": title, "content": item.get('word_scheme', ''),
                "url": f"https://s.weibo.com/weibo?q={item.get('note', '')}",
                "platform": "weibo", "source": "微博热搜",
                "author": "", "author_id": "", "category": item.get('category', '热搜'),
                "hot_score": float(item.get('raw_hot', 0)),
                "view_count": 0, "like_count": 0,
                "comment_count": item.get('num', 0),
                "collect_count": 0, "share_count": 0,
                "published_at": None,
                "raw_data": json.dumps(item, ensure_ascii=False)
            })
    except Exception:
        pass
    return items

def fetch_github_trending():
    items = []
    for lang in ["python", "typescript", "javascript"]:
        try:
            url = f"https://api.github.com/search/repositories?q=stars:>500+created:>2025-01-01+language:{lang}&sort=stars&order=desc&per_page=10"
            req = urllib.request.Request(url, headers={**HEADERS, "Accept": "application/vnd.github.v3+json"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode('utf-8'))
            for repo in data.get('items', [])[:10]:
                items.append({
                    "title": f"[GitHub] {repo.get('full_name', '')}",
                    "content": repo.get('description', '') or '',
                    "url": repo.get('html_url', ''),
                    "platform": "github", "source": f"GitHub-{lang}",
                    "author": repo.get('owner', {}).get('login', ''),
                    "author_id": str(repo.get('owner', {}).get('id', '')),
                    "category": f"code-{lang}",
                    "hot_score": float(repo.get('stargazers_count', 0)),
                    "view_count": 0, "like_count": repo.get('stargazers_count', 0),
                    "collect_count": repo.get('forks_count', 0),
                    "comment_count": repo.get('open_issues_count', 0),
                    "share_count": 0, "published_at": repo.get('created_at', ''),
                    "raw_data": json.dumps(repo, ensure_ascii=False)
                })
            time.sleep(0.3)
        except Exception:
            pass
    return items

def fetch_ithome():
    items = []
    try:
        req = urllib.request.Request("https://www.ithome.com/", headers=HEADERS)
        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read().decode('utf-8', errors='ignore')
        pattern = re.compile(r'<a href="(https://www\.ithome\.com/0/\d+/\d+\.htm)"[^>]*>([^<]+)</a>')
        matches = pattern.findall(html)
        if not matches:
            pattern2 = re.compile(r'<a href="(https://www\.ithome\.com/d/\d+\.html)" class="title">([^<]+)</a>')
            matches = pattern2.findall(html)
        seen = set()
        for url, title in matches[:50]:
            title = unescape(title.strip())
            if len(title) < 8 or title in seen:
                continue
            seen.add(title)
            items.append({
                "title": title, "content": "", "url": url,
                "platform": "ithome", "source": "IT之家",
                "author": "", "author_id": "", "category": "tech",
                "hot_score": 1000, "view_count": 0, "like_count": 0,
                "comment_count": 0, "collect_count": 0, "share_count": 0,
                "published_at": None, "raw_data": "{}"
            })
    except Exception:
        pass
    return items[:40]

def fetch_hackernews():
    items = []
    try:
        req = urllib.request.Request("https://hacker-news.firebaseio.com/v0/topstories.json", headers=HEADERS)
        with urllib.request.urlopen(req, timeout=15) as resp:
            top_ids = json.loads(resp.read().decode())[:15]
        fetch_deadline = time.time() + 90
        for sid in top_ids:
            if time.time() > fetch_deadline:
                break
            try:
                req2 = urllib.request.Request(f"https://hacker-news.firebaseio.com/v0/item/{sid}.json", headers=HEADERS)
                with urllib.request.urlopen(req2, timeout=8) as resp2:
                    story = json.loads(resp2.read().decode())
                if not story or story.get('type') != 'story':
                    continue
                title = story.get('title', '')
                if len(title) < 5:
                    continue
                items.append({
                    "title": title, "content": story.get('text', '') or '',
                    "url": story.get('url', f"https://news.ycombinator.com/item?id={sid}"),
                    "platform": "hackernews", "source": "HackerNews",
                    "author": story.get('by', ''),
                    "author_id": str(story.get('by', '')),
                    "category": "tech",
                    "hot_score": float(story.get('score', 0)),
                    "view_count": 0, "like_count": story.get('score', 0),
                    "comment_count": story.get('descendants', 0),
                    "collect_count": 0, "share_count": 0,
                    "published_at": datetime.fromtimestamp(story.get('time', 0)).isoformat() if story.get('time') else None,
                    "raw_data": json.dumps(story, ensure_ascii=False)
                })
                time.sleep(0.05)
            except Exception:
                pass
    except Exception:
        pass
    return items

# ============================================================
# 清洗与评估
# ============================================================
NOISE_KW = ["明星", "娱乐", "八卦", "绯闻", "综艺", "演唱会", "粉丝"]
HIGH_KW = [
    "AI", "LLM", "大模型", "GPT", "Claude", "Gemini", "OpenAI", "Anthropic",
    "发布", "开源", "突破", "颠覆", "革命", "新模型", "新功能",
    "融资", "收购", "独角兽", "突破性",
    "技术", "架构", "框架", "系统", "平台", "漏洞", "安全",
    "自动驾驶", "机器人", "芯片", "半导体", "GPU",
    "新能源汽车", "电动车", "iPhone", "华为", "小米", "苹果",
]

def is_noise(title, content):
    text = (title + content).lower()
    return sum(1 for kw in NOISE_KW if kw.lower() in text) >= 2

def get_chinese_ratio(text):
    c = len(re.findall(r'[\u4e00-\u9fff]', text))
    return c / len(text) if len(text) > 0 else 0

def evaluate(item):
    title, content = item.get('title', ''), item.get('content', '')
    hot = item.get('hot_score', 0)
    plat = item.get('platform', '')
    text = (title + content).lower()
    score = 0.0
    matched_kw = [kw for kw in HIGH_KW if kw.lower() in text]
    score += len(matched_kw) * 5
    if plat == 'github':
        score += 15 if hot > 10000 else (10 if hot > 1000 else 0)
    elif plat == 'bilibili':
        score += 15 if hot > 5000000 else (10 if hot > 1000000 else 5 if hot > 100000 else 0)
    elif plat == 'hackernews':
        score += 10 if hot > 100 else (5 if hot > 50 else 0)
    elif plat in ('ithome',):
        score += 8
    score += 5 if item.get('like_count', 0) > 10000 else 0
    score += 5 if item.get('comment_count', 0) > 1000 else 0
    item['chinese_ratio'] = get_chinese_ratio(title + content)
    item['language'] = 'zh' if item['chinese_ratio'] > 0.5 else 'en'
    if len(matched_kw) >= 4 and score >= 30:
        level = 5
    elif len(matched_kw) >= 3 and score >= 20:
        level = 4
    elif len(matched_kw) >= 2 and score >= 15:
        level = 3
    elif len(matched_kw) >= 1 and score >= 10:
        level = 2
    else:
        level = 1
    item['importance_score'] = round(score, 1)
    item['value_level'] = level
    item['value_reasons'] = f"关键词: {','.join(matched_kw[:3])}" if matched_kw else "常规内容"
    item['is_ai_related'] = 1 if any(kw in text for kw in ['ai', 'llm', 'gpt', '大模型', '模型', '神经', 'transformer']) else 0
    return item

def clean_dedup(items):
    conn = get_db()
    c = conn.cursor()
    try:
        c.execute("SELECT title FROM cleaned_intelligence WHERE cleaned_at > datetime('now', '-2 hours')")
        existing = set(r[0].lower() for r in c.fetchall())
        c.execute("SELECT title FROM raw_intelligence WHERE collected_at > datetime('now', '-2 hours')")
        existing_raw = set(r[0].lower() for r in c.fetchall())
    except Exception:
        existing = set()
        existing_raw = set()
    conn.close()
    seen = set()
    result = []
    for item in items:
        t = item.get('title', '').strip()
        if len(t) < 8 or t.lower() in seen or t.lower() in existing or t.lower() in existing_raw:
            continue
        if is_noise(t, item.get('content', '')):
            continue
        seen.add(t.lower())
        result.append(item)
    return result

def save_raw(conn, items):
    c = conn.cursor()
    saved = 0
    for item in items:
        try:
            c.execute("""INSERT INTO raw_intelligence 
                (title, content, url, platform, source, author, author_id, category,
                 hot_score, view_count, like_count, collect_count, comment_count, share_count,
                 published_at, collected_at, raw_data)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'),?)""",
                (item['title'], item.get('content', ''), item.get('url', ''),
                 item['platform'], item['source'],
                 item.get('author', ''), item.get('author_id', ''),
                 item.get('category', ''),
                 item.get('hot_score', 0), item.get('view_count', 0),
                 item.get('like_count', 0), item.get('collect_count', 0),
                 item.get('comment_count', 0), item.get('share_count', 0),
                 item.get('published_at'), item.get('raw_data', '{}')))
            saved += 1
        except Exception:
            pass
    return saved

def save_cleaned(conn, items):
    c = conn.cursor()
    saved = 0
    for item in items:
        try:
            c.execute("""INSERT INTO cleaned_intelligence 
                (title, content, url, source, platform, author, category,
                 importance_score, value_level, value_reasons, is_ai_related,
                 language, chinese_ratio, published_at, cleaned_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'))""",
                (item['title'], item.get('content', ''), item.get('url', ''),
                 item['source'], item['platform'],
                 item.get('author', ''), item.get('category', ''),
                 item['importance_score'], item['value_level'],
                 item.get('value_reasons', ''),
                 item.get('is_ai_related', 0),
                 item.get('language', 'zh'),
                 item.get('chinese_ratio', 1.0),
                 item.get('published_at')))
            saved += 1
        except Exception:
            pass
    return saved

def run():
    start_time = time.time()
    print("=" * 55)
    print("  🤖  Hermes 情报快速管线 (--fast 模式)")
    print("  ⏰  " + datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
    print("  📋  采集→清洗→评估→存储 (无推送)")
    print("=" * 55)

    # === Step 1: Parallel Collection ===
    print("\n📡 [1/4] 并行采集...")
    all_items = []

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {}
        for rid in [0, 36]:
            f = executor.submit(fetch_bilibili_ranking, rid)
            futures[f] = f"B站-{'全站' if rid == 0 else '科技'}"
        for fetcher, name in [
            (fetch_weibo_hot, "微博热搜"),
            (fetch_github_trending, "GitHub热门"),
            (fetch_ithome, "IT之家"),
            (fetch_hackernews, "HackerNews"),
        ]:
            f = executor.submit(fetcher)
            futures[f] = name

        for future in as_completed(futures, timeout=150):
            name = futures[future]
            try:
                items = future.result()
                print(f"    ✅ {name}: +{len(items)}条")
                all_items.extend(items)
            except Exception as e:
                print(f"    ❌ {name}: 失败 - {e}")

    print(f"    📊 合计: {len(all_items)}条")
    if not all_items:
        print("    ⚠️  无新数据,跳过")
        return

    # === Step 2: Dedup + Denoise ===
    print("\n🧹 [2/4] 去重&降噪...")
    cleaned = clean_dedup(all_items)
    removed = len(all_items) - len(cleaned)
    print(f"    ➡️  去重后: {len(cleaned)}条 (去除{removed}条重复/噪声)")
    if not cleaned:
        print("    ⚠️  无新内容,跳过")
        return

    # === Step 3: Evaluate ===
    print("\n📊 [3/4] 价值评估...")
    evaluated = sorted([evaluate(i) for i in cleaned], key=lambda x: x['importance_score'], reverse=True)
    level_counts = {}
    for item in evaluated:
        lv = item['value_level']
        level_counts[lv] = level_counts.get(lv, 0) + 1
    for lv in sorted(level_counts.keys(), reverse=True):
        print(f"    ⭐{lv}: {level_counts[lv]}条")
    
    high_val = [x for x in evaluated if x['value_level'] >= 4]
    if high_val:
        print(f"\n    🔥 高价值 (前5):")
        for item in high_val[:5]:
            print(f"      ⭐{item['value_level']} [{item['source']}] {item['title'][:55]}")

    # === Step 4: Save ===
    print("\n💾 [4/4] 存储...")
    conn = get_db()
    saved_raw = 0
    saved_clean = 0
    try:
        saved_raw = save_raw(conn, all_items)
        saved_clean = save_cleaned(conn, evaluated)
        conn.commit()
        print(f"    ✅ 原始数据: {saved_raw}条 | 清洗数据: {saved_clean}条")
    except Exception as e:
        print(f"    ❌ 存储失败: {e}")
        conn.rollback()
    finally:
        conn.close()

    # === DB Status Report ===
    elapsed = time.time() - start_time
    print("\n" + "=" * 55)
    print("  📊  数据库状态")
    print("=" * 55)

    conn = get_db()
    c = conn.cursor()
    try:
        c.execute("SELECT COUNT(*) FROM raw_intelligence")
        total_raw = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM cleaned_intelligence")
        total_clean = c.fetchone()[0]
        c.execute("SELECT MAX(collected_at) FROM raw_intelligence")
        latest_raw = c.fetchone()[0]
        c.execute("SELECT MAX(cleaned_at) FROM cleaned_intelligence")
        latest_clean = c.fetchone()[0]
        c.execute("SELECT source, COUNT(*) FROM raw_intelligence GROUP BY source ORDER BY COUNT(*) DESC LIMIT 8")
        sources = [(r[0], r[1]) for r in c.fetchall()]
        c.execute("SELECT value_level, COUNT(*) FROM cleaned_intelligence GROUP BY value_level ORDER BY value_level")
        levels = [(r[0], r[1]) for r in c.fetchall()]
        c.execute("SELECT id, title, source, value_level, importance_score FROM cleaned_intelligence ORDER BY id DESC LIMIT 5")
        latest5 = [(r[0], str(r[1])[:40], str(r[2])[:15], r[3], r[4]) for r in c.fetchall()]
    except Exception:
        total_raw, total_clean, latest_raw, latest_clean = 0, 0, "N/A", "N/A"
        sources, levels, latest5 = [], [], []
    conn.close()

    print(f"  📦 原始数据:      {total_raw:,} 条")
    print(f"  🧹 已清洗:        {total_clean:,} 条")
    print(f"  🕐 最新采集:      {latest_raw or 'N/A'}")
    print(f"  🕐 最新清洗:      {latest_clean or 'N/A'}")
    print(f"  ⚡ 耗时:          {elapsed:.1f}s")
    print(f"  ➕ 本次新增:      原始 {saved_raw} / 清洗 {saved_clean}")
    
    if sources:
        print(f"\n  📋 信息源 TOP 8:")
        for s, c in sources:
            print(f"    {s:15s}: {c:6d}条")
    if levels:
        print(f"\n  📊 价值分布:")
        for lv, cnt in levels:
            bar = "█" * min(cnt // 500, 30) + "░" * max(30 - min(cnt // 500, 30), 0)
            print(f"    ⭐{lv}: {cnt:>6d}条  {bar}")
    if latest5:
        print(f"\n  🔝 最新清洗:")
        for rid, t, s, lv, sc in latest5:
            print(f"    [{rid}] ⭐{lv}({sc}) {t}")

    print("\n" + "=" * 55)
    print("  ✅  快速管线完成 (未执行推送)")
    print("=" * 55)

if __name__ == "__main__":
    run()
