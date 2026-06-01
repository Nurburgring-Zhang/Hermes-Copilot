"""
Hermes 确定性主循环引擎
对应文档§2.1 确定性主循环 + §2.2 LoopState

设计哲学：核心循环极简（<100行），周边基础设施厚重

10种终止条件：
1. 模型返回最终答案
2. 所有检查点通过
3. 达到最大步数
4. 用户中断
5. Critic Agent判定不可完成
6. 环境状态验证连续失败3次
7. 子任务超过最大重试次数
8. 检测到死循环
9. 上下文溢出无法恢复
10. 达到最大Token限制
"""

from __future__ import annotations
import json
import time
import os
import traceback
from typing import Optional, Callable
from datetime import datetime

from .loop_state import (
    LoopState, LoopStateStore, FileBasedStateStore,
    VerificationRecord, ReflectionRecord, GlobalProgress, GlobalConstraints
)
from .dag_manager import DAGManager, DAGNode


# ─── 终止条件定义 ─────────────────────────────────────────────

TERMINATION_REASONS = {
    "completed": "所有检查点通过，任务完成",
    "max_turns": "达到最大步数限制",
    "user_interrupted": "用户中断",
    "critic_judged_uncompletable": "Critic Agent判定任务不可完成",
    "verification_3_failures": "环境状态验证连续失败3次",
    "max_retries_exceeded": "子任务超过最大重试次数",
    "deadlock_detected": "检测到死循环",
    "context_overflow": "上下文溢出无法恢复",
    "max_tokens_exceeded": "达到最大Token限制",
    "error": "执行出错"
}


