#!/home/administrator/.hermes/hermes-agent/venv/bin/python3
"""
Hermes Ultimate Collector — 全能力聚合采集器
=============================================
把所有采集能力组合在一起：unified_collector_v5 + 新采集器 + 通用网页提取 + RSS
格林主人最高指令：全部能力并行激活，一起组合使用

用法:
  python3 hermes_ultimate_collector.py --all         # 全平台全量采集
  python3 hermes_ultimate_collector.py --wechat      # 仅微信公众号
  python3 hermes_ultimate_collector.py --xhs         # 仅小红书
  python3 hermes_ultimate_collector.py --douyin      # 仅抖音
  python3 hermes_ultimate_collector.py --web url     # 通用网页提取
"""

import sqlite3, json, sys, os, time, hashlib, re, html
from datetime import datetime
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError
from urllib.request import Request, urlopen
from urllib.parse import quote, urlparse

HERMES = Path("/home/administrator/.hermes")
DB_PATH = HERMES / "intelligence.db"
LOG_PATH = HERMES / "logs" / "ultimate_collector.log"

def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    LOG_PATH.parent.mkdir(exist_ok=True)
    with open(LOG_PATH, "a") as f:
        f.write(line + "\n")

def get_db():
    return sqlite3.connect(str(DB_PATH), timeout=30)

def is_dup(db, url):
    url_hash = hashlib.md5(url.encode()).hexdigest()
    cur = db.cursor()
    cur.execute("SELECT id FROM raw_intelligence WHERE url_hash=?", (url_hash,))
    return cur.fetchone() is not None

def insert_article(db, source, platform, title, url, content, author="", summary="", category_tags=""):
    if is_dup(db, url):
        return False
    url_hash = hashlib.md5(url.encode()).hexdigest()
    cur = db.cursor()
    try:
        cur.execute("""
            INSERT INTO raw_intelligence 
            (title, content, url, source, platform, author, category_tags, collected_at, url_hash)
            VALUES (?,?,?,?,?,?,?, datetime('now','localtime'), ?)
        """, (title[:500], content[:100000] if content else "", url, source, platform, author[:100], category_tags, url_hash))
        db.commit()
        return True
    except Exception as e:
        log(f"  ⚠️ 入库失败: {e}")
        return False

# ============================================================
# 采集器1: unified_collector_v5 (35+平台)
# ============================================================
def run_unified_collector():
    log("📡 [能力1] unified_collector_v5: 快速模式(15核心平台,60s)...")
    try:
        import subprocess
        t0 = time.time()
        # 只跑最重要的10个平台，每个给60s
        core_platforms = ["weibo", "ithome", "toutiao", "baidu", "zhihu", 
                         "bilibili", "sina_tech", "hackernews", "csdn", "github"]
        total_new = 0
        for p in core_platforms:
            try:
                r = subprocess.run(
                    [str(HERMES / "hermes-agent/venv/bin/python3"), 
                     str(HERMES / "scripts/unified_collector_v5.py"), "--platform", p],
                    capture_output=True, text=True, timeout=60,
                    cwd=str(HERMES)
                )
                # 提取new=数量
                for line in (r.stdout or "").split('\n'):
                    for m in [re.search(r'new=(\d+)', line)]:
                        if m:
                            total_new += int(m.group(1))
                log(f"  {p}: 完成")
            except subprocess.TimeoutExpired:
                log(f"  {p}: 超时")
            except Exception as e:
                log(f"  {p}: {e}")
        elapsed = time.time() - t0
        log(f"  ✅ 核心平台完成: {elapsed:.0f}s, 新={total_new}")
        return total_new
    except Exception as e:
        log(f"  ❌ unified_collector失败: {e}")
        return 0

