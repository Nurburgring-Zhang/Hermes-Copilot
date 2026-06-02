#!/usr/bin/env python3
"""
Hermes 正文增强引擎 v2.0 (Content Enrichment Engine)
=====================================================
从 raw_intelligence 找出缺正文的文章,通过平台特定提取器获取真实正文。

用法:
    python content_enricher.py                        # 默认参数
    python content_enricher.py --limit 200            # 最多处理200条
    python content_enricher.py --rate-limit 0.5       # 每秒最多0.5个请求
    python content_enricher.py --dry-run              # 只统计不写入
    python content_enricher.py --batch 10 --interval 120  # 批处理模式
    python content_enricher.py --skip-platform github,bilibili  # 跳过某些平台
"""

import sqlite3, urllib.request, urllib.error, urllib.parse
import json, sys, time, re, html as html_mod
from pathlib import Path
from typing import Dict, List, Optional, Set, Any
from datetime import datetime

# ── 配置 ──
HERMES = Path("/home/administrator/.hermes")
DB_PATH = HERMES / "intelligence.db"
MIN_CONTENT_LEN = 50
RATE_LIMIT = 1.0
HTTP_TIMEOUT = 8
MAX_BATCH = 500
BATCH_INTERVAL = 60
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"

# ── 白名单平台(有真实文章URL的平台) ──
PLATFORMS_WITH_REAL_ARTICLES: Set[str] = {
    "ithome", "it_home_tw", "oschina", "solidot", "ifanr", "sspai",
    "devto", "sina_tech", "cnblogs", "github", "hackernews",
    "zhihu", "bilibili", "36kr", "tmtpost",
}

