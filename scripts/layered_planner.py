#!/usr/bin/env python3
"""
P1-3 三层分层规划脚本 (Layered Planner)
==========================================
功能:
- L1(目标层): 任务目标定义+成功标准清单+约束条件 → 调用一次
- L2(策略层): 方案评估+策略选择+阶段划分 → 调用一次
- L3(执行层): 逐步执行+每步验证 → 循环调用
- 输出分层规划文档到 reports/plans/

用法:
  python3 layered_planner.py l1 <task_id> <goal> [constraints...]
  python3 layered_planner.py l2 <task_id> <strategies...>
  python3 layered_planner.py l3 <task_id> <step> <step_desc> <verification>
  python3 layered_planner.py l3-verify <task_id> <step_index> <result>
  python3 layered_planner.py show <task_id>
  python3 layered_planner.py list
"""

import json, os, sys, time, hashlib
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any

HERMES = Path(os.path.expanduser("~/.hermes"))
REPORTS = HERMES / "reports"
PLANS_DIR = REPORTS / "plans"
TZ = timezone(timedelta(hours=8))

now = lambda: datetime.now(TZ).isoformat()


def ensure_dir():
    PLANS_DIR.mkdir(parents=True, exist_ok=True)


def _plan_path(task_id: str) -> Path:
    safe_id = task_id.replace("/", "_").replace("\\", "_")
    return PLANS_DIR / f"{safe_id}.json"


# ===== L1: 目标层 =====

def layer1_plan(
    task_id: str,
    goal: str,
    success_criteria: List[str],
    constraints: List[str],
    metadata: Optional[Dict] = None,
) -> Dict[str, Any]:
    """
    L1(目标层): 任务目标定义+成功标准清单+约束条件

    调用频率: 一次 (任务开始时)
    """
    ensure_dir()
    path = _plan_path(task_id)

    plan = {
        "task_id": task_id,
        "created_at": now(),
        "updated_at": now(),
        "status": "planning",
        "version": 1,
        "layers": {
            "L1_goal": {
                "status": "defined",
                "goal": goal,
                "success_criteria": success_criteria,
                "constraints": constraints,
                "metadata": metadata or {},
                "defined_at": now(),
            },
            "L2_strategy": {
                "status": "pending",
                "strategies_evaluated": [],
                "selected_strategy": None,
                "phases": [],
            },
            "L3_execution": {
                "status": "pending",
                "steps": [],
                "current_step": 0,
                "total_steps": 0,
                "verification_results": [],
            },
        },
    }

    path.write_text(json.dumps(plan, ensure_ascii=False, indent=2))
    return plan


# ===== L2: 策略层 =====

