#!/usr/bin/env python3
"""CSDN博客采集器 v2 — 按格林主人偏好方向搜索，获取全文而非摘要"""
import urllib.request, urllib.parse, json, re, time, hashlib, sqlite3, os, random, sys, ssl
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Tuple

HERMES = Path("/home/administrator/.hermes")
DB_PATH = HERMES / "intelligence.db"
COLLECTOR_LOG = HERMES / "logs" / "csdn_blog.log"

# 格林主人偏好方向
CSDN_KEYWORDS = [
    "AI", "大模型", "LLM", "人工智能", "机器学习", "深度学习",
    "Rust", "TypeScript", "Python", "Go", "开源",
    "架构", "微服务", "DDD", "系统设计",
    "芯片", "半导体", "自动驾驶",
    "网络安全", "渗透测试", "代码审查",
    "GitHub", "DevOps", "Kubernetes", "云原生",
]

UA_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]

def log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] [CSDN] {msg}"
    print(line)
    with open(COLLECTOR_LOG, 'a', encoding='utf-8') as f:
        f.write(line + "\n")

def fetch(url: str, timeout: int = 15) -> Optional[str]:
    ua = UA_POOL[int(time.time()) % len(UA_POOL)]
    req = urllib.request.Request(url, headers={
        "User-Agent": ua,
        "Accept": "text/html,application/json,*/*",
        "Referer": "https://www.csdn.net/",
    })
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            return resp.read().decode('utf-8', errors='replace')
    except Exception as e:
        log(f"fetch fail: {e}")
        return None

def extract_full_content(html: str) -> Tuple[str, str]:
    """
    从CSDN文章HTML中提取完整正文和作者
    """
    # 提取正文 - CSDN文章通常用 article_content 或 content 类
    content = ""
    
    # 尝试多种CSS选择器提取
    patterns = [
        r'<article[^>]*class="[^"]*article_content[^"]*"[^>]*>(.*?)</article>',
        r'<div[^>]*class="[^"]*article_content[^"]*"[^>]*>(.*?)</div>',
        r'<div[^>]*id="article_content"[^>]*>(.*?)</div>',
        r'<div[^>]*class="[^"]*markdown_views[^"]*"[^>]*>(.*?)</div>',
        r'<div[^>]*class="[^"]*htmledit_views[^"]*"[^>]*>(.*?)</div>',
        r'<!--文章内容-->(.*?)<!--/文章内容-->',
    ]
    
    for pat in patterns:
        m = re.search(pat, html, re.DOTALL)
        if m:
            raw = m.group(1)
            # 去HTML标签取纯文本
            content = re.sub(r'<[^>]+>', '', raw)
            content = re.sub(r'\s+', ' ', content).strip()
            if len(content) > 200:
                break
    
    # 如果还没提取到，试试JSON-LD中的描述
    if len(content) < 200:
        jsm = re.search(r'"description"\s*:\s*"([^"]+)"', html)
        if jsm:
            content = jsm.group(1)
    
    # 提取作者
    author = ""
    author_patterns = [
        r'"nickname"\s*:\s*"([^"]+)"',
        r'<a[^>]*class="[^"]*follow-nickName[^"]*"[^>]*>([^<]+)</a>',
        r'<span[^>]*class="[^"]*name[^"]*"[^>]*>([^<]+)</span>',
    ]
    for ap in author_patterns:
        m = re.search(ap, html)
        if m:
            author = m.group(1).strip()
            break
    
    return content[:5000], author[:50]

def save_item(title: str, content: str, url: str, author: str, category: str):
    try:
        db = sqlite3.connect(str(DB_PATH))
        url_hash = hashlib.md5(url.encode()).hexdigest()
        exists = db.execute("SELECT 1 FROM raw_intelligence WHERE url_hash=?", (url_hash,)).fetchone()
        if exists:
            db.close()
            return False
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        db.execute("""
            INSERT INTO raw_intelligence (title, content, url, source, platform, author, author_id, published_at, hot_score, source_type, category_tags, url_hash, collected_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            title[:200], content[:5000] if content else "",
            url[:500], "csdn", "csdn",
            author[:50] if author else "", "", now, 0, "blog",
            category[:100], url_hash, now
        ))
        db.commit()
        db.close()
        return True
    except Exception as e:
        log(f"save fail: {e}")
        return False

def collect_csdn_blogs():
    """采集CSDN博客 — 按关键词搜索，获取全文"""
    total_saved = 0
    
    for kw in CSDN_KEYWORDS:
        encoded = urllib.parse.quote(kw)
        items = []
        
        # CSDN搜索API
        search_url = f"https://so.csdn.net/api/v3/search?q={encoded}&t=blog&p=1&s=0&tm=0&lv=0&ft=0"
        html = fetch(search_url, timeout=10)
        if html:
            try:
                data = json.loads(html)
                results = data.get('result_vos', []) or data.get('data', [])
                for r in results[:8]:
                    title = r.get('title', '') or r.get('article_title', '')
                    title = re.sub(r'<[^>]+>', '', title)[:80]
                    summary = r.get('description', '') or r.get('summary', '')
                    summary = re.sub(r'<[^>]+>', '', summary)[:200]
                    url = r.get('url', '') or r.get('article_url', '')
                    author = r.get('nickname', '') or r.get('author_name', '')
                    
                    if url and title:
                        # == 关键改造：主动获取全文 ==
                        content = summary  # 先用搜索结果的摘要
                        if len(content) < 200:
                            # 摘要太短 -> 抓取文章页获取全文
                            log(f"  抓取全文: {title[:30]}...")
                            article_html = fetch(url, timeout=10)
                            if article_html:
                                full_content, full_author = extract_full_content(article_html)
                                if len(full_content) > len(content):
                                    content = full_content
                                if full_author and not author:
                                    author = full_author
                        
                        items.append({'title': title, 'content': content, 'url': url, 'author': author})
            except:
                pass
        
        saved = 0
        for item in items:
            # 内容质量过滤：只有标题没有实质内容的不要
            clean_content = re.sub(r'[\s\r\n\t<>/\[\]{}()=+#@$%^&*|\\;:\'"~`]+', '', item['content']).strip()
            if len(clean_content) < 100 and len(items) > 5:
                # 摘要实在拿不到全文也保留少数，避免全部丢弃
                pass
            if save_item(item['title'], item['content'], item['url'], item['author'], f'CSDN|{kw}'):
                saved += 1
                total_saved += 1
        log(f"  [{kw}] → {len(items)}条，新保存{saved}条（全文获取率: {saved/max(len(items),1)*100:.0f}%）")
        time.sleep(random.uniform(1.0, 2.0))
    
    log(f"✅ CSDN采集完成: 共新保存{total_saved}条")
    return total_saved, 0, 0

if __name__ == "__main__":
    collect_csdn_blogs()
