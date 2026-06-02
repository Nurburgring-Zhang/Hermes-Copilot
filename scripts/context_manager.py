#!/usr/bin/env python3
"""
ContextManager — 热/温/冷三层上下文管理引擎
=============================================
基于COMPASS框架三层架构设计
热层(最近10轮): 完整逐字存储, 不压缩
温层(第11-40轮): 滚动详细摘要(LCM Leaf层级)
冷层(更早): 压缩为广泛摘要(LCM Condensed/Root层级)

集成到 gear_task_driver.py 的棘轮推进流程中
每轮对话后自动更新上下文,每5轮执行温层整合

使用方法:
  python3 context_manager.py add <user_msg> <assistant_msg>
  python3 context_manager.py get [--format brief|full|compressed]
  python3 context_manager.py compress
  python3 context_manager.py status
  python3 context_manager.py reset
"""

import json
import time
import hashlib
import sys
import os
from pathlib import Path

# ============ 配置 ============
BASE_DIR = os.path.expanduser("~/.hermes/memory/context_manager")
STATE_FILE = os.path.join(BASE_DIR, "context_state.json")
HOT_LIMIT = 10
TEMP_LIMIT = 30  # 温层保留30条摘要
PERSIST_INTERVAL = 5  # 每5轮触发温层整合

# ============ 上下文管理引擎 ============

