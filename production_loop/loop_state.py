"""
LoopState — 全局状态唯一真相源
解决SaaS-Bench四大失败模式：
1. 越往后越做不对 → 全局进度追踪 (globalProgress)
2. 一步错步步错 → 操作后即时验证 (verificationHistory)
3. 做完不检查 → 强制验证记录 (verificationHistory)
4. 执行不稳定 → 确定性锚点 + 状态机 (fsmState)

融合文档§2.2 LoopState设计，但使用Hermes原生SQLite + JSON持久化
"""

from __future__ import annotations
import json
import time
import os
import sqlite3
from datetime import datetime
from dataclasses import dataclass, field, asdict
from typing import Optional

# ─── 类型定义 ─────────────────────────────────────────────────

@dataclass
class DAGNode:
    """DAG任务节点 — 每个子任务的定义"""
    id: str
    name: str
    description: str
    node_type: str = "action"  # action | verification | decision | recovery
    depends_on: list = field(default_factory=list)  # 前置依赖节点ID列表
    dependency_type: str = "all"  # all | any
    tool_name: Optional[str] = None
    tool_params: dict = field(default_factory=dict)
    sub_agent_type: Optional[str] = None

    # 成功标准（必须量化、可验证）
    success_criteria: list = field(default_factory=list)
    # 每个criterion: {"type": "state_check"|"value_match"|"existence"|"custom", "check": "...", "expected": ...}

    # 失败处理
    failure_policy: dict = field(default_factory=lambda: {
        "max_retries": 3,
        "retry_strategy": "backoff",
        "fallback_node_id": None,
        "escalate_on_failure": False
    })

    # 权重（用于计算整体进度）
    weight: float = 1.0

    # 风险评估
    risk_level: str = "low"  # low | medium | high | critical
    requires_user_approval: bool = False

    # 超时
    timeout_ms: int = 300000


@dataclass
class DAGEdge:
    """DAG边 — 依赖/数据流/触发关系"""
    from_node: str
    to_node: str
    edge_type: str = "dependency"  # dependency | data_flow | trigger
    data_mapping: dict = field(default_factory=dict)


@dataclass
class GlobalProgress:
    """全局进度追踪 — 解决'越往后越做不对'"""
    dag_id: str = ""
    current_node_id: str = ""
    completed_nodes: list = field(default_factory=list)
    failed_nodes: list = field(default_factory=list)
    skipped_nodes: list = field(default_factory=list)
    current_node_retry_count: int = 0
    overall_progress: float = 0.0  # 0-1


@dataclass
class Constraint:
    """约束定义"""
    id: str
    description: str
    verification_method: str = ""
    category: str = "hard"  # hard | soft


@dataclass
class GlobalConstraints:
    """全局约束锚定 — 防止目标漂移"""
    original_goal: str = ""
    business_rules: list = field(default_factory=list)
    hard_constraints: list = field(default_factory=list)
    soft_constraints: list = field(default_factory=list)
    constraint_check_history: list = field(default_factory=list)


@dataclass
class VerificationRecord:
    """验证记录"""
    step: int
    node_id: str
    tool_name: str
    passed: bool
    expected: str = ""
    actual: str = ""
    detail: str = ""
    timestamp: float = 0.0


@dataclass
class ReflectionRecord:
    """反思记录"""
    reflection_type: str = ""  # operational | strategic | goal
    node_id: str = ""
    content: str = ""
    improvement: str = ""
    timestamp: float = 0.0


@dataclass
class ToolUseStats:
    """工具调用统计"""
    total_calls: int = 0
    successful_calls: int = 0
    failed_calls: int = 0
    retried_calls: int = 0
    tool_specific: dict = field(default_factory=dict)


