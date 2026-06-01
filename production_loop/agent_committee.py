"""
专家协作委员会 — 专业化子代理系统
对应文档§2.3 专家协作委员会 + §4 闭环验证与反思

核心组件：
1. SubAgentDefinition — 子代理定义（白名单+隔离级别）
2. SubAgentOrchestrator — 子代理调度器
3. CriticAgent — 独立审计者
4. ThreeLayerReflection — 三层反思引擎
5. StructuredReflexion — 结构化反思工作流（失败→诊断→修复→验证→技能沉淀）
"""

from __future__ import annotations
import json
import time
import os
import subprocess
import tempfile
from typing import Optional, Callable
from dataclasses import dataclass, field
from datetime import datetime


# ─── 子代理定义（§2.3） ──────────────────────────────────────

@dataclass
class SubAgentDefinition:
    """子代理定义 — 每个子代理是独立的专业执行单元"""
    id: str
    name: str
    specialization: str = "execution"  # planning | execution | verification | critique | recovery | research
    model_config: dict = field(default_factory=lambda: {
        "provider": "deepseek",
        "model": "deepseek-chat",
        "temperature": 0.3,
        "max_tokens": 4096
    })
    allowed_tools: list = field(default_factory=list)
    disallowed_tools: list = field(default_factory=list)
    isolation_level: str = "process"  # process | worktree | container
    max_parallel_instances: int = 3
    timeout_ms: int = 300000

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "specialization": self.specialization,
            "model_config": self.model_config,
            "allowed_tools": self.allowed_tools,
            "disallowed_tools": self.disallowed_tools,
            "isolation_level": self.isolation_level,
            "max_parallel_instances": self.max_parallel_instances,
            "timeout_ms": self.timeout_ms
        }


# ─── 预定义子代理类型 ───────────────────────────────────────

SUB_AGENT_TEMPLATES = {
    "planning": SubAgentDefinition(
        id="planner",
        name="规划专家",
        specialization="planning",
        model_config={"provider": "deepseek", "model": "deepseek-chat",
                       "temperature": 0.2, "max_tokens": 4096},
        allowed_tools=["Read", "Search", "SessionSearch", "Memory"],
        disallowed_tools=["Write", "Execute", "Delete"],
        isolation_level="process"
    ),
    "execution": SubAgentDefinition(
        id="executor",
        name="执行专家",
        specialization="execution",
        model_config={"provider": "deepseek", "model": "deepseek-chat",
                       "temperature": 0.1, "max_tokens": 4096},
        allowed_tools=["Read", "Write", "Edit", "Terminal", "Patch",
                       "WebSearch", "SkillView"],
        disallowed_tools=["Delete", "NetworkScan"],
        isolation_level="process"
    ),
    "verification": SubAgentDefinition(
        id="verifier",
        name="验证专家",
        specialization="verification",
        model_config={"provider": "deepseek", "model": "deepseek-chat",
                       "temperature": 0.0, "max_tokens": 2048},
        allowed_tools=["Read", "Search", "Terminal", "DatabaseQuery"],
        disallowed_tools=["Write", "Edit", "Delete"],
        isolation_level="process"
    ),
    "critique": SubAgentDefinition(
        id="critic",
        name="审计专家（Critic）",
        specialization="critique",
        model_config={"provider": "deepseek", "model": "deepseek-chat",
                       "temperature": 0.0, "max_tokens": 4096},
        allowed_tools=["Read", "Search", "Memory"],
        disallowed_tools=["Write", "Edit", "Execute", "Delete"],
        isolation_level="process"
    ),
    "recovery": SubAgentDefinition(
        id="recovery",
        name="恢复专家",
        specialization="recovery",
        model_config={"provider": "deepseek", "model": "deepseek-chat",
                       "temperature": 0.0, "max_tokens": 4096},
        allowed_tools=["Read", "Write", "Edit", "Patch",
                       "Terminal", "Memory", "SkillManage"],
        disallowed_tools=["Delete"],
        isolation_level="process"
    ),
    "research": SubAgentDefinition(
        id="researcher",
        name="研究专家",
        specialization="research",
        model_config={"provider": "deepseek", "model": "deepseek-chat",
                       "temperature": 0.4, "max_tokens": 4096},
        allowed_tools=["WebSearch", "Read", "Search", "SessionSearch"],
        disallowed_tools=["Write", "Edit", "Execute"],
        isolation_level="process"
    )
}


