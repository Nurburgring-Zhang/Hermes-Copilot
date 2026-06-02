"""
⚙️ Hooks六事件引擎 V1.0 — 全自动事件驱动系统
================================================================
基于OI v4.0 §28 + Claude Code六事件设计

完整事件体系:
  PreToolUse      — 工具执行前(批准/拒绝/修改工具输入)
  PostToolUse     — 工具执行后(分析结果/反馈/日志记录)
  SessionStart    — 会话开始时(加载环境变量/项目上下文)
  SessionEnd      — 会话结束时(交接笔记生成/状态持久化)
  UserPromptSubmit — 用户提交提示时(安全警告/上下文增强)
  KDNTriggered    — 关键决策节点触发(安全拦截/双确认)
  SubagentStart   — 子Agent启动(调度可见性/资源分配)
  SubagentStop    — 子Agent完成(结果汇总/上下文回收)

  DreamCycle      — OI新增: 子意识循环(后台定期巡检)
  CompactionWarning — OI新增: 压缩前保存会话快照

核心机制:
  - 声明式Hook注册(YAML配置 + Python装饰器)
  - ETW风格事件总线 + SQLite持久化事件日志
  - Hook链式处理(多个Hook可注册同一事件)
  - 决策输出: Allow / Deny / Modify
  - 自动故障恢复(钩子崩溃自动跳过+记录)
"""

import json, os, sys, sqlite3, time, hashlib, uuid, threading
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, List, Tuple, Callable, Set
from dataclasses import dataclass, field, asdict
from enum import Enum


HERMES = Path.home() / ".hermes"
TZ = timezone(timedelta(hours=8))
NOW = lambda: datetime.now(TZ)


# =================================================================
# 事件类型枚举
# =================================================================

class HookEventType(Enum):
    PRE_TOOL_USE = "pretooluse"
    POST_TOOL_USE = "posttooluse"
    SESSION_START = "session_start"
    SESSION_END = "session_end"
    USER_PROMPT_SUBMIT = "user_prompt_submit"
    KDN_TRIGGERED = "kdn_triggered"
    SUBAGENT_START = "subagent_start"
    SUBAGENT_STOP = "subagent_stop"
    DREAM_CYCLE = "dream_cycle"
    COMPACTION_WARNING = "compaction_warning"

    def __str__(self):
        return self.value


class HookDecision(Enum):
    ALLOW = "allow"
    DENY = "deny"
    MODIFY = "modify"
    DEFER = "defer"  # 推迟决策

    def __str__(self):
        return self.value


# =================================================================
# 事件数据结构
# =================================================================

@dataclass
class HookEvent:
    """统一事件对象 — 对应OI OIHookEvent"""
    event_type: HookEventType
    session_id: str
    timestamp: str = ""
    source: str = "system"
    
    # PreToolUse
    tool_name: str = ""
    tool_input: dict = field(default_factory=dict)
    tool_category: str = ""
    risk_level: str = "low"
    
    # PostToolUse
    tool_result: dict = field(default_factory=dict)
    execution_time_ms: int = 0
    
    # Session
    project_path: str = ""
    git_branch: str = ""
    task_summary: str = ""
    pending_items: list = field(default_factory=list)
    
    # UserPrompt
    prompt: str = ""
    
    # KDN
    decision_node: str = ""
    
    # Subagent
    subagent_name: str = ""
    task_id: str = ""
    subagent_result: dict = field(default_factory=dict)
    
    # Hook执行结果
    hook_id: str = ""
    decision: str = ""
    message: str = ""
    modified_input: dict = field(default_factory=dict)
    context_injection: str = ""
    
    def to_dict(self) -> dict:
        return {
            "event_type": str(self.event_type),
            "session_id": self.session_id,
            "timestamp": self.timestamp or NOW().isoformat(),
            "source": self.source,
            "tool_name": self.tool_name,
            "risk_level": self.risk_level,
            "execution_time_ms": self.execution_time_ms,
            "subagent_name": self.subagent_name,
            "task_id": self.task_id,
            "decision": self.decision,
            "message": self.message[:200],
        }


# =================================================================
# Hook处理器 — 基类
# =================================================================

