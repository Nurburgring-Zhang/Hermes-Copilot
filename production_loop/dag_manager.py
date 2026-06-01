"""
DAG任务图 + 全局约束锚定
解决"越往后越做不对"和"目标漂移"

对应文档§3.2 DAG任务图、§3.3 全局约束锚定
"""

from __future__ import annotations
import json
import time
from typing import Optional
from dataclasses import dataclass, field


@dataclass
class DAGNode:
    """DAG任务节点 — 完整定义对应文档§3.2"""
    id: str
    name: str
    description: str = ""
    node_type: str = "action"  # action | verification | decision | recovery
    depends_on: list = field(default_factory=list)
    dependency_type: str = "all"  # all | any
    tool_name: Optional[str] = None
    tool_params: dict = field(default_factory=dict)
    sub_agent_type: Optional[str] = None

    # 成功标准
    success_criteria: list = field(default_factory=list)
    # 每个criterion: {"type": "state_check"|"value_match"|"existence"|"custom",
    #                 "check_function": "...", "expected_value": ..., "tolerance": ...}

    # 失败处理
    failure_policy: dict = field(default_factory=lambda: {
        "max_retries": 3,
        "retry_strategy": "backoff",
        "fallback_node_id": None,
        "escalate_on_failure": False
    })

    weight: float = 1.0
    risk_level: str = "low"  # low | medium | high | critical
    requires_user_approval: bool = False
    timeout_ms: int = 300000

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "node_type": self.node_type,
            "depends_on": self.depends_on,
            "dependency_type": self.dependency_type,
            "tool_name": self.tool_name,
            "tool_params": self.tool_params,
            "sub_agent_type": self.sub_agent_type,
            "success_criteria": self.success_criteria,
            "failure_policy": self.failure_policy,
            "weight": self.weight,
            "risk_level": self.risk_level,
            "requires_user_approval": self.requires_user_approval,
            "timeout_ms": self.timeout_ms
        }

    @classmethod
    def from_dict(cls, data: dict) -> "DAGNode":
        return cls(
            id=data["id"],
            name=data.get("name", ""),
            description=data.get("description", ""),
            node_type=data.get("node_type", "action"),
            depends_on=data.get("depends_on", []),
            dependency_type=data.get("dependency_type", "all"),
            tool_name=data.get("tool_name"),
            tool_params=data.get("tool_params", {}),
            sub_agent_type=data.get("sub_agent_type"),
            success_criteria=data.get("success_criteria", []),
            failure_policy=data.get("failure_policy", {"max_retries": 3}),
            weight=data.get("weight", 1.0),
            risk_level=data.get("risk_level", "low"),
            requires_user_approval=data.get("requires_user_approval", False),
            timeout_ms=data.get("timeout_ms", 300000)
        )


@dataclass
class DAGEdge:
    """DAG边"""
    from_node: str
    to_node: str
    edge_type: str = "dependency"
    data_mapping: dict = field(default_factory=dict)


class DAGManager:
    """
    DAG任务图管理器
    负责：生成DAG、验证DAG、拓扑排序、进度计算、依赖检查
    """

    @staticmethod
    def topological_sort(nodes: list, edges: list) -> list:
        """拓扑排序 — 计算执行顺序"""
        # 构建邻接表
        in_degree = {n["id"]: 0 for n in nodes}
        adj = {n["id"]: [] for n in nodes}

        for edge in edges:
            from_id, to_id = edge["from_node"], edge["to_node"]
            if edge.get("edge_type", "dependency") == "dependency":
                in_degree[to_id] = in_degree.get(to_id, 0) + 1
                adj.setdefault(from_id, []).append(to_id)

        # Kahn算法
        queue = [nid for nid, deg in in_degree.items() if deg == 0]
        result = []

        while queue:
            nid = queue.pop(0)
            result.append(nid)
            for neighbor in adj.get(nid, []):
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        # 检查是否有环
        if len(result) != len(nodes):
            cycle_nodes = set(n["id"] for n in nodes) - set(result)
            raise ValueError(f"DAG中存在环，涉及节点: {cycle_nodes}")

        return result

    @staticmethod
    def get_ready_nodes(nodes: list, edges: list,
                        completed_ids: list, failed_ids: list) -> list:
        """获取当前可执行的节点（所有前置依赖已满足）"""
        ready = []
        completed_set = set(completed_ids)
        failed_set = set(failed_ids)

        for node in nodes:
            node_id = node["id"]

            # 跳过已完成/失败的节点
            if node_id in completed_set or node_id in failed_set:
                continue

            # 检查前置依赖
            deps = node.get("depends_on", [])
            dep_type = node.get("dependency_type", "all")

            if dep_type == "all":
                # 需要所有前置完成
                all_done = all(d in completed_set for d in deps)
                if all_done:
                    ready.append(node)
            else:
                # 任一前置完成即可
                any_done = any(d in completed_set for d in deps)
                if any_done:
                    ready.append(node)

        return ready

    @staticmethod
    def calculate_progress(nodes: list, completed_ids: list) -> float:
        """计算整体执行进度"""
        if not nodes:
            return 0.0
        total_weight = sum(n.get("weight", 1.0) for n in nodes)
        completed_weight = sum(
            n.get("weight", 1.0)
            for n in nodes
            if n["id"] in completed_ids
        )
        return completed_weight / total_weight if total_weight > 0 else 0.0

    @staticmethod
    def validate_dag(nodes: list, edges: list) -> tuple:
        """验证DAG完整性 — 返回 (is_valid, errors)"""
        errors = []
        node_ids = set(n["id"] for n in nodes)

        # 检查每个边的from/to是否存在
        for edge in edges:
            if edge["from_node"] not in node_ids:
                errors.append(f"边 {edge['from_node']}→{edge['to_node']}: 源节点不存在")
            if edge["to_node"] not in node_ids:
                errors.append(f"边 {edge['from_node']}→{edge['to_node']}: 目标节点不存在")

        # 检查每个节点的依赖是否存在
        for node in nodes:
            for dep in node.get("depends_on", []):
                if dep not in node_ids:
                    errors.append(f"节点 {node['id']} 依赖了不存在的节点: {dep}")

        # 检查是否有孤立节点（可选）
        connected = set()
        for edge in edges:
            connected.add(edge["from_node"])
            connected.add(edge["to_node"])
        for node in nodes:
            if node["id"] not in connected and len(nodes) > 1:
                errors.append(f"节点 {node['id']} 是孤立的（无连接边）")

        # 尝试拓扑排序（检查环）
        try:
            DAGManager.topological_sort(nodes, edges)
        except ValueError as e:
            errors.append(str(e))

        return (len(errors) == 0, errors)

    @staticmethod
    def build_auto_dag(build_steps: list) -> dict:
        """
        自动构建DAG — 从步骤列表生成
        build_steps: [
            {"id": "step1", "name": "...", "depends_on": [...], "type": "action"},
            ...
        ]
        """
        nodes = []
        edges = []

        for i, step in enumerate(build_steps):
            node = {
                "id": step.get("id", f"step_{i}"),
                "name": step.get("name", f"步骤{i+1}"),
                "description": step.get("description", ""),
                "node_type": step.get("type", "action"),
                "depends_on": step.get("depends_on", []),
                "dependency_type": step.get("dependency_type", "all"),
                "tool_name": step.get("tool_name"),
                "tool_params": step.get("tool_params", {}),
                "sub_agent_type": step.get("sub_agent_type"),
                "success_criteria": step.get("success_criteria", []),
                "failure_policy": step.get("failure_policy", {"max_retries": 3}),
                "weight": step.get("weight", 1.0),
                "risk_level": step.get("risk_level", "low"),
                "requires_user_approval": step.get("requires_user_approval", False),
                "timeout_ms": step.get("timeout_ms", 300000)
            }
            nodes.append(node)

            # 自动生成边
            for dep in node["depends_on"]:
                edges.append({
                    "from_node": dep,
                    "to_node": node["id"],
                    "edge_type": "dependency",
                    "data_mapping": {}
                })

        return {"nodes": nodes, "edges": edges}


