#!/usr/bin/env python3
"""
Hermes 老旧数据压缩归档
======================
将cleaned_intelligence中7天前的数据压缩到history_archive表。
压缩时保留标题/平台/AI评分/摘要,删除原始正文。

规则:
- 7天前的数据 -> 归档
- 归档表: history_archive (id, title, platform, ai_score_total, summary, archived_at, compressed_from_id)
- 归档后从cleaned_intelligence删除
- 保留最近7天的数据用于推送
"""

import sqlite3, json, hashlib, logging, sys
from datetime import datetime, timedelta, date
from pathlib import Path

HERMES = Path("/home/administrator/.hermes")
DB_PATH = HERMES / "intelligence.db"
LOG_DIR = HERMES / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / f"archive_{date.today().strftime('%Y%m%d')}.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler(LOG_FILE, encoding="utf-8"), logging.StreamHandler()]
)
log = logging.getLogger("archive_engine")

def ensure_archive_table(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS history_archive (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            platform TEXT,
            source TEXT,
            url TEXT,
            ai_score_total REAL DEFAULT 0,
            ai_score_scarcity REAL DEFAULT 0,
            ai_score_impact REAL DEFAULT 0,
            ai_score_tech_depth REAL DEFAULT 0,
            ai_score_timeliness REAL DEFAULT 0,
            ai_score_preference REAL DEFAULT 0,
            ai_score_credibility REAL DEFAULT 0,
            summary TEXT,
            importance_score REAL DEFAULT 0,
            value_level INTEGER DEFAULT 0,
            collected_at TEXT,
            archived_at TEXT DEFAULT (datetime('now')),
            compressed_from_id INTEGER
        )
    """)
    conn.commit()

def archive_data(keep_days: int = 7):
    """归档7天前的数据"""
    conn = sqlite3.connect(str(DB_PATH))
    ensure_archive_table(conn)
    
    cutoff = (datetime.now() - timedelta(days=keep_days)).strftime("%Y-%m-%d")
    
    old_items = conn.execute("""
        SELECT id, title, platform, source, url, 
               ai_score_total, ai_score_scarcity, ai_score_impact,
               ai_score_tech_depth, ai_score_timeliness, ai_score_preference,
               ai_score_credibility, ai_score_reasoning,
               importance_score, value_level, collected_at
        FROM cleaned_intelligence
        WHERE DATE(cleaned_at) < ?
    """, (cutoff,)).fetchall()
    
    if not old_items:
        log.info("无可归档数据")
        conn.close()
        return {"archived": 0}
    
    archived = 0
    for row in old_items:
        item_id = row[0]
        reasoning = row[12] or "{}"
        summary = ""
        try:
            r = json.loads(reasoning)
            summary = r.get("summary", "")[:200]
        except:
            summary = row[1][:200] if row[1] else ""
        
        conn.execute("""
            INSERT INTO history_archive 
            (title, platform, source, url, 
             ai_score_total, ai_score_scarcity, ai_score_impact,
             ai_score_tech_depth, ai_score_timeliness, ai_score_preference,
             ai_score_credibility, summary,
             importance_score, value_level, collected_at, compressed_from_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            row[1], row[2], row[3], row[4],
            row[5], row[6], row[7], row[8], row[9], row[10], row[11],
            summary,
            row[13], row[14], row[15], item_id
        ))
        
        conn.execute("DELETE FROM cleaned_intelligence WHERE id = ?", (item_id,))
        archived += 1
        
        if archived % 500 == 0:
            conn.commit()
            log.info(f"已归档 {archived} 条...")
    
    conn.commit()
    conn.close()
    log.info(f"归档完成: {archived} 条")
    return {"archived": archived}

if __name__ == "__main__":
    keep_days = int(sys.argv[1]) if len(sys.argv) > 1 else 7
    result = archive_data(keep_days)
    print(json.dumps(result))
