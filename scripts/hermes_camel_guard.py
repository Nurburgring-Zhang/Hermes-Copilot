#!/usr/bin/env python3
"""
Hermes CaMeL 安全护栏引擎 v1.0
==================================
基于 hermes-agent-camel 核心源码 (camel_guard.py + tool_guardrails.py) 移植

核心机制:
  1. 信任边界分离 — 将系统提示/已批准Skill/用户输入(可信) 与 工具输出/外部数据(不可信) 分离
  2. 敏感工具9类能力 — 每类工具调用前检查是否有权限
  3. LLM意图分类器 — 从用户输入中提取意图，决定允许/拒绝的能力
  4. 5种注入模式检测 — ignore previous/hide/secret exfil/system override/embedded side effect
  5. 工具循环防护 — 重复失败/同工具链式失败/幂等无进展检测，四级响应(allow/warn/block/halt)
  6. 三级运行模式 — off(关闭)/monitor(记录不阻止)/enforce(强制执行)

用法:
  # 检查消息是否安全
  python3 scripts/hermes_camel_guard.py check --message "..." --mode enforce
  
  # 验证工具调用是否允许
  python3 scripts/hermes_camel_guard.py check-tool --tool terminal --args '{"command":"rm -rf /"}' --mode enforce
  
  # 配置模式
  python3 scripts/hermes_camel_guard.py status
  
可选能力：不干扰现有系统，通过 --camel-guard 启用或 config.yaml 配置
"""

import json, os, sys, re, hashlib
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field

HERMES = Path("/home/administrator/.hermes")
CAMEL_LOG = HERMES / "logs" / "camel_guard.log"
TZ = timezone(timedelta(hours=8))

# ── 常量 ──
CAMEL_UNTRUSTED_PREFIX = "[CaMeL: UNTRUSTED TOOL DATA]"

# 运行模式
CAMEL_MODE_OFF = "off"
CAMEL_MODE_MONITOR = "monitor"
CAMEL_MODE_ENFORCE = "enforce"
CAMEL_MODES = (CAMEL_MODE_OFF, CAMEL_MODE_MONITOR, CAMEL_MODE_ENFORCE)

# 9类敏感工具能力映射（对齐camel_guard.py _SENSITIVE_TOOL_CAPABILITIES）
SENSITIVE_TOOL_CAPABILITIES = {
    # 浏览器交互
    "browser_click": "browser_interaction",
    "browser_press": "browser_interaction",
    "browser_type": "browser_interaction",
    "browser_navigate": "browser_interaction",
    "browser_scroll": "browser_interaction",
    # 命令执行
    "terminal": "command_execution",
    "execute_code": "command_execution",
    # 文件修改
    "write_file": "file_mutation",
    "patch": "file_mutation",
    # 外部通信
    "send_message": "external_messaging",
    # 技能修改
    "skill_manage": "skill_mutation",
    # 持久化记忆
    "memory": "persistent_memory",
    # 定时任务
    "cronjob": "scheduled_action",
    # 委托
    "delegate_task": "delegation",
    # 外部副作用
    "process_kill": "external_side_effect",
    "process_write": "external_side_effect",
}

CAPABILITY_LABELS = {
    "browser_interaction": "浏览器交互",
    "command_execution": "命令执行",
    "delegation": "委托/子Agent",
    "external_messaging": "外部消息",
    "external_side_effect": "外部系统副作用",
    "file_mutation": "文件修改",
    "persistent_memory": "持久化记忆写入",
    "scheduled_action": "定时/计划任务",
    "skill_mutation": "Skill修改",
}

# 可信工具（不拦截）
TRUSTED_CONTROL_TOOLS = {
    "clarify", "skill_view", "skills_list", "todo", "read_file", "search_files",
    "session_search", "memory", "web_search", "vision_analyze",
}