def layer2_plan(
    task_id: str,
    strategies_evaluated: List[Dict[str, Any]],
    selected_strategy: str,
    phases: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    L2(策略层): 方案评估+策略选择+阶段划分

    调用频率: 一次 (L1完成后)

    参数:
        strategies_evaluated: [{"name": str, "pros": [str], "cons": [str], "score": float}, ...]
        selected_strategy: str — 选中的方案名称
        phases: [{"name": str, "goal": str, "steps": int, "dependencies": [str]}, ...]
    """
    path = _plan_path(task_id)
    plan = _load_plan(task_id)
    if plan is None:
        return {"ok": False, "error": f"规划文档不存在: {task_id}，请先执行L1"}

    plan["updated_at"] = now()
    plan["version"] = plan.get("version", 0) + 1
    plan["layers"]["L2_strategy"] = {
        "status": "defined",
        "strategies_evaluated": strategies_evaluated,
        "selected_strategy": selected_strategy,
        "phases": phases,
        "total_phases": len(phases),
        "defined_at": now(),
    }

    # 更新L3的状态
    total_steps = sum(p.get("steps", 1) for p in phases)
    plan["layers"]["L3_execution"]["total_steps"] = total_steps
    plan["layers"]["L3_execution"]["status"] = "ready"

    path.write_text(json.dumps(plan, ensure_ascii=False, indent=2))
    return plan


# ===== L3: 执行层 =====

def layer3_step(
    task_id: str,
    step_index: int,
    step_desc: str,
    verification: str,
    phase: str = "",
) -> Dict[str, Any]:
    """
    L3(执行层): 记录一个执行步骤

    调用频率: 每执行一步调用一次 (循环调用)

    参数:
        step_index: 步骤序号 (从1开始)
        step_desc: 步骤描述
        verification: 验证标准
        phase: 所属阶段名称
    """
    path = _plan_path(task_id)
    plan = _load_plan(task_id)
    if plan is None:
        return {"ok": False, "error": f"规划文档不存在: {task_id}，请先执行L1/L2"}

    plan["updated_at"] = now()
    plan["version"] = plan.get("version", 0) + 1

    step_entry = {
        "index": step_index,
        "phase": phase,
        "description": step_desc,
        "verification": verification,
        "status": "pending",
        "result": None,
        "verified": False,
        "recorded_at": now(),
    }

    steps = plan["layers"]["L3_execution"]["steps"]
    # 防止重复添加
    existing = [s for s in steps if s["index"] == step_index]
    if existing:
        existing[0].update(step_entry)
    else:
        steps.append(step_entry)

    plan["layers"]["L3_execution"]["current_step"] = step_index
    plan["layers"]["L3_execution"]["status"] = "executing"

    path.write_text(json.dumps(plan, ensure_ascii=False, indent=2))
    return plan


def layer3_verify(
    task_id: str,
    step_index: int,
    result: str,
    passed: bool,
    notes: str = "",
) -> Dict[str, Any]:
    """
    L3执行验证: 记录某一步的验证结果

    参数:
        step_index: 步骤序号
        result: 执行结果描述
        passed: 是否通过验证
        notes: 备注
    """
    path = _plan_path(task_id)
    plan = _load_plan(task_id)
    if plan is None:
        return {"ok": False, "error": f"规划文档不存在: {task_id}"}

    plan["updated_at"] = now()
    steps = plan["layers"]["L3_execution"]["steps"]

    for s in steps:
        if s["index"] == step_index:
            s["status"] = "passed" if passed else "failed"
            s["result"] = result
            s["verified"] = True
            s["verification_notes"] = notes
            s["verified_at"] = now()
            break

    # 检查是否所有步骤已完成
    all_done = all(s.get("verified", False) for s in steps)
    if all_done:
        plan["layers"]["L3_execution"]["status"] = "completed"
        plan["status"] = "completed"

    plan["layers"]["L3_execution"]["verification_results"].append({
        "step": step_index,
        "passed": passed,
        "result": result[:100],
        "ts": now(),
    })

    path.write_text(json.dumps(plan, ensure_ascii=False, indent=2))

    return {
        "ok": True,
        "step_index": step_index,
        "passed": passed,
        "all_completed": all_done if 'all_done' in dir() else False,
    }


# ===== 辅助函数 =====

def _load_plan(task_id: str) -> Optional[Dict[str, Any]]:
    path = _plan_path(task_id)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def show_plan(task_id: str) -> Optional[Dict]:
    """展示分层规划文档内容"""
    plan = _load_plan(task_id)
    if plan is None:
        return None
    return plan


def list_plans() -> List[Dict]:
    """列出所有规划文档"""
    ensure_dir()
    result = []
    for f in sorted(PLANS_DIR.glob("*.json"), key=os.path.getmtime, reverse=True):
        try:
            data = json.loads(f.read_text())
            l1 = data.get("layers", {}).get("L1_goal", {})
            l3 = data.get("layers", {}).get("L3_execution", {})
            result.append({
                "task_id": data.get("task_id", ""),
                "status": data.get("status", ""),
                "goal": l1.get("goal", "")[:80],
                "progress": f"{l3.get('current_step', 0)}/{l3.get('total_steps', 0)}",
                "updated_at": data.get("updated_at", ""),
            })
        except Exception:
            continue
    return result


# ===== 生成Markdown报告 =====

def generate_md_report(task_id: str) -> Optional[str]:
    """生成Markdown格式的分层规划报告"""
    plan = _load_plan(task_id)
    if plan is None:
        return None

    l1 = plan["layers"]["L1_goal"]
    l2 = plan["layers"]["L2_strategy"]
    l3 = plan["layers"]["L3_execution"]

    lines = []
    lines.append(f"# 分层规划报告: {task_id}")
    lines.append(f"状态: {plan['status']} | 更新: {plan['updated_at']}")
    lines.append("")

    lines.append("## L1: 目标层")
    lines.append(f"- **目标**: {l1.get('goal', '未定义')}")
    lines.append("- **成功标准**:")
    for c in l1.get("success_criteria", []):
        lines.append(f"  - [ ] {c}")
    lines.append("- **约束条件**:")
    for c in l1.get("constraints", []):
        lines.append(f"  - {c}")
    lines.append("")

    lines.append("## L2: 策略层")
    lines.append(f"- **选中策略**: {l2.get('selected_strategy', '未选择')}")
    lines.append("- **方案评估**:")
    for s in l2.get("strategies_evaluated", []):
        lines.append(f"  - {s.get('name', '?')} (评分: {s.get('score', 'N/A')})")
        for p in s.get("pros", []):
            lines.append(f"    - ✅ {p}")
        for c in s.get("cons", []):
            lines.append(f"    - ❌ {c}")
    lines.append("- **阶段划分**:")
    for p in l2.get("phases", []):
        lines.append(f"  - **{p.get('name', '?')}**: {p.get('goal', '')} ({p.get('steps', '?')}步)")
    lines.append("")

    lines.append("## L3: 执行层")
    lines.append(f"进度: {l3.get('current_step', 0)}/{l3.get('total_steps', 0)}")
    lines.append("")
    for s in l3.get("steps", []):
        status_icon = "✅" if s.get("status") == "passed" else ("❌" if s.get("status") == "failed" else "⏳")
        lines.append(f"### 步骤 {s['index']}: {s.get('description', '')} {status_icon}")
        lines.append(f"- **验证标准**: {s.get('verification', '')}")
        if s.get("result"):
            lines.append(f"- **结果**: {s['result'][:200]}")
        if s.get("verification_notes"):
            lines.append(f"- **备注**: {s['verification_notes']}")
        lines.append("")

    md_path = PLANS_DIR / f"{task_id}.md"
    md_content = "\n".join(lines)
    md_path.write_text(md_content, encoding='utf-8')
    return md_content


# ===== CLI =====
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "l1":
        if len(sys.argv) < 4:
            print("用法: layered_planner.py l1 <task_id> <goal> [constraint1] [constraint2] ...")
            sys.exit(1)
        task_id = sys.argv[2]
        goal = sys.argv[3]
        constraints = sys.argv[4:] if len(sys.argv) > 4 else []
        # 默认成功标准 (可由用户后续修改JSON)
        success_criteria = [
            "功能完整: 所有预期功能已实现",
            "测试通过: 核心测试用例全部通过",
            "无回归: 现有功能不受影响",
        ]
        plan = layer1_plan(task_id, goal, success_criteria, constraints)
        print(json.dumps({"ok": True, "task_id": task_id, "plan_status": plan["status"]}, ensure_ascii=False, indent=2))
        # 同时生成md报告
        generate_md_report(task_id)

    elif cmd == "l2":
        if len(sys.argv) < 4:
            print("用法: layered_planner.py l2 <task_id> <selected_strategy> [phase1:goal1:steps1] [phase2:goal2:steps2] ...")
            sys.exit(1)
        task_id = sys.argv[2]
        selected_strategy = sys.argv[3]

        strategies_evaluated = [{
            "name": selected_strategy,
            "pros": ["首选方案"],
            "cons": [],
            "score": 8.0,
        }]

        phases = []
        for arg in sys.argv[4:]:
            parts = arg.split(":", 2)
            phases.append({
                "name": parts[0],
                "goal": parts[1] if len(parts) > 1 else "",
                "steps": int(parts[2]) if len(parts) > 2 else 3,
                "dependencies": [],
            })

        plan = layer2_plan(task_id, strategies_evaluated, selected_strategy, phases)
        print(json.dumps({"ok": True, "task_id": task_id, "phases": len(phases), "total_steps": sum(p.get("steps", 1) for p in phases)}, ensure_ascii=False, indent=2))
        generate_md_report(task_id)

    elif cmd == "l3":
        if len(sys.argv) < 5:
            print("用法: layered_planner.py l3 <task_id> <step_index> <step_desc> <verification> [phase]")
            sys.exit(1)
        task_id = sys.argv[2]
        step_index = int(sys.argv[3])
        step_desc = sys.argv[4]
        verification = sys.argv[5]
        phase = sys.argv[6] if len(sys.argv) > 6 else ""
        plan = layer3_step(task_id, step_index, step_desc, verification, phase)
        print(json.dumps({"ok": True, "task_id": task_id, "step": step_index, "status": "recorded"}, ensure_ascii=False, indent=2))

    elif cmd == "l3-verify":
        if len(sys.argv) < 5:
            print("用法: layered_planner.py l3-verify <task_id> <step_index> <passed> [result]")
            sys.exit(1)
        task_id = sys.argv[2]
        step_index = int(sys.argv[3])
        passed = sys.argv[4].lower() in ("true", "yes", "1", "pass")
        result = sys.argv[5] if len(sys.argv) > 5 else ""
        r = layer3_verify(task_id, step_index, result, passed)
        print(json.dumps(r, ensure_ascii=False, indent=2))

    elif cmd == "show":
        task_id = sys.argv[2] if len(sys.argv) > 2 else ""
        if not task_id:
            print("用法: layered_planner.py show <task_id>")
            sys.exit(1)
        plan = show_plan(task_id)
        if plan:
            print(json.dumps(plan, ensure_ascii=False, indent=2))
        else:
            print(json.dumps({"ok": False, "error": f"规划不存在: {task_id}"}, ensure_ascii=False))

    elif cmd == "report":
        task_id = sys.argv[2] if len(sys.argv) > 2 else ""
        if not task_id:
            print("用法: layered_planner.py report <task_id>")
            sys.exit(1)
        md = generate_md_report(task_id)
        if md:
            print(md)
        else:
            print(json.dumps({"ok": False, "error": f"规划不存在: {task_id}"}, ensure_ascii=False))

    elif cmd == "list":
        plans = list_plans()
        print(json.dumps(plans, ensure_ascii=False, indent=2))

    else:
        print(f"未知命令: {cmd}")
        print(__doc__)
        sys.exit(1)