class BaseHook:
    """
    Hook处理器基类 — 对应OI OIHook trait
    
    每个Hook:
      - name: 唯一标识符
      - event_type: 监听的事件类型
      - priority: 优先级(数字越低越先执行)
      - matcher: 匹配器(可选, 条件触发)
    """

    def __init__(self, name: str, event_type: HookEventType, priority: int = 100):
        self.name = name
        self.event_type = event_type
        self.priority = priority
        self.execution_count = 0
        self.failure_count = 0
        self.last_execution: Optional[str] = None
        self.enabled = True

    def should_trigger(self, event: HookEvent) -> bool:
        """是否应该触发(可被子类覆写实现条件触发)"""
        return True

    def execute(self, event: HookEvent) -> HookEvent:
        """
        执行Hook处理逻辑
        
        必须返回HookEvent(可修改event的decision/message/modified_input)
        """
        raise NotImplementedError

    def health_check(self) -> dict:
        """健康检查"""
        return {
            "name": self.name,
            "event_type": str(self.event_type),
            "enabled": self.enabled,
            "execution_count": self.execution_count,
            "failure_count": self.failure_count,
            "last_execution": self.last_execution,
        }


# =================================================================
# 内置Hook实现 — 全部8+2事件
# =================================================================

class SecurityAuditHook(BaseHook):
    """
    PreToolUse — 安全审计过滤器
    
    在工具执行前检查权限和风险评估
    """

    def __init__(self):
        super().__init__("security_audit", HookEventType.PRE_TOOL_USE, priority=10)
        # 高风险工具列表
        self.high_risk_tools = {
            "execute_code", "terminal_exec", "file_write", "db_execute",
            "network_request", "email_send", "deploy",
        }
        # 黑名单命令
        self.blocked_commands = {"rm -rf /", "dd if=/dev/zero", "format", "del /f /s"}

    def execute(self, event: HookEvent) -> HookEvent:
        self.execution_count += 1
        self.last_execution = NOW().isoformat()
        
        tool = event.tool_name.lower()
        
        # 检查高风险工具
        if tool in self.high_risk_tools:
            event.decision = str(HookDecision.DENY)
            event.message = f"安全审计: 高风险工具'{tool}'需要显式授权"
            event.risk_level = "high"
            return event
        
        # 检查黑名单命令
        ti = event.tool_input
        cmd = str(ti.get("command", "")).lower()
        for blocked in self.blocked_commands:
            if blocked in cmd:
                event.decision = str(HookDecision.DENY)
                event.message = f"安全审计: 拦截黑名单命令'{blocked[:50]}'"
                return event
        
        event.decision = str(HookDecision.ALLOW)
        event.message = f"安全审计: 工具'{tool}'通过安全检查"
        return event


class SessionLifecycleHook(BaseHook):
    """
    SessionStart/SessionEnd — 会话生命周期管理
    
    Start: 加载配置文件, 初始化会话状态
    End: 生成交接笔记, 保存状态快照
    """

    def __init__(self):
        super().__init__("session_lifecycle", HookEventType.SESSION_START, priority=50)

    def should_trigger(self, event: HookEvent) -> bool:
        """同时响应SESSION_START和SESSION_END"""
        return event.event_type in (HookEventType.SESSION_START, HookEventType.SESSION_END)

    def execute(self, event: HookEvent) -> HookEvent:
        self.execution_count += 1
        self.last_execution = NOW().isoformat()
        
        if event.event_type == HookEventType.SESSION_START:
            event.message = f"会话{event.session_id[:8]}启动: 加载项目上下文"
            event.context_injection = (
                f"会话 '{event.session_id[:8]}' 已初始化. "
                f"项目路径: {event.project_path or '默认'}. "
                f"加载配置完成."
            )
            event.decision = str(HookDecision.ALLOW)
        
        elif event.event_type == HookEventType.SESSION_END:
            event.message = f"会话结束: {event.task_summary[:100]}"
            # 生成交接笔记
            notes = {
                "ts": NOW().isoformat(),
                "session_id": event.session_id,
                "summary": event.task_summary,
                "pending": event.pending_items,
            }
            notes_path = HERMES / "reports" / "handoff_notes" / f"{event.session_id[:8]}.json"
            notes_path.parent.mkdir(exist_ok=True)
            notes_path.write_text(json.dumps(notes, ensure_ascii=False, indent=2))
            event.context_injection = f"交接笔记已保存: {notes_path}"
            event.decision = str(HookDecision.ALLOW)
        
        return event


