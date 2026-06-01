"""
操作后即时验证 + 确定性错误检测(ReFlect) + 降级拦截器
对应文档§3.4 错误传播阻断 + §4.3 确定性错误检测 + §8.1 绝不降级实现

核心解决：
1. 一步错步步错 → 每一步后强制验证
2. 做完不检查 → 独立Verifier确认环境状态
3. 执行不稳定 → 确定性规则引擎（不依赖LLM）
4. 降级实现 → DegradationPreventer拦截
"""

from __future__ import annotations
import json
import time
import os
import re
from typing import Optional, Callable
from dataclasses import dataclass, field


# ─── 步骤验证器（§3.4） ──────────────────────────────────────

@dataclass
class VerificationResult:
    """验证结果"""
    passed: bool
    expected: str = ""
    actual: str = ""
    detail: str = ""
    strategy: str = ""  # state_snapshot_compare | re_read_page | database_assertion | value_match
    severity: str = "error"  # error | warning


class StepVerifier:
    """
    步骤验证器 — 解决"做完不检查"问题
    对应文档§3.4

    每个关键操作后，独立验证环境状态是否符合预期
    使用多种验证策略：快照对比、页面重读、数据库断言、值匹配
    """

    def __init__(self, state_reader: Callable = None,
                 db_query: Callable = None):
        """
        state_reader: 读取当前环境状态的函数
        db_query: 查询数据库的函数
        """
        self.state_reader = state_reader
        self.db_query = db_query

    async def verify_step(self, tool_call: dict, tool_result: dict,
                           loop_state: dict) -> VerificationResult:
        """
        验证单步操作 — 选择最佳验证策略
        """
        strategy = self._select_strategy(tool_call, tool_result)
        tool_name = tool_call.get("name", "")

        if strategy == "state_snapshot_compare":
            return await self._compare_snapshots(loop_state, tool_call)
        elif strategy == "re_read_page":
            return await self._verify_page_content(tool_call)
        elif strategy == "database_assertion":
            return await self._verify_database(tool_call)
        elif strategy == "value_match":
            return self._verify_value_match(tool_result, tool_call)
        else:
            # 默认：检查工具调用是否成功
            success = tool_result.get("success", False)
            return VerificationResult(
                passed=success,
                expected="success=true",
                actual=f"success={success}",
                detail="基础工具调用状态检查",
                strategy="value_match"
            )

    def _select_strategy(self, tool_call: dict, tool_result: dict) -> str:
        """选择最佳验证策略"""
        tool_name = tool_call.get("name", "")
        params = tool_call.get("parameters", {})

        # 写操作 → 快照对比
        if tool_name in ("Write", "Edit", "Patch", "Terminal"):
            command = str(params.get("command", params.get("path", "")))
            if any(kw in command for kw in ("rm", "mv", "cp", "chmod", "chown")):
                return "state_snapshot_compare"
            return "re_read_page"

        # 创建/提交操作 → 数据库断言
        if tool_name in ("Create", "Submit", "Insert", "Update", "Delete"):
            return "database_assertion"

        # 精确值匹配
        if tool_result.get("output") is not None:
            return "value_match"

        return "default"

    async def _compare_snapshots(self, loop_state: dict,
                                   tool_call: dict) -> VerificationResult:
        """快照对比验证 — 对比操作前后状态"""
        snapshots = loop_state.get("environment_snapshots", [])
        if len(snapshots) < 2:
            return VerificationResult(
                passed=True,
                detail="无足够快照用于对比",
                strategy="state_snapshot_compare",
                severity="warning"
            )

        before = snapshots[-2]
        after = snapshots[-1]

        # 检查关键变更
        changes = []
        for key in set(list(before.keys()) + list(after.keys())):
            if before.get(key) != after.get(key):
                changes.append(f"{key}: {before.get(key)} → {after.get(key)}")

        if not changes:
            return VerificationResult(
                passed=False,
                expected="操作后状态应发生变化",
                actual="状态无变化",
                detail="操作未产生任何状态变更",
                strategy="state_snapshot_compare"
            )

        return VerificationResult(
            passed=True,
            detail=f"状态变更: {'; '.join(changes[:5])}",
            strategy="state_snapshot_compare"
        )

    async def _verify_page_content(self, tool_call: dict) -> VerificationResult:
        """页面内容验证"""
        if self.state_reader:
            try:
                current_state = await self.state_reader()
                # 检查错误关键词
                error_keywords = ["错误", "Error", "失败", "Failed", "exception", "Exception"]
                state_str = str(current_state)
                for kw in error_keywords:
                    if kw in state_str:
                        return VerificationResult(
                            passed=False,
                            expected="操作后页面无错误",
                            actual=f"页面包含错误关键词: {kw}",
                            detail=f"验证发现错误信号: {kw}",
                            strategy="re_read_page",
                            severity="critical"
                        )
                return VerificationResult(
                    passed=True,
                    detail="页面状态正常",
                    strategy="re_read_page"
                )
            except Exception as e:
                return VerificationResult(
                    passed=False,
                    expected="页面可正常读取",
                    actual=f"读取失败: {str(e)}",
                    detail="页面读取异常",
                    strategy="re_read_page"
                )

        return VerificationResult(
            passed=True,
            detail="无state_reader，跳过页面验证",
            strategy="re_read_page",
            severity="warning"
        )

    async def _verify_database(self, tool_call: dict) -> VerificationResult:
        """数据库断言验证"""
        if self.db_query:
            try:
                result = await self.db_query(tool_call)
                return VerificationResult(
                    passed=result.get("found", False),
                    expected=result.get("expected", ""),
                    actual=result.get("actual", ""),
                    detail=result.get("detail", "数据库验证完成"),
                    strategy="database_assertion"
                )
            except Exception as e:
                return VerificationResult(
                    passed=False,
                    expected="数据库查询成功",
                    actual=f"查询失败: {str(e)}",
                    detail="数据库验证异常",
                    strategy="database_assertion"
                )

        return VerificationResult(
            passed=True,
            detail="无db_query，跳过数据库验证",
            strategy="database_assertion",
            severity="warning"
        )

    def _verify_value_match(self, tool_result: dict,
                             tool_call: dict) -> VerificationResult:
        """精确值匹配验证"""
        output = tool_result.get("output")
        expected = tool_call.get("parameters", {}).get("expected")

        if expected is not None and output is not None:
            matched = str(output) == str(expected)
            return VerificationResult(
                passed=matched,
                expected=str(expected),
                actual=str(output),
                detail=f"值匹配检查: {'通过' if matched else '失败'}",
                strategy="value_match"
            )

        # 无预期值，只检查是否有输出
        has_output = output is not None and str(output).strip()
        return VerificationResult(
            passed=has_output,
            expected="有输出结果",
            actual=f"输出为空" if not has_output else str(output)[:100],
            detail="基础输出检查",
            strategy="value_match"
        )

    def build_correction_prompt(self, failure: VerificationResult) -> str:
        """构建修正提示 — 验证失败时注入模型"""
        return f"""
⚠️ 上一步操作验证失败，必须修正后再继续

失败操作: {failure.detail}
期望结果: {failure.expected}
实际结果: {failure.actual}
验证策略: {failure.strategy}

请执行以下修正步骤:
1. 分析失败原因
2. 回滚或修正错误状态
3. 重新执行正确操作
4. 再次验证结果

⚠️ 在修正完成并验证通过之前，不要继续后续步骤。
"""


