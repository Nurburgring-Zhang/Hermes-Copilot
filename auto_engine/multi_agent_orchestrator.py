#!/usr/bin/env python3
"""
Hermes Multi-Agent Orchestrator v2.0
多Agent智能协作系统 - 负责任务分解、Agent调度、结果汇聚
"""
import json
import logging
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

HERMES = Path.home() / ".hermes"
ORCHESTRATOR_DIR = HERMES / "auto_engine"
ORCHESTRATOR_DB = ORCHESTRATOR_DIR / "orchestrator.db"


class MultiAgentOrchestrator:
    """
    Multi-Agent 协作中枢
    支持：Hierarchical / Parallel / Sequential / Fan-out-Fan-in 模式
    """

    def __init__(self):
        self.max_concurrent = 5
        self.execution_log = []
        self._init_db()

    def _init_db(self):
        conn = sqlite3.connect(str(ORCHESTRATOR_DB))
        conn.execute("""
            CREATE TABLE IF NOT EXISTS agent_tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT UNIQUE,
                parent_task_id TEXT,
                agent_id TEXT,
                agent_name TEXT,
                status TEXT,  -- pending/running/complete/failed
                priority INTEGER DEFAULT 5,
                input_data TEXT,
                output_data TEXT,
                error_msg TEXT,
                created_at TEXT,
                started_at TEXT,
                completed_at TEXT,
                duration_ms REAL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS orchestration_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT UNIQUE,
                task_type TEXT,
                mode TEXT,  -- hierarchical/parallel/sequential/fanout
                status TEXT,
                total_agents INTEGER,
                completed_agents INTEGER,
                created_at TEXT,
                completed_at TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS agent_performance (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_id TEXT,
                task_id TEXT,
                success INTEGER,
                duration_ms REAL,
                timestamp TEXT
            )
        """)
        conn.commit()
        conn.close()

    # ─────────────────────────────────────────────────────────────
    # 核心编排方法
    # ─────────────────────────────────────────────────────────────

    def assign_task(
        self,
        agent_id: str,
        agent_name: str,
        task: Dict[str, Any],
        parent_task_id: Optional[str] = None,
        priority: int = 5
    ) -> str:
        """分配任务给指定Agent"""
        import uuid
        task_id = task.get("task_id") or f"task_{uuid.uuid4().hex[:8]}"

        conn = sqlite3.connect(str(ORCHESTRATOR_DB))
        conn.execute("""
            INSERT OR REPLACE INTO agent_tasks
            (task_id, parent_task_id, agent_id, agent_name, status, priority, input_data, created_at)
            VALUES (?, ?, ?, ?, 'pending', ?, ?, ?)
        """, (
            task_id,
            parent_task_id,
            agent_id,
            agent_name,
            priority,
            json.dumps(task, ensure_ascii=False),
            datetime.now().isoformat()
        ))
        conn.commit()
        conn.close()

        logger.info(f"[Orchestrator] Task {task_id} assigned to {agent_id}")
        return task_id

    def execute_parallel(
        self,
        tasks: List[Dict[str, Any]],
        mode: str = "parallel"
    ) -> Dict[str, Any]:
        """
        并行执行多个任务（Fan-out模式）
        tasks: [{"agent_id": "...", "task": {...}}, ...]
        """
        session_id = f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        start_time = time.time()

        conn = sqlite3.connect(str(ORCHESTRATOR_DB))
        conn.execute("""
            INSERT INTO orchestration_sessions
            (session_id, task_type, mode, status, total_agents, completed_agents, created_at)
            VALUES (?, ?, ?, 'running', ?, 0, ?)
        """, (session_id, "parallel", mode, len(tasks), datetime.now().isoformat()))
        conn.commit()
        conn.close()

        # Simulate parallel execution (actual execution via delegate_task)
        results = []
        for t in tasks:
            agent_id = t.get("agent_id", "unknown")
            task = t.get("task", {})
            task_id = self.assign_task(agent_id, t.get("agent_name", agent_id), task, priority=t.get("priority", 5))
            results.append({
                "task_id": task_id,
                "agent_id": agent_id,
                "status": "dispatched",
                "task": task
            })

        return {
            "session_id": session_id,
            "mode": mode,
            "tasks_dispatched": len(tasks),
            "max_concurrent": self.max_concurrent,
            "execution_mode": "async_dispatch",
            "tasks": results
        }

    def hierarchical_execute(
        self,
        root_task: Dict[str, Any],
        sub_tasks: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        层级执行：先执行根任务，再派发子任务
        Level 1: Orchestrator/Manager Agent
        Level 2: Specialist Agents
        """
        session_id = f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        # Root task
        root_task_id = self.assign_task(
            root_task.get("agent_id", "orchestrator"),
            root_task.get("agent_name", "Orchestrator"),
            root_task,
            priority=1
        )

        # Sub tasks
        child_results = []
        for st in sub_tasks:
            child_id = self.assign_task(
                st.get("agent_id"),
                st.get("agent_name", st.get("agent_id")),
                st.get("task", st),
                parent_task_id=root_task_id,
                priority=st.get("priority", 5)
            )
            child_results.append({
                "task_id": child_id,
                "parent": root_task_id,
                "agent_id": st.get("agent_id"),
                "priority": st.get("priority", 5)
            })

        return {
            "session_id": session_id,
            "mode": "hierarchical",
            "root_task_id": root_task_id,
            "root_task": root_task,
            "sub_tasks": child_results,
            "coordination": "parent_warrants_children"
        }

    def fan_out_fan_in(
        self,
        coordinator: Dict[str, Any],
        workers: List[Dict[str, Any]],
        aggregation: str = "merge"
    ) -> Dict[str, Any]:
        """
        扇出扇入：1个协调者 → N个worker → 汇总
        """
        session_id = f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        coord_task_id = self.assign_task(
            coordinator.get("agent_id", "coordinator"),
            coordinator.get("agent_name", "Coordinator"),
            coordinator.get("task", coordinator),
            priority=1
        )

        worker_ids = []
        for w in workers:
            wid = self.assign_task(
                w.get("agent_id"),
                w.get("agent_name", w.get("agent_id")),
                w.get("task", w),
                parent_task_id=coord_task_id,
                priority=w.get("priority", 5)
            )
            worker_ids.append(wid)

        return {
            "session_id": session_id,
            "mode": "fan_out_fan_in",
            "coordinator_task_id": coord_task_id,
            "worker_count": len(workers),
            "worker_ids": worker_ids,
            "aggregation_method": aggregation,
            "status": "fan_out_initiated"
        }

    # ─────────────────────────────────────────────────────────────
    # 任务执行引擎
    # ─────────────────────────────────────────────────────────────

    def get_next_pending_task(self, agent_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """获取下一个待处理任务（用于Agent拉取）"""
        conn = sqlite3.connect(str(ORCHESTRATOR_DB))
        if agent_id:
            row = conn.execute("""
                SELECT task_id, agent_id, agent_name, input_data, priority
                FROM agent_tasks
                WHERE status = 'pending' AND agent_id = ?
                ORDER BY priority ASC, created_at ASC
                LIMIT 1
            """, (agent_id,)).fetchone()
        else:
            row = conn.execute("""
                SELECT task_id, agent_id, agent_name, input_data, priority
                FROM agent_tasks
                WHERE status = 'pending'
                ORDER BY priority ASC, created_at ASC
                LIMIT 1
            """).fetchone()
        conn.close()

        if row:
            return {
                "task_id": row[0],
                "agent_id": row[1],
                "agent_name": row[2],
                "input": json.loads(row[3]),
                "priority": row[4]
            }
        return None

    def complete_task(
        self,
        task_id: str,
        output_data: Any,
        error_msg: Optional[str] = None
    ) -> None:
        """标记任务完成"""
        conn = sqlite3.connect(str(ORCHESTRATOR_DB))
        status = "complete" if not error_msg else "failed"
        now = datetime.now()

        # Get start time to calculate duration
        row = conn.execute(
            "SELECT started_at FROM agent_tasks WHERE task_id = ?", (task_id,)
        ).fetchone()
        started = row[0] if row else now.isoformat()

        conn.execute("""
            UPDATE agent_tasks SET
                status = ?,
                output_data = ?,
                error_msg = ?,
                completed_at = ?,
                duration_ms = ?
            WHERE task_id = ?
        """, (
            status,
            json.dumps(output_data, ensure_ascii=False),
            error_msg or "",
            now.isoformat(),
            (datetime.fromisoformat(now.isoformat()) -
             datetime.fromisoformat(started)).total_seconds() * 1000,
            task_id
        ))

        # Log performance
        duration_ms = (datetime.fromisoformat(now.isoformat()) -
                      datetime.fromisoformat(started)).total_seconds() * 1000
        conn.execute("""
            INSERT INTO agent_performance (agent_id, task_id, success, duration_ms, timestamp)
            VALUES (?, ?, ?, ?, ?)
        """, (
            conn.execute("SELECT agent_id FROM agent_tasks WHERE task_id = ?", (task_id,)
            ).fetchone()[0],
            task_id, 1 if status == "complete" else 0, duration_ms, now.isoformat()
        ))

        conn.commit()
        conn.close()

    def get_session_status(self, session_id: str) -> Dict[str, Any]:
        """获取会话状态"""
        conn = sqlite3.connect(str(ORCHESTRATOR_DB))
        sess = conn.execute(
            "SELECT * FROM orchestration_sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
        if not sess:
            conn.close()
            return {"error": "Session not found"}

        # Count completed agents
        completed = conn.execute("""
            SELECT COUNT(*) FROM agent_tasks
            WHERE parent_task_id IN (
                SELECT task_id FROM agent_tasks WHERE parent_task_id IS NULL
                AND task_id IN (SELECT task_id FROM agent_tasks)
            )
        """).fetchone()[0]

        conn.close()
        return {
            "session_id": sess[1],
            "mode": sess[3],
            "status": sess[4],
            "total_agents": sess[5],
            "completed_agents": completed
        }

    def get_agent_workload(self) -> Dict[str, Any]:
        """获取各Agent当前负载"""
        conn = sqlite3.connect(str(ORCHESTRATOR_DB))
        rows = conn.execute("""
            SELECT agent_id,
                   COUNT(*) as pending,
                   SUM(CASE WHEN status='running' THEN 1 ELSE 0 END) as running,
                   SUM(CASE WHEN status='complete' THEN 1 ELSE 0 END) as complete,
                   SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) as failed
            FROM agent_tasks
            WHERE created_at >= datetime('now', '-24 hours')
            GROUP BY agent_id
        """).fetchall()
        conn.close()

        workload = {}
        for row in rows:
            workload[row[0]] = {
                "pending": row[1],
                "running": row[2],
                "complete": row[3],
                "failed": row[4]
            }
        return workload

    def get_stats(self) -> Dict[str, Any]:
        """获取编排统计"""
        conn = sqlite3.connect(str(ORCHESTRATOR_DB))
        cur = conn.cursor()

        total = cur.execute("SELECT COUNT(*) FROM agent_tasks").fetchone()[0]
        pending = cur.execute("SELECT COUNT(*) FROM agent_tasks WHERE status='pending'").fetchone()[0]
        running = cur.execute("SELECT COUNT(*) FROM agent_tasks WHERE status='running'").fetchone()[0]
        complete = cur.execute("SELECT COUNT(*) FROM agent_tasks WHERE status='complete'").fetchone()[0]
        failed = cur.execute("SELECT COUNT(*) FROM agent_tasks WHERE status='failed'").fetchone()[0]

        sessions = cur.execute("SELECT COUNT(*) FROM orchestration_sessions").fetchone()[0]

        # Avg task duration
        avg_dur = cur.execute(
            "SELECT AVG(duration_ms) FROM agent_tasks WHERE duration_ms IS NOT NULL"
        ).fetchone()[0]

        conn.close()
        return {
            "total_tasks": total,
            "pending": pending,
            "running": running,
            "complete": complete,
            "failed": failed,
            "sessions": sessions,
            "avg_task_duration_ms": round(avg_dur, 1) if avg_dur else 0
        }


_orchestrator = None


def get_orchestrator() -> MultiAgentOrchestrator:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = MultiAgentOrchestrator()
    return _orchestrator


if __name__ == "__main__":
    orch = get_orchestrator()
    stats = orch.get_stats()
    print(f"\n=== MULTI-AGENT ORCHESTRATOR ===")
    print(f"Total Tasks: {stats['total_tasks']}")
    print(f"Pending: {stats['pending']}, Running: {stats['running']}, "
          f"Complete: {stats['complete']}, Failed: {stats['failed']}")
    print(f"Sessions: {stats['sessions']}")
    print(f"Avg Duration: {stats['avg_task_duration_ms']}ms")

    print("\n=== ORCHESTRATION MODES ===")
    print("  hierarchical  - Manager → Specialists")
    print("  parallel     - Concurrent execution")
    print("  sequential   - One after another")
    print("  fan_out_in   - Coordinator → Workers → Aggregate")

    print("\n=== TEST DISPATCH ===")
    result = orch.execute_parallel([
        {"agent_id": "expert_001", "agent_name": "深度学习架构师", "task": {"type": "design", "input": "设计一个推荐系统"}, "priority": 1},
        {"agent_id": "expert_002", "agent_name": "NLP专家", "task": {"type": "nlp", "input": "文本分类"}, "priority": 2},
    ])
    print(f"Session: {result['session_id']}")
    print(f"Tasks dispatched: {result['tasks_dispatched']}")