class CriticAgent:
    """
    独立审计者 — 解决"Agen不检查自己作业"问题
    对应文档§4.2 Critic Agent + §4.1 三层反思

    核心职责：质疑而非肯定
    严苛的审计者标准：宁可多质疑，不可遗漏问题
    """

    SYSTEM_PROMPT = """你是一个严苛的审计者。你的职责是找出执行中的问题，而非肯定成果。

对每个子任务，你必须回答：
1. 边界条件是否全部覆盖？
2. 是否存在未验证的假设？
3. 执行路径是否是最优的？
4. 是否遗漏了任何验证步骤？
5. 如果有任何不确定性，标记为"需重做"。

审查标准：宁可多质疑，不可遗漏问题。
输出格式：JSON，包含passed(boolean)、issues(array)、recommendations(array)、severity(low|medium|high|critical)。"""

    def __init__(self, llm_caller: Callable = None):
        self.llm_caller = llm_caller

    async def review_execution(self, task: dict, execution_trace: list) -> dict:
        """
        审查任务执行 — 对应文档§4.2
        """
        prompt = f"""
        审查以下任务执行：

        任务定义: {json.dumps(task, ensure_ascii=False, indent=2)}
        执行轨迹: {json.dumps(execution_trace[-20:], ensure_ascii=False, indent=2)}

        请评估：
        1. 是否有任何步骤的边界条件未覆盖？
        2. 是否有未验证的假设？
        3. 执行路径是否为当前条件下的最优选择？
        4. 是否遗漏了任何必要的验证步骤？
        5. 整体质量评分（0-100）
        """

        if self.llm_caller:
            return await self.llm_caller("critic_review", prompt)
        return self._default_review(task, execution_trace)

    def _default_review(self, task: dict, execution_trace: list) -> dict:
        """默认审查（无LLM时的确定性检查）"""
        issues = []
        recommendations = []

        # 检查1: 是否有验证步骤
        has_verification = any(
            s.get("type") == "verification" for s in execution_trace
        )
        if not has_verification:
            issues.append("执行轨迹中没有验证步骤")

        # 检查2: 是否有失败重试
        has_retries = any(
            s.get("retry_count", 0) > 1 for s in execution_trace
        )
        if has_retries:
            retry_steps = [s for s in execution_trace if s.get("retry_count", 0) > 1]
            recommendations.append(f"以下步骤需要优化: {[s.get('name') for s in retry_steps]}")

        # 检查3: 完成度
        completed_nodes = task.get("dag", {}).get("completed_nodes", [])
        total_nodes = task.get("dag", {}).get("total_nodes", 0)
        if total_nodes > 0 and len(completed_nodes) < total_nodes:
            issues.append(f"任务未全部完成: {len(completed_nodes)}/{total_nodes}")

        return {
            "passed": len(issues) == 0,
            "issues": issues,
            "recommendations": recommendations,
            "severity": "critical" if len(issues) > 2 else "medium" if issues else "low",
            "score": max(0, 100 - len(issues) * 15)
        }

    async def strategic_reflection(self, loop_state: dict,
                                    completed_node: dict) -> dict:
        """
        策略层反思
        对应文档§4.1 — 每个子任务完成后触发
        """
        prompt = f"""
        作为独立的Critic Agent，请评估以下子任务的执行情况：

        子任务定义: {json.dumps(completed_node, ensure_ascii=False, indent=2)}
        整体进度: {loop_state.get('global_progress', {}).get('overall_progress', 0)}
        验证历史: {json.dumps(loop_state.get('verification_history', [])[-5:], ensure_ascii=False, indent=2)}

        请回答以下问题：
        1. 执行效率如何？（工具调用次数是否合理？有冗余操作吗？）
        2. 是否有更好的执行路径？
        3. 结果质量是否符合预期？
        4. 有哪些可改进的点？

        输出JSON格式：{{"assessment": "...", "improvement": "...", "efficiency_score": 0-100}}
        """
        if self.llm_caller:
            return await self.llm_caller("strategic_reflection", prompt)
        return {"assessment": "自动评估通过", "improvement": "无改进建议", "efficiency_score": 85}

    async def goal_reflection(self, loop_state: dict) -> dict:
        """
        目标层反思
        对应文档§4.1 — 定期检查是否在正确方向上
        """
        original_goal = loop_state.get("global_constraints", {}).get("original_goal", "")
        completed_nodes = loop_state.get("global_progress", {}).get("completed_nodes", [])
        total_nodes = len(loop_state.get("task_dag", {}).get("nodes", []))
        failed_nodes = loop_state.get("global_progress", {}).get("failed_nodes", [])

        prompt = f"""
        检查执行是否仍在正确方向上：

        原始目标: {original_goal}
        完成进度: {len(completed_nodes)}/{total_nodes} 节点
        失败节点: {json.dumps(failed_nodes, ensure_ascii=False)}

        请回答：
        1. 当前方向是否仍然与原始目标一致？
        2. 是否有偏离风险？
        3. 是否应该调整策略？

        输出JSON格式：
        {{"on_track": true/false, "detail": "...", "recommendation": "...", "deviation_risk": 0-1}}
        """
        if self.llm_caller:
            return await self.llm_caller("goal_reflection", prompt)

        # 确定性检查：如果有3个以上失败节点，偏离风险高
        deviation_risk = min(1.0, len(failed_nodes) * 0.15)
        return {
            "on_track": deviation_risk < 0.4,
            "detail": f"完成进度: {len(completed_nodes)}/{total_nodes}, 失败: {len(failed_nodes)}",
            "recommendation": "继续执行" if deviation_risk < 0.4 else "建议暂停并重新评估策略",
            "deviation_risk": deviation_risk
        }

    async def recovery_plan(self, loop_state: dict,
                             failed_node: dict) -> dict:
        """
        恢复计划 — 失败后的诊断和修正
        对应文档§5.1 — 结构化反思工作流
        """
        prompt = f"""
        任务执行失败，请制定恢复计划：

        失败节点: {json.dumps(failed_node, ensure_ascii=False, indent=2)}
        当前进度: {loop_state.get('global_progress', {}).get('overall_progress', 0)}
        重试次数: {loop_state.get('global_progress', {}).get('current_node_retry_count', 0)}
        验证历史: {json.dumps(loop_state.get('verification_history', [])[-3:], ensure_ascii=False, indent=2)}

        请使用5-Why分析法找出根因，然后给出恢复方案。

        输出JSON格式：
        {{"recovered": true/false, "detail": "...", "root_cause": "...", 
          "correction_plan": ["步骤1", "步骤2", ...], "is_reusable": true/false}}
        """
        if self.llm_caller:
            return await self.llm_caller("recovery_plan", prompt)
        return {
            "recovered": True,
            "detail": "自动恢复",
            "root_cause": "执行错误",
            "correction_plan": ["重试当前节点"],
            "is_reusable": True
        }

    async def check_degradation(self, agent_output: dict,
                                 original_goal: str,
                                 success_criteria: list) -> dict:
        """
        降级检测与拦截 — 对应文档§8.1
        检查Agent是否降低了任务范围、替换方案、跳过验证
        """
        issues = []

        # 检查1: 范围缩减
        output_desc = str(agent_output.get("description", ""))
        goal_keywords = set(original_goal.lower().split())
        output_keywords = set(output_desc.lower().split())
        coverage = len(goal_keywords & output_keywords) / max(len(goal_keywords), 1)

        if coverage < 0.3:
            issues.append(f"输出范围大幅缩减（关键词覆盖仅{coverage:.0%}）")

        # 检查2: 验证步骤跳过
        if agent_output.get("verification_skipped", False):
            issues.append("验证步骤被跳过")

        # 检查3: 方案替换
        if agent_output.get("implementation_replaced", False):
            issues.append("使用了替代方案而非原始要求")

        return {
            "degraded": len(issues) > 0,
            "issues": issues,
            "action": "block_and_escalate" if len(issues) > 1 else "warn",
            "coverage": coverage
        }


