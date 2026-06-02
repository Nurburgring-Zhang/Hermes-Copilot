#!/usr/bin/env python3
"""
小红书采集器 v5 - CloakBrowser方案
===============================
C++级Chromium反检测，过reCAPTCHA v3 0.9分
30/30检测通过，Cloudflare Turnstile ✅

策略：
  1. CloakBrowser打开探索页+搜索页
  2. 提取SSR渲染数据（标题/作者/点赞/封面）
  3. 入库到 raw_intelligence

 cron: 每2小时（比v4的3小时密）
"""

import sys, json, time, re, hashlib, sqlite3
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional

DB_PATH = Path("/home/administrator/.hermes/intelligence.db")
THIS_DIR = Path(__file__).parent

# 20个偏好关键词
XHS_KEYWORDS = [
    "AI", "新能源汽车", "军事", "美女", "摄影",
    "格斗", "游戏", "数码", "篮球", "旅游",
    "美食", "历史", "科技", "手机", "汽车",
]

MAX_PER_KEYWORD = 10
MAX_TOTAL = 100


def get_db():
    return sqlite3.connect(str(DB_PATH))


def url_hash(url: str) -> str:
    return hashlib.md5(url.encode()).hexdigest()


def insert_note(note: dict, source_type: str = "xhs_cloakbrowser") -> bool:
    """插入一条笔记到数据库"""
    try:
        url = note.get("href", "")
        title = note.get("title", "").strip()
        author = note.get("author", "").strip()
        note_id = note.get("noteId", "")
        like = note.get("like", "0")
        img = note.get("img", "")

        if not title or not note_id:
            return False
        if len(title) < 2:
            return False

        content = f"{title}\n作者: {author}\n👍{like}"
        uh = url_hash(url) if url else hashlib.md5(note_id.encode()).hexdigest()

        db = get_db()
        existing = db.execute("SELECT id FROM raw_intelligence WHERE url_hash=?", (uh,)).fetchone()
        if existing:
            db.close()
            return False

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        like_count = int(re.sub(r'[^0-9]', '', like) or 0)
        db.execute("""
            INSERT INTO raw_intelligence (title, content, url, source, author, like_count, hot_score, published_at, collected_at, url_hash)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            title, content, url, "xiaohongshu", author,
            like_count, 0, now, now, uh
        ))
        db.commit()
        db.close()
        return True
    except Exception as e:
        print(f"  [DB_ERROR] {e}")
        return False


def collect_xhs_cloak(max_items: int = 50) -> List[dict]:
    """使用CloakBrowser采集小红书"""
    from cloakbrowser import launch

    all_notes = []
    browser = launch(
        headless=True,
        humanize=True,
        args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"],
    )
    page = browser.new_page()

    try:
        # 策略1: 探索页
        print("  [XHS] 探索页采集...")
        page.goto("https://www.xiaohongshu.com/explore", timeout=30000, wait_until="domcontentloaded")
        time.sleep(4)

        explore_notes = page.evaluate("""
            () => {
                const items = document.querySelectorAll('.note-item');
                return Array.from(items).slice(0, 30).map(item => {
                    const link = item.querySelector('a');
                    const img = item.querySelector('img');
                    const titleEl = item.querySelector('.title, .note-title, [class*=title]');
                    const authorEl = item.querySelector('.author, .name, [class*=author]');
                    const likeEl = item.querySelector('.like, .count, [class*=like]');
                    const href = link ? link.href : '';
                    const match = href.match(/explore\\/([a-f0-9]+)/);
                    return {
                        href, img: img ? img.src : '',
                        title: titleEl ? titleEl.textContent.trim() : '',
                        author: authorEl ? authorEl.textContent.trim() : '',
                        like: likeEl ? likeEl.textContent.trim() : '0',
                        noteId: match ? match[1] : '',
                    };
                });
            }
        """)
        all_notes.extend(explore_notes)
        print(f"  [XHS] 探索页: {len(explore_notes)}条")

        # 策略2: 搜索页
        for kw in XHS_KEYWORDS:
            if len(all_notes) >= max_items:
                break
            try:
                url = f"https://www.xiaohongshu.com/search_result?keyword={kw}&source=web_search_result_notes"
                print(f"  [XHS] 搜索: {kw}")
                page.goto(url, timeout=20000, wait_until="domcontentloaded")
                time.sleep(3)

                search_notes = page.evaluate("""
                    (maxItems) => {
                        const items = document.querySelectorAll('.note-item, .feeds-page > div > div');
                        const results = []; const seen = new Set();
                        items.forEach(item => {
                            if (results.length >= maxItems) return;
                            const link = item.querySelector('a');
                            if (!link) return;
                            const href = link.href;
                            const match = href.match(/explore\\/([a-f0-9]+)/);
                            if (!match || seen.has(match[1])) return;
                            seen.add(match[1]);
                            const img = item.querySelector('img');
                            const titleEl = item.querySelector('.title, [class*=title]');
                            const authorEl = item.querySelector('.author, .name, [class*=author]');
                            const likeEl = item.querySelector('.like, .count, [class*=like]');
                            results.push({
                                href, img: img ? img.src : '',
                                title: titleEl ? titleEl.textContent.trim() : '',
                                author: authorEl ? authorEl.textContent.trim() : '',
                                like: likeEl ? likeEl.textContent.trim() : '0',
                                noteId: match[1],
                            });
                        });
                        return results;
                    }
                """, MAX_PER_KEYWORD)
                all_notes.extend(search_notes)
                print(f"    → {len(search_notes)}条")
            except Exception as e:
                print(f"    → 异常: {e}")

    finally:
        browser.close()

    # 去重
    seen_ids = set()
    unique = []
    for n in all_notes:
        if n["noteId"] and n["noteId"] not in seen_ids:
            seen_ids.add(n["noteId"])
            unique.append(n)
    return unique[:max_items]


def main():
    print("=" * 60)
    print("📕 小红书采集器 v5 (CloakBrowser)")
    print("=" * 60)

    start = time.time()
    notes = collect_xhs_cloak(max_items=MAX_TOTAL)
    elapsed = time.time() - start

    print(f"\n共采集 {len(notes)} 条")
    saved = 0
    for n in notes:
        if insert_note(n):
            saved += 1

    print(f"📊 候选 {len(notes)} → 新保存 {saved} 条 | 耗时 {elapsed:.1f}s")

    if saved > 0:
        print("\n📋 新入库示例:")
        db = get_db()
        rows = db.execute(
            "SELECT title, author, like_count FROM raw_intelligence WHERE source='xiaohongshu' ORDER BY id DESC LIMIT 5"
        ).fetchall()
        for r in rows:
            print(f"  [{r[1]}] {r[0][:45]} 👍{r[2]}")
        db.close()


if __name__ == "__main__":
    main()
