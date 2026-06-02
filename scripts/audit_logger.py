#!/usr/bin/env python3
"""
AuditLogger — Hermes全系统审计日志引擎 v1.0
==============================================
所有记忆查询/写入/加密/任务执行/漂移检测操作统一审计
SHA-256哈希链 + JSONL格式 + 每天自动摘要

设计:
  - 所有子系统写入统一审计日志
  - 每条记录带时间戳+SHA-256哈希+来源标识
  - 每日自动生成审计摘要报告
  - 支持可追溯的Merkle风格的哈希链

使用方法:
  python3 audit_logger.py write <event_type> <detail>
  python3 audit_logger.py summary [--hours N]
  python3 audit_logger.py search <keyword>
  python3 audit_logger.py status
"""

import json
import time
import hashlib
import sys
import os
from pathlib import Path
from datetime import datetime, timedelta

# ============ 配置 ============
AUDIT_DIR = os.path.expanduser("~/.hermes/logs/audit")
AUDIT_FILE = os.path.join(AUDIT_DIR, "audit_trail.jsonl")
DAILY_DIR = os.path.join(AUDIT_DIR, "daily")
CHAIN_FILE = os.path.join(AUDIT_DIR, "hash_chain.json")


class AuditLogger:
    """系统审计日志引擎 — 哈希链式审计"""

    def __init__(self):
        self.audit_dir = Path(AUDIT_DIR)
        self.daily_dir = Path(DAILY_DIR)
        self.audit_dir.mkdir(parents=True, exist_ok=True)
        self.daily_dir.mkdir(parents=True, exist_ok=True)
        self.chain_file = Path(CHAIN_FILE)
        self.chain = self._load_chain()

    def _load_chain(self):
        """加载哈希链"""
        if self.chain_file.exists():
            try:
                return json.loads(self.chain_file.read_text())
            except Exception:
                pass
        return {"chain": [], "last_hash": hashlib.sha256(b"genesis").hexdigest()}

    def _save_chain(self):
        """保存哈希链"""
        with open(self.chain_file, 'w') as f:
            json.dump(self.chain, f, ensure_ascii=False, indent=2)

    def _compute_entry_hash(self, entry):
        """计算审计条目的SHA-256哈希"""
        h = hashlib.sha256()
        h.update(json.dumps(entry, ensure_ascii=False, sort_keys=True).encode())
        return h.hexdigest()

    def write(self, event_type, detail, source="unknown", level="info"):
        """写入审计日志条目"""
        entry = {
            "ts": time.time(),
            "type": event_type,
            "detail": str(detail)[:1000],
            "source": source,
            "level": level,
            "prev_hash": self.chain["last_hash"]
        }

        # 计算自己的哈希
        entry_hash = self._compute_entry_hash(entry)
        entry["hash"] = entry_hash

        # 更新链
        self.chain["last_hash"] = entry_hash
        self.chain["chain"].append({
            "ts": entry["ts"],
            "type": event_type,
            "hash": entry_hash
        })

        # 限制链长度, 保留最近10000条
        if len(self.chain["chain"]) > 10000:
            self.chain["chain"] = self.chain["chain"][-10000:]

        # 写入日志文件
        with open(AUDIT_FILE, 'a', encoding='utf-8') as f:
            f.write(json.dumps(entry, ensure_ascii=False) + '\n')

        self._save_chain()
        return entry_hash

    def get_recent(self, hours=24, limit=100):
        """获取最近N小时的审计日志"""
        cutoff = time.time() - hours * 3600
        entries = []
        if not os.path.exists(AUDIT_FILE):
            return entries
        with open(AUDIT_FILE, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    entry = json.loads(line)
                    if entry["ts"] >= cutoff:
                        entries.append(entry)
                except Exception:
                    continue
        return entries[-limit:]

    def search(self, keyword):
        """搜索审计日志"""
        results = []
        if not os.path.exists(AUDIT_FILE):
            return results
        with open(AUDIT_FILE, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    entry = json.loads(line)
                    if keyword.lower() in json.dumps(entry, ensure_ascii=False).lower():
                        results.append(entry)
                except Exception:
                    continue
        return results

    def generate_daily_summary(self):
        """生成每日审计摘要"""
        today = datetime.now().strftime("%Y-%m-%d")
        entries = self.get_recent(hours=24)
        
        # 统计
        type_count = {}
        level_count = {}
        sources = set()
        for e in entries:
            t = e.get("type", "unknown")
            type_count[t] = type_count.get(t, 0) + 1
            l = e.get("level", "info")
            level_count[l] = level_count.get(l, 0) + 1
            sources.add(e.get("source", "unknown"))

        summary = {
            "date": today,
            "total_entries": len(entries),
            "type_breakdown": type_count,
            "level_breakdown": level_count,
            "sources": list(sources),
            "chain_head": self.chain["last_hash"][:32],
            "generated_at": time.time()
        }

        # 写入每日摘要
        summary_file = self.daily_dir / f"audit_summary_{today}.json"
        with open(summary_file, 'w', encoding='utf-8') as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)

        return summary

    def verify_chain(self):
        """验证审计链完整性"""
        if not os.path.exists(AUDIT_FILE):
            return {"ok": True, "entries": 0}

        prev_hash = hashlib.sha256(b"genesis").hexdigest()
        verified = 0
        violations = []

        with open(AUDIT_FILE, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    entry = json.loads(line)
                    stored_hash = entry.get("hash", "")
                    stored_prev = entry.get("prev_hash", "")

                    # 验证prev_hash链
                    if stored_prev != prev_hash:
                        violations.append({
                            "line": verified + 1,
                            "type": "chain_break",
                            "expected_prev": prev_hash[:16],
                            "actual_prev": stored_prev[:16]
                        })

                    # 验证自身哈希
                    entry_copy = dict(entry)
                    entry_copy.pop("hash", None)
                    computed = self._compute_entry_hash(entry_copy)
                    if computed != stored_hash:
                        violations.append({
                            "line": verified + 1,
                            "type": "hash_mismatch",
                            "computed": computed[:16],
                            "stored": stored_hash[:16]
                        })

                    prev_hash = stored_hash
                    verified += 1
                except Exception:
                    violations.append({"line": verified + 1, "type": "parse_error"})

        return {
            "ok": len(violations) == 0,
            "entries_verified": verified,
            "violations": violations,
            "violation_count": len(violations)
        }

    def get_status(self):
        """获取系统状态"""
        total = 0
        if os.path.exists(AUDIT_FILE):
            with open(AUDIT_FILE, 'r') as f:
                total = sum(1 for _ in f)

        return {
            "total_entries": total,
            "chain_length": len(self.chain["chain"]),
            "chain_head": self.chain["last_hash"][:32],
            "log_file_size_mb": os.path.getsize(AUDIT_FILE) / (1024*1024) if os.path.exists(AUDIT_FILE) else 0,
            "daily_summaries": len(list(self.daily_dir.glob("*.json")))
        }


# ============ CLI ============

def main():
    logger = AuditLogger()

    if len(sys.argv) < 2:
        print("用法: python3 audit_logger.py <命令> [参数...]")
        print("")
        print("命令:")
        print("  write <type> <detail> [--source <s>] [--level info|warn|error]")
        print("  summary [--hours N]")
        print("  search <keyword>")
        print("  verify")
        print("  status")
        return

    cmd = sys.argv[1]

    if cmd == "write":
        if len(sys.argv) < 4:
            print("用法: write <type> <detail> [--source <s>]")
            return
        event_type = sys.argv[2]
        detail = sys.argv[3]
        source = "cli"
        level = "info"
        if "--source" in sys.argv:
            source = sys.argv[sys.argv.index("--source") + 1]
        if "--level" in sys.argv:
            level = sys.argv[sys.argv.index("--level") + 1]
        h = logger.write(event_type, detail, source, level)
        print(f"✅ 已记录: hash={h[:16]}")

    elif cmd == "summary":
        hours = 24
        if "--hours" in sys.argv:
            hours = int(sys.argv[sys.argv.index("--hours") + 1])
        entries = logger.get_recent(hours=hours)
        
        type_count = {}
        for e in entries:
            t = e.get("type", "unknown")
            type_count[t] = type_count.get(t, 0) + 1

        print(f"近{hours}小时审计日志:")
        print(f"  总计: {len(entries)} 条")
        print(f"  类型分布:")
        for t, c in sorted(type_count.items(), key=lambda x: -x[1]):
            print(f"    {t}: {c}")

    elif cmd == "search":
        if len(sys.argv) < 3:
            print("用法: search <keyword>")
            return
        results = logger.search(sys.argv[2])
        print(f"找到 {len(results)} 条匹配记录:")
        for r in results[:20]:
            ts = datetime.fromtimestamp(r["ts"])
            print(f"  [{ts.strftime('%H:%M:%S')}] {r['type']}: {r['detail'][:100]}")

    elif cmd == "verify":
        result = logger.verify_chain()
        if result["ok"]:
            print(f"✅ 审计链完整: {result['entries_verified']}条全部通过")
        else:
            print(f"❌ 审计链有 {result['violation_count']} 处损坏!")
            for v in result["violations"][:10]:
                print(f"  line {v['line']}: {v.get('type', 'unknown')}")

    elif cmd == "status":
        s = logger.get_status()
        print(json.dumps(s, ensure_ascii=False, indent=2))

    else:
        print(f"未知命令: {cmd}")


if __name__ == "__main__":
    main()