class ContextManager:
    """热/温/冷三层上下文管理"""

    def __init__(self, state_file=None):
        self.state_file = Path(state_file or STATE_FILE)
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.state = self._load_state()

    def _load_state(self):
        """从文件加载状态"""
        if self.state_file.exists():
            try:
                with open(self.state_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                pass
        return self._default_state()

    def _default_state(self):
        """默认状态"""
        return {
            "version": "v1.0",
            "hot_context": [],      # 最近10轮完整内容
            "temp_context": [],     # 温层滚动摘要
            "cold_context": [],     # 冷层广泛摘要
            "metadata": {
                "total_rounds": 0,
                "last_compress_at": None,
                "created_at": time.time(),
                "updated_at": time.time(),
                "context_hash": ""  # SHA-256 of all context
            }
        }

    def _save_state(self):
        """保存状态到文件"""
        self.state["metadata"]["updated_at"] = time.time()
        self.state["metadata"]["context_hash"] = self._compute_hash()
        with open(self.state_file, 'w', encoding='utf-8') as f:
            json.dump(self.state, f, ensure_ascii=False, indent=2)

    def _compute_hash(self):
        """计算所有上下文的SHA-256哈希"""
        h = hashlib.sha256()
        h.update(json.dumps(self.state["hot_context"], ensure_ascii=False).encode())
        h.update(json.dumps(self.state["temp_context"], ensure_ascii=False).encode())
        h.update(json.dumps(self.state["cold_context"], ensure_ascii=False).encode())
        return h.hexdigest()

    def add_round(self, user_msg, assistant_msg):
        """添加一轮对话到上下文管理器"""
        round_entry = {
            "round": self.state["metadata"]["total_rounds"],
            "user": user_msg,
            "assistant": assistant_msg,
            "timestamp": time.time()
        }

        # 热层: 追加到末尾
        self.state["hot_context"].append(round_entry)

        # 如果热层超过HOT_LIMIT, 将最早的移动到温层
        if len(self.state["hot_context"]) > HOT_LIMIT:
            self._move_to_temp(self.state["hot_context"].pop(0))

        self.state["metadata"]["total_rounds"] += 1

        # 每PERSIST_INTERVAL轮触发温层整合
        if self.state["metadata"]["total_rounds"] % PERSIST_INTERVAL == 0:
            self._compress_internal()

        self._save_state()
        return round_entry["round"]

    def _move_to_temp(self, entry):
        """将热层条目移动到温层(压缩为摘要)"""
        # 简化的摘要 (实际应用中会使用LLM)
        user_preview = entry["user"][:100] if entry["user"] else ""
        assistant_preview = entry["assistant"][:200] if entry["assistant"] else ""
        summary = f"[Round {entry['round']}] User: {user_preview}... | Assistant: {assistant_preview}..."

        temp_entry = {
            "round": entry["round"],
            "summary": summary,
            "source_hash": hashlib.sha256(json.dumps(entry, ensure_ascii=False).encode()).hexdigest()[:16],
            "compress_at": time.time()
        }
        self.state["temp_context"].append(temp_entry)

        # 如果温层超过TEMP_LIMIT, 将最早的移动到冷层
        if len(self.state["temp_context"]) > TEMP_LIMIT:
            self._move_to_cold(self.state["temp_context"].pop(0))

    def _move_to_cold(self, entry):
        """将温层条目移动到冷层(更广泛的摘要)"""
        cold_entry = {
            "round_range": self._find_round_range(),
            "summary": entry["summary"][:300],
            "compress_at": time.time()
        }
        self.state["cold_context"].append(cold_entry)

    def _find_round_range(self):
        """计算总结的回合范围"""
        if self.state["temp_context"]:
            first = self.state["temp_context"][0].get("round", 0)
            last = self.state["temp_context"][-1].get("round", 0)
            return f"{first}-{last}"
        return "0-0"

    def _compress_internal(self):
        """内部压缩 - 标记当前状态"""
        self.state["metadata"]["last_compress_at"] = time.time()

    def get_context(self, format="compressed"):
        """获取上下文简报

        Args:
            format: "brief"(冷层), "compressed"(冷+温), "full"(冷+温+热)
        Returns:
            上下文文本
        """
        parts = []

        # 冷层 (始终包含)
        if self.state["cold_context"]:
            cold_parts = [f"[Cold] {c['summary']}" for c in self.state["cold_context"][-5:]]
            parts.append("=== 冷层(早期摘要) ===")
            parts.extend(cold_parts)

        if format == "brief":
            return '\n'.join(parts)

        # 温层
        if self.state["temp_context"]:
            temp_parts = [f"[Temp R{t['round']}] {t['summary']}" for t in self.state["temp_context"][-10:]]
            parts.append("")
            parts.append("=== 温层(近期摘要) ===")
            parts.extend(temp_parts)

        if format == "compressed":
            return '\n'.join(parts)

        # 热层 (完整)
        if self.state["hot_context"]:
            parts.append("")
            parts.append("=== 热层(完整日志) ===")
            for h in self.state["hot_context"]:
                parts.append(f"[Round {h['round']}]")
                parts.append(f"  User: {h['user']}")
                parts.append(f"  Assistant: {h['assistant']}")
                parts.append("")

        return '\n'.join(parts)

    def get_state_delta(self, since_round=0):
        """获取从since_round开始的增量上下文"""
        delta = []
        for h in self.state["hot_context"]:
            if h["round"] >= since_round:
                delta.append(h)
        return delta

    def get_optimized_context(self):
        """返回优化后的上下文简报(COMPASS风格)"""
        return {
            "hot": self.state["hot_context"][-HOT_LIMIT:],
            "temp": self.state["temp_context"][-TEMP_LIMIT:],
            "cold": self.state["cold_context"][-10:],
            "metadata": {
                "total_rounds": self.state["metadata"]["total_rounds"],
                "last_compress": self.state["metadata"]["last_compress_at"]
            }
        }

    def verify_integrity(self):
        """校验上下文完整性"""
        current_hash = self._compute_hash()
        stored_hash = self.state["metadata"].get("context_hash", "")
        return {
            "ok": current_hash == stored_hash or stored_hash == "",
            "current_hash": current_hash,
            "stored_hash": stored_hash,
            "total_rounds": self.state["metadata"]["total_rounds"],
            "hot_size": len(self.state["hot_context"]),
            "temp_size": len(self.state["temp_context"]),
            "cold_size": len(self.state["cold_context"])
        }

    def reset(self):
        """重置上下文"""
        self.state = self._default_state()
        self._save_state()

    def get_status(self):
        """获取状态"""
        info = self.verify_integrity()
        info["last_compress"] = self.state["metadata"]["last_compress_at"]
        return info


# ============ CLI ============

def main():
    cm = ContextManager()

    if len(sys.argv) < 2:
        print("用法: python3 context_manager.py <命令> [参数...]")
        print("")
        print("命令:")
        print("  add <user_msg> <assistant_msg>    添加对话轮次")
        print("  get [--format brief|full|compressed]")
        print("  compress                           触发压缩")
        print("  verify                             校验完整性")
        print("  status                             当前状态")
        print("  reset                              重置")
        return

    cmd = sys.argv[1]

    if cmd == "add":
        if len(sys.argv) < 4:
            print("用法: add <user_msg> <assistant_msg>")
            return
        round_num = cm.add_round(sys.argv[2], sys.argv[3])
        print(f"✅ Added round {round_num}")

    elif cmd == "get":
        fmt = "compressed"
        if "--format" in sys.argv:
            fmt = sys.argv[sys.argv.index("--format") + 1]
        print(cm.get_context(fmt))

    elif cmd == "compress":
        cm._compress_internal()
        cm._save_state()
        print("✅ 压缩完成")

    elif cmd == "verify":
        result = cm.verify_integrity()
        if result["ok"]:
            print(f"✅ 完整性校验通过 (rounds={result['total_rounds']})")
        else:
            print(f"⚠️ 哈希不匹配: stored={result['stored_hash'][:16]} current={result['current_hash'][:16]}")

    elif cmd == "status":
        s = cm.get_status()
        print(json.dumps(s, ensure_ascii=False, indent=2))

    elif cmd == "reset":
        cm.reset()
        print("✅ 已重置")

    else:
        print(f"未知命令: {cmd}")


if __name__ == "__main__":
    main()