class ThreeLayerReflectionEngine:
    """
    三层反思引擎 — 对应文档§4.1
    操作层(每步)→策略层(每子任务)→目标层(里程碑/异常)
    """

    def __init__(self, critic_agent: CriticAgent):
        self.critic = critic_agent

    async def operational_reflection(self, tool_call: dict,
                                      tool_result: dict,
                                      loop_state: dict) -> dict:
        """操作层反思：每个工具调用后即时验证"""
        verification = {
            "tool_name": tool_call.get("name", ""),
            "input_params": tool_call.get("parameters", {}),
            "output_preview": str(tool_result.get("output", ""))[:200],
            "execution_time": tool_result.get("duration", 0),
            "passed": tool_result.get("success", False),
            "timestamp": time.time()
        }

        if not verification["passed"]:
            return {
                "passed": False,
                "correction": f"工具调用失败: {tool_call.get('name', '')}",
                "severity": "critical"
            }

        return {"passed": True, "correction": None, "severity": "none"}

    async def strategic_reflection(self, completed_sub_task: dict,
                                    execution_trace: list,
                                    loop_state: dict) -> dict:
        """策略层反思：每个子任务完成后"""
        return await self.critic.strategic_reflection(loop_state, completed_sub_task)

    async def goal_reflection(self, loop_state: dict) -> dict:
        """目标层反思：定期检查整体方向"""
        return await self.critic.goal_reflection(loop_state)


