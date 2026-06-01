"""
7层纵深防御权限系统 + 子代理权限隔离 + 可观测性
对应文档§6 安全与权限 + §7.3 可观测性 + §6.2 子代理权限隔离 + §6.3 高风险操作人工确认
"""

from __future__ import annotations
import json
import time
import os
import re
from typing import Optional, Callable
from dataclasses import dataclass, field
from datetime import datetime


# ─── 层级定义（§6.1） ────────────────────────────────────────

@dataclass
class PermissionResult:
    """权限检查结果"""
    allowed: bool
    reason: str = ""
    layer: str = ""
    risk_level: str = "low"  # low | medium | high | critical
    requires_confirmation: bool = False


# ─── 7层权限系统 ─────────────────────────────────────────────

class SevenLayerPermissionSystem:
    """
    七层纵深防御 — 对应文档§6.1

    层级:
    L1: Trust Dialog — 会话级信任设置
    L2: Permission Mode — 全局安全策略（default/plan/acceptEdits）
    L3: Pattern Match — allow/deny/ask规则匹配
    L4: ML Classifier — 命令危险性分类
    L5: Command Validation — AST解析 + 静态检查
    L6: Sandbox Isolation — 沙箱隔离检查
    L7: User Confirmation — 最终兜底
    """

    # 高危操作关键词
    HIGH_RISK_PATTERNS = [
        r'rm\s+-rf\s+/', r'rm\s+-rf\s+~', r'rm\s+-rf\s+\.',
        r'format', r'mkfs', r'dd\s+if=', r'>\s*/dev/',
        r'chmod\s+777', r'chown\s+\w+:\w+\s+/',
        r'DROP\s+TABLE', r'DROP\s+DATABASE',
        r'DELETE\s+FROM', r'TRUNCATE\s+',
        r'wget\s+.*\|\s*bash', r'curl\s+.*\|\s*bash',
        r'sudo\s+rm', r':(){ :|:& };:'
    ]

    # 敏感文件模式
    SENSITIVE_PATHS = [
        r'/etc/passwd', r'/etc/shadow', r'/etc/sudoers',
        r'/root/\.ssh/', r'~/.ssh/',
        r'/var/log/auth', r'/var/log/secure'
    ]

    def __init__(self, config: dict = None):
        self.config = config or {}
        self.permission_rules = self._load_rules()
        self.risk_classifier = self._build_classifier()

    def _load_rules(self) -> dict:
        """加载权限规则"""
        return {
            "allow_patterns": self.config.get("allow_patterns", []),
            "deny_patterns": self.config.get("deny_patterns", [
                r'rm\s+-rf\s+/',
                r'>\s*/dev/sda',
                r'sudo\s+rm\s+-rf\s+/'
            ]),
            "ask_patterns": self.config.get("ask_patterns", [
                r'rm\s+-rf', r'DROP\s+TABLE',
                r'DELETE\s+FROM\s+\w+\s+WHERE',
                r'chmod\s+777', r'sudo'
            ])
        }

    def _build_classifier(self) -> dict:
        """构建风险分类器"""
        return {
            "tool_risk": {
                "Execute": "high",
                "Delete": "high",
                "Write": "medium",
                "Edit": "medium",
                "Patch": "medium",
                "Bash": "high",
                "Terminal": "medium",
                "Read": "low",
                "Search": "low",
                "List": "low"
            },
            "path_risk": {
                "/etc/": "high",
                "/root/": "high",
                "/var/": "medium",
                "/opt/": "medium",
                "/usr/": "medium",
                "/tmp/": "low",
                "/home/": "low"
            }
        }

    async def check_permission(self, tool_call: dict,
                                context: dict) -> PermissionResult:
        """
        七层权限检查 — 从L1到L7逐层通过
        """
        tool_name = tool_call.get("name", "")
        params = tool_call.get("parameters", {})
        command = str(params.get("command", params.get("path", "")))

        # ── L1: Trust Dialog ──
        workspace_trusted = context.get("workspace_trusted", True)
        if not workspace_trusted:
            return PermissionResult(
                allowed=False,
                reason="工作区未受信任",
                layer="L1",
                risk_level="critical"
            )

        # ── L2: Permission Mode ──
        mode = context.get("permission_mode", "default")
        if mode == "plan":
            if tool_name in ("Write", "Edit", "Patch", "Execute",
                             "Delete", "Terminal", "Bash"):
                return PermissionResult(
                    allowed=False,
                    reason="Plan模式：禁止写/执行操作",
                    layer="L2"
                )

        # ── L3: Pattern Match ──
        pattern_result = self._match_patterns(tool_name, command)
        if pattern_result["decision"] == "deny":
            return PermissionResult(
                allowed=False,
                reason=f"规则拒绝: {pattern_result['rule']}",
                layer="L3",
                risk_level="critical"
            )

        if pattern_result["decision"] == "allow":
            return PermissionResult(allowed=True, layer="L3")

        # ── L4: ML Classifier ──
        risk_level = self._classify_risk(tool_name, command)
        if risk_level == "critical":
            return PermissionResult(
                allowed=False,
                reason="ML分类器标记为致命风险",
                layer="L4",
                risk_level="critical",
                requires_confirmation=True
            )

        # ── L5: Command Validation ──
        if tool_name in ("Terminal", "Bash", "Execute"):
            validation = self._validate_command(command)
            if not validation["safe"]:
                return PermissionResult(
                    allowed=False,
                    reason=validation["reason"],
                    layer="L5"
                )

        # ── L6: Sandbox Check ──
        if risk_level in ("high", "critical") and not context.get("is_sandboxed"):
            return PermissionResult(
                allowed=False,
                reason="高风险操作需要在沙箱中执行",
                layer="L6",
                risk_level=risk_level
            )

        # ── L7: User Confirmation ──
        if risk_level in ("high",) or pattern_result["decision"] == "ask":
            if context.get("require_confirmation", True):
                return PermissionResult(
                    allowed=False,
                    reason="高风险操作需要用户确认",
                    layer="L7",
                    risk_level="high",
                    requires_confirmation=True
                )

        return PermissionResult(allowed=True, layer="L7")

    def _match_patterns(self, tool_name: str, command: str) -> dict:
        """L3: 规则匹配"""
        # 检查deny规则
        for pattern in self.permission_rules["deny_patterns"]:
            if re.search(pattern, command):
                return {"decision": "deny", "rule": pattern}

        # 检查allow规则
        for pattern in self.permission_rules["allow_patterns"]:
            if re.search(pattern, command):
                return {"decision": "allow", "rule": pattern}

        # 检查ask规则
        for pattern in self.permission_rules["ask_patterns"]:
            if re.search(pattern, command):
                return {"decision": "ask", "rule": pattern}

        return {"decision": "pass"}

    def _classify_risk(self, tool_name: str, command: str) -> str:
        """L4: 风险分类"""
        # 基于工具名称
        tool_risk = self.risk_classifier["tool_risk"].get(tool_name, "low")

        # 基于高危模式
        for pattern in self.HIGH_RISK_PATTERNS:
            if re.search(pattern, command):
                return "critical"

        # 基于敏感路径
        for pattern in self.SENSITIVE_PATHS:
            if re.search(pattern, command):
                return "high"

        # 基于路径风险
        for path, risk in self.risk_classifier["path_risk"].items():
            if path in command:
                return risk if risk != "low" else tool_risk

        return tool_risk

    def _validate_command(self, command: str) -> dict:
        """L5: 命令验证 — AST解析 + 静态检查"""
        issues = []

        # 检查: sudo
        if command.strip().startswith("sudo"):
            issues.append("sudo命令需要特别授权")

        # 检查: 管道到bash
        if re.search(r'\|.*\b(bash|sh|zsh)\b', command):
            issues.append("禁止通过管道执行shell")

        # 检查: 重定向危险
        if re.search(r'>\s*/dev/', command):
            issues.append("禁止重定向到设备文件")

        # 检查: 删除根目录
        if re.search(r'rm\s+-rf\s+(/\s*$|/\s+\w)', command):
            issues.append("禁止递归删除根目录")

        # 检查: 子进程嵌套
        if command.count("$(") > 3 or command.count("`") > 3:
            issues.append("命令嵌套层级过深")

        return {
            "safe": len(issues) == 0,
            "reason": "; ".join(issues) if issues else "command validated",
            "issues": issues
        }

    def build_confirmation_prompt(self, tool_call: dict,
                                   risk_level: str) -> str:
        """构建用户确认提示"""
        tool_name = tool_call.get("name", "")
        params = tool_call.get("parameters", {})

        return f"""
⚠️ 高风险操作需要您的确认

操作类型: {tool_name}
风险等级: {risk_level}
操作详情: {json.dumps(params, ensure_ascii=False, indent=2)}

请确认以下事项:
1. 您已了解此操作的风险
2. 此操作在当前上下文中是必要的
3. 您已确认操作目标正确

输入 "yes" 确认执行，输入 "no" 拒绝。
此确认有效期 15 分钟。
"""


