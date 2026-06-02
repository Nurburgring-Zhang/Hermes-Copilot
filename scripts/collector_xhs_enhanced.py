#!/usr/bin/env python3
"""
小红书增强采集器 - 多关键词 + Playwright浏览器 + HTTP API双策略

策略:
  1. 优先使用Playwright浏览器采集(多关键词搜索 + 发现页滚动)
  2. 浏览器不可用时fallback到HTTP API采集(搜索API + 发现页API)
  3. 15个偏好关键词,每个取10条

数据库: /home/administrator/.hermes/intelligence.db
表:     raw_intelligence

依赖:
  - playwright (pip install playwright && playwright install chromium)
"""

import re
import json
import time
import hashlib
import ssl
import sqlite3
import sys
from datetime import datetime
from urllib.request import Request, urlopen
from typing import List, Dict, Optional
from pathlib import Path

# ============================================================
# 配置
# ============================================================
DB_PATH = Path("/home/administrator/.hermes/intelligence.db")
HERMES = Path("/home/administrator/.hermes")

# 15个用户偏好关键词
XHS_KEYWORDS = [
    "AI", "新能源汽车", "军事", "美女", "摄影",
    "格斗", "游戏", "数码", "篮球", "旅游",
    "美食", "历史", "科技", "手机", "汽车",
]

# 每个关键词取10条
MAX_PER_KEYWORD = 10