# ── 数据库 ──
def get_db():
    conn = sqlite3.connect(str(DB_PATH), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=15000;")
    return conn

# ── HTTP抓取 ──
def fetch_url(url: str, timeout: int = HTTP_TIMEOUT) -> Optional[str]:
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/json,*/*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        })
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except Exception:
        return None

def fetch_json(url: str) -> Optional[dict]:
    text = fetch_url(url)
    if text:
        try: return json.loads(text)
        except: return None
    return None

# ── HTML清理 ──
def clean_html(html: str) -> str:
    """清理HTML标签,返回纯文本"""
    for tag in ['script','style','nav','header','footer','noscript','svg','iframe']:
        html = re.sub(f'<{tag}[^>]*>.*?</{tag}>', '', html, flags=re.DOTALL|re.IGNORECASE)
    text = re.sub(r'<[^>]+>', '\n', html)
    text = html_mod.unescape(text)
    text = re.sub(r'&[a-z]+;', ' ', text)
    text = re.sub(r'\n\s*\n', '\n', text)
    return text.strip()

def extract_paragraphs(html: str, min_len: int = 20) -> List[str]:
    """提取所有<p>标签正文"""
    ps = re.findall(r'<p[^>]*>(.*?)</p>', html, re.DOTALL)
    texts = []
    seen = set()
    for p in ps:
        text = re.sub(r'<[^>]+>', '', p).strip()
        text = re.sub(r'&[a-z]+;', ' ', text)
        text = re.sub(r'&#?\d+;', ' ', text)
        text = re.sub(r'\s+', ' ', text).strip()
        if len(text) >= min_len and text not in seen:
            texts.append(text)
            seen.add(text)
    return texts

# ── 平台特定提取器 ──
def extract_ithome(url: str) -> Optional[str]:
    """IT之家正文"""
    html = fetch_url(url)
    if not html: return None
    # 找<div class="post_content">内部的<p>
    m = re.search(r'<div[^>]*class="[^"]*post_content[^"]*"[^>]*>(.*?)</div>\s*</div>', html, re.DOTALL)
    if m:
        texts = extract_paragraphs(m.group(1), 15)
        if texts: return '\n'.join(texts[:20])
    texts = extract_paragraphs(html)
    return '\n'.join(texts[:20]) if texts else None

def extract_oschina(url: str) -> Optional[str]:
    url = url.replace('oschina.net/news/', 'oschina.net/news/')  # 确保不会改
    html = fetch_url(url)
    if not html: return None
    for cls in ['content', 'article-content', 'article_detail']:
        m = re.search(rf'<div[^>]*class="[^"]*{cls}[^"]*"[^>]*>(.*?)</div>\s*</div>', html, re.DOTALL)
        if m:
            texts = extract_paragraphs(m.group(1), 15)
            if texts: return '\n'.join(texts[:20])
    texts = extract_paragraphs(html)
    return '\n'.join(texts[:20]) if texts else None

def extract_solidot(url: str) -> Optional[str]:
    html = fetch_url(url)
    if not html: return None
    m = re.search(r'<div[^>]*class="[^"]*p_mainnew[^"]*"[^>]*>(.*?)</div>', html, re.DOTALL)
    if m:
        texts = extract_paragraphs(m.group(1), 10)
        if texts: return '\n'.join(texts[:20])
    texts = extract_paragraphs(html)
    return '\n'.join(texts[:20]) if texts else None

def extract_ifanr(url: str) -> Optional[str]:
    html = fetch_url(url)
    if not html: return None
    m = re.search(r'<div[^>]*class="[^"]*entry-content[^"]*"[^>]*>(.*?)</div>', html, re.DOTALL)
    if m:
        texts = extract_paragraphs(m.group(1), 15)
        if texts: return '\n'.join(texts[:20])
    texts = extract_paragraphs(html)
    return '\n'.join(texts[:20]) if texts else None

def extract_sspai(url: str) -> Optional[str]:
    html = fetch_url(url)
    if not html: return None
    m = re.search(r'<article[^>]*>(.*?)</article>', html, re.DOTALL)
    if m:
        texts = extract_paragraphs(m.group(1), 15)
        if texts: return '\n'.join(texts[:20])
    texts = extract_paragraphs(html)
    return '\n'.join(texts[:20]) if texts else None

def extract_devto(url: str) -> Optional[str]:
    html = fetch_url(url)
    if not html: return None
    for cls in ['crayons-article__body', 'article-body']:
        m = re.search(rf'<div[^>]*class="[^"]*{cls}[^"]*"[^>]*>(.*?)</div>', html, re.DOTALL)
        if m:
            texts = extract_paragraphs(m.group(1), 15)
            if texts: return '\n'.join(texts[:20])
    texts = extract_paragraphs(html)
    return '\n'.join(texts[:20]) if texts else None

def extract_sina_tech(url: str) -> Optional[str]:
    html = fetch_url(url)
    if not html: return None
    for cls in ['article-body', 'article_content', 'main-content']:
        m = re.search(rf'<div[^>]*class="[^"]*{cls}[^"]*"[^>]*>(.*?)</div>', html, re.DOTALL)
        if m:
            texts = extract_paragraphs(m.group(1), 15)
            if texts: return '\n'.join(texts[:20])
    texts = extract_paragraphs(html)
    return '\n'.join(texts[:20]) if texts else None

def extract_cnblogs(url: str) -> Optional[str]:
    html = fetch_url(url)
    if not html: return None
    m = re.search(r'<div[^>]*id="cnblogs_post_body"[^>]*>(.*?)</div>', html, re.DOTALL)
    if m:
        texts = extract_paragraphs(m.group(1), 15)
        if texts: return '\n'.join(texts[:20])
    texts = extract_paragraphs(html)
    return '\n'.join(texts[:20]) if texts else None

def extract_36kr(url: str) -> Optional[str]:
    """36氪可以从JSON API获取正文"""
    # 尝试从URL提取文章ID
    m = re.search(r'/(\d+)\.html', url)
    if not m:
        m = re.search(r'36kr\.com/p/(\d+)', url)
    if m:
        aid = m.group(1)
        api_url = f"https://36kr.com/api/articles/{aid}"
        data = fetch_json(api_url)
        if data:
            content = data.get('data', {}).get('content', '')
            if content:
                text = re.sub(r'<[^>]+>', '', content)
                text = html_mod.unescape(text)
                text = re.sub(r'\s+', ' ', text).strip()
                if len(text) > 100:
                    return text[:2000]
    return None

def extract_tmtpost(url: str) -> Optional[str]:
    html = fetch_url(url)
    if not html: return None
    for cls in ['article-content', 'content', 'detail-content']:
        m = re.search(rf'<div[^>]*class="[^"]*{cls}[^"]*"[^>]*>(.*?)</div>', html, re.DOTALL)
        if m:
            texts = extract_paragraphs(m.group(1), 15)
            if texts: return '\n'.join(texts[:20])
    texts = extract_paragraphs(html)
    return '\n'.join(texts[:20]) if texts else None

def extract_hackernews(url: str) -> Optional[str]:
    """HackerNews页面"""
    html = fetch_url(url)
    if not html: return None
    # HN评论页面
    texts = []
    for tr in re.findall(r'<tr[^>]*class="[^"]*athing[^"]*"[^>]*>(.*?)</tr>', html, re.DOTALL):
        m = re.search(r'<td[^>]*class="[^"]*title[^"]*"[^>]*>(.*?)</td>', tr, re.DOTALL)
        if m:
            t = re.sub(r'<[^>]+>', '', m.group(1)).strip()
            if t and len(t) > 20:
                texts.append(t)
    if texts: return '\n'.join(texts[:15])
    # 备用
    texts = extract_paragraphs(html, 15)
    return '\n'.join(texts[:15]) if texts else None

def extract_bilibili(url: str) -> Optional[str]:
    """B站视频: 通过API获取简介"""
    m = re.search(r'video/(BV\w+)', url)
    if not m: return None
    bvid = m.group(1)
    api = f"https://api.bilibili.com/x/web-interface/view?bvid={bvid}"
    data = fetch_json(api)
    if data and data.get('code') == 0:
        desc = data['data'].get('desc', '')
        title = data['data'].get('title', '')
        if desc and len(desc) > 20:
            return f"【{title}】\n{desc}"
    return None

def extract_zhihu(url: str) -> Optional[str]:
    """知乎回答/文章"""
    html = fetch_url(url)
    if not html: return None
    # 找回答内容
    for cls in ['RichText', 'ContentItem', 'RichContent']:
        m = re.search(rf'<div[^>]*class="[^"]*{cls}[^"]*"[^>]*>(.*?)</div>', html, re.DOTALL)
        if m:
            texts = extract_paragraphs(m.group(1), 15)
            if texts: return '\n'.join(texts[:20])
    texts = extract_paragraphs(html, 15)
    return '\n'.join(texts[:20]) if texts else None

def extract_github(url: str) -> Optional[str]:
    """GitHub仓库描述"""
    # 使用GitHub API
    m = re.search(r'github\.com/([^/]+)/([^/]+)', url)
    if not m: return None
    owner, repo = m.group(1), m.group(2).split('/')[0].split('?')[0]
    api = f"https://api.github.com/repos/{owner}/{repo}"
    data = fetch_json(api)
    if data:
        desc = data.get('description', '') or ''
        topics = ', '.join(data.get('topics', [])[:10])
        lang = data.get('language', '')
        stars = data.get('stargazers_count', 0)
        text = f"{desc}\n语言: {lang} | ⭐{stars:,} | 标签: {topics}"
        return text if len(text) > 20 else None
    return None

def extract_ithome_tw(url: str) -> Optional[str]:
    return extract_ithome(url)

# ── 提取器注册 ──
EXTRACTORS = {
    "ithome": extract_ithome,
    "it_home_tw": extract_ithome_tw,
    "oschina": extract_oschina,
    "solidot": extract_solidot,
    "ifanr": extract_ifanr,
    "sspai": extract_sspai,
    "devto": extract_devto,
    "sina_tech": extract_sina_tech,
    "cnblogs": extract_cnblogs,
    "36kr": extract_36kr,
    "tmtpost": extract_tmtpost,
    "hackernews": extract_hackernews,
    "bilibili": extract_bilibili,
    "zhihu": extract_zhihu,
    "github": extract_github,
}

# ── 核心逻辑 ──
def find_articles(conn, limit):
    # 确保白名单平台没有遗漏
    platforms_list = "','".join(PLATFORMS_WITH_REAL_ARTICLES)
    # 优先处理非B站(B站视频简介通常很短,放到最后),同时跳过GitHub(API有频率限制)
    cur = conn.execute(f"""
        SELECT id, title, content, url, source, platform, published_at
        FROM raw_intelligence
        WHERE LENGTH(COALESCE(content, '')) < ?
          AND platform IN ('{platforms_list}')
          AND url IS NOT NULL AND url != ''
          AND url NOT LIKE '%api%zhihu%'
        ORDER BY CASE
            WHEN platform='bilibili' THEN 2
            WHEN platform='github' THEN 1
            ELSE 0
        END, id ASC
        LIMIT ?
    """, (MIN_CONTENT_LEN, limit))
    return [dict(r) for r in cur.fetchall()]

def enrich_one(item: dict) -> dict:
    """尝试增强一篇文章"""
    platform = item.get("platform", "")
    url = item.get("url", "")
    
    # 获取提取器
    extractor = EXTRACTORS.get(platform)
    if not extractor:
        return {"id": item["id"], "status": "skip", "reason": f"无提取器: {platform}"}
    
    try:
        content = extractor(url)
        # B站视频简介通常较短,降低阈值
        min_len = 30 if platform == 'bilibili' else 80
        if content and len(content) > min_len:
            return {"id": item["id"], "status": "ok", "content": content[:2000]}
        else:
            return {"id": item["id"], "status": "skip", "reason": f"提取内容过短({len(content) if content else 0}chars, 阈值{min_len})"}
    except Exception as e:
        return {"id": item["id"], "status": "fail", "reason": str(e)[:100]}

def run(limit=MAX_BATCH, dry_run=False, skip_platforms=None):
    conn = get_db()
    articles = find_articles(conn, limit)
    
    stats = {"total": 0, "ok": 0, "skip": 0, "fail": 0, "details": []}
    
    if skip_platforms:
        articles = [a for a in articles if a["platform"] not in skip_platforms]
    
    stats["total"] = len(articles)
    
    for i, item in enumerate(articles):
        result = enrich_one(item)
        stats[result["status"]] = stats.get(result["status"], 0) + 1
        stats["details"].append(result)
        
        # 限速
        time.sleep(1.0 / RATE_LIMIT)
        
        if (i + 1) % 50 == 0:
            conn.commit()
    
    # 写入数据库
    if not dry_run:
        for r in stats["details"]:
            if r["status"] == "ok":
                conn.execute(
                    "UPDATE raw_intelligence SET content = ? WHERE id = ?",
                    (r["content"], r["id"])
                )
        conn.commit()
    
    conn.close()
    
    result = {
        "candidates": stats["total"],
        "enriched": stats.get("ok", 0),
        "skipped": stats.get("skip", 0),
        "failed": stats.get("fail", 0),
        "total_remaining": None,
    }
    
    # 获取全局剩余数量
    try:
        c2 = get_db()
        platforms_list = "','".join(PLATFORMS_WITH_REAL_ARTICLES)
        remaining = c2.execute(f"""
            SELECT COUNT(*) FROM raw_intelligence
            WHERE LENGTH(COALESCE(content, '')) < ?
              AND platform IN ('{platforms_list}')
        """, (MIN_CONTENT_LEN,)).fetchone()[0]
        result["total_remaining"] = remaining
        c2.close()
    except:
        pass
    
    return result

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=MAX_BATCH)
    parser.add_argument("--rate-limit", type=float, default=RATE_LIMIT)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-platform", help="逗号分隔的跳过平台")
    parser.add_argument("--batch", type=int, default=0, help="批处理每轮条数")
    parser.add_argument("--interval", type=int, default=BATCH_INTERVAL)
    parser.add_argument("--json", action="store_true", help="输出JSON")
    args = parser.parse_args()
    
    RATE_LIMIT = args.rate_limit
    skip = set(args.skip_platform.split(",")) if args.skip_platform else None
    
    result = run(limit=args.limit, dry_run=args.dry_run, skip_platforms=skip)
    
    if args.json:
        print(json.dumps(result, ensure_ascii=False))
    else:
        print(f"\n正文增强引擎执行完成:")
        print(f"  候选: {result['candidates']}")
        print(f"  已增强: {result['enriched']}")
        print(f"  跳过: {result['skipped']}")
        print(f"  失败: {result['failed']}")
        if result['total_remaining'] is not None:
            print(f"  全局剩余: {result['total_remaining']}")

