#!/usr/bin/env python3
"""
Hermes 数据压缩归档系统 v1.0
===========================
将超过7天的历史数据压缩存储,释放数据库空间。

压缩策略:
1. cleaned_intelligence 中超过7天的条目 → 压缩摘要后存入 archive表,删除原始记录
2. raw_intelligence 中超过7天的记录 → 压缩后删除
3. 保留最近7天数据供实时评分和推送
4. AI评分过的条目永不删除(压缩但保留)
"""

import sqlite3, json, sys, os, time, logging, re
from datetime import datetime, timedelta, date
from pathlib import Path
from typing import List, Dict
from collections import defaultdict

HERMES = Path("/home/administrator/.hermes")
DB_PATH = HERMES / "intelligence.db"
LOG_DIR = HERMES / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / f"archive_{date.today().strftime('%Y%m%d')}.log"
ARCHIVE_DIR = HERMES / "archive"
ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler(LOG_FILE, encoding="utf-8"), logging.StreamHandler()]
)
log = logging.getLogger("archiver")


def ensure_archive_table():
    """确保存档表存在"""
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS archive_cleaned (
            id INTEGER PRIMARY KEY,
            title TEXT,
            platform TEXT,
            source TEXT,
            archived_at TEXT DEFAULT (datetime('now','localtime')),
            compressed_data TEXT,  -- JSON压缩后的全量数据
            ai_score_total REAL DEFAULT 0,
            ai_score_reasoning TEXT DEFAULT '',
            ai_scored_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS archive_raw (
            id INTEGER PRIMARY KEY,
            archived_at TEXT DEFAULT (datetime('now','localtime')),
            compressed_summary TEXT
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_archive_cleaned_platform ON archive_cleaned(platform)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_archive_cleaned_archived ON archive_cleaned(archived_at)
    """)
    conn.commit()
    conn.close()


def compress_cleaned(days_old: int = 7, batch_size: int = 500) -> Dict:
    """
    压缩 cleaned_intelligence 中超过 days_old 天的数据
    
    策略:
    1. AI已评分的:压缩全字段保留到archive,删除原始
    2. AI未评分的(不重要):直接删除
    """
    conn = sqlite3.connect(str(DB_PATH))
    cutoff = (datetime.now() - timedelta(days=days_old)).strftime("%Y-%m-%d %H:%M:%S")

    # 获取超过7天且AI已评分的条目
    rows = conn.execute("""
        SELECT id, title, content, url, source, platform, author, 
               published_at, collected_at, tags, category,
               importance_score, value_level, is_ai_related, personal_match_score,
               ai_score_scarcity, ai_score_impact, ai_score_tech_depth,
               ai_score_timeliness, ai_score_preference, ai_score_credibility,
               ai_score_total, ai_score_reasoning, ai_scored_at
        FROM cleaned_intelligence
        WHERE (published_at IS NOT NULL AND published_at < ?)
        ORDER BY published_at ASC
        LIMIT ?
    """, (cutoff, batch_size)).fetchall()

    if not rows:
        conn.close()
        return {"archived": 0, "deleted_unscored": 0, "message": "无超过7天的数据"}

    cols = [d[0] for d in conn.execute("PRAGMA table_info(cleaned_intelligence)").fetchall()]
    col_set = set(cols)

    archived = 0
    deleted_unscored = 0
    deleted_scored = 0

    for row in rows:
        item = dict(zip(
            ["id", "title", "content", "url", "source", "platform", "author",
             "published_at", "collected_at", "tags", "category",
             "importance_score", "value_level", "is_ai_related", "personal_match_score",
             "ai_score_scarcity", "ai_score_impact", "ai_score_tech_depth",
             "ai_score_timeliness", "ai_score_preference", "ai_score_credibility",
             "ai_score_total", "ai_score_reasoning", "ai_scored_at"],
            row
        ))

        item_id = item["id"]
        ai_total = item.get("ai_score_total", 0) or 0

        if ai_total > 0 and item.get("ai_score_reasoning"):
            # AI已评分 → 压缩存档
            compressed = {
                "id": item_id,
                "title": item["title"],
                "platform": item["platform"],
                "source": item["source"],
                "author": item["author"],
                "content": (item.get("content") or "")[:500],  # 只保留前500字
                "url": item.get("url", ""),
                "published_at": item.get("published_at", ""),
                "tags": item.get("tags", ""),
                "importance_score": item.get("importance_score", 0),
                "ai_score_scarcity": item.get("ai_score_scarcity", 0),
                "ai_score_impact": item.get("ai_score_impact", 0),
                "ai_score_tech_depth": item.get("ai_score_tech_depth", 0),
                "ai_score_timeliness": item.get("ai_score_timeliness", 0),
                "ai_score_preference": item.get("ai_score_preference", 0),
                "ai_score_credibility": item.get("ai_score_credibility", 0),
                "ai_score_total": ai_total,
            }

            conn.execute(
                "INSERT OR IGNORE INTO archive_cleaned (id, title, platform, source, archived_at, compressed_data, ai_score_total, ai_score_reasoning, ai_scored_at) VALUES (?, ?, ?, ?, datetime('now','localtime'), ?, ?, ?, ?)",
                (item_id, item["title"], item["platform"], item["source"],
                 json.dumps(compressed, ensure_ascii=False),
                 ai_total,
                 item.get("ai_score_reasoning", ""),
                 item.get("ai_scored_at", ""))
            )
            archived += 1
        else:
            # AI未评分 → 直接删除(不重要数据)
            deleted_unscored += 1

        # 从cleaned_intelligence删除
        conn.execute("DELETE FROM cleaned_intelligence WHERE id = ?", (item_id,))

    conn.commit()
    conn.close()

    result = {
        "archived": archived,
        "deleted_unscored": deleted_unscored,
        "total_processed": len(rows),
        "cutoff_date": cutoff,
    }
    log.info(f"  压缩完成: 存档{archived}条, 删除无评分{deleted_unscored}条")
    return result


def compress_raw(days_old: int = 3, batch_size: int = 1000) -> Dict:
    """
    压缩 raw_intelligence 中超过 days_old 天的数据
    原始数据只统计数量,不需要存档
    """
    conn = sqlite3.connect(str(DB_PATH))
    cutoff = (datetime.now() - timedelta(days=days_old)).strftime("%Y-%m-%d %H:%M:%S")

    # 统计超期数据
    total_old = conn.execute(
        "SELECT COUNT(*) FROM raw_intelligence WHERE collected_at < ?",
        (cutoff,)
    ).fetchone()[0]

    if total_old == 0:
        conn.close()
        return {"deleted": 0, "message": "无超过3天的原始数据"}

    # 删除超期数据
    conn.execute("DELETE FROM raw_intelligence WHERE collected_at < ?", (cutoff,))
    conn.commit()

    # 记录摘要
    summary = {
        "deleted": total_old,
        "cutoff": cutoff,
        "archived_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "note": f"删除了{total_old}条超过{int(days_old)}天的原始采集数据"
    }
    conn.execute(
        "INSERT INTO archive_raw (id, compressed_summary) VALUES (?, ?)",
        (int(time.time()), json.dumps(summary, ensure_ascii=False))
    )
    conn.commit()
    conn.close()

    log.info(f"  原始数据删除: {total_old}条 (>{days_old}天)")
    return {"deleted": total_old}


def archive_stats() -> Dict:
    """查看归档统计"""
    conn = sqlite3.connect(str(DB_PATH))
    archived_clean = conn.execute("SELECT COUNT(*) FROM archive_cleaned").fetchone()[0]
    archived_raw = conn.execute("SELECT COUNT(*) FROM archive_raw").fetchone()[0]
    clean_left = conn.execute("SELECT COUNT(*) FROM cleaned_intelligence").fetchone()[0]
    raw_left = conn.execute("SELECT COUNT(*) FROM raw_intelligence").fetchone()[0]

    # 按平台分布
    platform_dist = conn.execute(
        "SELECT platform, COUNT(*) FROM archive_cleaned GROUP BY platform ORDER BY COUNT(*) DESC LIMIT 10"
    ).fetchall()

    # 最高分存档
    top_archived = conn.execute(
        "SELECT id, title, ai_score_total, platform FROM archive_cleaned ORDER BY ai_score_total DESC LIMIT 5"
    ).fetchall()

    conn.close()

    return {
        "archived_clean": archived_clean,
        "archived_raw": archived_raw,
        "clean_left": clean_left,
        "raw_left": raw_left,
        "platform_dist": platform_dist,
        "top_archived": top_archived,
    }


def main():
    ensure_archive_table()

    if "--status" in sys.argv:
        s = archive_stats()
        print(f"📦 归档统计:")
        print(f"  archive_cleaned: {s['archived_clean']} 条")
        print(f"  archive_raw: {s['archived_raw']} 条")
        print(f"  cleaned_intelligence (剩余): {s['clean_left']} 条")
        print(f"  raw_intelligence (剩余): {s['raw_left']} 条")
        print(f"\n  存档平台分布TOP5:")
        for p, c in s['platform_dist'][:5]:
            print(f"    {p}: {c}")
        print(f"\n  最高分存档:")
        for t in s['top_archived']:
            print(f"    #{t[0]} [{t[3]}] → {t[2]:.0f}分 {t[1][:40]}")
        return

    if "--dry-run" in sys.argv:
        # 只统计不执行
        conn = sqlite3.connect(str(DB_PATH))
        cutoff_7 = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")
        old_clean = conn.execute(
            "SELECT COUNT(*) FROM cleaned_intelligence WHERE published_at < ?",
            (cutoff_7,)
        ).fetchone()[0]
        old_clean_scored = conn.execute(
            "SELECT COUNT(*) FROM cleaned_intelligence WHERE published_at < ? AND ai_score_total > 0",
            (cutoff_7,)
        ).fetchone()[0]

        cutoff_3 = (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d %H:%M:%S")
        old_raw = conn.execute(
            "SELECT COUNT(*) FROM raw_intelligence WHERE collected_at < ?",
            (cutoff_3,)
        ).fetchone()[0]
        conn.close()

        print(f"🔍 DRY RUN: 可压缩概览")
        print(f"  cleaned超7天: {old_clean} 条 (其中AI已评分: {old_clean_scored})")
        print(f"  raw超3天: {old_raw} 条")
        print(f"  压缩后可释放: ~{old_clean + old_raw} 条")
        return

    log.info("=" * 60)
    log.info(f"📦 Hermes 数据压缩归档系统 启动")
    log.info(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # 步骤1: 压缩原始数据 (>3天)
    log.info("\n步骤1: 压缩原始采集数据(>3天)")
    result_raw = compress_raw(days_old=3, batch_size=2000)
    log.info(f"  删除: {result_raw.get('deleted', 0)} 条")

    # 步骤2: 压缩cleaned数据 (>7天)
    log.info(f"\n步骤2: 压缩cleaned数据(>7天)")
    total_archived = 0
    total_deleted = 0
    for batch in range(10):
        result = compress_cleaned(days_old=7, batch_size=500)
        if result.get("total_processed", 0) == 0:
            break
        total_archived += result.get("archived", 0)
        total_deleted += result.get("deleted_unscored", 0)
        log.info(f"  批次{batch+1}: 存档{result.get('archived',0)} 删除{result.get('deleted_unscored',0)}")

    # 步骤3: VACUUM回收空间
    log.info("\n步骤3: VACUUM回收数据库空间")
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("VACUUM")
    conn.close()
    log.info("  VACUUM完成")

    # 步骤4: 最终状态
    log.info(f"\n步骤4: 归档后状态")
    s = archive_stats()
    log.info(f"  archive_cleaned: {s['archived_clean']}")
    log.info(f"  cleaned剩余: {s['clean_left']}")
    log.info(f"  raw剩余: {s['raw_left']}")

    log.info(f"\n✅ 压缩完成! 存档{total_archived}条, 删除{total_deleted}条无评分数据")
    print(f"ARCHIVE_RESULT:存档{total_archived}条,删除{total_deleted}条,raw清理{result_raw.get('deleted',0)}条")


if __name__ == "__main__":
    main()