@dataclass
class LoopState:
    """
    LoopState — Agent执行全状态
    对应文档§2.2的完整LoopState TypeScript定义，使用Python dataclass实现
    """
    # 基础标识
    session_id: str = ""
    task_id: str = ""

    # 消息历史（核心上下文）— 外部引用，不在序列化中保存
    messages: list = field(default_factory=list)

    # 全局进度追踪
    global_progress: GlobalProgress = field(default_factory=GlobalProgress)

    # 全局约束
    global_constraints: GlobalConstraints = field(default_factory=GlobalConstraints)

    # 任务DAG
    task_dag: dict = field(default_factory=lambda: {"nodes": [], "edges": []})

    # 状态机状态
    fsm_state: str = "IDLE"  # IDLE|PLANNING|EXECUTING|VERIFYING|REFLECTING|WAITING_FOR_USER|RECOVERING

    # 上下文管理
    context_management: dict = field(default_factory=lambda: {
        "total_tokens_estimate": 0,
        "compaction_count": 0,
        "last_compaction_turn": 0
    })

    # 验证历史
    verification_history: list = field(default_factory=list)

    # 反思历史
    reflection_history: list = field(default_factory=list)

    # 工具调用统计
    tool_use_stats: ToolUseStats = field(default_factory=ToolUseStats)

    # 循环控制
    turn_count: int = 0
    max_output_tokens_recovery_count: int = 0
    has_attempted_reactive_compact: bool = False

    # 恢复状态
    recovery_state: dict = field(default_factory=dict)

    # 用户交互
    pending_approvals: list = field(default_factory=list)
    user_interventions: list = field(default_factory=list)

    # 环境快照
    environment_snapshots: list = field(default_factory=list)

    def record_verification_failure(self, node_id: str, verification: dict):
        """记录验证失败到全局进度"""
        self.global_progress.failed_nodes.append({
            "node_id": node_id,
            "reason": verification.get("detail", "unknown"),
            "retry_count": self.global_progress.current_node_retry_count,
            "timestamp": time.time()
        })

    def mark_node_completed(self, node_id: str):
        """标记节点完成"""
        if node_id not in self.global_progress.completed_nodes:
            self.global_progress.completed_nodes.append(node_id)
        self._recalc_progress()

    def get_previous_results(self, depends_on: list) -> dict:
        """获取前置依赖节点的执行结果"""
        results = {}
        for dep_id in depends_on:
            for record in self.verification_history:
                if record.node_id == dep_id:
                    results[dep_id] = {
                        "passed": record.passed,
                        "detail": record.detail
                    }
        return results

    def _recalc_progress(self):
        """重新计算整体进度"""
        nodes = self.task_dag.get("nodes", [])
        if not nodes:
            self.global_progress.overall_progress = 0.0
            return
        total_weight = sum(n.get("weight", 1.0) for n in nodes)
        completed_weight = sum(
            n.get("weight", 1.0)
            for n in nodes
            if n["id"] in self.global_progress.completed_nodes
        )
        self.global_progress.overall_progress = (
            completed_weight / total_weight if total_weight > 0 else 0.0
        )

    def to_dict(self) -> dict:
        """序列化为字典（用于保存）"""
        return {
            "session_id": self.session_id,
            "task_id": self.task_id,
            "global_progress": asdict(self.global_progress),
            "global_constraints": asdict(self.global_constraints),
            "task_dag": self.task_dag,
            "fsm_state": self.fsm_state,
            "context_management": self.context_management,
            "verification_history": [asdict(v) for v in self.verification_history],
            "reflection_history": [asdict(r) for r in self.reflection_history],
            "tool_use_stats": asdict(self.tool_use_stats),
            "turn_count": self.turn_count,
            "recovery_state": self.recovery_state,
            "pending_approvals": self.pending_approvals,
            "user_interventions": self.user_interventions,
            "environment_snapshots": self.environment_snapshots,
            "updated_at": datetime.now().isoformat()
        }

    @classmethod
    def from_dict(cls, data: dict) -> "LoopState":
        """从字典反序列化"""
        state = cls()
        state.session_id = data.get("session_id", "")
        state.task_id = data.get("task_id", "")
        state.global_progress = GlobalProgress(**data.get("global_progress", {}))
        state.global_constraints = GlobalConstraints(**data.get("global_constraints", {}))
        state.task_dag = data.get("task_dag", {"nodes": [], "edges": []})
        state.fsm_state = data.get("fsm_state", "IDLE")
        state.context_management = data.get("context_management", {})
        state.verification_history = [VerificationRecord(**v) for v in data.get("verification_history", [])]
        state.reflection_history = [ReflectionRecord(**r) for r in data.get("reflection_history", [])]
        state.tool_use_stats = ToolUseStats(**data.get("tool_use_stats", {}))
        state.turn_count = data.get("turn_count", 0)
        state.recovery_state = data.get("recovery_state", {})
        state.pending_approvals = data.get("pending_approvals", [])
        state.user_interventions = data.get("user_interventions", [])
        state.environment_snapshots = data.get("environment_snapshots", [])
        return state