# ============================================================
# 采集器2: wechat-mp-mcp (微信公众号MCP)
# ============================================================
def collect_wechat_mp():
    log("📡 [能力2] wechat-mp-mcp: 微信公众号采集...")
    try:
        sys.path.insert(0, str(HERMES / "scripts/collectors/wechat-mp-mcp/src"))
        sys.path.insert(0, str(HERMES / "scripts/collectors/wechat-mp-mcp"))
        from wechat_mp_mcp.client import WeixinClient
        log("  ✅ wechat_mp_mcp import成功")
        
        try:
            from wechat_mp_mcp.auth import load_auth
            auth = load_auth()
            client = WeixinClient(auth=auth)
        except Exception as e:
            log(f"  ⚠️ 微信未登录: {e}")
            log("  💡 请运行: python3 -c \"from wechat_mp_mcp.auth import load_auth; auth=load_auth()\"")
            log("     或先扫码登录")
            return 0
        
        # 检查登录状态
        if not client.is_logged_in():
            log("  ⚠️ 未登录微信公众号，跳过MCP采集")
            log("  💡 请先运行: python3 -m wechat_mp_mcp.login 扫码登录")
            return 0
        
        # 采集几个热门公众号
        accounts = ["量子位", "机器之心", "雷锋网", "36氪", "爱范儿", 
                     "CSDN", "InfoQ", "极客公园", "钛媒体", "虎嗅"]
        total = 0
        for acc in accounts:
            try:
                articles = client.search_account(acc)
                for art in articles:
                    db = get_db()
                    ok = insert_article(db, "wechat_mp", "weixin",
                                        art.get("title",""), art.get("link",""),
                                        art.get("body",""), art.get("author",""),
                                        category_tags="AI|科技")
                    db.close()
                    if ok:
                        total += 1
                log(f"  {acc}: {len(articles)}篇")
                time.sleep(1)
            except Exception as e:
                log(f"  {acc}: {e}")
        log(f"  ✅ 微信MCP: 共{total}篇新文章")
        return total
    except ImportError:
        log("  ⚠️ wechat_mp_mcp未安装，跳过")
        return 0
    except Exception as e:
        log(f"  ❌ 微信MCP失败: {e}")
        return 0

# ============================================================
# 采集器3: xiaohongshu-skill (小红书)
# ============================================================
def collect_xiaohongshu():
    log("📡 [能力3] xiaohongshu-skill: 小红书采集...")
    # 方案A: 使用xiaohongshu-skill（已修复相对引用）
    try:
        sys.path.insert(0, str(HERMES / "scripts/collectors/xiaohongshu-skill/scripts"))
        sys.path.insert(0, str(HERMES / "scripts/collectors/xiaohongshu-skill"))
        # 直接import（相对引用已修复）
        from client import XiaohongshuClient, DEFAULT_COOKIE_PATH
        import search
        
        log("  ✅ xiaohongshu-skill import成功，尝试采集...")
        
        # 检查登录状态
        try:
            client = XiaohongshuClient(cookie_path=DEFAULT_COOKIE_PATH)
            if not client.cookies or not client.check_cookie():
                log("  ⚠️ 小红书cookie过期，需要重新扫码登录")
                log("  💡 运行: python3 -c \"from client import XiaohongshuClient; XiaohongshuClient().login()\"")
                # 仍然尝试搜索（Playwright方式可以无需cookie）
        except Exception as e:
            log(f"  ⚠️ 小红书client初始化: {e}")
        
        db = get_db()
        total = 0
        
        keywords = ["AI", "人工智能", "科技", "数码", "编程", "Python", "深度学习", "ChatGPT", "大模型"]
        for kw in keywords[:3]:  # 先试3个，避免太慢
            try:
                notes = search.search(kw, limit=5)
                for note in (notes or []):
                    title = note.get("title", "") or note.get("display_title", "")
                    note_id = note.get("id", "") or note.get("note_id", "")
                    url = f"https://www.xiaohongshu.com/explore/{note_id}"
                    content = note.get("desc", "") or note.get("description", "")
                    author = note.get("user", {}).get("nickname", "") if isinstance(note.get("user"), dict) else ""
                    ok = insert_article(db, "xhs_browser", "xiaohongshu",
                                        title, url, content, author,
                                        category_tags="AI|科技")
                    if ok:
                        total += 1
                log(f"  '{kw}': {len(notes or [])}篇")
            except Exception as e:
                log(f"  '{kw}': {e}")
        db.close()
        log(f"  ✅ 小红书Playwright: 共{total}篇新文章")
        return total
    except ImportError as e:
        log(f"  ⚠️ xiaohongshu-skill search模块不可用: {e}")
    except Exception as e:
        log(f"  ❌ xiaohongshu-skill失败: {e}")
    
    # 方案B: 尝试xhs库（需cookie登录）
    log("  ↻ 尝试xhs库方案（需扫码登录）...")
    try:
        import xhs
        from xhs import XhsClient
        
        c = XhsClient()
        # 检查是否有有效cookie
        from xhs.core import SearchSortType, SearchNoteType
        notes = c.get_note_by_keyword("AI", page=1, page_size=3, sort=SearchSortType.GENERAL, note_type=SearchNoteType.ALL)
        if notes:
            db = get_db()
            total = 0
            keywords = ["AI", "人工智能", "科技", "数码", "Python", "深度学习", "大模型"]
            for kw in keywords[:2]:
                try:
                    notes = c.get_note_by_keyword(kw, page=1, page_size=10, sort=SearchSortType.GENERAL, note_type=SearchNoteType.ALL)
                    for note in (notes or []):
                        title = getattr(note, 'title', '') or (note.get('title','') if isinstance(note, dict) else '')
                        note_id = getattr(note, 'note_id', '') or (note.get('note_id','') if isinstance(note, dict) else '')
                        url = f"https://www.xiaohongshu.com/explore/{note_id}"
                        content = getattr(note, 'desc', '') or (note.get('desc','') if isinstance(note, dict) else '')
                        ok = insert_article(db, "xhs_api", "xiaohongshu", title, url, content, category_tags="AI|科技")
                        if ok: total += 1
                    log(f"  '{kw}': {len(notes or [])}篇")
                except Exception as e:
                    log(f"  '{kw}': {e}")
            db.close()
            log(f"  ✅ xhs库API: 共{total}篇")
            return total
        else:
            log("  ⚠️ xhs库cookie无效，跳过")
    except Exception as e:
        log(f"  ⚠️ xhs库方案失败: {e}")
    
    log("  ❌ 小红书无可用方案，请扫码登录")
    return 0