# ─── 全局约束锚定（§3.3） ──────────────────────────────────────

class GlobalConstraintManager:
    """
    全局约束管理器 — 防止目标漂移
    对应文档§3.3
    """

    @staticmethod
    def build_constraint_section(constraints: dict) -> str:
        """构建约束注入文本 — 注入到模型上下文中"""
        hard = constraints.get("hard_constraints", [])
        soft = constraints.get("soft_constraints", [])
        rules = constraints.get("business_rules", [])
        original_goal = constraints.get("original_goal", "")
        check_history = constraints.get("constraint_check_history", [])[-3:]

        section = f"""
⚠️ 全局约束（必须遵守，不可偏离）

原始任务目标（最高优先级）:
{original_goal}

硬约束（违反将导致任务失败）:
"""
        for c in hard:
            section += f"  - [{c.get('id', '?')}] {c.get('description', '')}\n"
            if c.get('verification_method'):
                section += f"    验证方式: {c['verification_method']}\n"

        if rules:
            section += "\n业务规则:\n"
            for r in rules:
                section += f"  - {r}\n"

        if soft:
            section += "\n软约束（尽量满足）:\n"
            for c in soft:
                section += f"  - [{c.get('id', '?')}] {c.get('description', '')}\n"

        if check_history:
            section += "\n最近约束检查:\n"
            for h in check_history:
                passed = "✓" if h.get("passed") else "✗"
                section += f"  [{passed}] {h.get('constraint_id', '?')}: {h.get('detail', '')}\n"

        section += "\n⚠️ 在执行任何操作前，确认其符合以上所有约束。\n"

        return section

    @staticmethod
    def check_constraints(
        planned_action: dict,
        constraints: dict
    ) -> dict:
        """检查计划操作是否符合所有约束"""
        violations = []
        hard = constraints.get("hard_constraints", [])

        for constraint in hard:
            # 简单关键词匹配检查
            constraint_keywords = constraint.get("keywords", [])
            action_desc = str(planned_action.get("description", ""))
            verb = planned_action.get("verb", "")

            # 检查约束是否被违反
            if constraint.get("type") == "prohibit":
                for kw in constraint_keywords:
                    if kw in action_desc or kw in verb:
                        violations.append({
                            "constraint_id": constraint["id"],
                            "description": constraint["description"],
                            "violation_detail": f"操作包含禁止关键词: {kw}",
                            "severity": "error"
                        })

        return {
            "all_passed": len(violations) == 0,
            "violations": violations,
            "timestamp": time.time()
        }

    @staticmethod
    def check_drift(
        original_goal: str,
        recent_context: str
    ) -> dict:
        """检测目标漂移风险 — 基于语义相似度估算"""
        # 简单关键词覆盖检测
        goal_words = set(original_goal.lower().split())
        context_words = set(recent_context.lower().split())

        if not goal_words:
            return {"risk": 0.0, "detail": "无法检测（目标为空）"}

        overlap = goal_words & context_words
        coverage = len(overlap) / len(goal_words) if goal_words else 0

        # 覆盖度越低，偏离风险越高
        risk = 1.0 - coverage
        return {
            "risk": min(1.0, max(0.0, risk)),
            "detail": f"关键词覆盖: {len(overlap)}/{len(goal_words)} ({coverage:.0%})",
            "coverage": coverage,
            "missing_keywords": list(goal_words - context_words)[:10]
        }