# ─── 持久化层 ────────────────────────────────────────────────

class LoopStateStore:
    """
    LoopState持久化存储
    使用SQLite存储，支持检查点、状态变迁审计日志
    对应文档§3.1的状态变更记录表
    """

    DB_PATH = os.path.expanduser("~/.hermes/state/loop_state.db")

    def __init__(self, db_path: str = None):
        self.db_path = db_path or self.DB_PATH
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        """初始化数据库表结构"""
        conn = self._get_conn()
        try:
            conn.executescript("""
                -- 状态变更记录表（不可变日志）— 对应文档§3.1
                CREATE TABLE IF NOT EXISTS agent_state_transitions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    from_state TEXT NOT NULL,
                    to_state TEXT NOT NULL,
                    trigger_event TEXT NOT NULL,
                    trigger_reason TEXT NOT NULL,
                    loop_state_snapshot TEXT NOT NULL,
                    created_at TEXT DEFAULT (datetime('now'))
                );
                CREATE INDEX IF NOT EXISTS idx_transitions_session
                    ON agent_state_transitions(session_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_transitions_task
                    ON agent_state_transitions(task_id);

                -- 检查点快照表（支持断点恢复）— 对应文档§3.1
                CREATE TABLE IF NOT EXISTS agent_checkpoints (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    checkpoint_type TEXT NOT NULL,
                    state_data TEXT NOT NULL,
                    dag_progress TEXT NOT NULL,
                    created_at TEXT DEFAULT (datetime('now'))
                );
                CREATE INDEX IF NOT EXISTS idx_checkpoints_session
                    ON agent_checkpoints(session_id);
                CREATE INDEX IF NOT EXISTS idx_checkpoints_created
                    ON agent_checkpoints(created_at);

                -- 任务表
                CREATE TABLE IF NOT EXISTS agent_tasks (
                    task_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    original_goal TEXT NOT NULL,
                    status TEXT DEFAULT 'pending',
                    dag_json TEXT,
                    created_at TEXT DEFAULT (datetime('now')),
                    completed_at TEXT,
                    final_result TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_tasks_status ON agent_tasks(status);

                -- 验证日志表
                CREATE TABLE IF NOT EXISTS agent_verification_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    node_id TEXT NOT NULL,
                    tool_name TEXT NOT NULL,
                    passed INTEGER NOT NULL,
                    expected TEXT,
                    actual TEXT,
                    detail TEXT,
                    timestamp REAL
                );
                CREATE INDEX IF NOT EXISTS idx_verification_session
                    ON agent_verification_log(session_id);
            """)
            conn.commit()
        finally:
            conn.close()

    def save_state_transition(
        self, session_id: str, task_id: str,
        from_state: str, to_state: str,
        trigger_event: str, trigger_reason: str,
        loop_state: LoopState = None
    ):
        """记录状态变迁（不可变审计日志）"""
        conn = self._get_conn()
        try:
            conn.execute(
                """INSERT INTO agent_state_transitions
                   (session_id, task_id, from_state, to_state,
                    trigger_event, trigger_reason, loop_state_snapshot)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (session_id, task_id, from_state, to_state,
                 trigger_event, trigger_reason,
                 json.dumps(loop_state.to_dict(), ensure_ascii=False))
            )
            conn.commit()
        finally:
            conn.close()

    def save_checkpoint(
        self, session_id: str, checkpoint_type: str,
        loop_state: LoopState
    ) -> int:
        """保存检查点"""
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                """INSERT INTO agent_checkpoints
                   (session_id, checkpoint_type, state_data, dag_progress)
                   VALUES (?, ?, ?, ?)""",
                (session_id, checkpoint_type,
                 json.dumps(loop_state.to_dict(), ensure_ascii=False),
                 json.dumps(loop_state.global_progress.__dict__, ensure_ascii=False))
            )
            conn.commit()
            return cursor.lastrowid
        finally:
            conn.close()

    def load_latest_checkpoint(self, session_id: str) -> Optional[LoopState]:
        """加载最近一次检查点"""
        conn = self._get_conn()
        try:
            row = conn.execute(
                """SELECT state_data FROM agent_checkpoints
                   WHERE session_id = ?
                   ORDER BY id DESC LIMIT 1""",
                (session_id,)
            ).fetchone()
            if row:
                data = json.loads(row["state_data"])
                return LoopState.from_dict(data)
            return None
        finally:
            conn.close()

    def create_task(self, task_id: str, session_id: str,
                    original_goal: str, dag: dict = None) -> bool:
        """创建任务记录"""
        conn = self._get_conn()
        try:
            conn.execute(
                """INSERT OR IGNORE INTO agent_tasks
                   (task_id, session_id, original_goal, dag_json)
                   VALUES (?, ?, ?, ?)""",
                (task_id, session_id, original_goal,
                 json.dumps(dag, ensure_ascii=False) if dag else None)
            )
            conn.commit()
            return True
        finally:
            conn.close()

    def update_task_status(self, task_id: str, status: str,
                           final_result: str = None):
        """更新任务状态"""
        conn = self._get_conn()
        try:
            if status == "completed":
                conn.execute(
                    """UPDATE agent_tasks SET status = ?, completed_at = datetime('now'),
                       final_result = ? WHERE task_id = ?""",
                    (status, final_result, task_id)
                )
            else:
                conn.execute(
                    "UPDATE agent_tasks SET status = ? WHERE task_id = ?",
                    (status, task_id)
                )
            conn.commit()
        finally:
            conn.close()

    def log_verification(self, session_id: str, task_id: str,
                         node_id: str, tool_name: str,
                         passed: bool, expected: str = "",
                         actual: str = "", detail: str = ""):
        """记录验证结果"""
        conn = self._get_conn()
        try:
            conn.execute(
                """INSERT INTO agent_verification_log
                   (session_id, task_id, node_id, tool_name,
                    passed, expected, actual, detail, timestamp)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (session_id, task_id, node_id, tool_name,
                 1 if passed else 0, expected, actual, detail, time.time())
            )
            conn.commit()
        finally:
            conn.close()

    def get_task_status(self, task_id: str) -> Optional[dict]:
        """获取任务状态"""
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT * FROM agent_tasks WHERE task_id = ?",
                (task_id,)
            ).fetchone()
            if row:
                return dict(row)
            return None
        finally:
            conn.close()

    def get_unfinished_tasks(self) -> list:
        """获取所有未完成的任务"""
        conn = self._get_conn()
        try:
            rows = conn.execute(
                "SELECT * FROM agent_tasks WHERE status IN ('pending', 'running')"
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()


# ─── 检查点文件（文件即状态） ─────────────────────────────────

class FileBasedStateStore:
    """
    5文件状态管理 — 对应文档§7.1
    文件即状态架构，无需重型框架
    """

    STATE_DIR = os.path.expanduser("~/.hermes/state")
    TRACES_DIR = os.path.expanduser("~/.hermes/traces")
    CHECKPOINTS_DIR = os.path.expanduser("~/.hermes/checkpoints")

    def __init__(self):
        for d in [self.STATE_DIR, self.TRACES_DIR, self.CHECKPOINTS_DIR]:
            os.makedirs(d, exist_ok=True)

    # ── run_state.json: 当前DAG执行进度 ──
    def save_run_state(self, loop_state: LoopState):
        """保存当前运行状态"""
        path = os.path.join(self.STATE_DIR, "run_state.json")
        data = loop_state.to_dict()
        data["_meta"] = {"saved_at": datetime.now().isoformat()}
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def load_run_state(self) -> Optional[LoopState]:
        """加载运行状态"""
        path = os.path.join(self.STATE_DIR, "run_state.json")
        if not os.path.exists(path):
            return None
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        data.pop("_meta", None)
        return LoopState.from_dict(data)

    # ── last_success.json: 最近一次成功快照 ──
    def save_last_success(self, loop_state: LoopState):
        """保存最近成功状态"""
        path = os.path.join(self.STATE_DIR, "last_success.json")
        data = loop_state.to_dict()
        data["_meta"] = {"saved_at": datetime.now().isoformat()}
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def load_last_success(self) -> Optional[LoopState]:
        """加载最近成功状态"""
        path = os.path.join(self.STATE_DIR, "last_success.json")
        if not os.path.exists(path):
            return None
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        data.pop("_meta", None)
        return LoopState.from_dict(data)

    # ── dedupe_index.json: 去重索引 ──
    def save_dedupe_index(self, index: dict):
        """保存去重索引"""
        path = os.path.join(self.STATE_DIR, "dedupe_index.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(index, f, ensure_ascii=False, indent=2)

    def load_dedupe_index(self) -> dict:
        """加载去重索引"""
        path = os.path.join(self.STATE_DIR, "dedupe_index.json")
        if not os.path.exists(path):
            return {}
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    # ── execution_log.jsonl: 结构化执行日志 ──
    def log_execution(self, session_id: str, record: dict):
        """记录一条执行日志"""
        path = os.path.join(self.STATE_DIR, f"execution_{session_id}.jsonl")
        record["_timestamp"] = datetime.now().isoformat()
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    # ── handoff.md: 任务间上下文传递 ──
    def save_handoff(self, session_id: str, content: str):
        """保存handoff上下文"""
        path = os.path.join(self.STATE_DIR, f"handoff_{session_id}.md")
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)

    def load_handoff(self, session_id: str) -> Optional[str]:
        """加载handoff上下文"""
        path = os.path.join(self.STATE_DIR, f"handoff_{session_id}.md")
        if not os.path.exists(path):
            return None
        with open(path, "r", encoding="utf-8") as f:
            return f.read()

    # ── 检查点快照 ──
    def save_checkpoint_file(self, loop_state: LoopState):
        """保存增量式检查点"""
        checkpoint_dir = os.path.join(
            self.CHECKPOINTS_DIR, loop_state.session_id
        )
        os.makedirs(checkpoint_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(
            checkpoint_dir,
            f"checkpoint_{timestamp}.json"
        )
        data = loop_state.to_dict()
        data["_meta"] = {"saved_at": datetime.now().isoformat()}
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        # 清理旧检查点（只保留最近10个）
        self._cleanup_old_checkpoints(loop_state.session_id)

        return path

    def _cleanup_old_checkpoints(self, session_id: str, keep: int = 10):
        """清理旧检查点"""
        checkpoint_dir = os.path.join(self.CHECKPOINTS_DIR, session_id)
        if not os.path.exists(checkpoint_dir):
            return
        checkpoints = sorted([
            os.path.join(checkpoint_dir, f)
            for f in os.listdir(checkpoint_dir)
            if f.startswith("checkpoint_") and f.endswith(".json")
        ])
        for old_path in checkpoints[:-keep]:
            try:
                os.remove(old_path)
            except OSError:
                pass

    # ── 执行轨迹 ──
    def log_trace(self, task_id: str, record: dict):
        """记录执行轨迹"""
        trace_dir = os.path.join(self.TRACES_DIR, task_id)
        os.makedirs(trace_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(trace_dir, f"trace_{timestamp}.jsonl")
        record["_timestamp"] = datetime.now().isoformat()
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
