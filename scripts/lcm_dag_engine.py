#!/usr/bin/env python3
"""
LCM DAG层次化增量摘要引擎 v1.0
========================================
基于Lossless Context Management论文 + lossless-claw插件设计
实现: DAG增量摘要树 + SQLite持久化 + SHA-256完整性校验 + 完整溯源

集成到Hermes齿轮系统: gear_task_driver → lcm_dag_engine → gear_context_compressor
三冗余记忆引擎之一 (LCM DAG + Mem0 + Hindsight)

使用方法:
  python3 lcm_dag_engine.py store <session_id> <role> <content>   # 存储消息
  python3 lcm_dag_engine.py leaf <msg_ids> <summary>               # 创建摘要节点
  python3 lcm_dag_engine.py retrieve [--depth N]                    # 检索上下文
  python3 lcm_dag_engine.py verify                                   # 校验完整性
  python3 lcm_dag_engine.py consolidate                              # 主动整合摘要
  python3 lcm_dag_engine.py status                                   # 显示引擎状态
"""

import sqlite3
import json
import hashlib
import time
import sys
import os
from pathlib import Path

# ============ 配置 ============
DB_PATH = os.path.expanduser("~/.hermes/memory/lcm_dag/lcm_store.db")
CONSOLIDATION_THRESHOLD = 4  # 同层4个节点时自动凝练
MAX_DEPTH = 10

# ============ LCM DAG 引擎 ============