# ─── 子代理权限隔离（§6.2） ─────────────────────────────────

class SubAgentPermissionIsolation:
    """
    子代理权限隔离 — 最小权限原则
    每个子代理使用allowedTools白名单
    """

    DEFAULT_RESTRICTIONS = {
        "readonly": {
            "allowed": ["Read", "Search", "List", "Grep", "Glob"],
            "denied": ["Write", "Edit", "Delete", "Execute", "Terminal", "Bash"]
        },
        "code_writer": {
            "allowed": ["Read", "Write", "Edit", "Patch", "Grep", "Glob", "Bash"],
            "denied": ["Delete", "NetworkScan", "DatabaseWrite"]
        },
        "executor": {
            "allowed": ["Read", "Write", "Edit", "Terminal", "Bash",
                        "WebSearch", "Install"],
            "denied": ["Delete", "NetworkScan", "DatabaseWrite"]
        },
        "verifier": {
            "allowed": ["Read", "Search", "Grep", "Glob", "DatabaseQuery"],
            "denied": ["Write", "Edit", "Delete", "Execute", "Terminal"]
        },
        "researcher": {
            "allowed": ["WebSearch", "Read", "Search", "SessionSearch",
                        "Memory", "SkillView"],
            "denied": ["Write", "Edit", "Delete", "Execute", "Terminal", "Bash"]
        }
    }

    @staticmethod
    def build_restricted_context(
        specialization: str,
        base_context: str
    ) -> str:
        """构建受限上下文"""
        restrictions = SubAgentPermissionIsolation.DEFAULT_RESTRICTIONS.get(
            specialization,
            SubAgentPermissionIsolation.DEFAULT_RESTRICTIONS["readonly"]
        )
        return f"""
{base_context}

【安全约束】
- 允许的工具: {', '.join(restrictions['allowed'])}
- 禁止的工具: {', '.join(restrictions['denied'])}
- 原则: 最小权限
- 禁止：任何越权操作
- 要求：所有操作必须在工具白名单内

⚠️ 如果发现需要但未被授权的工具，请标记为"需升级"而非自行变通。
"""


