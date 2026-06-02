#!/usr/bin/env python3
"""
recall_injector.py — 自动召回注入守护进程 (用于 cron 调度)
======================================================================
每轮对话开始前，从 active_memory.db 检索相关记忆并写入 wake_guide.json
这样 Hermes 在下一轮对话启动时自动读到这些记忆

对应 Hy-Memory: before-prompt-build 中的 recall 行为

用法：
  python3 scripts/recall_injector.py [user_input_text]
  
  如果不传参数，读取最新的 user_input 并自动注入
"""

import json
import sys
import time
from pathlib import Path

REPORTS_DIR = Path.home() / ".hermes" / "reports"
SCRIPTS_DIR = Path.home() / ".hermes" / "scripts"
INJECTION_FILE = REPORTS_DIR / "auto_recall_injection.json"

sys.path.insert(0, str(SCRIPTS_DIR))
from auto_recall import AutoRecall


def inject_recall(user_text: str = "") -> dict:
    """
    执行召回注入，结果写入文件
    
    返回注入的描述信息
    """
    recaller = AutoRecall()
    
    if not user_text:
        # 读取最新的 wake_guide 中的用户消息（如果有）
        wake_guide = REPORTS_DIR / "wake_guide.json"
        if wake_guide.exists():
            try:
                data = json.loads(wake_guide.read_text())
                user_text = data.get("last_user_message", "")
            except (json.JSONDecodeError, KeyError):
                user_text = ""
    
    # 执行召回 + 获取人物画像
    recall = recaller.recall_for_session(user_text) if user_text else ""
    persona = recaller.get_persona_context()
    
    # 构建注入数据
    injection = {
        "timestamp": time.time(),
        "user_input": user_text,
        "recall_memories": recall,
        "persona_context": persona,
        "has_recall": bool(recall),
        "has_persona": bool(persona),
    }
    
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    INJECTION_FILE.write_text(
        json.dumps(injection, ensure_ascii=False, indent=2),
        encoding='utf-8'
    )
    
    return injection


if __name__ == "__main__":
    user_text = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else ""
    result = inject_recall(user_text)
    print(f"Recall injection: {'✅' if result['has_recall'] else '⏳'} "
          f"Persona: {'✅' if result['has_persona'] else '⏳'}")
    if result['has_recall']:
        print("---")
        print(result['recall_memories'])