class LCMDAGEngine:
    """Lossless Context Management DAG层次化增量摘要引擎"""

    def __init__(self, db_path=None):
        self.db_path = Path(db_path or DB_PATH)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self):
        """初始化数据库schema - DAG摘要节点 + 原始消息 + 审计日志"""
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS raw_messages (
                msg_id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                token_count INTEGER DEFAULT 0,
                created_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS summary_nodes (
                node_id TEXT PRIMARY KEY,
                parent_id TEXT,
                depth INTEGER NOT NULL,
                summary_text TEXT NOT NULL,
                summary_hash TEXT NOT NULL,
                start_msg_id INTEGER,
                end_msg_id INTEGER,
                msg_count INTEGER DEFAULT 0,
                source TEXT DEFAULT 'auto',
                created_at REAL NOT NULL,
                compressed INTEGER DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS audit_log (
                log_id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                event_detail TEXT,
                node_id TEXT,
                checksum TEXT,
                created_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_lcm_depth ON summary_nodes(depth);
            CREATE INDEX IF NOT EXISTS idx_lcm_parent ON summary_nodes(parent_id);
            CREATE INDEX IF NOT EXISTS idx_lcm_session ON raw_messages(session_id);
            CREATE INDEX IF NOT EXISTS idx_lcm_audit_type ON audit_log(event_type);
        """)
        self.conn.commit()

    def _log_audit(self, event_type, event_detail="", node_id="", checksum=""):
        """写入审计日志"""
        self.conn.execute(
            "INSERT INTO audit_log (event_type, event_detail, node_id, checksum, created_at) VALUES (?,?,?,?,?)",
            (event_type, str(event_detail)[:500], node_id, checksum, time.time())
        )
        self.conn.commit()

    def store_message(self, session_id, role, content):
        """存储原始消息，返回msg_id"""
        content_hash = hashlib.sha256(content.encode('utf-8')).hexdigest()
        token_count = len(content.split())
        c = self.conn.execute(
            "INSERT INTO raw_messages (session_id,role,content,content_hash,token_count,created_at) VALUES (?,?,?,?,?,?)",
            (session_id, role, content, content_hash, token_count, time.time())
        )
        self.conn.commit()
        self._log_audit("message_stored", f"session={session_id} role={role} tokens={token_count}",
                        str(c.lastrowid), content_hash)
        return c.lastrowid

    def generate_summary_node(self, msg_ids, summary_text, depth=0, source="auto"):
        """创建摘要节点，返回node_id"""
        shash = hashlib.sha256(summary_text.encode('utf-8')).hexdigest()
        node_id = f"lcm:{depth}:{int(time.time())}:{shash[:12]}"
        self.conn.execute(
            """INSERT INTO summary_nodes 
               (node_id, parent_id, depth, summary_text, summary_hash, 
                start_msg_id, end_msg_id, msg_count, source, created_at, compressed)
               VALUES (?,?,?,?,?,?,?,?,?,?,1)""",
            (node_id, None, depth, summary_text, shash,
             msg_ids[0], msg_ids[-1], len(msg_ids), source, time.time())
        )
        self.conn.commit()
        self._log_audit("summary_created", f"depth={depth} msgs={len(msg_ids)}",
                        node_id, shash)
        self._check_consolidation(depth)
        return node_id

    def _check_consolidation(self, from_depth=0):
        """检查是否需要向上整合 - 同层节点>=阈值时自动凝练"""
        for depth in range(from_depth, MAX_DEPTH):
            c = self.conn.execute(
                "SELECT COUNT(*) FROM summary_nodes WHERE depth=? AND compressed=1",
                (depth,)
            )
            count = c.fetchone()[0]
            if count >= CONSOLIDATION_THRESHOLD:
                self._consolidate_at_depth(depth)
                return True
        return False

    def _consolidate_at_depth(self, depth):
        """将depth层的N个节点凝练为1个depth+1节点"""
        nodes = self.conn.execute(
            "SELECT * FROM summary_nodes WHERE depth=? AND compressed=1 ORDER BY created_at LIMIT ?",
            (depth, CONSOLIDATION_THRESHOLD)
        ).fetchall()
        if len(nodes) < CONSOLIDATION_THRESHOLD:
            return

        summaries = [n["summary_text"] for n in nodes]
        children_ids = [n["node_id"] for n in nodes]
        
        # 合并摘要 — 使用LLM拼接，这里先用连接符（实际使用时替换为LLM调用）
        merged = " | ".join(summaries)
        parent_node_id = f"lcm:{depth+1}:{int(time.time())}:{hashlib.sha256(merged.encode()[:16]).hexdigest()[:12]}"
        mhash = hashlib.sha256(merged.encode('utf-8')).hexdigest()

        # 更新子节点parent_id
        for cid in children_ids:
            self.conn.execute("UPDATE summary_nodes SET parent_id=? WHERE node_id=?", (parent_node_id, cid))

        # 创建父节点
        msg_ranges = [(n["start_msg_id"], n["end_msg_id"]) for n in nodes]
        start_msg = min(r[0] for r in msg_ranges)
        end_msg = max(r[1] for r in msg_ranges)
        total_msgs = sum(n["msg_count"] for n in nodes)

        self.conn.execute(
            """INSERT INTO summary_nodes 
               (node_id, parent_id, depth, summary_text, summary_hash,
                start_msg_id, end_msg_id, msg_count, source, created_at, compressed)
               VALUES (?,?,?,?,?,?,?,?,?,?,1)""",
            (parent_node_id, None, depth+1, merged, mhash,
             start_msg, end_msg, total_msgs, "auto_consolidate", time.time())
        )
        self.conn.commit()
        self._log_audit("consolidated",
                        f"depth={depth}->{depth+1} children={len(children_ids)}",
                        parent_node_id, mhash)

    def retrieve_context(self, max_depth=3, max_tokens=2000):
        """逐层收集上下文 - 从高层摘要到低层详情"""
        context_parts = []
        for d in range(min(max_depth, MAX_DEPTH), -1, -1):
            c = self.conn.execute(
                "SELECT summary_text, node_id, depth, msg_count FROM summary_nodes WHERE depth=? ORDER BY created_at DESC LIMIT 5",
                (d,)
            )
            for row in c:
                context_parts.append(f"[D{d}:{row['node_id'][:24]}] {row['summary_text']}")
        return '\n'.join(context_parts)

    def get_message_by_id(self, msg_id):
        """按msg_id获取原始消息"""
        c = self.conn.execute("SELECT * FROM raw_messages WHERE msg_id=?", (msg_id,))
        row = c.fetchone()
        return dict(row) if row else None

    def get_node_children(self, node_id):
        """获取某个节点的所有子节点"""
        c = self.conn.execute("SELECT * FROM summary_nodes WHERE parent_id=?", (node_id,))
        return [dict(row) for row in c.fetchall()]

    def expand_node(self, node_id):
        """展开摘要节点 - 获取该节点覆盖的所有原始消息"""
        node = self.conn.execute("SELECT * FROM summary_nodes WHERE node_id=?", (node_id,)).fetchone()
        if not node:
            return None
        msgs = self.conn.execute(
            "SELECT * FROM raw_messages WHERE msg_id BETWEEN ? AND ? ORDER BY msg_id",
            (node["start_msg_id"], node["end_msg_id"])
        ).fetchall()
        return {
            "node": dict(node),
            "messages": [dict(m) for m in msgs]
        }

    def verify_integrity(self):
        """验证所有节点SHA-256哈希完整性 - 返回损坏节点列表"""
        c = self.conn.execute("SELECT node_id, summary_text, summary_hash FROM summary_nodes")
        violations = []
        for node_id, text, expected_hash in c.fetchall():
            actual_hash = hashlib.sha256(text.encode('utf-8')).hexdigest()
            if actual_hash != expected_hash:
                violations.append({
                    "node_id": node_id,
                    "expected": expected_hash,
                    "actual": actual_hash
                })
        # 也验证原始消息
        c2 = self.conn.execute("SELECT msg_id, content, content_hash FROM raw_messages")
        for msg_id, content, expected_hash in c2.fetchall():
            actual_hash = hashlib.sha256(content.encode('utf-8')).hexdigest()
            if actual_hash != expected_hash:
                violations.append({
                    "msg_id": msg_id,
                    "expected": expected_hash,
                    "actual": actual_hash
                })
        self._log_audit("integrity_check",
                        f"violations={len(violations)} total_nodes={self._count_nodes()} total_msgs={self._count_msgs()}",
                        "", hashlib.sha256(str(violations).encode()).hexdigest()[:16])
        return violations

    def get_status(self):
        """获取引擎状态"""
        return {
            "total_messages": self._count_msgs(),
            "total_nodes": self._count_nodes(),
            "nodes_by_depth": self._nodes_by_depth(),
            "db_size_mb": self._db_size(),
            "audit_log_entries": self._count_audit(),
            "last_consolidation": self._last_event("consolidated"),
            "last_integrity_check": self._last_event("integrity_check"),
        }

    def _count_msgs(self):
        c = self.conn.execute("SELECT COUNT(*) FROM raw_messages")
        return c.fetchone()[0]

    def _count_nodes(self):
        c = self.conn.execute("SELECT COUNT(*) FROM summary_nodes")
        return c.fetchone()[0]

    def _nodes_by_depth(self):
        c = self.conn.execute("SELECT depth, COUNT(*) as cnt FROM summary_nodes GROUP BY depth ORDER BY depth")
        return {row["depth"]: row["cnt"] for row in c.fetchall()}

    def _db_size(self):
        try:
            return Path(str(self.db_path)).stat().st_size / (1024 * 1024)
        except Exception:
            return 0.0

    def _count_audit(self):
        c = self.conn.execute("SELECT COUNT(*) FROM audit_log")
        return c.fetchone()[0]

    def _last_event(self, event_type):
        c = self.conn.execute(
            "SELECT created_at FROM audit_log WHERE event_type=? ORDER BY created_at DESC LIMIT 1",
            (event_type,)
        )
        row = c.fetchone()
        return row["created_at"] if row else None


# ============ CLI 入口 ============

def main():
    engine = LCMDAGEngine()

    if len(sys.argv) < 2:
        print("用法: python3 lcm_dag_engine.py <命令> [参数...]")
        print("")
        print("命令:")
        print("  store <session_id> <role> <content>    存储消息")
        print("  leaf <msg_ids_json> <summary>           创建摘要节点")
        print("  retrieve [--depth N]                    检索上下文")
        print("  expand <node_id>                        展开节点原始消息")
        print("  verify                                   完整性校验")
        print("  consolidate                             主动整合摘要")
        print("  status                                  引擎状态")
        return

    cmd = sys.argv[1]

    if cmd == "store":
        if len(sys.argv) < 5:
            print("用法: store <session_id> <role> <content>")
            return
        msg_id = engine.store_message(sys.argv[2], sys.argv[3], sys.argv[4])
        print(f"STORED msg_id={msg_id}")

    elif cmd == "leaf":
        if len(sys.argv) < 4:
            print("用法: leaf <msg_ids_json> <summary>")
            return
        msg_ids = json.loads(sys.argv[2])
        node_id = engine.generate_summary_node(msg_ids, sys.argv[3], depth=0)
        print(f"CREATED node_id={node_id}")

    elif cmd == "retrieve":
        depth = 3
        if "--depth" in sys.argv:
            depth = int(sys.argv[sys.argv.index("--depth") + 1])
        ctx = engine.retrieve_context(max_depth=depth)
        print(ctx)

    elif cmd == "expand":
        if len(sys.argv) < 3:
            print("用法: expand <node_id>")
            return
        result = engine.expand_node(sys.argv[2])
        if result:
            print(f"Node: {result['node']['node_id']} (depth={result['node']['depth']})")
            for m in result['messages']:
                print(f"  [{m['msg_id']}] {m['role']}: {m['content'][:100]}...")
        else:
            print(f"Node not found: {sys.argv[2]}")

    elif cmd == "verify":
        violations = engine.verify_integrity()
        if violations:
            print(f"完整性校验失败! 发现 {len(violations)} 个损坏:")
            for v in violations:
                print(f"  - {v}")
        else:
            print("✅ 完整性校验通过 - 所有节点SHA-256哈希匹配")

    elif cmd == "consolidate":
        for d in range(MAX_DEPTH):
            if engine._check_consolidation(d):
                print(f"✅ depth={d} 整合完成")
        print("整合检查完成")

    elif cmd == "status":
        status = engine.get_status()
        print(f"原始消息数: {status['total_messages']}")
        print(f"摘要节点数: {status['total_nodes']}")
        print(f"节点深度分布: {json.dumps(status['nodes_by_depth'], indent=2)}")
        print(f"数据库大小: {status['db_size_mb']:.2f} MB")
        print(f"审计日志条目: {status['audit_log_entries']}")
        print(f"上次整合: {status['last_consolidation']}")
        print(f"上次完整性校验: {status['last_integrity_check']}")

    else:
        print(f"未知命令: {cmd}")


if __name__ == "__main__":
    main()