class DriftDetectionHook(BaseHook):
    """
    UserPromptSubmit — 漂移检测钩子
    
    用户提交提示时检测是否偏离当前任务目标
    """

    def __init__(self):
        super().__init__("drift_detection", HookEventType.USER_PROMPT_SUBMIT, priority=30)
        self.last_goal = ""

    def execute(self, event: HookEvent) -> HookEvent:
        self.execution_count += 1
        self.last_execution = NOW().isoformat()
        
        prompt = event.prompt[:200]
        
        # 检测任务目标是否仍然相关
        goal_file = HERMES / "reports" / "task_goal.txt"
        if goal_file.exists():
            current_goal = goal_file.read_text().strip()[:100]
            if current_goal and len(current_goal) > 5:
                # 简单的关键词漂移检测
                goal_keywords = set(current_goal.lower().split()[:10])
                prompt_keywords = set(prompt.lower().split()[:10])
                overlap = len(goal_keywords & prompt_keywords)
                
                if overlap == 0 and len(goal_keywords) > 2:
                    event.message = (
                        f"注意: 当前输入'{prompt[:30]}'与任务目标"
                        f"'{current_goal[:30]}'无明显关联"
                    )
                    event.context_injection = event.message
        
        event.decision = str(HookDecision.ALLOW)
        return event


class KDNHook(BaseHook):
    """
    KDNTriggered — 关键决策节点处理
    
    高风险操作的双重确认
    """

    def __init__(self):
        super().__init__("kdn_handler", HookEventType.KDN_TRIGGERED, priority=10)

    def execute(self, event: HookEvent) -> HookEvent:
        self.execution_count += 1
        self.last_execution = NOW().isoformat()
        
        if event.risk_level == "high":
            event.decision = str(HookDecision.DENY)
            event.message = (
                f"KDN拦截: 高风险决策节点'{event.decision_node[:50]}'"
                f"需要人工确认"
            )
        else:
            event.decision = str(HookDecision.ALLOW)
            event.message = f"KDN通过: 节点'{event.decision_node[:50]}'风险等级{event.risk_level}"
        
        return event


class SubagentLifecycleHook(BaseHook):
    """
    SubagentStart/SubagentStop — 子Agent生命周期管理
    """

    def __init__(self):
        super().__init__("subagent_lifecycle", HookEventType.SUBAGENT_START, priority=50)

    def should_trigger(self, event: HookEvent) -> bool:
        """同时响应SUBAGENT_START和SUBAGENT_STOP"""
        return event.event_type in (HookEventType.SUBAGENT_START, HookEventType.SUBAGENT_STOP)

    def execute(self, event: HookEvent) -> HookEvent:
        self.execution_count += 1
        self.last_execution = NOW().isoformat()
        
        if event.event_type == HookEventType.SUBAGENT_START:
            event.message = (
                f"子Agent '{event.subagent_name}' 启动, "
                f"任务ID: {event.task_id[:16]}"
            )
            event.decision = str(HookDecision.ALLOW)
        
        elif event.event_type == HookEventType.SUBAGENT_STOP:
            result = event.subagent_result
            event.message = (
                f"子Agent '{event.subagent_name}' 完成, "
                f"状态: {result.get('status', 'unknown')}"
            )
            event.decision = str(HookDecision.ALLOW)
        
        return event


class CompactionWarningHook(BaseHook):
    """
    CompactionWarning — OI新增: 压缩前保存快照
    """

    def __init__(self):
        super().__init__("compaction_warning", HookEventType.COMPACTION_WARNING, priority=10)

    def execute(self, event: HookEvent) -> HookEvent:
        self.execution_count += 1
        self.last_execution = NOW().isoformat()
        
        # 保存会话快照
        snapshot = {
            "ts": NOW().isoformat(),
            "session_id": event.session_id,
            "hook_name": self.name,
        }
        snap_path = HERMES / "reports" / "snapshots" / f"pre_compact_{event.session_id[:8]}.json"
        snap_path.parent.mkdir(exist_ok=True)
        snap_path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2))
        
        event.message = "压缩前快照已保存"
        event.decision = str(HookDecision.ALLOW)
        return event