UA_POOL = [
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15F79 Safari/604.1",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]

# 小红书API端点（已验证可用的）
XHS_API_ENDPOINTS = [
    {
        "name": "web_search_v1",
        "url_template": "https://www.xiaohongshu.com/api/sns/web/v1/search/notes?keyword={kw}&page=1&page_size=20&sort=general",
        "referer": "https://www.xiaohongshu.com/",
    },
]


# ============================================================
# 工具函数
# ============================================================
def _url_hash(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()[:32]


def _normalize_date(date_str: str) -> str:
    if not date_str or date_str == "None":
        return ""
    date_str = date_str.strip()
    for fmt in [
        "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%d %H:%M:%S", "%Y-%m-%d",
    ]:
        try:
            dt = datetime.strptime(date_str[:19], fmt)
            return dt.strftime("%Y-%m-%dT%H:%M:%S")
        except:
            pass
    m = re.search(r"(\d{4}-\d{2}-\d{2})", date_str)
    if m:
        return m.group(1) + "T00:00:00"
    return date_str


def _extract_tags(title: str, content: str = "") -> str:
    """从标题/内容提取行业标签"""
    text = (title + " " + (content or "")).lower()
    tags = []
    if any(k in text for k in ["ai", "gpt", "chatgpt", "大模型", "人工智能", "llm"]):
        tags.append("AI")
    if any(k in text for k in ["手机", "iphone", "小米", "华为", "测评", "评测", "数码"]):
        tags.append("Tech")
    if any(k in text for k in ["摄影", "相机", "镜头", "拍照", "调色"]):
        tags.append("Photography")
    if any(k in text for k in ["汽车", "特斯拉", "新能源", "比亚迪", "试驾"]):
        tags.append("Auto")
    if any(k in text for k in ["美食", "探店", "咖啡", "烘焙", "餐厅"]):
        tags.append("Food")
    if any(k in text for k in ["旅行", "自驾", "露营", "酒店", "旅游"]):
        tags.append("Travel")
    if any(k in text for k in ["格斗", "mma", "拳击", "搏击", "ufc"]):
        tags.append("Combat")
    if any(k in text for k in ["游戏", "steam", "switch", "ps5", "手游"]):
        tags.append("Game")
    if any(k in text for k in ["军事", "战争", "国防", "武器", "军队"]):
        tags.append("Military")
    if any(k in text for k in ["篮球", "nba", "cba", "球赛"]):
        tags.append("Basketball")
    if any(k in text for k in ["历史", "古代", "历史"]):
        tags.append("History")
    if any(k in text for k in ["美女", "小姐姐", "穿搭"]):
        tags.append("Beauty")
    return "|".join(tags) if tags else "XHS|General"


def _http_fetch(url: str, headers: dict = None, timeout: int = 15) -> str:
    """HTTP GET请求"""
    ua = UA_POOL[int(time.time()) % len(UA_POOL)]
    h = {"User-Agent": ua}
    if headers:
        h.update(headers)
    try:
        req = Request(url, headers=h)
        ctx = ssl.create_default_context()
        with urlopen(req, timeout=timeout, context=ctx) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        return ""


def _insert_db(items: List[dict]) -> int:
    """写入数据库"""
    if not items:
        return 0
    new_count = 0
    try:
        db = sqlite3.connect(str(DB_PATH), timeout=30)
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for item in items:
            title = item.get("title", "")
            url = item.get("url", "")
            if not title or not url:
                continue
            url_h = _url_hash(url)
            pub_at = _normalize_date(item.get("published_at", ""))
            try:
                db.execute(
                    """INSERT OR IGNORE INTO raw_intelligence
                       (title,content,url,source,platform,author,author_id,category,tags,
                        hot_score,view_count,like_count,collect_count,comment_count,share_count,
                        published_at,collected_at,url_hash,source_type)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        title[:500],
                        item.get("content", "")[:2000],
                        url,
                        item.get("source", ""),
                        item.get("platform", "xiaohongshu"),
                        item.get("author", ""),
                        item.get("author_id", ""),
                        item.get("category_tags", ""),
                        item.get("tags", ""),
                        float(item.get("hot_score", 0)),
                        int(item.get("view_count", 0)),
                        int(item.get("like_count", 0)),
                        int(item.get("collect_count", 0)),
                        int(item.get("comment_count", 0)),
                        int(item.get("share_count", 0)),
                        pub_at,
                        now,
                        url_h,
                        item.get("source_type", "xhs_enhanced"),
                    ),
                )
                db.commit()
                if db.total_changes > 0:
                    new_count += 1
            except:
                pass
        db.close()
    except Exception as e:
        print(f"  [XHS DB] Error: {e}")
    return new_count


# ============================================================
# 策略1: Playwright浏览器采集(优先)
# ============================================================
def collect_xhs_playwright(keywords: List[str] = None, max_per_kw: int = 10) -> List[dict]:
    """
    使用Playwright打开小红书页面,从JS渲染的DOM中提取笔记数据
    参考 enhanced_collector_v7.py 的 collect_xiaohongshu_enhanced 实现
    """
    items = []
    seen_urls = set()
    seen_titles = set()

    if keywords is None:
        keywords = XHS_KEYWORDS

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("  [XHS] Playwright not installed, skipping browser strategy")
        return items

    try:
        with sync_playwright() as p:
            # 使用headless=new模式
            browser = p.chromium.launch(
                headless=True,
                args=[
                    "--headless=new",
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-web-security",
                    "--disable-features=IsolateOrigins,site-per-process",
                ],
            )
            context = browser.new_context(
                viewport={"width": 393, "height": 852},
                user_agent=UA_POOL[0],
                locale="zh-CN",
                permissions=["geolocation"],
            )
            context.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                window.chrome = {runtime: {}};
            """)

            page = context.new_page()

            # ============================================
            # Step 1: 发现页滚动采集
            # ============================================
            print("  [XHS] Phase 1: Discover page scroll...")
            try:
                resp = page.goto(
                    "https://www.xiaohongshu.com/explore",
                    timeout=25000,
                    wait_until="domcontentloaded",
                )
                time.sleep(5)

                # 滚动加载更多
                for _ in range(5):
                    page.evaluate("window.scrollBy(0, 800)")
                    time.sleep(1.5)

                content = page.content()
                notes = _extract_notes_from_html(content)
                for n in notes:
                    url = n.get("url", "")
                    title = n.get("title", "")
                    if url and url not in seen_urls and title not in seen_titles:
                        seen_urls.add(url)
                        seen_titles.add(title)
                        n["source_type"] = "playwright_discover"
                        items.append(n)
                print(f"  [XHS] Discover page: {len(notes)} found")
            except Exception as e:
                print(f"  [XHS] Discover page error: {e}")

            # ============================================
            # Step 2: 多关键词搜索
            # ============================================
            print(f"  [XHS] Phase 2: Multi-keyword search ({len(keywords)} keywords)...")
            for kw in keywords:
                if len(seen_urls) >= len(keywords) * max_per_kw:
                    break
                try:
                    encoded_kw = kw
                    from urllib.parse import quote
                    encoded_kw = quote(kw, safe="")

                    search_url = (
                        f"https://www.xiaohongshu.com/search_result"
                        f"?keyword={encoded_kw}&source=web_search_result_notes"
                    )
                    page.goto(search_url, timeout=20000, wait_until="domcontentloaded")
                    time.sleep(3)

                    # 滚动几次加载更多
                    for _ in range(3):
                        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                        time.sleep(1.5)

                    content = page.content()
                    notes = _extract_notes_from_html(content)

                    count = 0
                    for n in notes:
                        if count >= max_per_kw:
                            break
                        url = n.get("url", "")
                        title = n.get("title", "")
                        if url and url not in seen_urls and title not in seen_titles:
                            seen_urls.add(url)
                            seen_titles.add(title)
                            n["source_type"] = "playwright_search"
                            n["category_tags"] = "Xiaohongshu|" + _extract_tags(title)
                            n["tags"] = _extract_tags(title, n.get("content", ""))
                            items.append(n)
                            count += 1

                    print(f"    [{kw}] {count} items")
                except Exception as e:
                    print(f"    [{kw}] Error: {e}")

                time.sleep(1)

            browser.close()

    except Exception as e:
        print(f"  [XHS] Playwright error: {e}")

    return items


def _extract_notes_from_html(content: str) -> List[dict]:
    """
    从小红书页面HTML提取笔记数据
    支持: __INITIAL_STATE__ JSON + DOM正则提取
    """
    items = []

    # ============================================
    # 方法1: 从 __INITIAL_STATE__ 提取
    # ============================================
    state_match = re.search(
        r"window\.__INITIAL_STATE__\s*=\s*JSON\.parse\(\s*'(.+?)'\s*\)",
        content,
        re.DOTALL,
    )
    if not state_match:
        state_match = re.search(
            r"window\.__INITIAL_STATE__\s*=\s*({.*?});?\s*</script>",
            content,
            re.DOTALL,
        )

    if state_match:
        try:
            import html as html_module

            json_str = state_match.group(1)
            # 尝试unescape
            json_str = html_module.unescape(json_str)
            # 处理转义
            json_str = json_str.replace('\\"', '"').replace("\\'", "'")
            data = json.loads(json_str)

            # 遍历各种可能的路径
            note_items = []

            # 路径: feed > noteResult > items
            feed = data.get("feed", data.get("noteFeed", {}))
            if isinstance(feed, dict):
                note_result = feed.get("noteResult", {})
                if isinstance(note_result, dict):
                    note_items = note_result.get("items", [])

            # 路径: search > notes
            if not note_items:
                search = data.get("search", {})
                if isinstance(search, dict):
                    note_items = search.get("notes", search.get("items", []))

            # 路径: note > noteListMap
            if not note_items:
                note_section = data.get("note", {})
                if isinstance(note_section, dict):
                    note_map = note_section.get("noteListMap", {})
                    if isinstance(note_map, dict):
                        for note_id, note_data in note_map.items():
                            if isinstance(note_data, dict):
                                note_items.append(note_data)

            # 递归查找所有含items的字典
            if not note_items:
                def find_items(obj, depth=0):
                    if depth > 5:
                        return []
                    results = []
                    if isinstance(obj, dict):
                        if "items" in obj and isinstance(obj["items"], list):
                            results.extend(obj["items"])
                        for v in obj.values():
                            results.extend(find_items(v, depth + 1))
                    return results
                note_items = find_items(data)

            for note in note_items:
                if not isinstance(note, dict):
                    continue
                title = (
                    note.get("title")
                    or note.get("display_title")
                    or note.get("displayTitle")
                    or ""
                )
                if not title:
                    continue

                note_id = (
                    note.get("id")
                    or note.get("note_id")
                    or note.get("noteId")
                    or ""
                )
                url = (
                    f"https://www.xiaohongshu.com/explore/{note_id}"
                    if note_id
                    else ""
                )

                author = (
                    note.get("user", {})
                    .get("nickname", note.get("author", ""))
                )
                author_id = (
                    note.get("user", {}).get("userId", note.get("userId", ""))
                )

                interact = note.get(
                    "interact_info",
                    note.get("interactInfo", {}),
                )
                if not isinstance(interact, dict):
                    interact = {}
                likes = int(interact.get("liked_count", interact.get("likeCount", 0)))
                collects = int(
                    interact.get("collected_count", interact.get("collectedCount", 0))
                )
                comments = int(
                    interact.get("comment_count", interact.get("commentCount", 0))
                )

                pub_time = (
                    note.get("time")
                    or note.get("create_time")
                    or note.get("createTime")
                    or ""
                )
                desc = (
                    note.get("desc")
                    or note.get("description")
                    or ""
                )

                items.append(
                    {
                        "platform": "xiaohongshu",
                        "title": title[:120],
                        "content": desc[:300],
                        "url": url,
                        "author": author if isinstance(author, str) else "",
                        "author_id": author_id if isinstance(author_id, str) else "",
                        "published_at": _normalize_date(str(pub_time)),
                        "hot_score": likes + collects * 3 + comments * 2,
                        "like_count": likes,
                        "collect_count": collects,
                        "comment_count": comments,
                        "share_count": 0,
                        "source_type": "initial_state",
                        "category_tags": "Xiaohongshu|Explore",
                        "tags": _extract_tags(title, desc),
                        "source": "xiaohongshu",
                    }
                )

        except Exception as e:
            pass

    # ============================================
    # 方法2: 从DOM直接提取(兜底)
    # ============================================
    if len(items) < 5:
        # 提取note ID
        note_ids = re.findall(r'/explore/([a-f0-9]{24})', content)
        titles = re.findall(
            r'<div[^>]*class="[^"]*title[^"]*"[^>]*>([^<]{5,100})<',
            content,
        )
        if not titles:
            titles = re.findall(
                r'data-title="([^"]{5,100})"',
                content,
            )

        for i, nid in enumerate(note_ids[:30]):
            url = f"https://www.xiaohongshu.com/explore/{nid}"
            t = titles[i][:80] if i < len(titles) else f"XHS-{nid[:8]}"
            seen_check = url
            if any(it.get("url") == url for it in items):
                continue
            items.append(
                {
                    "platform": "xiaohongshu",
                    "title": t,
                    "content": "",
                    "url": url,
                    "author": "",
                    "author_id": nid,
                    "published_at": "",
                    "hot_score": 0,
                    "like_count": 0,
                    "collect_count": 0,
                    "comment_count": 0,
                    "share_count": 0,
                    "source_type": "dom_extract",
                    "category_tags": "Xiaohongshu|Explore",
                    "tags": "XHS|DOM",
                    "source": "xiaohongshu",
                }
            )

    return items


# ============================================================
# 策略2: HTTP API采集(浏览器不可用时fallback)
# ============================================================
def collect_xhs_api(keywords: List[str] = None, max_per_kw: int = 10) -> List[dict]:
    """
    通过小红书HTTP API采集搜索结果
    使用多个API端点轮换
    """
    items = []
    seen_urls = set()
    seen_titles = set()

    if keywords is None:
        keywords = XHS_KEYWORDS

    for kw in keywords:
        collected = 0
        for endpoint in XHS_API_ENDPOINTS:
            if collected >= max_per_kw:
                break
            try:
                url = endpoint["url_template"].format(kw=kw)
                out = _http_fetch(
                    url,
                    {
                        "User-Agent": UA_POOL[1],
                        "Referer": endpoint["referer"],
                        "Accept": "application/json, text/plain, */*",
                        "Origin": "https://www.xiaohongshu.com",
                    },
                    timeout=10,
                )

                if not out or len(out) < 50:
                    continue

                try:
                    d = json.loads(out)
                except json.JSONDecodeError:
                    json_match = re.search(r'\{.*"items".*\}', out, re.DOTALL)
                    if json_match:
                        try:
                            d = json.loads(json_match.group())
                        except:
                            continue
                    else:
                        continue

                # 解析搜索结果
                notes = []
                if isinstance(d.get("data"), dict):
                    notes = d["data"].get("items", d["data"].get("notes", []))
                elif isinstance(d.get("data"), list):
                    notes = d["data"]
                elif isinstance(d.get("items"), list):
                    notes = d["items"]
                elif isinstance(d.get("notes"), list):
                    notes = d["notes"]

                if not notes and isinstance(d.get("result"), dict):
                    notes = d["result"].get("items", [])

                count = 0
                for note in notes:
                    if count >= max_per_kw - collected:
                        break
                    if not isinstance(note, dict):
                        continue

                    title = (
                        note.get("title")
                        or note.get("display_title")
                        or note.get("note_card", {}).get("title", "")
                    )
                    if not title:
                        continue

                    note_id = (
                        note.get("id")
                        or note.get("note_id")
                        or note.get("note_card", {}).get("note_id", "")
                    )
                    url = (
                        f"https://www.xiaohongshu.com/discovery/item/{note_id}"
                        if note_id
                        else ""
                    )

                    if not url or url in seen_urls or title in seen_titles:
                        continue
                    seen_urls.add(url)
                    seen_titles.add(title)

                    author = (
                        note.get("user", {}).get("nickname", "")
                        or note.get("author", "")
                        or note.get("note_card", {}).get("user", {}).get("nickname", "")
                    )

                    interact = note.get("interact_info", note.get("liked_count", {}))
                    if not isinstance(interact, dict):
                        interact = {}
                    likes = int(interact.get("liked_count", 0))
                    collects = int(interact.get("collected_count", 0))
                    comments = int(interact.get("comment_count", 0))

                    pub_time = (
                        note.get("time")
                        or note.get("create_time")
                        or note.get("note_card", {}).get("time", "")
                    )
                    content = (
                        note.get("desc")
                        or note.get("description")
                        or note.get("note_card", {}).get("desc", "")
                    )[:300]

                    items.append(
                        {
                            "platform": "xiaohongshu",
                            "title": title[:120],
                            "content": content,
                            "url": url,
                            "author": author if isinstance(author, str) else "",
                            "author_id": note_id,
                            "published_at": _normalize_date(str(pub_time)),
                            "hot_score": likes + collects * 3 + comments * 2,
                            "like_count": likes,
                            "collect_count": collects,
                            "comment_count": comments,
                            "share_count": 0,
                            "source_type": "api_search",
                            "category_tags": "Xiaohongshu|" + _extract_tags(title),
                            "tags": _extract_tags(title, content),
                            "source": "xiaohongshu",
                        }
                    )
                    count += 1
                    collected += 1

            except Exception:
                continue

        time.sleep(0.3)

    return items


def collect_xhs_discover_api(max_items: int = 30) -> List[dict]:
    """
    通过小红书发现页API获取热门内容
    """
    items = []
    seen_urls = set()
    seen_titles = set()

    discover_urls = [
        "https://www.xiaohongshu.com/web_api/sns/v1/feed?page=1&page_size=20",
        "https://edith.xiaohongshu.com/api/sns/web/v1/feed?page=1&page_size=20",
    ]

    for url in discover_urls:
        try:
            out = _http_fetch(
                url,
                {
                    "User-Agent": UA_POOL[1],
                    "Referer": "https://www.xiaohongshu.com/",
                    "Accept": "application/json",
                },
                timeout=10,
            )
            if not out or len(out) < 50:
                continue

            try:
                d = json.loads(out)
            except json.JSONDecodeError:
                continue

            notes = []
            if isinstance(d.get("data"), dict):
                notes = d["data"].get("items", [])
            elif isinstance(d.get("items"), list):
                notes = d["items"]

            for note in notes[:max_items]:
                if not isinstance(note, dict):
                    continue
                title = note.get("title", note.get("display_title", ""))
                note_id = note.get("id", note.get("note_id", ""))
                if not title or not note_id:
                    continue
                url = f"https://www.xiaohongshu.com/explore/{note_id}"
                if url in seen_urls or title in seen_titles:
                    continue
                seen_urls.add(url)
                seen_titles.add(title)

                author = note.get("user", {}).get("nickname", "")
                items.append(
                    {
                        "platform": "xiaohongshu",
                        "title": title[:120],
                        "content": (note.get("desc", "") or "")[:300],
                        "url": url,
                        "author": author,
                        "author_id": note_id,
                        "published_at": _normalize_date(
                            str(note.get("time", note.get("create_time", "")))
                        ),
                        "hot_score": 0,
                        "source_type": "api_discover",
                        "category_tags": "Xiaohongshu|Explore",
                        "tags": "XHS|Discover",
                        "source": "xiaohongshu",
                    }
                )

            if items:
                break

        except Exception:
            continue

    return items


# ============================================================
# 主入口
# ============================================================
def collect_xhs_enhanced() -> List[dict]:
    """
    小红书增强采集主函数
    优先使用Playwright浏览器,不可用时fallback到HTTP API
    """
    all_items = []
    seen_urls = set()
    seen_titles = set()

    def dedup_and_extend(new_items):
        for item in new_items:
            url = item.get("url", "")
            title = item.get("title", "")
            if url and url not in seen_urls and title not in seen_titles:
                seen_urls.add(url)
                seen_titles.add(title)
                all_items.append(item)

    # ============================================
    # Phase 1: Playwright浏览器采集(优先)
    # ============================================
    print("  [XHS] === Phase 1: Playwright Browser ===")
    browser_items = collect_xhs_playwright(
        keywords=XHS_KEYWORDS, max_per_kw=MAX_PER_KEYWORD
    )
    dedup_and_extend(browser_items)
    print(f"  [XHS] Playwright total: {len(browser_items)} raw, {len(all_items)} unique")

    # ============================================
    # Phase 2: 如果浏览器不可用或数据不足,fallback到HTTP API
    # ============================================
    if len(all_items) < 30:
        print("  [XHS] === Phase 2: HTTP API Fallback ===")

        # 2a: 搜索API
        print("  [XHS] Phase 2a: Search API...")
        api_items = collect_xhs_api(
            keywords=XHS_KEYWORDS, max_per_kw=MAX_PER_KEYWORD
        )
        dedup_and_extend(api_items)
        print(f"  [XHS] Search API: {len(api_items)} raw, +{len(api_items)} unique")

        # 2b: 发现页API
        if len(all_items) < 50:
            print("  [XHS] Phase 2b: Discover API...")
            discover_items = collect_xhs_discover_api(max_items=30)
            dedup_and_extend(discover_items)
            print(f"  [XHS] Discover API: {len(discover_items)} raw, +{len(discover_items)} unique")

        # 2c: HTML页面直接提取(兜底)
        if len(all_items) < 40:
            print("  [XHS] Phase 2c: HTML direct extraction...")
            html_items = _collect_xhs_html_fallback(
                keywords=XHS_KEYWORDS, max_per_kw=MAX_PER_KEYWORD
            )
            dedup_and_extend(html_items)
            print(f"  [XHS] HTML fallback: {len(html_items)} raw")

    print(f"  [XHS] === Total: {len(all_items)} unique items ===")
    return all_items


def _collect_xhs_html_fallback(
    keywords: List[str] = None, max_per_kw: int = 10
) -> List[dict]:
    """
    HTML页面直接提取(最后兜底)
    直接从搜索页面HTML使用正则提取
    """
    items = []
    seen_urls = set()
    seen_titles = set()

    if keywords is None:
        keywords = XHS_KEYWORDS

    for kw in keywords[:8]:  # 减少数量,HTML提取较慢
        try:
            from urllib.parse import quote
            encoded_kw = quote(kw, safe="")
            search_url = (
                f"https://www.xiaohongshu.com/search_result"
                f"?keyword={encoded_kw}&source=web_search_result_notes"
            )
            out = _http_fetch(
                search_url,
                {
                    "User-Agent": UA_POOL[1],
                    "Referer": "https://www.xiaohongshu.com/",
                    "Accept": "text/html, */*",
                },
                timeout=10,
            )

            if not out or len(out) < 500:
                continue

            # 提取note_id
            note_ids = re.findall(r"/discovery/item/([a-f0-9]{24})", out)
            for nid in note_ids[:max_per_kw]:
                url = f"https://www.xiaohongshu.com/discovery/item/{nid}"
                if url not in seen_urls:
                    seen_urls.add(url)
                    items.append(
                        {
                            "platform": "xiaohongshu",
                            "title": f"XHS-{kw}-{nid[:6]}",
                            "content": f"XHS Note from search: {kw}",
                            "url": url,
                            "author": "",
                            "author_id": nid,
                            "published_at": "",
                            "hot_score": 0,
                            "like_count": 0,
                            "collect_count": 0,
                            "comment_count": 0,
                            "share_count": 0,
                            "source_type": "html_fallback",
                            "category_tags": "Xiaohongshu|" + _extract_tags(kw),
                            "tags": _extract_tags(kw),
                            "source": "xiaohongshu",
                        }
                    )

        except Exception:
            continue

        time.sleep(0.5)

    return items


def main():
    """主入口:采集并写入数据库"""
    print("=" * 60)
    print("  小红书增强采集器 - Multi-Strategy Collector")
    print(f"  Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Keywords: {len(XHS_KEYWORDS)} keywords, {MAX_PER_KEYWORD} each")
    print("=" * 60)

    items = collect_xhs_enhanced()

    if items:
        new_count = _insert_db(items)
        print(f"\n  Results: {len(items)} total, {new_count} new in DB")
    else:
        print("\n  No items collected")

    print("=" * 60)
    return len(items)


if __name__ == "__main__":
    main()