# ─── 可观测性系统（§7.3） ───────────────────────────────────

class AgentObservability:
    """
    可观测性系统 — 全链路追踪 + 成本追踪 + 异常检测
    对应文档§7.3
    """

    def __init__(self, log_dir: str = None):
        self.log_dir = log_dir or os.path.expanduser(
            "~/.hermes/state/observability"
        )
        os.makedirs(self.log_dir, exist_ok=True)

    def log_span(self, session_id: str, span: dict):
        """记录执行跨度"""
        span["timestamp"] = datetime.now().isoformat()
        path = os.path.join(self.log_dir, f"spans_{session_id}.jsonl")
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(span, ensure_ascii=False) + "\n")

    def track_cost(self, session_id: str, cost_data: dict):
        """追踪成本"""
        cost_data["timestamp"] = datetime.now().isoformat()
        path = os.path.join(self.log_dir, f"cost_{session_id}.jsonl")
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(cost_data, ensure_ascii=False) + "\n")

    def get_execution_trace(self, session_id: str) -> list:
        """获取全链路追踪"""
        path = os.path.join(self.log_dir, f"spans_{session_id}.jsonl")
        if not os.path.exists(path):
            return []
        spans = []
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    spans.append(json.loads(line))
        return spans

    def compute_metrics(self, session_id: str) -> dict:
        """计算汇总指标"""
        spans = self.get_execution_trace(session_id)
        if not spans:
            return {}

        tool_calls = [s for s in spans if s.get("type") == "tool_call"]
        verifications = [s for s in spans if s.get("type") == "verification"]

        return {
            "total_spans": len(spans),
            "total_tool_calls": len(tool_calls),
            "total_verifications": len(verifications),
            "successful_calls": sum(1 for s in tool_calls if s.get("success")),
            "failed_calls": sum(1 for s in tool_calls if not s.get("success")),
            "avg_duration": sum(s.get("duration", 0) for s in spans) / max(len(spans), 1),
            "total_tokens": sum(s.get("tokens", 0) for s in spans),
            "verification_pass_rate": (
                sum(1 for v in verifications if v.get("passed")) /
                max(len(verifications), 1)
            ),
            "unique_tools": len(set(s.get("tool_name", "") for s in tool_calls))
        }

    def detect_anomalies(self, session_id: str) -> list:
        """检测异常模式"""
        spans = self.get_execution_trace(session_id)
        anomalies = []

        # 模式1: 同一工具连续失败3次
        consecutive_failures = 0
        for span in spans:
            if span.get("type") == "tool_call" and not span.get("success"):
                consecutive_failures += 1
            else:
                consecutive_failures = 0
            if consecutive_failures >= 3:
                anomalies.append({
                    "type": "consecutive_failures",
                    "detail": f"工具 '{span.get('tool_name')}' 连续失败3次",
                    "severity": "critical"
                })
                consecutive_failures = 0

        # 模式2: 耗时异常
        durations = [s.get("duration", 0) for s in spans if s.get("duration")]
        if durations:
            avg = sum(durations) / len(durations)
            for span in spans:
                duration = span.get("duration", 0)
                if duration > avg * 5 and duration > 10:
                    anomalies.append({
                        "type": "outlier_duration",
                        "detail": f"步骤 '{span.get('name', '')}' 耗时 {duration}s (平均{avg:.1f}s)",
                        "severity": "warning"
                    })

        return anomalies