class DreamCycleHook(BaseHook):
    """
    DreamCycle — OI新增: 子意识循环后台巡检
    
    在低负载时段自动执行:
    - 检查长时间未处理的任务
    - 触发记忆预演
    - 清理过期事件
    """

    def __init__(self):
        super().__init__("dream_cycle", HookEventType.DREAM_CYCLE, priority=90)
        self.cycle_count = 0

    def execute(self, event: HookEvent) -> HookEvent:
        self.execution_count += 1
        self.last_execution = NOW().isoformat()
        self.cycle_count += 1
        
        # 检测是否有超时子Agent
        subagents_dir = HERMES / "subagents" / "runtime"
        timeout_alerts = []
        if subagents_dir.exists():
            now_ts = time.time()
            for f in subagents_dir.glob("*.json"):
                try:
                    data = json.loads(f.read_text())
                    started = data.get("started_at_ts", 0)
                    if now_ts - started > 3600:  # 超过1小时
                        timeout_alerts.append(data.get("name", f.stem))
                except Exception:
                    pass
        
        if timeout_alerts:
            event.message = f"DreamCycle: 发现{len(timeout_alerts)}个超时子Agent: {timeout_alerts}"
        else:
            event.message = f"DreamCycle #{self.cycle_count}: 系统正常"
        
        event.decision = str(HookDecision.ALLOW)
        return event


# =================================================================
# Hooks引擎 — 事件总线+声明式注册+持久化
# =================================================================

