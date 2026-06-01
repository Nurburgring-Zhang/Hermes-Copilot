#!/usr/bin/env python3
"""
Hermes 检查点记录器 — 保存任务段断点，支持中断恢复
=====================================================
LLM在每段任务完成后调用:
  python3 ~/.hermes/scripts/checkpoint_recorder.py save "<段名>" "<进度描述>"

中断恢复时读取:
  python3 ~/.hermes/scripts/checkpoint_recorder.py status

全量历史:
  python3 ~/.hermes/scripts/checkpoint_recorder.py history

清除:
  python3 ~/.hermes/scripts/checkpoint_recorder.py clear
"""

import json, sys
from pathlib import Path
from datetime import datetime

HERMES = Path("/home/administrator/.hermes")
CHECKPOINT_FILE = HERMES / "reports" / "task_checkpoints.json"


def load():
    if CHECKPOINT_FILE.exists():
        try:
            return json.loads(CHECKPOINT_FILE.read_text())
        except:
            pass
    return {"current_task": None, "checkpoints": [], "completed_segments": []}


def save(segment_name: str, description: str):
    data = load()
    now = datetime.now().isoformat()
    cp = {
        "ts": now,
        "segment": segment_name,
        "description": description,
    }
    data["checkpoints"].append(cp)
    data["current_task"] = segment_name
    data["completed_segments"].append(segment_name)
    # 最多保留50个检查点
    if len(data["checkpoints"]) > 50:
        data["checkpoints"] = data["checkpoints"][-50:]
    CHECKPOINT_FILE.parent.mkdir(parents=True, exist_ok=True)
    CHECKPOINT_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    print(f"[CHECKPOINT] ✅ 保存段: {segment_name}")
    print(f"  描述: {description}")
    print(f"  时间: {now}")
    print(f"  已完成段: {len(data['completed_segments'])}/{sum(1 for c in data['checkpoints'])}")


def status():
    data = load()
    if not data["checkpoints"]:
        print("[CHECKPOINT] ⚠️ 无检查点记录")
        return
    last = data["checkpoints"][-1]
    print(f"[CHECKPOINT] 当前状态")
    print(f"  当前段: {data['current_task'] or '无'}")
    print(f"  最后检查点: {last['segment']} ({last['ts']})")
    print(f"  已完成段数: {len(data['completed_segments'])}")
    print(f"  所有已完成段: {', '.join(data['completed_segments']) if data['completed_segments'] else '无'}")
    print(f"  最后描述: {last['description']}")


def history():
    data = load()
    if not data["checkpoints"]:
        print("[CHECKPOINT] 无检查点历史")
        return
    print(f"[CHECKPOINT] 全量检查点历史 ({len(data['checkpoints'])}条)")
    for i, cp in enumerate(data["checkpoints"]):
        print(f"  {i+1}. [{cp['ts']}] {cp['segment']}: {cp['description']}")


def clear():
    CHECKPOINT_FILE.write_text(json.dumps({"current_task": None, "checkpoints": [], "completed_segments": []}, ensure_ascii=False, indent=2))
    print("[CHECKPOINT] ✅ 已清除所有检查点")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "save":
        seg = sys.argv[2] if len(sys.argv) > 2 else "unknown"
        desc = sys.argv[3] if len(sys.argv) > 3 else ""
        save(seg, desc)
    elif cmd == "status":
        status()
    elif cmd == "history":
        history()
    elif cmd == "clear":
        clear()
    else:
        print(f"用法: python3 checkpoint_recorder.py [save|status|history|clear]")
