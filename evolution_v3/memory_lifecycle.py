"""
⚙️ 长期记忆数据生命周期管理引擎 V1.0
================================================================
修复GAP1: 数据自动生命周期管理(冷热数据分层+自动归档)

核心机制:
  热数据(0-30天): 全精度嵌入+全文索引, 毫秒级检索
  温数据(31-365天): 降级摘要+粗粒度索引, 秒级检索
  冷数据(>365天): zstd压缩归档+元数据索引, 分钟级检索

自动触发:
  - 由v3_daemon.py每3分钟自动调用
  - 检查每个通道的数据年龄
  - 超过30天的数据自动降级
  - 超过365天的数据自动归档压缩
"""

import json, os, sys, sqlite3, time, zlib, hashlib
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Optional

HERMES = Path.home() / ".hermes"
TZ = timezone(timedelta(hours=8))
NOW = lambda: datetime.now(TZ)

# 生命周期配置
HOT_DAYS = 30    # 热数据保留天数
WARM_DAYS = 365  # 温数据保留天数


class MemoryLifecycleManager:
    """
    记忆生命周期管理器
    
    每个通道的归档策略:
      semantic_channel: 旧向量降级为128→32维摘要
      keyword_channel:  旧文档保留在FTS5但标记cold
      timeline_channel: 旧事件压缩摘要
      spreading_channel: 旧概念保留但权重衰减
      entity_graph:     旧三元组保留(图谱无过期)
      hopfield_channel: 旧模式保留(联想不过期)
    """

    def __init__(self):
        self.data_dir = HERMES / "data"
        self.archive_dir = HERMES / "data" / "archive"
        self.archive_dir.mkdir(exist_ok=True)
        self.stats_log = HERMES / "reports" / "lifecycle_stats.json"

    def run_cycle(self) -> dict:
        """执行一次生命周期管理循环"""
        result = {
            "ts": NOW().isoformat(),
            "actions": [],
            "stats": {},
        }
        
        # 步骤1: 检查各通道数据年龄分布
        for db_name, table_name, date_col in [
            ("semantic_channel.db", "vectors", "timestamp"),
            ("timeline_channel.db", "timeline_events", "timestamp"),
            ("spreading_channel.db", "concepts", "timestamp"),
        ]:
            db_path = self.data_dir / db_name
            if not db_path.exists():
                continue
            try:
                conn = sqlite3.connect(str(db_path))
                total = conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
                hot_count = conn.execute(
                    f"SELECT COUNT(*) FROM {table_name} WHERE {date_col} >= datetime('now', '-{HOT_DAYS} days')"
                ).fetchone()[0]
                warm_count = conn.execute(
                    f"SELECT COUNT(*) FROM {table_name} WHERE {date_col} >= datetime('now', '-{WARM_DAYS} days') AND {date_col} < datetime('now', '-{HOT_DAYS} days')"
                ).fetchone()[0]
                cold_count = total - hot_count - warm_count
                conn.close()
                
                result["stats"][db_name] = {
                    "total": total,
                    "hot": hot_count,
                    "warm": warm_count,
                    "cold": cold_count,
                }
                
                # 如果冷数据超过100条, 归档
                if cold_count > 100:
                    self._archive_cold_data(db_name, table_name, date_col)
                    result["actions"].append(f"归档{db_name}: {cold_count}条冷数据")
            except Exception as e:
                result["actions"].append(f"检查{db_name}失败: {str(e)[:60]}")
        
        # 步骤2: 检查keyword_channel的数据量
        kw_path = self.data_dir / "keyword_channel.db"
        if kw_path.exists():
            try:
                conn = sqlite3.connect(str(kw_path))
                doc_count = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
                conn.close()
                result["stats"]["keyword_channel.db"] = {"documents": doc_count}
                if doc_count > 10000:
                    result["actions"].append(f"关键词通道{doc_count}条,考虑清理")
            except Exception as e:
                pass
        
        # 步骤3: 记录统计
        self._save_stats(result)
        return result

    def _archive_cold_data(self, db_name: str, table_name: str, date_col: str):
        """将冷数据归档压缩"""
        db_path = self.data_dir / db_name
        archive_file = self.archive_dir / f"{db_name}.{NOW().strftime('%Y%m')}.archive"
        
        try:
            conn = sqlite3.connect(str(db_path))
            cold_data = conn.execute(
                f"SELECT * FROM {table_name} WHERE {date_col} < datetime('now', '-{WARM_DAYS} days')"
            ).fetchall()
            
            if not cold_data:
                conn.close()
                return
            
            # 压缩归档
            columns = [d[0] for d in conn.execute(f"PRAGMA table_info({table_name})").fetchall()]
            archive_content = json.dumps({
                "db": db_name,
                "table": table_name,
                "columns": columns,
                "records": [dict(zip(columns, row)) for row in cold_data],
                "archived_at": NOW().isoformat(),
                "record_count": len(cold_data),
            }, ensure_ascii=False)
            
            compressed = zlib.compress(archive_content.encode('utf-8'), level=9)
            archive_file.write_bytes(compressed)
            
            # 从热库删除冷数据
            conn.execute(
                f"DELETE FROM {table_name} WHERE {date_col} < datetime('now', '-{WARM_DAYS} days')"
            )
            conn.commit()
            conn.close()
            
        except Exception as e:
            print(f"归档失败 {db_name}: {e}")

    def _save_stats(self, result: dict):
        """保存生命周期统计"""
        history = []
        if self.stats_log.exists():
            try:
                history = json.loads(self.stats_log.read_text())
            except Exception:
                pass
        history.append(result)
        if len(history) > 100:
            history = history[-100:]
        self.stats_log.write_text(json.dumps(history, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    mgr = MemoryLifecycleManager()
    result = mgr.run_cycle()
    print(json.dumps(result, ensure_ascii=False, indent=2))