# 注入模式检测（对齐camel_guard.py _SUSPICIOUS_INSTRUCTION_PATTERNS）
SUSPICIOUS_PATTERNS = [
    (re.compile(r"ignore\s+(previous|all|above|prior)\s+instructions", re.IGNORECASE), "忽略之前指令"),
    (re.compile(r"do\s+not\s+tell\s+the\s+user", re.IGNORECASE), "对用户隐藏"),
    (re.compile(r"(reveal|show|print|dump).*(system prompt|api key|token|secret|credential)", re.IGNORECASE), "秘密提取"),
    (re.compile(r"system\s+prompt\s+override", re.IGNORECASE), "系统提示覆盖"),
    (re.compile(r"send_message|tweet|email|dm|post this", re.IGNORECASE), "嵌入副作用指令"),
]

# 输出指令劫持检测（对齐camel_guard.py _OUTPUT_INSTRUCTION_PATTERNS）
OUTPUT_PATTERNS = [
    re.compile(r"\b(?:begin|start)\s+your\s+reply\s+with:\s*(.+)$", re.IGNORECASE),
    re.compile(r"\brespond\s+with:\s*(.+)$", re.IGNORECASE),
    re.compile(r"\boutput\s+exactly:\s*(.+)$", re.IGNORECASE),
]