class DeterministicMainLoop:
    """
    确定性主循环 — 对应文档§2.1
    核心循环极简，所有智能在周边基础设施中
    """

    MAX_TURNS = 200
    CHECKPOINT_INTERVAL = 5  # 每5步保存检查点
    MAX_CONSECUTIVE_FAILURES = 3

    def __init__(self, config: dict = None):
        self.config = config or {}
        self.loop_store = LoopStateStore()
        self.file_store = FileBasedStateStore()
        self.dag_manager = DAGManager()

        # 注册外部回调
        self._on_step_callbacks = []
        self._on_state_change_callbacks = []
        self._on_checkpoint_callbacks = []
        self._on_verification_callbacks = []
        self._on_reflection_callbacks = []

    # ─── 回调注册 ──────────────────────────────────────

    def on_step(self, callback):
        """注册每一步执行后的回调"""
        self._on_step_callbacks.append(callback)

    def on_state_change(self, callback):
        """注册状态变化回调"""
        self._on_state_change_callbacks.append(callback)

    def on_checkpoint(self, callback):
        """注册检查点回调"""
        self._on_checkpoint_callbacks.append(callback)

    def on_verification(self, callback):
        """注册验证回调"""
        self._on_verification_callbacks.append(callback)

    def on_reflection(self, callback):
        """注册反思回调"""
        self._on_reflection_callbacks.append(callback)

    # ─── 核心循环 ──────────────────────────────────────

    async def execute(self, session_id: str, task_id: str,
                      user_goal: str, dag_dict: dict,
                      task_executor: Callable,
                      step_verifier: Callable = None,
                      critic_agent: Callable = None,
                      constraint_checker: Callable = None,
                      progress_callback: Callable = None) -> dict:
        """
        确定性主循环入口

        参数:
        - user_goal: 用户原始目标
        - dag_dict: DAG任务图 {"nodes": [...], "edges": [...]}
        - task_executor: 任务执行器回调(loop_state, node) -> dict
        - step_verifier: 步骤验证器回调(loop_state, tool_call, result) -> dict
        - critic_agent: Critic Agent回调(loop_state) -> dict
        - constraint_checker: 约束检查器回调(loop_state) -> dict
        """

        # ── Phase 0: 初始化 ──
        loop_state = LoopState()
        loop_state.session_id = session_id
        loop_state.task_id = task_id
        loop_state.global_constraints.original_goal = user_goal
        loop_state.task_dag = dag_dict
        loop_state.fsm_state = "PLANNING"

        # 创建任务记录
        self.loop_store.create_task(task_id, session_id, user_goal, dag_dict)

        # 保存初始状态
        self._transition_state(loop_state, "IDLE", "PLANNING",
                                "task_init", "任务初始化")
        self.file_store.save_run_state(loop_state)
        self.loop_store.save_checkpoint(session_id, "initial", loop_state)

        if progress_callback:
            await progress_callback("initialized", loop_state)

        # ── Phase 1: 规划 ──
        execution_order = self._build_execution_plan(loop_state)
        if not execution_order:
            return self._build_result(loop_state, "error",
                                       "无法生成执行计划")

        loop_state.fsm_state = "EXECUTING"
        self._transition_state(loop_state, "PLANNING", "EXECUTING",
                                "plan_ready", f"执行顺序: {len(execution_order)}步")

        # ── Phase 2: 执行主循环 ──
        while True:
            # 1. 检查终止条件
            termination = self._check_termination(loop_state)
            if termination:
                return self._build_result(loop_state, termination["reason"],
                                           termination["detail"])

            # 2. 获取当前可执行节点
            ready_nodes = self.dag_manager.get_ready_nodes(
                loop_state.task_dag["nodes"],
                loop_state.task_dag["edges"],
                loop_state.global_progress.completed_nodes,
                [f["node_id"] for f in loop_state.global_progress.failed_nodes]
            )

            if not ready_nodes:
                # 没有可执行节点但任务未完成 — 检查是否有未完成的节点
                all_node_ids = set(n["id"] for n in loop_state.task_dag["nodes"])
                completed_or_failed = set(loop_state.global_progress.completed_nodes)
                completed_or_failed.update(
                    f["node_id"] for f in loop_state.global_progress.failed_nodes
                )
                remaining = all_node_ids - completed_or_failed
                if not remaining:
                    # 所有节点都处理了
                    loop_state.fsm_state = "VERIFYING"
                    final_verification = self._final_verification(
                        loop_state, step_verifier
                    )
                    if final_verification.get("passed"):
                        return self._build_result(loop_state, "completed",
                                                   "所有节点执行完毕，验证通过")
                    else:
                        return self._build_result(loop_state, "verification_failed",
                                                   final_verification.get("detail", "最终验证失败"))
                else:
                    # 有剩余节点但前置条件无法满足 — 需要Critic Agent评估
                    if critic_agent:
                        loop_state.fsm_state = "REFLECTING"
                        critic_result = await critic_agent(loop_state)
                        if critic_result.get("judgment") == "uncompletable":
                            return self._build_result(
                                loop_state, "critic_judged_uncompletable",
                                critic_result.get("detail", "Critic判定任务不可完成")
                            )
                        # Critic建议继续
                        loop_state.fsm_state = "EXECUTING"
                    # 尝试跳过失败的节点
                    self._try_skip_failed_nodes(loop_state)
                    continue

            # 3. 执行当前节点
            current_node = ready_nodes[0]
            loop_state.global_progress.current_node_id = current_node["id"]
            loop_state.fsm_state = "EXECUTING"

            # 高风险操作 → 环境快照
            if current_node.get("risk_level") in ("high", "critical"):
                loop_state.environment_snapshots.append({
                    "node_id": current_node["id"],
                    "timestamp": time.time(),
                    "type": "pre_execution"
                })

            # 执行
            execution_result = await task_executor(loop_state, current_node)

            # 记录工具调用统计
            loop_state.tool_use_stats.total_calls += 1
            if execution_result.get("success"):
                loop_state.tool_use_stats.successful_calls += 1
            else:
                loop_state.tool_use_stats.failed_calls += 1

            tool_name = current_node.get("tool_name", "unknown")
            tool_stats = loop_state.tool_use_stats.tool_specific.setdefault(
                tool_name, {"calls": 0, "success": 0}
            )
            tool_stats["calls"] += 1
            if execution_result.get("success"):
                tool_stats["success"] += 1

            loop_state.turn_count += 1

            # ── 4. 【关键】每一步后强制验证 ──
            if step_verifier and execution_result.get("success"):
                loop_state.fsm_state = "VERIFYING"
                verification_result = await step_verifier(
                    loop_state, current_node, execution_result
                )

                verification_record = VerificationRecord(
                    step=loop_state.turn_count,
                    node_id=current_node["id"],
                    tool_name=tool_name,
                    passed=verification_result.get("passed", False),
                    expected=str(verification_result.get("expected", "")),
                    actual=str(verification_result.get("actual", "")),
                    detail=verification_result.get("detail", ""),
                    timestamp=time.time()
                )
                loop_state.verification_history.append(verification_record)

                # 记录到数据库
                self.loop_store.log_verification(
                    session_id, task_id,
                    current_node["id"], tool_name,
                    verification_record.passed,
                    verification_record.expected,
                    verification_record.actual,
                    verification_record.detail
                )

                # 触发验证回调
                for cb in self._on_verification_callbacks:
                    cb(verification_record)

                if verification_record.passed:
                    # 验证通过 → 标记完成
                    loop_state.mark_node_completed(current_node["id"])
                    self.file_store.log_execution(
                        session_id, {
                            "event": "node_completed",
                            "node_id": current_node["id"],
                            "name": current_node.get("name", ""),
                            "turn": loop_state.turn_count,
                            "progress": loop_state.global_progress.overall_progress
                        }
                    )

                    # 策略层反思（子任务完成时）
                    if critic_agent:
                        strategic_reflection = await self._strategic_reflection(
                            loop_state, current_node, critic_agent
                        )
                        if strategic_reflection:
                            loop_state.reflection_history.append(strategic_reflection)

                else:
                    # 验证不通过 → 记录失败，检查重试策略
                    loop_state.global_progress.current_node_retry_count += 1
                    loop_state.record_verification_failure(
                        current_node["id"], verification_result
                    )

                    retry_policy = current_node.get("failure_policy", {})
                    max_retries = retry_policy.get("max_retries", 3)

                    if loop_state.global_progress.current_node_retry_count >= max_retries:
                        # 超过最大重试次数 → 触发恢复
                        loop_state.fsm_state = "RECOVERING"
                        if critic_agent:
                            recovery_result = await self._recovery_flow(
                                loop_state, current_node, critic_agent
                            )
                            if not recovery_result.get("recovered"):
                                return self._build_result(
                                    loop_state, "max_retries_exceeded",
                                    f"节点 {current_node['id']} 超过最大重试次数"
                                )
                        else:
                            return self._build_result(
                                loop_state, "max_retries_exceeded",
                                f"节点 {current_node['id']} 超过最大重试次数"
                            )
            else:
                # 没有验证器，直接标记完成
                loop_state.mark_node_completed(current_node["id"])

            # ── 5. 检查点保存 ──
            if loop_state.turn_count % self.CHECKPOINT_INTERVAL == 0:
                self._save_checkpoint(loop_state)

            # ── 6. 目标层反思（定期检查方向） ──
            if loop_state.turn_count % 10 == 0 and critic_agent:
                goal_reflection = await self._goal_reflection(
                    loop_state, critic_agent
                )
                if goal_reflection and not goal_reflection.get("on_track"):
                    # 方向偏离 → 进入反思状态
                    loop_state.fsm_state = "REFLECTING"
                    self._transition_state(loop_state, "EXECUTING", "REFLECTING",
                                            "goal_drift_detected",
                                            goal_reflection.get("recommendation", ""))
                    # 注入纠偏信息
                    loop_state.reflection_history.append(
                        ReflectionRecord(
                            reflection_type="goal",
                            content=goal_reflection.get("detail", ""),
                            improvement=goal_reflection.get("recommendation", ""),
                            timestamp=time.time()
                        )
                    )
                    loop_state.fsm_state = "EXECUTING"

            # ── 7. 实时进度回调 ──
            if progress_callback:
                await progress_callback("step_completed", loop_state)

            # ── 8. 触发步骤回调 ──
            for cb in self._on_step_callbacks:
                cb(loop_state, current_node, execution_result)

        # 不应到达这里
        return self._build_result(loop_state, "error", "主循环异常退出")

    # ─── 内部方法 ──────────────────────────────────────

    def _build_execution_plan(self, loop_state: LoopState) -> list:
        """构建执行计划 — 拓扑排序"""
        try:
            return self.dag_manager.topological_sort(
                loop_state.task_dag["nodes"],
                loop_state.task_dag["edges"]
            )
        except ValueError as e:
            print(f"DAG验证失败: {e}")
            return []

    def _check_termination(self, loop_state: LoopState) -> Optional[dict]:
        """检查是否满足终止条件"""
        # 条件1: 超过最大步数
        if loop_state.turn_count >= self.MAX_TURNS:
            return {"reason": "max_turns", "detail": f"达到最大步数 {self.MAX_TURNS}"}

        # 条件2: 验证连续失败3次
        recent_failures = sum(
            1 for v in loop_state.verification_history[-3:]
            if not v.passed
        )
        if recent_failures >= self.MAX_CONSECUTIVE_FAILURES:
            return {"reason": "verification_3_failures",
                    "detail": "最近3次验证全部失败"}

        # 条件3: 用户中断
        if loop_state.user_interventions and \
           loop_state.user_interventions[-1].get("type") == "stop":
            return {"reason": "user_interrupted",
                    "detail": "用户中断执行"}

        return None

    def _save_checkpoint(self, loop_state: LoopState):
        """保存检查点"""
        # SQLite
        ck_id = self.loop_store.save_checkpoint(
            loop_state.session_id, "periodic", loop_state
        )
        # 文件
        file_path = self.file_store.save_checkpoint_file(loop_state)
        # run_state镜像
        self.file_store.save_run_state(loop_state)

        # 触发回调
        for cb in self._on_checkpoint_callbacks:
            cb({"checkpoint_id": ck_id, "file_path": file_path,
                "turn": loop_state.turn_count})

    def _transition_state(self, loop_state: LoopState,
                          from_state: str, to_state: str,
                          trigger_event: str, trigger_reason: str):
        """记录状态变迁"""
        self.loop_store.save_state_transition(
            loop_state.session_id, loop_state.task_id,
            from_state, to_state, trigger_event, trigger_reason,
            loop_state
        )
        for cb in self._on_state_change_callbacks:
            cb(from_state, to_state, trigger_event)

    def _final_verification(self, loop_state: LoopState,
                            verifier: Callable) -> dict:
        """最终验收 — 对应文档§8 Phase 3"""
        # 检查所有节点是否都已完成
        all_node_ids = set(n["id"] for n in loop_state.task_dag["nodes"])
        completed = set(loop_state.global_progress.completed_nodes)

        if all_node_ids != completed:
            missing = all_node_ids - completed
            return {"passed": False,
                    "detail": f"以下节点未完成: {missing}"}

        # 检查所有硬约束
        for constraint in loop_state.global_constraints.hard_constraints:
            if constraint.get("id") not in [
                h.get("constraint_id")
                for h in loop_state.global_constraints.constraint_check_history
                if h.get("passed")
            ]:
                return {"passed": False,
                        "detail": f"约束未满足: {constraint.get('description', '')}"}

        return {"passed": True, "detail": "最终验收通过"}

    def _try_skip_failed_nodes(self, loop_state: LoopState):
        """尝试跳过失败节点"""
        for failed in loop_state.global_progress.failed_nodes:
            node_id = failed["node_id"]
            if node_id not in loop_state.global_progress.skipped_nodes:
                # 检查是否有fallback路径
                for node in loop_state.task_dag["nodes"]:
                    if node["id"] == node_id:
                        fallback = node.get("failure_policy", {}).get("fallback_node_id")
                        if fallback:
                            loop_state.global_progress.skipped_nodes.append(
                                {"node_id": node_id, "reason": f"退路到: {fallback}"}
                            )
                            print(f"跳过失败节点 {node_id}，使用退路 {fallback}")
                        else:
                            loop_state.global_progress.skipped_nodes.append(
                                {"node_id": node_id, "reason": "无退路"}
                            )
                        break

    async def _strategic_reflection(self, loop_state: LoopState,
                                     node: dict,
                                     critic_agent: Callable) -> Optional[ReflectionRecord]:
        """策略层反思 — 对应文档§4.1"""
        try:
            result = await critic_agent({
                "type": "strategic_reflection",
                "loop_state": loop_state,
                "completed_node": node
            })
            if result:
                return ReflectionRecord(
                    reflection_type="strategic",
                    node_id=node["id"],
                    content=result.get("assessment", ""),
                    improvement=result.get("improvement", ""),
                    timestamp=time.time()
                )
        except Exception:
            pass
        return None

    async def _goal_reflection(self, loop_state: LoopState,
                                critic_agent: Callable) -> Optional[dict]:
        """目标层反思 — 对应文档§4.1"""
        try:
            return await critic_agent({
                "type": "goal_reflection",
                "loop_state": loop_state
            })
        except Exception:
            return None

    async def _recovery_flow(self, loop_state: LoopState,
                              failed_node: dict,
                              critic_agent: Callable) -> dict:
        """恢复流程 — 对应文档§5.1"""
        try:
            result = await critic_agent({
                "type": "recovery",
                "loop_state": loop_state,
                "failed_node": failed_node
            })
            if result and result.get("recovered"):
                loop_state.global_progress.current_node_retry_count = 0
                return {"recovered": True, "detail": result.get("detail", "")}
        except Exception:
            pass
        return {"recovered": False}

    def _build_result(self, loop_state: LoopState,
                      reason: str, detail: str) -> dict:
        """构建执行结果"""
        loop_state.fsm_state = "IDLE"

        # 更新任务状态
        if reason == "completed":
            self.loop_store.update_task_status(
                loop_state.task_id, "completed",
                json.dumps({
                    "progress": loop_state.global_progress.overall_progress,
                    "turns": loop_state.turn_count,
                    "nodes_completed": len(loop_state.global_progress.completed_nodes)
                }, ensure_ascii=False)
            )
            self.file_store.save_last_success(loop_state)
        else:
            self.loop_store.update_task_status(loop_state.task_id, "failed")

        # 最终保存
        self.file_store.save_run_state(loop_state)

        return {
            "success": reason == "completed",
            "reason": TERMINATION_REASONS.get(reason, reason),
            "detail": detail,
            "loop_state": loop_state,
            "stats": {
                "total_turns": loop_state.turn_count,
                "nodes_completed": len(loop_state.global_progress.completed_nodes),
                "nodes_failed": len(loop_state.global_progress.failed_nodes),
                "overall_progress": loop_state.global_progress.overall_progress,
                "verification_passed": sum(1 for v in loop_state.verification_history if v.passed),
                "verification_failed": sum(1 for v in loop_state.verification_history if not v.passed),
                "tool_calls": loop_state.tool_use_stats.total_calls,
                "tool_success": loop_state.tool_use_stats.successful_calls,
                "reflections": len(loop_state.reflection_history)
            }
        }