# ─── 确定性错误检测器 ReFlect（§4.3） ──────────────────────

@dataclass
class DetectionRule:
    """检测规则定义"""
    id: str
    description: str
    trigger_tools: list = field(default_factory=list)
    check_fn: Callable = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "description": self.description,
            "trigger_tools": self.trigger_tools
        }


class DeterministicErrorDetector:
    """
    确定性错误检测器 ReFlect
    对应文档§4.3 — 不依赖LLM的规则引擎

    独立于LLM的确定性检测，确保永远能检测到：
    1. 死循环检测
    2. 错误页面检测
    3. 上下文溢出检测
    4. 工具调用模式异常检测
    5. 目标漂移检测
    """

    def __init__(self):
        self.rules = self._build_rules()
        self.detection_history = []

    def _build_rules(self) -> list:
        """构建确定性检测规则"""
        return [
            # 规则1: 创建操作后的页面检查
            {
                "id": "post_action_page_check",
                "description": "检测表单创建/提交后是否进入正确页面",
                "trigger_tools": ["Write", "Edit", "Patch", "Submit", "Create"],
                "check_fn": self._check_post_action_page
            },
            # 规则2: 死循环检测
            {
                "id": "loop_detection",
                "description": "检测同一工具同一参数连续重复调用",
                "trigger_tools": [],
                "check_fn": self._check_infinite_loop
            },
            # 规则3: 上下文溢出预警
            {
                "id": "context_overflow_warning",
                "description": "检测上下文即将溢出",
                "trigger_tools": [],
                "check_fn": self._check_context_overflow
            },
            # 规则4: 连续失败检测
            {
                "id": "consecutive_failure_detection",
                "description": "检测工具调用连续失败",
                "trigger_tools": [],
                "check_fn": self._check_consecutive_failures
            },
            # 规则5: 空操作检测
            {
                "id": "noop_detection",
                "description": "检测无实际效果的工具调用",
                "trigger_tools": ["Read", "Search", "List"],
                "check_fn": self._check_noop
            },
            # 规则6: 耗时异常检测
            {
                "id": "outlier_duration_detection",
                "description": "检测单步耗时异常",
                "trigger_tools": [],
                "check_fn": self._check_outlier_duration
            },
            # 规则7: 输出截断检测
            {
                "id": "truncation_detection",
                "description": "检测输出是否被截断",
                "trigger_tools": ["Read", "Terminal", "WebSearch"],
                "check_fn": self._check_truncation
            }
        ]

    async def detect(self, tool_call: dict, context: dict) -> list:
        """
        每次工具调用后执行所有规则检查
        返回检测到的问题列表
        """
        results = []
        tool_name = tool_call.get("name", "")

        for rule in self.rules:
            try:
                # 检查是否匹配触发工具列表
                if rule["trigger_tools"] and tool_name not in rule["trigger_tools"]:
                    continue

                result = rule["check_fn"](tool_call, context)
                if result.get("detected"):
                    result["rule_id"] = rule["id"]
                    result["tool_name"] = tool_name
                    result["timestamp"] = time.time()
                    results.append(result)
                    self.detection_history.append(result)
            except Exception as e:
                # 规则执行失败不影响其他规则
                pass

        return results

    def _check_post_action_page(self, tool_call: dict,
                                 context: dict) -> dict:
        """规则1: 操作后页面检查"""
        result_text = str(context.get("tool_result", {}).get("output", ""))
        error_keywords = ["error", "Error", "ERROR", "失败", "错误",
                          "exception", "Exception", "not found",
                          "permission denied", "access denied"]

        for kw in error_keywords:
            if kw in result_text or kw in str(tool_call.get("parameters", {})):
                return {
                    "detected": True,
                    "type": "post_action_error",
                    "severity": "critical",
                    "suggestion": f"操作后检测到错误关键词: {kw}，建议回滚并重试",
                    "keyword": kw
                }

        return {"detected": False}

    def _check_infinite_loop(self, tool_call: dict,
                              context: dict) -> dict:
        """规则2: 死循环检测"""
        call_history = context.get("tool_call_history", [])
        if len(call_history) < 3:
            return {"detected": False}

        last_3 = call_history[-3:]
        all_same = all(
            c.get("name") == last_3[0].get("name") and
            json.dumps(c.get("parameters", {}), sort_keys=True) ==
            json.dumps(last_3[0].get("parameters", {}), sort_keys=True)
            for c in last_3
        )

        if all_same:
            return {
                "detected": True,
                "type": "infinite_loop",
                "severity": "critical",
                "suggestion": f"检测到死循环（{last_3[0].get('name')} × 3次），"
                              f"建议：1.检查操作是否实际生效 2.尝试不同参数 3.跳过当前步骤",
                "tool_name": last_3[0].get("name"),
                "params": last_3[0].get("parameters", {})
            }

        return {"detected": False}

    def _check_context_overflow(self, tool_call: dict,
                                 context: dict) -> dict:
        """规则3: 上下文溢出预警"""
        estimated = context.get("context_management", {}).get("total_tokens_estimate", 0)
        max_tokens = context.get("max_context_tokens", 64000)

        if estimated > max_tokens * 0.8:
            return {
                "detected": True,
                "type": "context_near_overflow",
                "severity": "warning",
                "suggestion": f"上下文使用量 {estimated}/{max_tokens} ({estimated/max_tokens:.0%})，建议立即触发压缩",
                "usage_ratio": estimated / max_tokens
            }

        return {"detected": False}

    def _check_consecutive_failures(self, tool_call: dict,
                                     context: dict) -> dict:
        """规则4: 连续失败检测"""
        verifications = context.get("verification_history", [])
        recent_failures = sum(
            1 for v in verifications[-3:]
            if not v.get("passed", True)
        )

        if recent_failures >= 3:
            return {
                "detected": True,
                "type": "consecutive_failure",
                "severity": "critical",
                "suggestion": f"最近3次验证全部失败，建议暂停并启动结构化反思工作流",
                "failure_count": recent_failures
            }

        return {"detected": False}

    def _check_noop(self, tool_call: dict, context: dict) -> dict:
        """规则5: 空操作检测"""
        tool_name = tool_call.get("name", "")
        output = str(context.get("tool_result", {}).get("output", ""))

        # 读工具返回空
        if tool_name in ("Read", "List", "Search") and not output.strip():
            consecutive_reads = sum(
                1 for h in context.get("tool_call_history", [])[-5:]
                if h.get("name") in ("Read", "List", "Search") and
                not h.get("output", "").strip()
            )
            if consecutive_reads >= 3:
                return {
                    "detected": True,
                    "type": "noop_loop",
                    "severity": "warning",
                    "suggestion": "连续3次读操作返回空，建议检查路径或换个方式获取信息",
                    "consecutive": consecutive_reads
                }

        return {"detected": False}

    def _check_outlier_duration(self, tool_call: dict,
                                 context: dict) -> dict:
        """规则6: 耗时异常检测"""
        duration = context.get("tool_result", {}).get("duration", 0)
        durations = [
            h.get("duration", 0)
            for h in context.get("tool_call_history", [])[-10:]
        ]
        if durations:
            avg = sum(durations) / len(durations)
            if duration > avg * 5 and duration > 10:
                return {
                    "detected": True,
                    "type": "outlier_duration",
                    "severity": "warning",
                    "suggestion": f"操作耗时异常 ({duration}s vs 平均{avg:.1f}s)，可能网络或系统问题",
                    "duration": duration,
                    "average": avg
                }

        return {"detected": False}

    def _check_truncation(self, tool_call: dict, context: dict) -> dict:
        """规则7: 输出截断检测"""
        output = str(context.get("tool_result", {}).get("output", ""))
        if output.endswith("...") or "(truncated)" in output.lower():
            return {
                "detected": True,
                "type": "output_truncation",
                "severity": "warning",
                "suggestion": "输出被截断，建议分步读取或使用文件旁路方案",
                "output_end": output[-50:]
            }

        return {"detected": False}