class StructuredReflexionWorkflow:
    """
    结构化反思工作流 — 对应文档§5.1
    失败→诊断→修复→验证→技能沉淀
    Phase 1: 5-Why根因分析
    Phase 2: 生成修正方案
    Phase 3: 执行修正
    Phase 4: 验证修正效果
    Phase 5: 经验记录到技能库
    """

    def __init__(self, critic_agent: CriticAgent,
                 skill_updater: Callable = None):
        self.critic = critic_agent
        self.skill_updater = skill_updater

    async def execute(self, failure: dict, loop_state: dict) -> dict:
        """执行完整的结构化反思"""
        result = {}

        # Phase 1: 5-Why根因分析
        root_cause = self._diagnose_root_cause(failure, loop_state)
        result["root_cause"] = root_cause

        # Phase 2: 生成修正方案
        correction_plan = await self._generate_correction(
            root_cause, loop_state
        )
        result["correction_plan"] = correction_plan

        # Phase 3: 执行修正
        correction_result = self._execute_correction(
            correction_plan, loop_state
        )
        result["correction_result"] = correction_result

        # Phase 4: 验证修正效果
        verification = self._verify_correction(
            correction_result, loop_state
        )
        result["verification"] = verification

        # Phase 5: 经验记录到技能库
        if verification.get("passed") and root_cause.get("is_reusable"):
            if self.skill_updater:
                await self.skill_updater({
                    "failure_description": failure.get("description", ""),
                    "root_cause": root_cause,
                    "solution": correction_plan,
                    "verification": verification
                })
            result["skill_updated"] = True
        else:
            result["skill_updated"] = False

        return result

    def _diagnose_root_cause(self, failure: dict,
                              loop_state: dict) -> dict:
        """5-Why根因分析"""
        issue = failure.get("description", "")
        why_chain = [issue]

        # 逐层追问
        whys = {
            "工具调用失败": "参数不正确或环境状态异常",
            "参数不正确或环境状态异常": "缺少操作前状态确认",
            "缺少操作前状态确认": "验证机制未触发",
            "验证机制未触发": "步骤验证器未配置",
            "步骤验证器未配置": "系统架构缺陷",
        }

        current = issue
        for _ in range(5):
            root = whys.get(current)
            if root:
                why_chain.append(root)
                current = root
            else:
                break

        # 分类根因
        if "验证" in why_chain[-1]:
            category = "verification_error"
        elif "工具" in why_chain[-1]:
            category = "tool_error"
        elif "参数" in why_chain[-1]:
            category = "planning_error"
        elif "环境" in why_chain[-1]:
            category = "environment_error"
        elif "上下文" in why_chain[-1]:
            category = "context_error"
        else:
            category = "execution_error"

        return {
            "why_chain": why_chain,
            "category": category,
            "is_reusable": category != "environment_error",
            "root_description": why_chain[-1]
        }

    async def _generate_correction(self, root_cause: dict,
                                    loop_state: dict) -> dict:
        """生成修正方案"""
        correction_map = {
            "verification_error": {
                "action": "add_verification_step",
                "detail": "在工具调用后添加强制验证步骤"
            },
            "tool_error": {
                "action": "fix_tool_parameters",
                "detail": "修正工具参数并重试"
            },
            "planning_error": {
                "action": "replan_dag",
                "detail": "重新规划任务DAG"
            },
            "context_error": {
                "action": "compress_and_reload",
                "detail": "压缩上下文并重新加载关键信息"
            },
            "execution_error": {
                "action": "retry_with_correction",
                "detail": "修正执行方式后重试"
            },
            "environment_error": {
                "action": "escalate_to_human",
                "detail": "环境问题需人工处理"
            }
        }

        category = root_cause.get("category", "execution_error")
        return correction_map.get(category, {"action": "retry", "detail": "通用重试"})

    def _execute_correction(self, plan: dict, loop_state: dict) -> dict:
        """执行修正（实际由MainLoop调用，这里是模拟）"""
        return {
            "action_taken": plan.get("action", ""),
            "success": True,
            "detail": plan.get("detail", "")
        }

    def _verify_correction(self, result: dict, loop_state: dict) -> dict:
        """验证修正效果"""
        return {
            "passed": result.get("success", False),
            "detail": f"修正{'成功' if result.get('success') else '失败'}: {result.get('detail', '')}"
        }


