#!/usr/bin/env python3
"""
Hermes 低分数据清理器 v1.0 — 清理+归档低质量数据
===================================================
将AI评分<20的低质量数据从主库清理到归档表，
保持主库清爽，只保留有价值数据。

格林主人最高指令(2026-05-24): 
  低分数据(<20)必须清理，不能堆积在主库！
"""

import sqlite3, json, time
from datetime import datetime, timezone, timedelta
from pathlib import Path

HERMES = Path("/home/administrator/.hermes")
DB_PATH = HERMES / "intelligence.db"
LOG_PATH = HERMES / "logs" / "lowscore_cleaner.log"
TZ = timezone(timedelta(hours=8))
now = lambda: datetime.now(TZ)
THRESHOLD = 20  # 低于此分数被认为低质量


def log(msg: str):
    ts = now().isoformat()
    line = f"[{ts}] {msg}"
    print(line)
    LOG_PATH.parent.mkdir(exist_ok=True)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def clean_lowscore_data(dry_run: bool = False, batch_size: int = 1000) -> dict:
    """
    清理低分数据：
    1. 扫描 cleaned_intelligence 中 ai_score_total < 20 的数据
    2. 归档到 archive_cleaned 表（保留完整评分信息）
    3. 从 cleaned_intelligence 删除
    4. 统计结果
    """
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    cursor = conn.cursor()

    stats = {
        "scanned": 0,
        "archived": 0,
        "deleted": 0,
        "low_score": 0,
        "errors": 0,
        "remaining_low": 0,
        "db_size_before_mb": 0,
        "db_size_after_mb": 0,
    }

    # DB大小
    stats["db_size_before_mb"] = round(DB_PATH.stat().st_size / (1024 * 1024), 2)

    # 阶段1: 统计 + 归档低分数据
    log(f"{'🔍 DRY RUN' if dry_run else '🧹 开始清理'} — ai_score_total < {THRESHOLD}")

    # 查所有低分数据
    low_items = cursor.execute("""
        SELECT id, raw_id, title, content, url, source, platform, author,
               category, tags, importance_score, ai_score_total,
               ai_score_scarcity, ai_score_impact, ai_score_tech_depth,
               ai_score_timeliness, ai_score_preference, ai_score_credibility,
               ai_score_reasoning, collected_at, is_processed, personal_match_score
        FROM cleaned_intelligence 
        WHERE ai_score_total < ? OR ai_score_total IS NULL
        ORDER BY ai_score_total ASC
    """, (THRESHOLD,)).fetchall()

    stats["low_score"] = len(low_items)
    log(f"发现 {len(low_items)} 条低分数据 (ai_score_total < {THRESHOLD})")

    # 统计分数分布
    bins = {f"{i}-{i+9}": 0 for i in range(0, THRESHOLD, 10)}
    bins["null"] = 0
    for item in low_items:
        score = item[11]  # ai_score_total
        if score is None:
            bins["null"] += 1
        else:
            key = f"{int(score)//10*10}-{int(score)//10*10+9}"
            if key in bins:
                bins[key] += 1
    for k, v in bins.items():
        if v > 0:
            log(f"  分数区间 {k}: {v}条")

    # 阶段2: 归档到 archive_cleaned
    cols_str = ", ".join([str(d[0]) for d in cursor.execute("PRAGMA table_info(archive_cleaned)").fetchall()])
    log(f"归档列: {cols_str}")
    
    archived = 0
    deleted = 0
    errors = 0

    if not dry_run:
        for i in range(0, len(low_items), batch_size):
            batch = low_items[i:i+batch_size]
            batch_archived = 0
            batch_deleted = 0
            batch_errors = 0

            for item in batch:
                try:
                    item_id = item[0]  # cleaned_intelligence.id
                    
                    # 先检查是否已归档
                    exists = cursor.execute(
                        "SELECT COUNT(*) FROM archive_cleaned WHERE id = ?", 
                        (item_id,)
                    ).fetchone()[0]
                    
                    if exists == 0:
                        # 归档
                        compressed = {
                            "title": item[2],
                            "content": (item[3] or "")[:500],
                            "source": item[5],
                            "platform": item[6],
                            "url": item[4],
                        }
                        cursor.execute("""
                            INSERT OR IGNORE INTO archive_cleaned 
                            (id, title, platform, source, archived_at, compressed_data,
                             ai_score_total, ai_score_reasoning, ai_scored_at)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (
                            item_id,
                            (item[2] or "")[:500],
                            item[6] or "",
                            item[5] or "",
                            now().isoformat(),
                            json.dumps(compressed, ensure_ascii=False)[:2000],
                            item[11],  # ai_score_total
                            (item[18] or "")[:1000],  # ai_score_reasoning
                            now().isoformat(),
                        ))
                        batch_archived += 1

                    # 从主表删除
                    cursor.execute("DELETE FROM cleaned_intelligence WHERE id = ?", (item_id,))
                    batch_deleted += 1

                except Exception as e:
                    log(f"❌ 处理失败 id={item[0]}: {e}")
                    batch_errors += 1

            conn.commit()
            archived += batch_archived
            deleted += batch_deleted
            errors += batch_errors
            log(f"  批次 {i//batch_size + 1}: 归档{batch_archived} 删除{batch_deleted} 错误{batch_errors}")

    else:
        # Dry run: 只统计不操作
        log("   [DRY RUN] 不执行实际归档/删除")
        archived = len(low_items)
        deleted = len(low_items)

    stats["archived"] = archived
    stats["deleted"] = deleted
    stats["errors"] = errors

    # 阶段3: 统计剩余
    remaining = cursor.execute("""
        SELECT COUNT(*) FROM cleaned_intelligence 
        WHERE ai_score_total < ? OR ai_score_total IS NULL
    """, (THRESHOLD,)).fetchone()[0]
    stats["remaining_low"] = remaining

    # 阶段4: VACUUM 回收空间
    if not dry_run and deleted > 0:
        log("🔄 VACUUM 回收磁盘空间...")
        cursor.execute("VACUUM")
        log("✅ VACUUM 完成")

    stats["db_size_after_mb"] = round(DB_PATH.stat().st_size / (1024 * 1024), 2)

    conn.close()

    log(f"{'='*50}")
    log(f"清理完成:")
    log(f"  低分数据: {stats['low_score']}条")
    log(f"  已归档:   {stats['archived']}条")
    log(f"  已删除:   {stats['deleted']}条")
    log(f"  剩余低分: {stats['remaining_low']}条")
    log(f"  DB大小:   {stats['db_size_before_mb']}MB → {stats['db_size_after_mb']}MB")
    log(f"  {'DRY RUN' if dry_run else '✅ 清理完成'}")

    return stats


def also_clean_raw_orphans(dry_run: bool = False) -> dict:
    """
    清理raw_intelligence中已归档cleaned数据的raw记录
    （在cleaned中被清理的数据，raw中的对应记录也标记或删除）
    """
    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()
    stats = {"raw_orphans": 0, "raw_deleted": 0}

    # 清理管道留下的5,680条未清洗raw数据
    # 这包括重复和噪声
    dirty = cursor.execute("""
        SELECT r.id, r.title FROM raw_intelligence r
        LEFT JOIN cleaned_intelligence c ON r.id = c.raw_id
        LEFT JOIN archive_cleaned a ON c.id = a.id
        WHERE c.raw_id IS NULL
          AND r.collected_at < datetime('now', '-3 day')
        ORDER BY r.id ASC
    """).fetchall()

    stats["raw_orphans"] = len(dirty)
    log(f"原始表中3天前未清洗的孤立数据: {len(dirty)}条")

    if not dry_run and dirty:
        ids = [str(r[0]) for r in dirty]
        cursor.execute(f"DELETE FROM raw_intelligence WHERE id IN ({','.join(ids)})")
        conn.commit()
        stats["raw_deleted"] = len(dirty)
        log(f"✅ 已删除 {len(dirty)} 条孤立raw数据")

    conn.close()
    return stats


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Hermes 低分数据清理器")
    parser.add_argument("--dry-run", action="store_true", help="只统计不操作")
    parser.add_argument("--threshold", type=int, default=20, help="分数阈值(默认20)")
    parser.add_argument("--fast", action="store_true", help="快速模式: 不VACUUM")
    args = parser.parse_args()

    if args.threshold:
        THRESHOLD = args.threshold

    log(f"🏁 Hermes 低分数据清理器 v1.0")
    log(f"   DB: {DB_PATH}")
    log(f"   阈值: ai_score_total < {THRESHOLD}")
    log(f"   模式: {'DRY RUN' if args.dry_run else '实际执行'}")

    result = clean_lowscore_data(dry_run=args.dry_run)
    if not args.dry_run:
        raw_result = also_clean_raw_orphans(dry_run=args.dry_run)
        result.update(raw_result)

    print(f"\n{'='*60}")
    print(f"结果: {json.dumps(result, ensure_ascii=False, indent=2)}")
    print(f"{'='*60}")