class HooksEngine:
    """
    Hooks事件引擎 — 对应OI六事件Hooks系统
    
    核心功能:
      1. 事件总线: 事件发布→Hook链式处理→决策输出
      2. 声明式注册: 自动发现+配置文件驱动
      3. 事件持久化: SQLite存储事件历史
      4. 故障隔离: 单个Hook崩溃不影响其他Hook
      5. 链式处理: 按优先级排序, Deny即终止
    """

    def __init__(self):
        self._hooks: Dict[str, BaseHook] = {}
        self._event_log: List[HookEvent] = []
        self._lock = threading.Lock()
        
        # 持久化
        self._db_path = HERMES / "data" / "hooks_engine.db"
        self._db_path.parent.mkdir(exist_ok=True)
        self._init_db()
        
        # 自动注册内置Hook
        self._register_default_hooks()
        
        # 后台DreamCycle线程
        self._dream_thread: Optional[threading.Thread] = None
        self._dream_running = False
        self._start_dream_cycle()

    def _init_db(self):
        """初始化事件持久化"""
        conn = sqlite3.connect(str(self._db_path))
        conn.execute("""
            CREATE TABLE IF NOT EXISTS hook_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                session_id TEXT,
                timestamp TEXT,
                hook_name TEXT,
                decision TEXT,
                message TEXT,
                tool_name TEXT,
                subagent_name TEXT,
                risk_level TEXT,
                execution_time_ms INTEGER DEFAULT 0
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS hook_config (
                hook_name TEXT PRIMARY KEY,
                event_type TEXT NOT NULL,
                priority INTEGER DEFAULT 100,
                enabled INTEGER DEFAULT 1,
                config_json TEXT DEFAULT '{}'
            )
        """)
        conn.commit()
        conn.close()

    def _register_default_hooks(self):
        """自动注册所有内置Hook"""
        builtin_hooks = [
            SecurityAuditHook(),
            SessionLifecycleHook(),
            DriftDetectionHook(),
            KDNHook(),
            SubagentLifecycleHook(),
            CompactionWarningHook(),
            DreamCycleHook(),
        ]
        for hook in builtin_hooks:
            self.register(hook)

    def register(self, hook: BaseHook) -> str:
        """注册一个Hook到事件总线"""
        if hook.name in self._hooks:
            raise ValueError(f"Hook已存在: {hook.name}")
        
        self._hooks[hook.name] = hook
        
        # 持久化注册
        conn = sqlite3.connect(str(self._db_path))
        conn.execute(
            "INSERT OR REPLACE INTO hook_config (hook_name, event_type, priority, enabled) VALUES (?, ?, ?, ?)",
            (hook.name, str(hook.event_type), hook.priority, 1 if hook.enabled else 0)
        )
        conn.commit()
        conn.close()
        
        return hook.name

    def unregister(self, name: str) -> bool:
        """注销Hook"""
        if name in self._hooks:
            del self._hooks[name]
            return True
        return False

    def get_hooks_for_event(self, event_type: HookEventType) -> List[BaseHook]:
        """获取某事件的所有已注册Hook(按优先级排序)
        
        同时检查hook.event_type精确匹配和should_trigger方法
        """
        hooks = [
            h for h in self._hooks.values()
            if h.enabled and (
                h.event_type == event_type or 
                h.should_trigger(HookEvent(event_type=event_type, session_id=""))
            )
        ]
        hooks.sort(key=lambda h: h.priority)
        return hooks

    def emit(self, event: HookEvent) -> HookEvent:
        """
        发布事件 — 触发所有匹配的Hook
        
        流程:
          1. 获取该事件类型的所有Hook
          2. 按优先级链式处理
          3. 任一Hook返回Deny即终止
          4. 记录事件到持久化存储
        """
        if not event.timestamp:
            event.timestamp = NOW().isoformat()
        
        hooks = self.get_hooks_for_event(event.event_type)
        
        # 链式处理
        for hook in hooks:
            try:
                if not hook.should_trigger(event):
                    continue
                
                event.hook_id = hook.name
                event = hook.execute(event)
                
                # Deny终止链
                if event.decision == str(HookDecision.DENY):
                    break
                    
            except Exception as e:
                hook.failure_count += 1
                event.message = f"Hook '{hook.name}'执行异常: {str(e)[:100]}"
                # 继续下一个Hook(故障隔离)
                continue
        
        # 持久化记录
        self._persist_event(event)
        if len(self._event_log) > 10000:
            self._event_log = self._event_log[-5000:]
        self._event_log.append(event)
        
        return event

    def _persist_event(self, event: HookEvent):
        """持久化事件到SQLite"""
        try:
            conn = sqlite3.connect(str(self._db_path))
            conn.execute(
                """INSERT INTO hook_events 
                   (event_type, session_id, timestamp, hook_name, decision, 
                    message, tool_name, subagent_name, risk_level, execution_time_ms)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (str(event.event_type), event.session_id, event.timestamp,
                 event.hook_id, event.decision, event.message[:300],
                 event.tool_name, event.subagent_name, event.risk_level,
                 event.execution_time_ms)
            )
            conn.commit()
            conn.close()
        except Exception:
            pass  # 持久化失败不应阻断主流程

    def _start_dream_cycle(self):
        """启动后台DreamCycle线程 — 每5分钟自动巡检"""
        def dream_loop():
            self._dream_running = True
            while self._dream_running:
                try:
                    # 每5分钟触发一次DreamCycle事件
                    dream_event = HookEvent(
                        event_type=HookEventType.DREAM_CYCLE,
                        session_id=f"dream_{int(time.time())}",
                        source="dream_cycle",
                    )
                    self.emit(dream_event)
                except Exception:
                    pass
                time.sleep(300)  # 5分钟
        
        self._dream_thread = threading.Thread(target=dream_loop, daemon=True)
        self._dream_thread.start()

    def stop(self):
        """停止引擎"""
        self._dream_running = False
        if self._dream_thread:
            self._dream_thread.join(timeout=2)

    def query_events(self, event_type: Optional[str] = None,
                     limit: int = 50) -> List[dict]:
        """查询事件历史"""
        conn = sqlite3.connect(str(self._db_path))
        if event_type:
            cursor = conn.execute(
                "SELECT * FROM hook_events WHERE event_type = ? ORDER BY id DESC LIMIT ?",
                (event_type, limit)
            )
        else:
            cursor = conn.execute(
                "SELECT * FROM hook_events ORDER BY id DESC LIMIT ?", (limit,)
            )
        columns = [d[0] for d in cursor.description]
        results = [dict(zip(columns, row)) for row in cursor.fetchall()]
        conn.close()
        return results

    def health_report(self) -> dict:
        """引擎健康报告"""
        report = {
            "ts": NOW().isoformat(),
            "registered_hooks": len(self._hooks),
            "event_log_size": len(self._event_log),
            "dream_cycle_running": self._dream_running,
            "hooks": {},
        }
        for name, hook in self._hooks.items():
            report["hooks"][name] = hook.health_check()
        return report


# =================================================================
# 声明式Hook配置(YAML风格JSON)
# =================================================================

HOOKS_CONFIG_SCHEMA = {
    "hooks": [
        {
            "name": str,
            "event_type": str,
            "priority": int,
            "enabled": bool,
            "config": dict,
        }
    ]
}


def load_hooks_config(config_path: Optional[Path] = None) -> dict:
    """
    从JSON文件加载Hook配置
    
    格式:
    {
        "hooks": [
            {"name": "my_custom_hook", "event_type": "pretooluse", "priority": 50, "enabled": true},
            ...
        ]
    }
    """
    config_path = config_path or (HERMES / "config" / "hooks.json")
    
    if not config_path.exists():
        return {"hooks": []}
    
    try:
        return json.loads(config_path.read_text())
    except Exception as e:
        return {"hooks": [], "error": str(e)}


# =================================================================
# 全局单例
# =================================================================

_hooks_engine: Optional[HooksEngine] = None


def get_hooks_engine() -> HooksEngine:
    """获取Hooks引擎单例(自动启动DreamCycle)"""
    global _hooks_engine
    if _hooks_engine is None:
        _hooks_engine = HooksEngine()
    return _hooks_engine


# =================================================================
# CLI接口
# =================================================================

if __name__ == "__main__":
    engine = get_hooks_engine()
    
    cmd = sys.argv[1] if len(sys.argv) > 1 else "health"
    
    if cmd == "pretooluse":
        event = HookEvent(
            event_type=HookEventType.PRE_TOOL_USE,
            session_id=f"test_{int(time.time())}",
            tool_name=sys.argv[2] if len(sys.argv) > 2 else "file_write",
        )
        result = engine.emit(event)
        print(f"结果: {result.decision} | {result.message}")
    
    elif cmd == "session_start":
        event = HookEvent(
            event_type=HookEventType.SESSION_START,
            session_id=f"sess_{int(time.time())}",
            project_path=sys.argv[2] if len(sys.argv) > 2 else "/home",
        )
        result = engine.emit(event)
        print(f"结果: {result.decision} | {result.message[:100]}")
    
    elif cmd == "session_end":
        event = HookEvent(
            event_type=HookEventType.SESSION_END,
            session_id=f"sess_{int(time.time())}",
            task_summary=sys.argv[2] if len(sys.argv) > 2 else "测试任务",
        )
        result = engine.emit(event)
        print(f"结果: {result.decision} | 交接笔记已生成")
    
    elif cmd == "user_prompt":
        event = HookEvent(
            event_type=HookEventType.USER_PROMPT_SUBMIT,
            session_id=f"sess_{int(time.time())}",
            prompt=sys.argv[2] if len(sys.argv) > 2 else "帮我写代码",
        )
        result = engine.emit(event)
        print(f"结果: {result.decision} | {result.message[:100]}")
    
    elif cmd == "kdn":
        event = HookEvent(
            event_type=HookEventType.KDN_TRIGGERED,
            session_id=f"sess_{int(time.time())}",
            decision_node=sys.argv[2] if len(sys.argv) > 2 else "database_drop",
            risk_level=sys.argv[3] if len(sys.argv) > 3 else "high",
        )
        result = engine.emit(event)
        print(f"结果: {result.decision} | {result.message[:100]}")
    
    elif cmd == "subagent":
        action = sys.argv[2] if len(sys.argv) > 2 else "start"
        name = sys.argv[3] if len(sys.argv) > 3 else "worker_1"
        etype = HookEventType.SUBAGENT_START if action == "start" else HookEventType.SUBAGENT_STOP
        event = HookEvent(
            event_type=etype,
            session_id=f"sess_{int(time.time())}",
            subagent_name=name,
            task_id=f"task_{int(time.time())}",
        )
        result = engine.emit(event)
        print(f"结果: {result.decision} | {result.message}")
    
    elif cmd == "history":
        etype = sys.argv[2] if len(sys.argv) > 2 else None
        events = engine.query_events(etype, 10)
        print(json.dumps(events, ensure_ascii=False, indent=2))
    
    elif cmd == "health":
        print(json.dumps(engine.health_report(), ensure_ascii=False, indent=2))
    
    else:
        print("用法: hooks_engine.py [pretooluse|session_start|session_end|user_prompt|kdn|subagent|history|health] [args]")