# ─── 降级检测与拦截器（§8.1） ──────────────────────────────

class DegradationPreventer:
    """
    降级检测与拦截器 — 对应文档§8.1 "绝不降级实现"
    
    检测5种降级模式：
    1. 范围缩减 — Agent缩小了任务范围
    2. 方案替换 — 用简单方案替代了要求方案
    3. 验证跳过 — 跳过了验证步骤
    4. 字段缺失 — 关键字段未实现
    5. 简化实现 — 用MVP/示例替代生产级
    """

    DEGRADATION_KEYWORDS = {
        "scope_reduction": [
            "只实现", "简化为", "仅支持", "先做", "例子",
            "样例", "演示", "核心功能", "基本功能",
            "MVP", "最小可行", "简化版", "demo"
        ],
        "batch_generation": [
            "批量生成", "循环生成", "批量创建", "批量实现",
            "用循环", "模板生成", "自动生成所有"
        ],
        "implementation_replacement": [
            "替换为", "改用", "替代方案", "变通",
            "用xxx代替", "由于xx限制"
        ],
        "verification_skip": [
            "跳过验证", "不验证", "略过", "不做测试",
            "先不测", "后续再补", "手动验证"
        ],
        "placeholder": [
            "占位符", "TODO", "待实现", "待补充",
            "placeholder", "FIXME", "HACK"
        ]
    }

    def __init__(self, critic_agent=None):
        self.critic = critic_agent

    async def check_for_degradation(
        self,
        agent_output: dict,
        original_goal: str,
        success_criteria: list = None
    ) -> dict:
        """
        检查输出是否存在降级

        返回:
        {
            "degraded": True/False,
            "issues": [str],
            "action": "block_and_escalate" | "warn" | "pass",
            "details": {...}
        }
        """
        issues = []
        output_text = str(agent_output.get("description", agent_output.get("output", "")))
        output_text += " " + str(agent_output.get("result", ""))

        # 1. 范围缩减检测
        scope_issues = self._check_scope_reduction(output_text, original_goal)
        issues.extend(scope_issues)

        # 2. 批量生成检测（格林主人禁令）
        batch_issues = self._check_batch_generation(output_text)
        issues.extend(batch_issues)

        # 3. 方案替换检测
        replacement_issues = self._check_implementation_replacement(output_text)
        issues.extend(replacement_issues)

        # 4. 验证跳过检测
        verify_issues = self._check_verification_skip(output_text)
        issues.extend(verify_issues)

        # 5. 占位符检测
        placeholder_issues = self._check_placeholder(output_text)
        issues.extend(placeholder_issues)

        # 6. 成功标准覆盖检查
        if success_criteria:
            criteria_issues = self._check_criteria_coverage(
                agent_output, success_criteria
            )
            issues.extend(criteria_issues)

        # 7. LLM增强检测
        if self.critic and issues:
            critic_result = await self.critic.check_degradation(
                agent_output, original_goal, success_criteria or []
            )
            if critic_result.get("degraded"):
                issues.extend(critic_result.get("issues", []))

        severity = self._assess_severity(issues)
        return {
            "degraded": len(issues) > 0,
            "issues": issues,
            "action": severity["action"],
            "severity": severity["level"],
            "details": {
                "scope_reduction": len(scope_issues),
                "replacement": len(replacement_issues),
                "skip_verification": len(verify_issues),
                "placeholder": len(placeholder_issues),
                "criteria_missed": len(criteria_issues) if success_criteria else 0
            }
        }

    def _check_scope_reduction(self, output: str, goal: str) -> list:
        """检查范围缩减"""
        issues = []
        output_lower = output.lower()

        # 检查是否包含降级关键词（排除负向声明，如"无任何简化"、"没有简化"）
        for kw in self.DEGRADATION_KEYWORDS["scope_reduction"]:
            if kw in output_lower:
                # 检查是否是否定语境
                negations = ["无任何", "没有", "不存在", "杜绝了", "no", "without"]
                is_negated = any(neg in output_lower for neg in negations)
                if not is_negated:
                    issues.append(f"检测到范围缩减信号: '{kw}'")

        return issues

    def _check_batch_generation(self, output: str) -> list:
        """检查批量生成 — 格林主人禁令"""
        issues = []
        output_lower = output.lower()
        for kw in self.DEGRADATION_KEYWORDS.get("batch_generation", []):
            if kw in output_lower:
                negations = ["无任何", "没有", "禁止", "杜绝", "no", "without"]
                if not any(neg in output_lower for neg in negations):
                    issues.append(f"检测到批量生成信号: '{kw}'")
        return issues

    def _check_implementation_replacement(self, output: str) -> list:
        """检查方案替换"""
        issues = []
        output_lower = output.lower()
        for kw in self.DEGRADATION_KEYWORDS["implementation_replacement"]:
            if kw in output_lower:
                issues.append(f"检测到方案替换信号: '{kw}'")
        return issues

    def _check_verification_skip(self, output: str) -> list:
        """检查验证跳过"""
        issues = []
        output_lower = output.lower()
        for kw in self.DEGRADATION_KEYWORDS["verification_skip"]:
            if kw in output_lower:
                issues.append(f"检测到验证跳过信号: '{kw}'")
        return issues

    def _check_placeholder(self, output: str) -> list:
        """检查占位符"""
        issues = []
        output_lower = output.lower()
        for kw in self.DEGRADATION_KEYWORDS["placeholder"]:
            # 对中文关键词直接匹配，对英文关键词(如TODO/FIXME/HACK)大小写不敏感
            kw_lower = kw.lower()
            if kw in output or kw_lower in output_lower or kw.upper() in output:
                # 检查是否是否定语境
                negations = ["无任何", "没有", "不存在", "杜绝了", "no ", "without"]
                is_negated = any(neg in output_lower for neg in negations)
                if not is_negated:
                    issues.append(f"检测到占位符: '{kw}'")
        return issues

    def _check_criteria_coverage(self, output: dict,
                                  criteria: list) -> list:
        """检查成功标准覆盖度"""
        issues = []
        output_text = str(output)
        for criterion in criteria:
            description = criterion.get("description", criterion.get("name", ""))
            if description and description not in output_text:
                issues.append(f"成功标准未覆盖: {description}")
        return issues

    def _assess_severity(self, issues: list) -> dict:
        """评估问题严重程度"""
        if len(issues) >= 3:
            return {"level": "critical", "action": "block_and_escalate"}
        elif len(issues) >= 1:
            return {"level": "high", "action": "block_and_escalate"}
        return {"level": "pass", "action": "pass"}


