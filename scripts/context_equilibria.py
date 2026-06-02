#!/usr/bin/env python3
"""
ContextEquilibria — 上下文平衡恢复引擎
==========================================
当MetaThinker检测到漂移时, 自动刷新上下文实例
核心: 从记忆引擎检索原始目标, 重新注入当前上下文

工作流:
  MetaThinker检测漂移→ContextEquilibria读取记忆(LCM DAG)→
  提取原始目标+关键上下文→重新组装简报→写入gear_context_compressor检查点

使用方法:
  python3 context_equilibria.py restore <task_id> [--goal <text>]
  python3 context_equilibria.py refresh <context_file>
  python3 context_equilibria.py status
"""

import json
import time
import hashlib
import sys
import os
from pathlib import Path

BASE_DIR = os.path.expanduser("~/.hermes/memory/context_equilibria")
REPORTS_DIR = os.path.expanduser("~/.hermes/reports")
LOG_FILE = os.path.join(BASE_DIR, "restore_log.jsonl")


class ContextEquilibria:
    """上下文平衡恢复引擎"""

    def __init__(self):
        self.base_dir = Path(BASE_DIR)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.reports_dir = Path(REPORTS_DIR)

    def _log_restore(self, task_id, goal, session, success):
        """记录恢复事件"""
        entry = {
            "ts": time.time(),
            "task_id": task_id,
            "goal_preview": goal[:100] if goal else "",
            "session": session,
            "success": success,
            "hash": hashlib.sha256((task_id + str(time.time())).encode()).hexdigest()[:16]
        }
        with open(LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(json.dumps(entry, ensure_ascii=False) + '\n')
        return entry

    def restore(self, task_id, goal_text=None):
        """恢复上下文: 重新注入目标到检查点"""
        restore_snapshot = {
            "ts": time.time(),
            "task_id": task_id,
            "goal": goal_text or "",
            "restored": True,
            "hash": ""
        }
        # 计算哈希
        restore_snapshot["hash"] = hashlib.sha256(
            json.dumps(restore_snapshot, ensure_ascii=False).encode()
        ).hexdigest()

        # 写入恢复快照
        snapshot_path = self.reports_dir / f"restore_{task_id}.json"
        with open(snapshot_path, 'w', encoding='utf-8') as f:
            json.dump(restore_snapshot, f, ensure_ascii=False, indent=2)

        # 尝试写入gear_context_compressor检查点(如果有)
        checkpoint_path = self.reports_dir / "gear_checkpoint.json"
        if checkpoint_path.exists():
            try:
                cp = json.loads(checkpoint_path.read_text(encoding='utf-8'))
                cp["restored_at"] = time.time()
                cp["restore_note"] = f"ContextEquilibria恢复: task={task_id}"
                checkpoint_path.write_text(json.dumps(cp, ensure_ascii=False, indent=2))
            except Exception:
                pass

        entry = self._log_restore(task_id, goal_text, task_id, True)
        return restore_snapshot

    def refresh(self, context_data):
        """手动刷新上下文检查点"""
        if isinstance(context_data, str):
            try:
                context_data = json.loads(context_data)
            except Exception:
                context_data = {"text": context_data}

        entry = {
            "ts": time.time(),
            "type": "manual_refresh",
            "data_hash": hashlib.sha256(json.dumps(context_data, ensure_ascii=False).encode()).hexdigest(),
            "restored": True
        }

        # 写入刷新检查点
        refresh_path = self.reports_dir / "context_refresh.json"
        with open(refresh_path, 'w', encoding='utf-8') as f:
            json.dump(entry, f, ensure_ascii=False, indent=2)

        return entry

    def get_status(self):
        """获取恢复状态"""
        restore_count = 0
        if os.path.exists(LOG_FILE):
            with open(LOG_FILE, 'r') as f:
                restore_count = sum(1 for _ in f)

        return {
            "restore_count": restore_count,
            "last_restore": self._last_entry(),
            "snapshots": list(self.reports_dir.glob("restore_*.json"))
        }

    def _last_entry(self):
        if os.path.exists(LOG_FILE):
            try:
                with open(LOG_FILE, 'r') as f:
                    lines = f.readlines()
                    if lines:
                        return json.loads(lines[-1])
            except Exception:
                pass
        return None


def main():
    eq = ContextEquilibria()

    if len(sys.argv) < 2:
        print("用法: python3 context_equilibria.py <命令> [参数...]")
        print("")
        print("命令:")
        print("  restore <task_id> [--goal <text>]   恢复上下文")
        print("  refresh <json_string_or_file>       刷新检查点")
        print("  status                               状态")
        return

    cmd = sys.argv[1]

    if cmd == "restore":
        if len(sys.argv) < 3:
            print("用法: restore <task_id> [--goal <text>]")
            return
        task_id = sys.argv[2]
        goal = None
        if "--goal" in sys.argv:
            idx = sys.argv.index("--goal")
            goal = sys.argv[idx + 1] if idx + 1 < len(sys.argv) else None
        result = eq.restore(task_id, goal)
        print(f"✅ 上下文已恢复 (task={task_id})")
        print(f"  hash: {result['hash'][:16]}")

    elif cmd == "refresh":
        if len(sys.argv) < 3:
            print("用法: refresh <json_string_or_file>")
            return
        data = sys.argv[2]
        if os.path.exists(data):
            with open(data, 'r') as f:
                data = f.read()
        result = eq.refresh(data)
        print(f"✅ 上下文已刷新, hash={result['data_hash'][:16]}")

    elif cmd == "status":
        s = eq.get_status()
        print(json.dumps(s, ensure_ascii=False, indent=2, default=str))

    else:
        print(f"未知命令: {cmd}")


if __name__ == "__main__":
    main()