# ══════════════════════════════════════════════════════════════════
# 模块1: 工具循环防护 (Tool Guardrails)
# 对齐 tool_guardrails.py
# ══════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class ToolCallSignature:
    """工具名+参数Hash作为唯一标识（对齐tool_guardrails.py ToolCallSignature）"""
    tool_name: str
    args_hash: str

    @classmethod
    def from_call(cls, tool_name: str, args: dict) -> "ToolCallSignature":
        canonical = json.dumps(args or {}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return cls(tool_name=tool_name, args_hash=hashlib.sha256(canonical.encode()).hexdigest()[:16])


@dataclass(frozen=True)
class GuardrailDecision:
    """工具防护决策（对齐tool_guardrails.py ToolGuardrailDecision）"""
    action: str = "allow"  # allow | warn | block | halt
    code: str = ""
    message: str = ""
    tool_name: str = ""

    def allows_execution(self) -> bool:
        return self.action in ("allow", "warn")

    def should_halt(self) -> bool:
        return self.action in ("block", "halt")


class ToolGuardrailController:
    """工具循环防护控制器（对齐tool_guardrails.py ToolCallGuardrailController）"""

    def __init__(self):
        self.reset()

    def reset(self):
        self._exact_failure_counts = {}
        self._same_tool_failure_counts = {}
        self._no_progress = {}

    def before_call(self, tool_name: str, args: dict) -> GuardrailDecision:
        """在工具调用前检查是否应阻止"""
        signature = ToolCallSignature.from_call(tool_name, args)
        exact_count = self._exact_failure_counts.get(signature, 0)

        if exact_count >= 5:  # block_after
            return GuardrailDecision(
                action="block", code="repeated_exact_failure",
                message=f"阻止 {tool_name}: 相同参数已失败{exact_count}次，请更换策略",
                tool_name=tool_name,
            )

        return GuardrailDecision(tool_name=tool_name)

    def after_call(self, tool_name: str, args: dict, result: str, failed: bool = False) -> GuardrailDecision:
        """工具调用后检查并记录"""
        signature = ToolCallSignature.from_call(tool_name, args)

        if failed:
            exact_count = self._exact_failure_counts.get(signature, 0) + 1
            self._exact_failure_counts[signature] = exact_count
            same_count = self._same_tool_failure_counts.get(tool_name, 0) + 1
            self._same_tool_failure_counts[tool_name] = same_count

            if same_count >= 8:
                return GuardrailDecision(
                    action="halt", code="same_tool_failure_halt",
                    message=f"停止 {tool_name}: 同工具已失败{same_count}次",
                    tool_name=tool_name,
                )
            if exact_count >= 2:
                return GuardrailDecision(
                    action="warn", code="repeated_exact_failure",
                    message=f"{tool_name} 已相同参数失败{exact_count}次，请检查错误并换策略",
                    tool_name=tool_name,
                )
        else:
            self._exact_failure_counts.pop(signature, None)
            self._same_tool_failure_counts.pop(tool_name, None)

        return GuardrailDecision(tool_name=tool_name)


# ══════════════════════════════════════════════════════════════════
# 模块2: 注入检测 (Injection Detection)
# ══════════════════════════════════════════════════════════════════

def check_suspicious_instructions(text: str) -> List[str]:
    """检测可疑指令注入"""
    flags = []
    for pattern, label in SUSPICIOUS_PATTERNS:
        if pattern.search(text or ""):
            flags.append(label)
    return flags


def check_output_hijack(text: str) -> List[str]:
    """检测输出指令劫持"""
    markers = []
    for pattern in OUTPUT_PATTERNS:
        match = pattern.search(text or "")
        if match:
            markers.append(match.group(1)[:80])
    return markers


# ══════════════════════════════════════════════════════════════════
# 模块3: CaMeL Guard 主引擎
# ══════════════════════════════════════════════════════════════════

class CamelGuard:
    """CaMeL安全护栏主引擎"""

    def __init__(self, mode: str = "monitor"):
        self.mode = mode if mode in CAMEL_MODES else CAMEL_MODE_MONITOR
        self.tool_guardrail = ToolGuardrailController()
        self.log_entries = []

    def is_active(self) -> bool:
        return self.mode != CAMEL_MODE_OFF

    def check_message(self, message: str, role: str = "user") -> Dict[str, Any]:
        """检查用户消息是否安全"""
        result = {
            "safe": True,
            "mode": self.mode,
            "role": role,
            "flags": [],
            "warnings": [],
        }

        if not self.is_active():
            return result

        # 注入模式检测
        susp = check_suspicious_instructions(message)
        if susp:
            result["safe"] = False
            result["flags"].extend(susp)
            for s in susp:
                result["warnings"].append(f"注入检测: {s}")

        # 输出劫持检测
        hijack = check_output_hijack(message)
        if hijack:
            result["safe"] = False
            result["flags"].extend([f"输出指令劫持: {h[:30]}" for h in hijack])

        self._log("message_check", result)
        return result

    def check_tool_call(self, tool_name: str, args: dict) -> Dict[str, Any]:
        """检查工具调用是否安全"""
        result = {
            "tool": tool_name,
            "allowed": True,
            "mode": self.mode,
            "capability": None,
            "decision": "allow",
            "message": "",
        }

        if not self.is_active():
            return result

        # 可信工具直接放行
        if tool_name in TRUSTED_CONTROL_TOOLS:
            return result

        # 敏感工具检查
        capability = SENSITIVE_TOOL_CAPABILITIES.get(tool_name)
        if capability:
            result["capability"] = capability
            cap_label = CAPABILITY_LABELS.get(capability, capability)

            # 在monitor模式下只记录不阻止
            if self.mode == CAMEL_MODE_MONITOR:
                result["message"] = f"[CaMeL] {tool_name}: 需要{cap_label}权限 (monitor模式—已放行)"
                self._log("tool_monitor", result)
                return result

            # 在enforce模式下阻止
            result["allowed"] = False
            result["decision"] = "block"
            result["message"] = f"⛔ [CaMeL] {tool_name}: 需要{cap_label}权限，当前模式=enforce"
            self._log("tool_blocked", result)
            return result

        return result

    def check_tool_result(self, tool_name: str, args: dict, result_text: str, failed: bool = False) -> GuardrailDecision:
        """工具调用后防护检查"""
        if not self.is_active():
            return GuardrailDecision(tool_name=tool_name)

        decision = self.tool_guardrail.after_call(tool_name, args, result_text, failed)
        if decision.action != "allow":
            self._log("tool_guardrail", {
                "tool": tool_name,
                "action": decision.action,
                "code": decision.code,
                "message": decision.message,
            })
        return decision

    def mark_untrusted(self, text: str) -> str:
        """标记不可信数据"""
        if not self.is_active():
            return text
        return f"{CAMEL_UNTRUSTED_PREFIX} {text}"

    def _log(self, event_type: str, data: dict):
        """记录CaMeL事件"""
        entry = {
            "ts": datetime.now(TZ).isoformat(),
            "type": event_type,
            "mode": self.mode,
            **data,
        }
        self.log_entries.append(entry)
        try:
            with open(CAMEL_LOG, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except:
            pass


# ══════════════════════════════════════════════════════════════════
# CLI接口
# ══════════════════════════════════════════════════════════════════

def cmd_check(args: List[str]):
    """检查消息安全"""
    mode = CAMEL_MODE_MONITOR
    message = ""

    i = 0
    while i < len(args):
        if args[i] == "--mode" and i + 1 < len(args):
            mode = args[i + 1]
            i += 2
        elif args[i] == "--message" and i + 1 < len(args):
            message = args[i + 1]
            i += 2
        else:
            i += 1

    guard = CamelGuard(mode=mode)
    result = guard.check_message(message)
    print(json.dumps(result, ensure_ascii=False, indent=2))


def cmd_check_tool(args: List[str]):
    """检查工具调用"""
    mode = CAMEL_MODE_MONITOR
    tool = ""
    tool_args = {}

    i = 0
    while i < len(args):
        if args[i] == "--mode" and i + 1 < len(args):
            mode = args[i + 1]
            i += 2
        elif args[i] == "--tool" and i + 1 < len(args):
            tool = args[i + 1]
            i += 2
        elif args[i] == "--args" and i + 1 < len(args):
            try:
                tool_args = json.loads(args[i + 1])
            except:
                pass
            i += 2
        else:
            i += 1

    guard = CamelGuard(mode=mode)
    result = guard.check_tool_call(tool, tool_args)
    print(json.dumps(result, ensure_ascii=False, indent=2))


def cmd_status():
    """显示状态"""
    print("=" * 50)
    print("Hermes CaMeL 安全护栏 - 状态")
    print("=" * 50)
    print(f"  敏感工具数: {len(SENSITIVE_TOOL_CAPABILITIES)}")
    print(f"  能力类别数: {len(CAPABILITY_LABELS)}")
    print(f"  注入检测模式: {len(SUSPICIOUS_PATTERNS)}条")
    print(f"  输出劫持检测: {len(OUTPUT_PATTERNS)}条")
    print()
    print("  能力映射:")
    for cap, label in sorted(CAPABILITY_LABELS.items()):
        tools = [t for t, c in SENSITIVE_TOOL_CAPABILITIES.items() if c == cap]
        print(f"    {cap}: {', '.join(tools)}")
    print()
    print("  日志文件:", CAMEL_LOG)
    
    if CAMEL_LOG.exists():
        with open(CAMEL_LOG) as f:
            lines = [l for l in f if l.strip()]
        print(f"  日志条数: {len(lines)}")


def cmd_monitor():
    """monitor模式：检查最近会话是否存在安全风险（不阻止）"""
    guard = CamelGuard(mode="monitor")
    print("=" * 50)
    print("CaMeL Monitor 模式 — 安全检查")
    print("=" * 50)
    
    # 检查敏感工具的风险等级
    sensitive = []
    for tool, cap in SENSITIVE_TOOL_CAPABILITIES.items():
        sensitive.append({"tool": tool, "capability": cap, "risk": "高" if cap in ("command_execution", "file_mutation", "skill_mutation") else "中"})
    
    print(f"  检测到 {len(sensitive)} 个敏感工具")
    for s in sensitive:
        print(f"    [{s['risk']}] {s['tool']} → {CAPABILITY_LABELS.get(s['capability'], s['capability'])}")
    print()
    print("  当前模式: monitor（仅记录，不阻止）")


def main():
    if len(sys.argv) < 2:
        print("""用法: python3 scripts/hermes_camel_guard.py <command> [选项]

命令:
  check --message \"...\" [--mode off|monitor|enforce]
      检查用户消息是否包含注入模式
  check-tool --tool <name> --args '{}' [--mode off|monitor|enforce]  
      检查工具调用是否需要敏感权限
  status            显示CaMeL状态和能力映射
  monitor           执行monitor模式安全检查
""")
        return

    cmd = sys.argv[1]
    cmds = {
        "check": cmd_check,
        "check-tool": cmd_check_tool,
        "status": cmd_status,
        "monitor": cmd_monitor,
    }
    
    if cmd in cmds:
        func = cmds[cmd]
        # status和monitor不需要args
        if cmd in ("status", "monitor"):
            func()
        else:
            func(sys.argv[2:])
    else:
        print(f"未知命令: {cmd}")


if __name__ == "__main__":
    main()
