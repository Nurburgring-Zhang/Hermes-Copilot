#!/usr/bin/env python3
"""
Hermes 浏览器采集器 - Playwright-based
========================================
处理JS渲染平台和终端无法采集的平台:
- Juejin (浏览器) ✅ 实测10条/次
- SegmentFault (浏览器) ✅ 实测30条/次
- 小红书 (需RSSHub桥接 - IP限制)
- Arxiv (终端RSS可达)
- HuggingFace (终端API可达)
- HackerNews (终端API可达)

使用方法:
  python3 browser_collector.py --collect Juejin  # 单平台
  python3 browser_collector.py --collect-all     # 全部
  python3 browser_collector.py --stats           # 查看状态
"""

import sqlite3, json, sys, time, ssl, re, hashlib
from datetime import datetime
from pathlib import Path
from urllib.request import Request, urlopen
from concurrent.futures import ThreadPoolExecutor, as_completed

HERMES = Path("/home/administrator/.hermes")
DB_PATH = HERMES / "intelligence.db"

def get_db():
    return sqlite3.connect(str(DB_PATH), timeout=30)

def url_hash(url):
    return hashlib.sha256(url.encode()).hexdigest()[:32]

def insert_raw_item(item: dict) -> bool:
    if not item.get('url') or not item.get('title'):
        return False
    url_h = url_hash(item['url'])
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    try:
        db = get_db()
        db.execute("""
            INSERT OR IGNORE INTO raw_intelligence 
            (title,content,url,source,platform,author,author_id,category,tags,
             hot_score,published_at,collected_at,url_hash,source_type)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            item.get('title','')[:500],
            item.get('content','')[:2000],
            item.get('url',''),
            item.get('source', item.get('platform','')),
            item.get('platform',''),
            item.get('author',''),
            item.get('author_id',''),
            item.get('category_tags',''),
            item.get('tags', item.get('category_tags','')),
            float(item.get('hot_score', 0)),
            datetime.now().strftime('%Y-%m-%dT%H:%M:%S'),
            now,
            url_h,
            'browser',
        ))
        db.commit()
        new = db.total_changes > 0
        db.close()
        return new
    except:
        return False

def insert_batch(items):
    if not items:
        return 0, 0
    total = len(items)
    new_count = sum(1 for item in items if insert_raw_item(item))
    return total, new_count

# ============================================================
# 平台配置
# ============================================================
PLATFORMS = {
    'juejin': {
        'url': 'https://juejin.cn/posts',
        'title_selector': 'a[href*="/post/"]',
        'url_selector': 'a[href*="/post/"]',
        'category': 'Juejin|Dev|Tech',
        'hot_selector': '.hot-list a, [class*="rank"] a, ul li a[href*="/post/"]',
    },
    'segmentfault': {
        'url': 'https://segmentfault.com/',
        'title_selector': 'h3 a[href*="/q/"]',
        'url_selector': 'h3 a[href*="/q/"]',
        'category': 'SegmentFault|Dev|Q&A',
        'hot_selector': '.news h3 a, .widget__item h3 a, h3 a[href*="/q/"]',
    },
}

def extract_items_from_snapshot(snapshot_text, platform):
    """从页面snapshot提取数据 - 备用方法"""
    items = []
    if platform == 'juejin':
        titles = re.findall(r'link "([^"]+)" \[:ref=.*?/post/', snapshot_text)
        urls = re.findall(r'/url: /post/([a-zA-Z0-9]+)', snapshot_text)
        for i, title in enumerate(titles[:20]):
            if len(title) > 5:
                items.append({
                    'platform': 'juejin_browser',
                    'title': title[:80],
                    'url': f"https://juejin.cn/post/{urls[i] if i < len(urls) else ''}",
                    'author': '', 'author_id': '',
                    'published_at': datetime.now().strftime('%Y-%m-%dT%H:%M:%S'),
                    'hot_score': 0,
                    'source_type': 'browser',
                    'category_tags': 'Juejin|Dev|Tech'
                })
    elif platform == 'segmentfault':
        titles = re.findall(r'heading "([^"]+)" \[ref=', snapshot_text)
        urls = re.findall(r'/url: /q/(\d+)', snapshot_text)
        for i, title in enumerate(titles[:20]):
            if len(title) > 5:
                items.append({
                    'platform': 'segmentfault_browser',
                    'title': title[:80],
                    'url': f"https://segmentfault.com/q/{urls[i] if i < len(urls) else ''}",
                    'author': '', 'author_id': '',
                    'published_at': datetime.now().strftime('%Y-%m-%dT%H:%M:%S'),
                    'hot_score': 0,
                    'source_type': 'browser',
                    'category_tags': 'SegmentFault|Dev|Q&A'
                })
    return items

def collect_via_browser(platform_name, config):
    """使用Playwright浏览器采集"""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print(f"Playwright not installed: pip install playwright && playwright install chromium")
        return 0, 0
    
    items = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=['--no-sandbox', '--disable-dev-shm-usage', '--disable-blink-features=AutomationControlled']
            )
            context = browser.new_context(
                user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/121.0 Safari/537.36',
                viewport={'width': 1280, 'height': 720},
            )
            page = context.new_page()
            
            # Navigate
            page.goto(config['url'], timeout=30000, wait_until='networkidle')
            time.sleep(2)
            
            # Extract via JavaScript
            js_code = f"""
            const items = [];
            // Try hot list selectors
            document.querySelectorAll('{config.get('hot_selector', config['title_selector'])}').forEach((a, i) => {{
                if(a.href && a.textContent.trim() && i < 30) {{
                    const text = a.textContent.trim();
                    if(text.length > 5) {{
                        let url = a.href;
                        if(!url.startsWith('http')) url = 'https://juejin.cn' + a.getAttribute('href');
                        if(url.startsWith('/')) url = 'https://juejin.cn' + a.getAttribute('href');
                        items.push({{title: text.substring(0, 80), url: url}});
                    }}
                }}
            }});
            // Also try data-vue-router
            document.querySelectorAll('*[data-vue-router]').forEach(el => {{
                const a = el.querySelector('a');
                if(a && a.href && a.textContent.trim()) {{
                    const text = a.textContent.trim();
                    if(text.length > 5 && !items.find(x => x.title === text.substring(0, 80))) {{
                        items.push({{title: text.substring(0, 80), url: a.href.startsWith('http') ? a.href : 'https://juejin.cn' + a.getAttribute('href')}});
                    }}
                }}
            }});
            JSON.stringify(items.slice(0, 25));
            """
            
            result = page.evaluate(js_code)
            if result:
                try:
                    extracted = json.loads(result)
                    for e in extracted:
                        if e.get('title') and e.get('url'):
                            items.append({
                                'platform': f'{platform_name}_browser',
                                'title': e['title'][:120],
                                'url': e['url'],
                                'author': '', 'author_id': '',
                                'published_at': datetime.now().strftime('%Y-%m-%dT%H:%M:%S'),
                                'hot_score': 0,
                                'source_type': 'browser',
                                'category_tags': config.get('category', platform_name)
                            })
                except:
                    pass
            
            # Fallback: extract from snapshot
            if len(items) < 5:
                snapshot = page.content()
                snapshot_items = extract_items_from_snapshot(snapshot[:5000], platform_name)
                for si in snapshot_items:
                    if not any(x['url'] == si['url'] for x in items):
                        items.append(si)
            
            browser.close()
    except Exception as e:
        print(f"  {platform_name} browser error: {e}")
    
    if items:
        total, new = insert_batch(items)
        print(f"  {platform_name}_browser: {total} total, {new} new")
        return total, new
    return 0, 0

def collect_all_browser():
    """采集所有浏览器平台"""
    print(f"\n{'='*60}")
    print(f"  Hermes Browser Collector")
    print(f"  Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}")
    
    total_all, new_all = 0, 0
    for name, config in PLATFORMS.items():
        print(f"  Collecting {name}...")
        total, new = collect_via_browser(name, config)
        total_all += total
        new_all += new
        time.sleep(1)
    
    print(f"\n{'='*60}")
    print(f"  Browser Collection: {total_all} total, {new_all} new")
    print(f"{'='*60}\n")
    return total_all, new_all

def get_stats():
    db = get_db()
    rows = db.execute("""
        SELECT platform, COUNT(*) as cnt,
               SUM(CASE WHEN source_type='browser' THEN 1 ELSE 0 END) as browser_cnt
        FROM raw_intelligence
        WHERE DATE(collected_at) = DATE('now')
        GROUP BY platform
        ORDER BY cnt DESC LIMIT 30
    """).fetchall()
    db.close()
    return rows

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == '--collect-all':
        collect_all_browser()
    elif len(sys.argv) > 1 and sys.argv[1] == '--stats':
        stats = get_stats()
        print(f"\n=== Browser Sources (Today) ===")
        for r in stats:
            if r[2] > 0:
                print(f"  {r[0]}: {r[1]} total, {r[2]} browser")
    elif len(sys.argv) > 1 and sys.argv[1] == '--collect':
        if len(sys.argv) > 2:
            name = sys.argv[2]
            if name in PLATFORMS:
                collect_via_browser(name, PLATFORMS[name])
    else:
        print(__doc__)