class SubAgentOrchestrator:
    """
    子代理编排器 — 对应文档§2.3
    负责：任务分发、隔离环境创建、上下文注入、清理回收
    """

    def __init__(self, delegate_task_fn: Callable = None):
        """
        delegate_task_fn: Hermes的delegate_task工具，用于实际调度子代理
        如果为None，使用本地subprocess模拟
        """
        self.delegate = delegate_task_fn
        self.active_instances = {}
        self._instance_counters = {}

    async def dispatch(self, task: dict,
                       specialization: str = "execution") -> dict:
        """
        分发任务给合适的子代理

        task: {
            "id": str,
            "goal": str,
            "context": str,
            "toolsets": [str],
            "dag_node": dict  # 可选
        }
        """
        definition = SUB_AGENT_TEMPLATES.get(
            specialization,
            SUB_AGENT_TEMPLATES["execution"]
        )

        # 检查并发限制
        await self._wait_for_capacity(definition)

        # 构建子代理上下文
        sub_context = self._build_context(task, definition)

        if self.delegate:
            # 使用Hermes的delegate_task进行真实调度
            try:
                result = await self.delegate(
                    goal=task.get("goal", ""),
                    context=sub_context,
                    toolsets=task.get("toolsets", ["terminal", "file", "web"])
                )
                return {"success": True, "result": result, "agent_id": definition.id}
            except Exception as e:
                return {"success": False, "error": str(e), "agent_id": definition.id}
        else:
            # 本地模拟（用于测试）
            return self._local_execute(definition, task)

    def _build_context(self, task: dict, definition: SubAgentDefinition) -> str:
        """构建子代理上下文 — 仅注入必要信息，最小权限"""
        context_parts = [
            f"【角色】你是一个{definition.name}，专业领域: {definition.specialization}",
            f"【任务】{task.get('goal', '')}",
            f"【背景】{task.get('context', '')}",
            f"【可用工具】{', '.join(definition.allowed_tools)}",
            f"【禁止工具】{', '.join(definition.disallowed_tools)}",
            "【约束】",
            "1. 所有操作必须在自己的隔离环境中执行",
            "2. 完成时返回压缩摘要（不超过500字）",
            "3. 如果遇到无法解决的问题，标记为'需升级'",
            "4. 每个操作前先确认状态",
            "5. 操作后必须验证结果"
        ]

        dag_node = task.get("dag_node", {})
        if dag_node:
            context_parts.extend([
                f"【DAG节点】{json.dumps(dag_node, ensure_ascii=False)}",
                f"【成功标准】{json.dumps(dag_node.get('success_criteria', []), ensure_ascii=False)}"
            ])

        return "\n".join(context_parts)

    async def _wait_for_capacity(self, definition: SubAgentDefinition):
        """等待并发容量"""
        counter = self._instance_counters.setdefault(definition.id, 0)
        if counter >= definition.max_parallel_instances:
            # 简单等待
            import asyncio
            await asyncio.sleep(2)

    def _local_execute(self, definition: SubAgentDefinition,
                        task: dict) -> dict:
        """本地执行（用于测试/无delegate_task可用时）"""
        return {
            "success": True,
            "result": {
                "agent": definition.name,
                "specialization": definition.specialization,
                "task": task.get("goal", "")[:100],
                "executed_in": "local",
                "summary": f"{definition.name}已完成任务处理"
            },
            "agent_id": definition.id
        }

    def get_active_count(self) -> dict:
        """获取当前活跃实例数"""
        return dict(self._instance_counters)


# ─── Critic Cron: 定期自动Critic审查 ─────────────────────────

CRITIC_CRON_PROMPT = """你是一个严苛的Critic Agent审计者。你的职责是：

1. 审查当前所有活跃会话的执行状态
2. 识别是否有偏离目标的执行路径
3. 检测是否有降级实现
4. 检查验证覆盖率是否达标
5. 生成审计报告

输出格式：
- 活跃会话数
- 异常会话列表
- 建议修正操作
- 质量评分

严格标准：宁可多质疑，不可遗漏问题。
"""
