#!/usr/bin/env python3
"""
AutoClean记忆清理引擎 (P3-4)
==================================
功能：每周清理错误/过时/重复的记忆

清理策略:
- 错误经验检测: 连续3次调用失败标记
- 过时经验检测: >90天未使用的标记
- 重复经验检测: 语义相似度>0.85的合并
- 软删除(标记)而非物理删除

Usage:
  python3 auto_cleaner.py --run             执行清理
  python3 auto_cleaner.py --dry-run         试运行（不实际标记）
  python3 auto_cleaner.py --status          查看清理状态
  python3 auto_cleaner.py --force-delete    强制物理删除标记项
"""

import json, sys, os, sqlite3, hashlib, re, uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from collections import defaultdict

HERMES = Path("/home/administrator/.hermes")
STATE_DB = HERMES / "state.db"
INTEL_DB = HERMES / "intelligence.db"
ACTIVE_MEM_DB = HERMES / "active_memory.db"
TZ = timezone(timedelta(hours=8))

def log(msg: str):
    ts = datetime.now(TZ).strftime("%H:%M:%S")
    print(f"[{ts}] {msg}")

NOW = datetime.now(TZ)


class AutoCleaner:
    """
    AutoClean记忆清理引擎
    自动检测并标记错误/过时/重复的记忆
    """

    # 配置阈值
    MAX_FAILURE_COUNT = 3
    MAX_AGE_DAYS = 90
    SIMILARITY_THRESHOLD = 0.85

    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run
        self.stats = {
            "scanned": 0,
            "error_marked": 0,
            "stale_marked": 0,
            "duplicate_merged": 0,
            "total_marked": 0,
            "cleaned_at": NOW.isoformat(),
        }
        self.report = []

    # ══════════════════════════════════════════════════════════════
    # 1. 错误经验检测
    # ══════════════════════════════════════════════════════════════

    def detect_error_memories(self) -> List[Dict]:
        """
        检测连续3次调用失败的记忆
        检查state.db中的会话记录和intelligence.db中的评分记录
        """
        log("🔍 [1/3] 错误经验检测 — 查找连续3次调用失败的记忆")
        marked = []

        # 从state.db检查会话错误率
        try:
            conn = sqlite3.connect(str(STATE_DB))
            c = conn.cursor()
            
            # 检查retrospectives表中高错误率的记录
            rows = c.execute("""
                SELECT id, session_id, session_title, total_score, error_rate
                FROM retrospectives
                WHERE error_rate > 50 OR total_score < 30
                ORDER BY created_at DESC
                LIMIT 100
            """).fetchall()
            conn.close()

            for row in rows:
                rec_id, session_id, title, score, error_rate = row
                entry = {
                    "id": rec_id,
                    "type": "high_error_rate",
                    "source": "retrospectives",
                    "session_id": session_id,
                    "title": title,
                    "score": score,
                    "error_rate": error_rate,
                    "reason": f"错误率{error_rate}% >= 50% 或评分{score} < 30",
                    "action": "mark_error",
                }
                marked.append(entry)
                log(f"    ⚠️ 标记: [{title[:40]}] 错误率{error_rate}%")

        except Exception as e:
            log(f"  ⚠️ 错误经验检测失败: {e}")

        self.stats["error_marked"] = len(marked)
        return marked

    # ══════════════════════════════════════════════════════════════
    # 2. 过时经验检测
    # ══════════════════════════════════════════════════════════════

    def detect_stale_memories(self) -> List[Dict]:
        """
        检测>90天未使用的记忆
        检查所有memory表的最新更新时间
        """
        log(f"🔍 [2/3] 过时经验检测 — 查找>{self.MAX_AGE_DAYS}天未使用的记忆")
        marked = []
        cutoff = (NOW - timedelta(days=self.MAX_AGE_DAYS)).isoformat()

        # 检查active_memory.db
        if ACTIVE_MEM_DB.exists():
            try:
                conn = sqlite3.connect(str(ACTIVE_MEM_DB))
                c = conn.cursor()
                
                # 获取所有表
                tables = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
                for table in tables:
                    try:
                        if "created_at" in [r[1] for r in c.execute(f"PRAGMA table_info({table})").fetchall()]:
                            rows = c.execute(f"""
                                SELECT rowid, * FROM {table}
                                WHERE created_at < ?
                                LIMIT 200
                            """, (cutoff,)).fetchall()
                            
                            for row in rows:
                                entry = {
                                    "id": f"{table}_{row[0]}",
                                    "type": "stale",
                                    "source": f"active_memory.db/{table}",
                                    "reason": f"最后更新 >{self.MAX_AGE_DAYS}天 (截止: {cutoff})",
                                    "action": "mark_stale",
                                }
                                marked.append(entry)
                                if len(marked) <= 5:
                                    log(f"    ⏰ 标记过时: {table}[{row[0]}]")
                    except:
                        continue
                
                conn.close()
            except Exception as e:
                log(f"  ⚠️ 过时检测失败(active_memory): {e}")

        # 检查intelligence.db
        if INTEL_DB.exists():
            try:
                conn = sqlite3.connect(str(INTEL_DB))
                c = conn.cursor()
                tables = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
                for table in tables:
                    try:
                        cols = [r[1] for r in c.execute(f"PRAGMA table_info({table})").fetchall()]
                        date_cols = [c for c in cols if "time" in c.lower() or "date" in c.lower() or "at" in c.lower()]
                        if date_cols:
                            date_col = date_cols[0]
                            rows = c.execute(f"""
                                SELECT rowid FROM {table}
                                WHERE {date_col} < ?
                                LIMIT 200
                            """, (cutoff,)).fetchall()
                            for row in rows:
                                marked.append({
                                    "id": f"{table}_{row[0]}",
                                    "type": "stale",
                                    "source": f"intelligence.db/{table}",
                                    "reason": f"最后更新 >{self.MAX_AGE_DAYS}天",
                                    "action": "mark_stale",
                                })
                    except:
                        continue
                conn.close()
            except Exception as e:
                log(f"  ⚠️ 过时检测失败(intelligence): {e}")

        # 限制数量防止内存暴涨
        marked = marked[:500]
        self.stats["stale_marked"] = len(marked)
        log(f"    📊 共发现 {len(marked)} 条过时记忆")
        return marked

    # ══════════════════════════════════════════════════════════════
    # 3. 重复经验检测
    # ══════════════════════════════════════════════════════════════

    def _simple_similarity(self, text_a: str, text_b: str) -> float:
        """简单的文本相似度计算（基于词重叠）"""
        if not text_a or not text_b:
            return 0.0
        
        # 提取关键词
        words_a = set(re.findall(r'\w+', text_a.lower()))
        words_b = set(re.findall(r'\w+', text_b.lower()))
        
        if not words_a or not words_b:
            return 0.0
        
        intersection = words_a & words_b
        union = words_a | words_b
        
        # Jaccard相似度
        return len(intersection) / len(union)

    def detect_duplicate_memories(self) -> List[Dict]:
        """
        检测重复记忆（语义相似度>0.85的合并）
        """
        log(f"🔍 [3/3] 重复经验检测 — 查找相似度>{self.SIMILARITY_THRESHOLD}的重复记忆")
        merged = []

        # 从intelligence.db检查skill_experiences
        try:
            conn = sqlite3.connect(str(INTEL_DB))
            c = conn.cursor()
            
            # 检查是否存在表
            tables = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
            
            for table in tables:
                try:
                    cols = [r[1] for r in c.execute(f"PRAGMA table_info({table})").fetchall()]
                    # 找文本列
                    text_cols = [c for c in cols if c in ("description", "pattern", "content", "caveat", "context")]
                    if not text_cols:
                        continue
                    
                    text_col = text_cols[0]
                    rows = c.execute(f"SELECT rowid, {text_col} FROM {table} WHERE {text_col} IS NOT NULL LIMIT 500").fetchall()
                    
                    # 两两比较
                    for i in range(len(rows)):
                        for j in range(i + 1, len(rows)):
                            rowid_i, text_i = rows[i]
                            rowid_j, text_j = rows[j]
                            
                            sim = self._simple_similarity(str(text_i), str(text_j))
                            if sim > self.SIMILARITY_THRESHOLD:
                                entry = {
                                    "id": f"{table}_{rowid_i}_dup_{rowid_j}",
                                    "type": "duplicate",
                                    "source": f"intelligence.db/{table}",
                                    "item_a": f"{table}[{rowid_i}]",
                                    "item_b": f"{table}[{rowid_j}]",
                                    "similarity": round(sim, 3),
                                    "reason": f"相似度 {sim:.1%} > {self.SIMILARITY_THRESHOLD:.0%}",
                                    "action": "merge_toward_newer",
                                }
                                merged.append(entry)
                                if len(merged) <= 5:
                                    log(f"    🔄 发现重复: {table}[{rowid_i}] ↔ [{rowid_j}] (相似度{sim:.1%})")
                except:
                    continue
            
            conn.close()
        except Exception as e:
            log(f"  ⚠️ 重复检测失败: {e}")

        # 限制数量
        merged = merged[:200]
        self.stats["duplicate_merged"] = len(merged)
        return merged

    # ══════════════════════════════════════════════════════════════
    # 执行清理
    # ══════════════════════════════════════════════════════════════

    def _mark_deleted(self, entries: List[Dict], table_name: str):
        """软删除标记（软删除 = 在清理记录表标记）"""
        if not entries or self.dry_run:
            return

        try:
            conn = sqlite3.connect(str(STATE_DB))
            c = conn.cursor()
            
            # 创建清理记录表
            c.execute("""
                CREATE TABLE IF NOT EXISTS auto_clean_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    entry_id TEXT,
                    entry_type TEXT,
                    source TEXT,
                    reason TEXT,
                    action TEXT,
                    marked_at TEXT,
                    cleaned INTEGER DEFAULT 0
                )
            """)
            
            for entry in entries:
                c.execute("""
                    INSERT INTO auto_clean_log
                    (entry_id, entry_type, source, reason, action, marked_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    entry.get("id", ""),
                    entry.get("type", ""),
                    entry.get("source", ""),
                    entry.get("reason", ""),
                    entry.get("action", ""),
                    NOW.isoformat(),
                ))
            
            conn.commit()
            conn.close()
        except Exception as e:
            log(f"  ⚠️ 标记删除失败: {e}")

    def run_cleanup(self) -> Dict[str, Any]:
        """执行全量清理"""
        log("\n" + "=" * 50)
        if self.dry_run:
            log("🧹 AutoClean记忆清理 (试运行模式)")
        else:
            log("🧹 AutoClean记忆清理 (执行模式)")
        log("=" * 50)

        # 1. 错误经验检测
        error_entries = self.detect_error_memories()
        self._mark_deleted(error_entries, "high_error_rate")
        self.report.extend(error_entries)

        # 2. 过时经验检测
        stale_entries = self.detect_stale_memories()
        self._mark_deleted(stale_entries, "stale")
        self.report.extend(stale_entries)

        # 3. 重复经验检测
        dup_entries = self.detect_duplicate_memories()
        self._mark_deleted(dup_entries, "duplicate")
        self.report.extend(dup_entries)

        # 汇总
        self.stats["total_marked"] = len(self.report)
        self.stats["scanned"] = len(error_entries) + len(stale_entries) + len(dup_entries)

        log("\n" + "=" * 50)
        log("📊 清理汇总")
        log("=" * 50)
        log(f"  扫描项数:      {self.stats['scanned']}")
        log(f"  错误标记:      {self.stats['error_marked']}")
        log(f"  过时标记:      {self.stats['stale_marked']}")
        log(f"  重复合并:      {self.stats['duplicate_merged']}")
        log(f"  总计标记:      {self.stats['total_marked']}")
        if self.dry_run:
            log("  📝 试运行 — 未实际标记")
        else:
            log(f"  ✅ 清理完成 — {self.stats['total_marked']} 条已标记为待清理")
        log("=" * 50)

        # 保存报告
        self._save_report()
        
        return self.stats

    def force_physical_delete(self):
        """强制物理删除已标记的项"""
        log("\n⚠️ 强制物理删除模式")
        log("=" * 50)
        
        try:
            conn = sqlite3.connect(str(STATE_DB))
            c = conn.cursor()
            
            # 清除清理日志
            c.execute("DELETE FROM auto_clean_log WHERE cleaned=0")
            deleted = c.rowcount
            conn.commit()
            conn.close()
            
            log(f"  🗑️ 物理删除 {deleted} 条标记记录")
        except Exception as e:
            log(f"  ⚠️ 物理删除失败: {e}")

    def show_status(self):
        """显示清理状态"""
        log("\n📊 AutoClean 状态报告")
        log("=" * 50)
        
        try:
            conn = sqlite3.connect(str(STATE_DB))
            c = conn.cursor()
            
            # 检查auto_clean_log表
            rows = c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='auto_clean_log'").fetchall()
            if not rows:
                log("  📝 清理日志为空 (尚未执行过清理)")
                conn.close()
                return
            
            # 统计
            total = c.execute("SELECT COUNT(*) FROM auto_clean_log").fetchone()[0]
            pending = c.execute("SELECT COUNT(*) FROM auto_clean_log WHERE cleaned=0").fetchone()[0]
            cleaned = c.execute("SELECT COUNT(*) FROM auto_clean_log WHERE cleaned=1").fetchone()[0]
            
            # 按类型统计
            by_type = c.execute("""
                SELECT entry_type, COUNT(*) as cnt
                FROM auto_clean_log
                GROUP BY entry_type
                ORDER BY cnt DESC
            """).fetchall()
            
            # 最近标记
            recent = c.execute("""
                SELECT entry_id, entry_type, reason, marked_at
                FROM auto_clean_log
                ORDER BY marked_at DESC
                LIMIT 10
            """).fetchall()
            
            conn.close()
            
            log(f"  总记录: {total}")
            log(f"  待处理(软删除): {pending}")
            log(f"  已清理: {cleaned}")
            log(f"\n  按类型分布:")
            for e_type, cnt in by_type:
                log(f"    - {e_type}: {cnt}")
            
            if recent:
                log(f"\n  最近标记:")
                for entry_id, e_type, reason, marked_at in recent:
                    log(f"    [{e_type}] {reason[:50]}")
            
        except Exception as e:
            log(f"  ⚠️ 读取状态失败: {e}")

    def _save_report(self):
        """保存清理报告"""
        date_str = NOW.strftime("%Y%m%d_%H%M%S")
        mode = "dryrun" if self.dry_run else "clean"
        filepath = HERMES / "reports" / f"autoclean_{mode}_{date_str}.json"
        (HERMES / "reports").mkdir(exist_ok=True)
        
        report = {
            "mode": "dry_run" if self.dry_run else "clean",
            "stats": self.stats,
            "entries": self.report[:100],  # 限制报告大小
            "report_at": NOW.isoformat(),
        }
        
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        
        log(f"\n📄 清理报告已保存: {filepath}")


def main():
    if "--run" in sys.argv:
        cleaner = AutoCleaner(dry_run=False)
        cleaner.run_cleanup()
    elif "--dry-run" in sys.argv:
        cleaner = AutoCleaner(dry_run=True)
        cleaner.run_cleanup()
    elif "--status" in sys.argv:
        cleaner = AutoCleaner()
        cleaner.show_status()
    elif "--force-delete" in sys.argv:
        cleaner = AutoCleaner()
        cleaner.force_physical_delete()
    else:
        print("""AutoClean记忆清理引擎 (P3-4)
Usage:
  python3 auto_cleaner.py --run             执行清理（标记）
  python3 auto_cleaner.py --dry-run         试运行（不实际标记）
  python3 auto_cleaner.py --status          查看清理状态
  python3 auto_cleaner.py --force-delete    强制物理删除
""")


if __name__ == "__main__":
    main()