# ============================================================
# 采集器4: 通用网页提取 (trafilatura/readability)
# ============================================================
def collect_web_article(url, source="web_extract"):
    log(f"📡 [能力4] 通用网页提取: {url[:80]}...")
    try:
        import trafilatura
        downloaded = trafilatura.fetch_url(url)
        if downloaded:
            text = trafilatura.extract(downloaded)
            if text and len(text) > 100:
                title = text.split('\n')[0][:100] if text else "网页提取"
                db = get_db()
                ok = insert_article(db, source, "web",
                                    title, url, text,
                                    category_tags="通用")
                db.close()
                if ok:
                    log(f"  ✅ 提取成功: {len(text)}字")
                    return 1
    except ImportError:
        pass
    except Exception as e:
        log(f"  ⚠️ trafilatura失败: {e}")
    
    # fallback: readability
    try:
        from readability import Document
        import requests
        resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        doc = Document(resp.text)
        title = doc.title()[:100] if doc.title() else "网页"
        summary = doc.summary()
        content = re.sub(r'<[^>]+>', '', summary)[:100000]
        if len(content) > 100:
            db = get_db()
            ok = insert_article(db, source, "web", title, url, content, category_tags="通用")
            db.close()
            if ok:
                log(f"  ✅ readability提取: {len(content)}字")
                return 1
    except Exception as e:
        log(f"  ⚠️ readability失败: {e}")
    return 0

# ============================================================
# 采集器5: RSS采集增强
# ============================================================
def collect_rss_feeds():
    log("📡 [能力5] RSS采集增强...")
    import feedparser
    
    feeds = [
        ("36氪", "https://36kr.com/feed", "36kr"),
        ("博客园", "https://feed.cnblogs.com/blog/sitehome/rss", "cnblogs"),
        ("知乎日报", "https://daily.zhihu.com/rss", "zhihu_daily"),
        ("Solidot", "https://www.solidot.org/index.rss", "solidot"),
        ("InfoQ", "https://www.infoq.cn/feed", "infoq"),
    ]
    
    db = get_db()
    total = 0
    for name, url, source in feeds:
        try:
            feed = feedparser.parse(url)
            count = 0
            for entry in feed.entries[:20]:
                ok = insert_article(db, source, name,
                                    entry.get("title","")[:500],
                                    entry.get("link",""),
                                    entry.get("summary","") or entry.get("description",""),
                                    entry.get("author","") or "",
                                    category_tags="RSS")
                if ok:
                    count += 1
            total += count
            log(f"  {name}: {count}篇")
        except Exception as e:
            log(f"  {name}: {e}")
    db.close()
    log(f"  ✅ RSS: 共{total}篇新文章")
    return total

