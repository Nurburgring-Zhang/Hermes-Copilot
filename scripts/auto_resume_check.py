#!/usr/bin/env python3
"""
Hermes 唤醒恢复脚本 v1.0
=========================
每次Hermes醒来时自动检查当前活跃任务并恢复。
格林主人最高指令:不可跳过,不可中断。

在SOUL.md §19.1中注册为step4。
"""
import json, sys, os
from pathlib import Path
from datetime import datetime

HERMES = Path("/home/administrator/.hermes")
TASK_FILE = HERMES / "task_current.json"
TRACKER = HERMES / "task_tracker.json"
LOG = HERMES / "logs/auto_resume.log"

def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] ♻️ {msg}"
    print(line)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG, "a") as f:
        f.write(line + "\n")

def main():
    print("=" * 60)
    print("  HERMES 唤醒恢复检查")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    
    # 检查task_current.json
    if not TASK_FILE.exists():
        log("✅ 无活跃任务")
        print("STATUS=NO_ACTIVE_TASK")
        return
    
    try:
        task = json.loads(TASK_FILE.read_text())
    except:
        log("⚠️ task_current.json 损坏,跳过")
        print("STATUS=CORRUPTED")
        return
    
    task_id = task.get("task_id", "?")
    status = task.get("status", "?")
    
    if status == "completed":
        log(f"✅ 任务 {task_id} 已完成")
        print("STATUS=COMPLETED")
        return
    
    # 计算未完成步骤
    steps = task.get("steps", {})
    total = len(steps)
    done = sum(1 for s in steps.values() if s.get("status") == "completed")
    pending = total - done
    
    log(f"⚠️ 任务 {task_id} 未完成: {done}/{total} 已完成, {pending} 待完成")
    log(f"   下一步: {task.get('next_action', '?')}")
    
    # 列出未完成步骤
    for name, step in steps.items():
        status_icon = "✅" if step.get("status") == "completed" else "⏳"
        log(f"  {status_icon} {name}: {step.get('note', '?')}")
    
    print(f"STATUS=INCOMPLETE:{done}/{total}")
    print(f"NEXT_ACTION={task.get('next_action', '?')}")
    return task

if __name__ == "__main__":
    task = main()
    sys.exit(0 if task is None or task.get("status") == "completed" else 1)
