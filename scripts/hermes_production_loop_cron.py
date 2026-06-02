#!/usr/bin/env python3
"""
Hermes CaMeL Guard 集成到 production_loop 的自动安全检查模块

用法：
  python3 scripts/production_loop_cron.py check       # 每10分钟 — 含CaMeL安全审计
  python3 scripts/production_loop_cron.py critic      # 每30分钟 — CaMeL趋势分析
  python3 scripts/production_loop_cron.py deep_check  # 每2小时 — 安全深度验证
"""

import json, os, sys, time, subprocess
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from production_loop.engine import ProductionLoopEngine, resume_interrupted
from production_loop.loop_state import LoopStateStore, FileBasedStateStore

HERMES_HOME = os.path.expanduser("~/.hermes")
CAMEL_GUARD_SCRIPT = os.path.join(HERMES_HOME, "scripts", "hermes_camel_guard.py")
CAMEL_LOG = os.path.join(HERMES_HOME, "logs", "camel_guard.log")
AUDIT_PATH = os.path.join(HERMES_HOME, "reports", "production_loop_audit.json")

def run_camel_check() -> dict:
    """执行CaMeL安全检查 — 读取日志，统计风险"""
    result = {
        "timestamp": datetime.now().isoformat(),
        "injection_events": 0,
        "sensitive_tools_called": [],
        "warnings": [],
        "status": "safe",
    }
    
    if not os.path.exists(CAMEL_LOG):
        return result
    
    try:
        with open(CAMEL_LOG) as f:
            lines = [l.strip() for l in f if l.strip()]
        
        recent = lines[-50:] if len(lines) > 50 else lines
        for line in recent:
            try:
                entry = json.loads(line)
                etype = entry.get("type", "")
                if etype in ("tool_blocked",):
                    result["injection_events"] += 1
                    tool = entry.get("tool", "?")
                    if tool not in result["sensitive_tools_called"]:
                        result["sensitive_tools_called"].append(tool)
                    result["warnings"].append(f"工具阻止: {tool}")
                    result["status"] = "warning"
            except:
                continue
        
        print(f"[{datetime.now().isoformat()}] CaMeL安全: "
              f"{result['injection_events']}个注入事件, "
              f"状态={result['status']}")
    
    except Exception as e:
        print(f"[{datetime.now().isoformat()}] CaMeL检查异常: {e}")
        result["status"] = "error"
    
    return result


def run_check():
    """执行CaMeL安全检查 — 每10分钟"""
    store = LoopStateStore()
    file_store = FileBasedStateStore()

    # 1. 原有中断检查
    run_state = file_store.load_run_state()
    if run_state and run_state.fsm_state not in ("IDLE",):
        print(f"[{datetime.now().isoformat()}] 检测到中断任务: "
              f"{run_state.task_id} (状态: {run_state.fsm_state})")
        resume_interrupted()
    else:
        print(f"[{datetime.now().isoformat()}] 无中断任务")

    # 2. 数据库健康
    unfinished = store.get_unfinished_tasks()
    if unfinished:
        print(f"  未完成任务: {len(unfinished)}")
        for task in unfinished[:3]:
            print(f"    - {task['task_id'][:16]}: {task.get('status', '?')}")

    # 3. CaMeL安全检查
    camel_result = run_camel_check()
    
    # 4. 写入审计快照（含CaMeL信息）
    audit = {
        "timestamp": datetime.now().isoformat(),
        "unfinished_tasks": len(unfinished),
        "engine_running": run_state is not None,
        "camel_guard": camel_result,
    }
    with open(AUDIT_PATH, "w") as f:
        json.dump(audit, f, indent=2)


def run_critic():
    """Critic审查 — 每30分钟（含CaMeL趋势分析）"""
    store = LoopStateStore()
    unfinished = store.get_unfinished_tasks()

    report = {
        "timestamp": datetime.now().isoformat(),
        "active_sessions": len(unfinished),
        "sessions": [],
        "camel_guard": run_camel_check(),
    }

    for task in unfinished:
        report["sessions"].append({
            "task_id": task["task_id"],
            "goal": task.get("original_goal", "")[:80],
            "status": task.get("status", "unknown"),
            "created": task.get("created_at", ""),
        })

    report_path = os.path.join(HERMES_HOME, "reports", "critic_report.json")
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)

    print(f"[{datetime.now().isoformat()}] Critic审查完成: "
          f"{len(unfinished)}活跃会话, CaMeL状态={report['camel_guard']['status']}")


def run_deep_check():
    """深度验证 — 每2小时（含CaMeL完整性）"""
    file_store = FileBasedStateStore()

    checks = {
        "run_state.json": os.path.exists(
            os.path.expanduser("~/.hermes/state/run_state.json")),
        "last_success.json": os.path.exists(
            os.path.expanduser("~/.hermes/state/last_success.json")),
        "camel_guard.py": os.path.exists(CAMEL_GUARD_SCRIPT),
        "camel_guard.log": os.path.exists(CAMEL_LOG),
    }

    all_ok = all(checks.values())
    print(f"[{datetime.now().isoformat()}] "
          f"状态+安全文件完整性: {'通过' if all_ok else '异常'}")
    for name, ok in checks.items():
        print(f"  {name}: {'✓' if ok else '✗'}")

    return all_ok


if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else "check"
    actions = {"check": run_check, "critic": run_critic, "deep_check": run_deep_check}
    
    if action in actions:
        actions[action]()
    else:
        print(f"未知操作: {action}")