# ============================================================
# 采集器6: 浏览器采集 (Playwright)
# ============================================================
def collect_via_browser():
    log("📡 [能力6] Playwright浏览器采集...")
    total = 0
    
    targets = [
        ("CSDN", "https://www.csdn.net/", "csdn", 
         """() => {
    const items = [];
    document.querySelectorAll('a[href*="/article/details/"]').forEach(a => {
        if(a.href && a.textContent.trim().length > 5) items.push({title:a.textContent.trim().substring(0,80), url:a.href});
    });
    return items.slice(0,20);
}"""),
        ("知乎", "https://www.zhihu.com/explore", "zhihu",
         """() => {
    const items = [];
    document.querySelectorAll('a[href*="zhihu.com/question"]').forEach(a => {
        if(a.href && a.textContent.trim().length > 5) items.push({title:a.textContent.trim().substring(0,80), url:a.href});
    });
    return items.slice(0,20);
}"""),
        ("SegmentFault", "https://segmentfault.com/", "segmentfault",
         """() => {
    const items = [];
    document.querySelectorAll('h3 a[href*="/a/"]').forEach(a => {
        if(a.href && a.textContent.trim().length > 5) {
            items.push({title:a.textContent.trim().substring(0,80), url:a.href.startsWith('http') ? a.href : 'https://segmentfault.com' + a.href});
        }
    });
    return items.slice(0,15);
}"""),
    ]
    
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            for name, url, source, js in targets:
                try:
                    page = browser.new_page()
                    page.goto(url, timeout=30000, wait_until="domcontentloaded")
                    time.sleep(2)
                    result = page.evaluate(js)
                    page.close()
                    
                    db = get_db()
                    count = 0
                    for item in (result or []):
                        if item.get("title") and item.get("url") and len(item["title"]) > 5:
                            ok = insert_article(db, f"{source}_browser", name,
                                                item["title"][:500], item["url"],
                                                "", category_tags="浏览器采集")
                            if ok:
                                count += 1
                    total += count
                    db.close()
                    log(f"  {name}: {count}篇")
                except Exception as e:
                    log(f"  {name}: {e}")
            browser.close()
    except Exception as e:
        log(f"  ❌ Playwright失败: {e}")
    
    log(f"  ✅ 浏览器采集: 共{total}篇新文章")
    return total

# ============================================================
# 主入口
# ============================================================
def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "--all"
    
    log("=" * 60)
    log("🚀 HERMES ULTIMATE COLLECTOR — 全能力聚合采集")
    log(f"   {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log("=" * 60)
    
    results = {}
    t0 = time.time()
    
    if mode == "--all":
        # 并行启动多个采集器
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = {
                executor.submit(run_unified_collector): "unified_v5",
                executor.submit(collect_rss_feeds): "rss",
                executor.submit(collect_via_browser): "browser",
                executor.submit(collect_xiaohongshu): "xiaohongshu",
            }
            for future in as_completed(futures):
                name = futures[future]
                try:
                    results[name] = future.result(timeout=300)
                except TimeoutError:
                    results[name] = "timeout"
                except Exception as e:
                    results[name] = f"error: {e}"
        
        # 串行执行依赖登录的微信采集
        results["wechat_mp"] = collect_wechat_mp()
        
    elif mode == "--wechat":
        results["wechat_mp"] = collect_wechat_mp()
    elif mode == "--xhs":
        results["xiaohongshu"] = collect_xiaohongshu()
    elif mode == "--web" and len(sys.argv) > 2:
        results["web_extract"] = collect_web_article(sys.argv[2])
    elif mode == "--rss":
        results["rss"] = collect_rss_feeds()
    elif mode == "--browser":
        results["browser"] = collect_via_browser()
    else:
        print("用法:")
        print("  python3 hermes_ultimate_collector.py --all      # 全平台")
        print("  python3 hermes_ultimate_collector.py --wechat   # 微信")
        print("  python3 hermes_ultimate_collector.py --xhs      # 小红书")
        print("  python3 hermes_ultimate_collector.py --web url  # 网页提取")
        print("  python3 hermes_ultimate_collector.py --rss      # RSS")
        print("  python3 hermes_ultimate_collector.py --browser  # 浏览器")
        return
    
    elapsed = time.time() - t0
    log("=" * 60)
    log(f"📊 采集汇总 ({elapsed:.0f}s):")
    for name, count in results.items():
        log(f"  {name}: {count}")
    log("=" * 60)

if __name__ == "__main__":
    main()