# ─── 验证组合器 ───────────────────────────────────────────────

class VerificationPipeline:
    """
    验证组合器 — 将StepVerifier + ReFlect + DegradationPreventer串联
    每个工具调用后执行全链路验证
    """

    def __init__(self, step_verifier: StepVerifier,
                 error_detector: DeterministicErrorDetector,
                 degradation_preventer: DegradationPreventer):
        self.verifier = step_verifier
        self.detector = error_detector
        self.preventer = degradation_preventer

    async def verify_all(self, tool_call: dict, tool_result: dict,
                          loop_state: dict, context: dict) -> dict:
        """
        全链路验证 — 每次工具调用后执行

        返回:
        {
            "step_verified": bool,
            "errors_detected": [dict],
            "degradation_detected": bool,
            "all_passed": bool,
            "must_stop": bool,
            "correction_prompt": str
        }
        """
        result = {
            "step_verified": False,
            "errors_detected": [],
            "degradation_detected": False,
            "all_passed": True,
            "must_stop": False,
            "correction_prompt": None
        }

        # 1. 步骤验证
        verification = await self.verifier.verify_step(
            tool_call, tool_result, loop_state
        )
        result["step_verified"] = verification.passed

        if not verification.passed:
            result["all_passed"] = False
            result["correction_prompt"] = self.verifier.build_correction_prompt(
                verification
            )

        # 2. 确定性错误检测
        errors = await self.detector.detect(tool_call, context)
        result["errors_detected"] = errors

        critical_errors = [e for e in errors if e.get("severity") == "critical"]
        if critical_errors:
            result["all_passed"] = False
            result["must_stop"] = True

        # 3. 降级检测
        if context.get("is_final_output"):
            degradation = await self.preventer.check_for_degradation(
                {"output": str(tool_result.get("output", ""))},
                loop_state.get("global_constraints", {}).get("original_goal", ""),
                loop_state.get("task_dag", {}).get("success_criteria", [])
            )
            result["degradation_detected"] = degradation.get("degraded", False)
            if degradation.get("degraded"):
                result["all_passed"] = False
                if degradation.get("action") == "block_and_escalate":
                    result["must_stop"] = True

        return result
