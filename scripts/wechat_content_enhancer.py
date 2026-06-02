#!/usr/bin/env python3
"""
微信公众号文章内容增强采集器 v1.0
====================================
从已入库的sogou_wechat文章中提取真实微信公众号文章URL，
访问mp.weixin.qq.com获取完整文章内容。

策略:
1. 从intelligence.db中获取sogou_wechat来源但content为空/过短的文章
2. 通过搜狗链接跳转到真实mp.weixin.qq.com地址
3. 提取完整文章内容并更新cleaned_intelligence表

使用方式:
  python3 wechat_content_enhancer.py          # 增量增强(每次50篇)
  python3 wechat_content_enhancer.py --full   # 全量增强所有空内容文章
"""

import sqlite3, re, time, hashlib
from datetime import datetime
from pathlib import Path
from urllib.request import Request, urlopen

HERMES = Path("/home/administrator/.hermes")
DB_PATH = HERMES / "intelligence.db"

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"


def fetch_url(url, timeout=15):
    """获取URL内容"""
    try:
        req = Request(url, headers={"User-Agent": UA})
        with urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except Exception:
        return ""


def extract_wechat_content(html):
    """从微信公众号文章HTML中提取正文内容"""
    # 提取标题
    title = ""
    m = re.search(r'<title>(.*?)</title>', html)
    if m:
        title = m.group(1).strip()
    
    # 提取作者
    author = ""
    m = re.search(r'var author_name\s*=\s*["\'](.*?)["\']', html)
    if m:
        author = m.group(1).strip()
    # 另一种格式
    if not author:
        m = re.search(r'"author_name"\s*:\s*"(.*?)"', html)
        if m:
            author = m.group(1).strip()
    
    # 提取正文 - 微信公众号文章正文在rich_media_content中
    content = ""
    m = re.search(r'id="js_content".*?>(.*?)</div>\s*<script', html, re.DOTALL)
    if m:
        content = m.group(1)
        content = re.sub(r'<[^>]+>', '', content)
        content = re.sub(r'\s+', ' ', content).strip()
    
    # 提取发布时间
    pub_time = ""
    m = re.search(r'var ct\s*=\s*["\'](\d+)["\']', html)
    if m:
        try:
            ts = int(m.group(1))
            pub_time = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
        except:
            pass
    
    return title, author, content, pub_time


def get_wechat_urls_to_process(limit=50, full=False):
    """获取需要增强内容的微信文章"""
    conn = sqlite3.connect(str(DB_PATH))
    
    if full:
        rows = conn.execute("""
            SELECT id, url FROM raw_intelligence 
            WHERE platform = 'sogou_wechat'
               OR (source = 'sogou_wechat')
            ORDER BY id DESC
        """).fetchall()
    else:
        rows = conn.execute("""
            SELECT r.id, r.url FROM raw_intelligence r
            WHERE (r.platform = 'sogou_wechat' OR r.source = 'sogou_wechat')
              AND r.id NOT IN (
                  SELECT raw_id FROM cleaned_intelligence 
                  WHERE LENGTH(COALESCE(content, '')) > 200
                    AND raw_id IS NOT NULL
              )
            ORDER BY r.id DESC
            LIMIT ?
        """, (limit,)).fetchall()
    
    conn.close()
    return rows


def resolve_real_url(sogou_url):
    """通过搜狗跳转链接获取真实mp.weixin.qq.com地址"""
    html = fetch_url(sogou_url)
    # 搜狗跳转页面里通常有真实的mp.weixin.qq.com链接
    m = re.search(r'url\s*=\s*["\'](https?://mp\.weixin\.qq\.com[^"\']+)["\']', html)
    if m:
        return m.group(1)
    # 另一种格式: window.location
    m = re.search(r'window\.location\.href\s*=\s*["\'](https?://mp\.weixin\.qq\.com[^"\']+)["\']', html)
    if m:
        return m.group(1)
    # 直接重定向
    return sogou_url


def enhance_one(row_id, sogou_url):
    """增强单条文章内容"""
    print(f"  #{row_id}: 解析URL...", end=" ")
    
    # 解析真实URL
    real_url = resolve_real_url(sogou_url)
    if not real_url or real_url == sogou_url:
        print("❌ 无法解析真实URL")
        return False
    
    # 获取文章内容
    html = fetch_url(real_url, timeout=20)
    if not html or len(html) < 500:
        print("❌ 无法获取文章")
        return False
    
    title, author, content, pub_time = extract_wechat_content(html)
    
    if not content or len(content) < 100:
        print("❌ 正文提取失败")
        return False
    
    # 更新数据库
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("""
        UPDATE raw_intelligence 
        SET content = ?, author = ?, published_at = COALESCE(NULLIF(?, ''), published_at)
        WHERE id = ?
    """, (content[:5000], author, pub_time, row_id))
    
    # 如果有对应的cleaned_intelligence，也更新
    conn.execute("""
        UPDATE cleaned_intelligence
        SET content = ?, author = COALESCE(NULLIF(?, ''), author)
        WHERE raw_id = ? AND LENGTH(COALESCE(content, '')) < LENGTH(?)
    """, (content[:2000], author, row_id, content[:2000]))
    
    conn.commit()
    conn.close()
    
    title_short = title[:40] if title else "无标题"
    print(f"✅ {len(content)}字 | {title_short}")
    return True


def main():
    import sys
    full = "--full" in sys.argv
    limit = 500 if full else 50
    
    print(f"微信公众号内容增强器 — 模式: {'全量' if full else '增量'}")
    
    rows = get_wechat_urls_to_process(limit=limit, full=full)
    print(f"待处理: {len(rows)} 条微信文章")
    
    success = 0
    for i, (row_id, url) in enumerate(rows):
        if enhance_one(row_id, url):
            success += 1
        if (i + 1) % 10 == 0:
            print(f"  进度: {i+1}/{len(rows)}, 成功: {success}")
        time.sleep(1)  # 避免频率限制
    
    print(f"\n✅ 完成: {success}/{len(rows)} 条文章内容已增强")


if __name__ == "__main__":
    main()