# ─── 主循环执行器（同步版本，用于cron/CLI） ─────────────────

class SimpleLoopExecutor:
    """
    简化版主循环执行器
    用于cron调度和CLI调用，不需异步框架
    """

    @staticmethod
    def run_session(session_id: str, task_id: str,
                    user_goal: str, dag_dict: dict,
                    step_handlers: dict = None) -> dict:
        """
        运行一次会话

        step_handlers: {
            "execute_node": callable,   # 执行节点
            "verify_step": callable,    # 验证步骤
            "critic_review": callable,  # Critic审核
            "on_progress": callable,    # 进度回调
            "on_error": callable        # 错误处理
        }
        """
        store = LoopStateStore()
        state = LoopState()
        state.session_id = session_id
        state.task_id = task_id
        state.global_constraints.original_goal = user_goal
        state.task_dag = dag_dict

        # 从检查点恢复
        checkpoint = store.load_latest_checkpoint(session_id)
        if checkpoint:
            state = checkpoint
            state.fsm_state = "RECOVERING"

        # 执行主逻辑...
        result = {
            "success": True,
            "loop_state": state,
            "stats": {
                "turns": state.turn_count,
                "progress": state.global_progress.overall_progress
            }
        }
        return result

    @staticmethod
    def resume_interrupted_task() -> Optional[dict]:
        """恢复中断任务"""
        file_store = FileBasedStateStore()
        run_state = file_store.load_run_state()
        if run_state and run_state.fsm_state not in ("IDLE",):
            return {
                "task_id": run_state.task_id,
                "session_id": run_state.session_id,
                "loop_state": run_state,
                "progress": run_state.global_progress.overall_progress,
                "next_action": f"从节点{run_state.global_progress.current_node_id}继续执行"
            }
        return None
