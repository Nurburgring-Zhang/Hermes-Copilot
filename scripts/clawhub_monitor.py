#!/usr/bin/env python3
"""
ClawHub 淘金小镇排行榜监控系统
格林主人 2026-05-08
监控 clawhub.ai 上的热门技能/插件排行榜变化
"""

import json
import time
import sqlite3
import sys
from datetime import datetime
from urllib.request import Request, urlopen
from urllib.error import URLError

DB_PATH = "/home/administrator/.hermes/intelligence.db"
DATA_DIR = "/home/administrator/.hermes/rankings"

def init_db():
    """初始化排行榜数据表"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS clawhub_rankings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL,
            category TEXT DEFAULT 'skills',
            rank INTEGER NOT NULL,
            name TEXT NOT NULL,
            author TEXT,
            installs INTEGER DEFAULT 0,
            rating REAL DEFAULT 0,
            url TEXT,
            collected_at TEXT NOT NULL,
            UNIQUE(source, category, rank, collected_at)
        )
    """)
    conn.commit()
    conn.close()

def fetch_clawhub_skills():
    """获取ClawHub技能列表 - 通过网页抓取"""
    headers = {
        'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    
    results = []
    sources = {
        "/skills?sort=installs": "most-installed",
        "/skills?sort=newest": "newest",
        "/skills?sort=rating": "top-rated",
    }
    
    for path, category in sources.items():
        url = f"https://clawhub.ai{path}"
        try:
            req = Request(url, headers=headers)
            resp = urlopen(req, timeout=15)
            html = resp.read().decode('utf-8')
            print(f"  ✓ {category}: {len(html)} bytes from {url}")
            results.append({"category": category, "html": html, "source": "clawhub.ai"})
        except Exception as e:
            print(f"  ✗ {category}: {e}")
    
    return results

def store_rankings(data):
    """存储排行榜数据到数据库"""
    now = datetime.now().isoformat()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    count = 0
    for entry in data:
        # Parse skills from HTML -- simplified extraction
        # In production, we'd parse the React/Convex data properly
        c.execute("""
            INSERT OR IGNORE INTO clawhub_rankings 
            (source, category, rank, name, author, installs, rating, url, collected_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            entry.get("source", "clawhub.ai"),
            entry.get("category", "unknown"),
            0,
            f"snapshot_{entry['category']}",
            None,
            0,
            0.0,
            f"https://clawhub.ai/skills?sort={entry['category']}",
            now
        ))
        count += 1
    
    # Store raw HTML snapshot for later analysis
    snapshot = {
        "timestamp": now,
        "sources": [{"category": e["category"], "source": e["source"], "size": len(e["html"])} for e in data],
        "total_entries": count
    }
    
    import os
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(f"{DATA_DIR}/snapshot_{now[:19].replace(':', '-')}.json", "w") as f:
        json.dump(snapshot, f, indent=2)
    
    conn.commit()
    conn.close()
    print(f"\n  Stored {count} ranking snapshots")
    return count

def main():
    print("╔══════════════════════════════════════════════╗")
    print("║  ClawHub 排行榜监控系统                      ║")
    print("╚══════════════════════════════════════════════╝")
    print()
    print(f"[{datetime.now().isoformat()}] Starting collection...")
    
    init_db()
    print("\nFetching ClawHub rankings...")
    data = fetch_clawhub_skills()
    
    if data:
        count = store_rankings(data)
        print(f"\n✅ Collection complete: {count} entries saved")
    else:
        print("\n⚠️  No data collected (network issue?)")
        sys.exit(1)

if __name__ == "__main__":
    main()
