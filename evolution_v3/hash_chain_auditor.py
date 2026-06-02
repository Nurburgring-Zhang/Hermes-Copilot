"""
⚙️ 链式哈希审计系统 V1.0 — 不可篡改的操作审计日志
================================================================
对应 OI§32: 链式哈希结构 + §5.4: 哈希链完整性

每条日志包含:
  - SHA-256(上一条日志) → 形成链式结构
  - 操作类型/时间/结果
  - 可验证的完整性证明
"""

import json, os, sys, hashlib, time
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, List

HERMES = Path.home() / ".hermes"
TZ = timezone(timedelta(hours=8))
NOW = lambda: datetime.now(TZ)


class HashChainAuditor:
    """
    链式哈希审计器 — 对应OI第五层安全
    
    结构:
      log_entry = {
        "index": int,           # 序号
        "ts": str,              # 时间戳
        "action": str,          # 操作类型
        "detail": str,          # 操作详情
        "prev_hash": str,       # SHA-256(上一条日志)
        "hash": str,            # SHA-256(本条日志)
        "actor": str,           # 执行者
        "category": str,        # 分类(system/security/memory/task)
        "result": str,          # 结果
      }
    
    完整性验证:
      任意第三方可通过计算hash链验证日志未被篡改
    """

    def __init__(self, log_path: Optional[Path] = None):
        self.log_path = log_path or (HERMES / "reports" / "hash_chain_audit.json")
        self.log_path.parent.mkdir(exist_ok=True)
        self._chain: List[dict] = []
        self._load_chain()

    def _load_chain(self):
        """加载现有日志链"""
        if self.log_path.exists():
            try:
                data = json.loads(self.log_path.read_text())
                if isinstance(data, list):
                    self._chain = data
            except Exception:
                pass

    def _save_chain(self):
        """保存日志链"""
        self.log_path.write_text(json.dumps(self._chain, ensure_ascii=False, indent=2))

    def _compute_hash(self, entry: dict) -> str:
        """计算单条日志的SHA-256哈希"""
        # 排除hash字段自身防止循环
        entry_copy = {k: v for k, v in entry.items() if k != "hash"}
        content = json.dumps(entry_copy, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(content.encode()).hexdigest()

    def log(self, action: str, detail: str = "", actor: str = "system",
            category: str = "system", result: str = "ok") -> dict:
        """
        写入审计日志(自动链式哈希)
        
        示例:
          auditor.log("task.create", "创建任务#123", actor="hermes", category="task")
        """
        index = len(self._chain)
        prev_hash = self._chain[-1]["hash"] if self._chain else "0" * 64
        
        entry = {
            "index": index,
            "ts": NOW().isoformat(),
            "action": action,
            "detail": detail[:500],
            "prev_hash": prev_hash,
            "hash": "",  # 占位,在compute_hash前移除
            "actor": actor,
            "category": category,
            "result": result,
        }
        
        # 计算哈希(不含hash字段)
        entry_hash = self._compute_hash(entry)
        entry["hash"] = entry_hash
        
        self._chain.append(entry)
        self._save_chain()
        
        # 保持链长度合理(最近10000条)
        if len(self._chain) > 10000:
            self._chain = self._chain[-10000:]
            self._save_chain()
        
        return entry

    def verify_chain(self) -> dict:
        """
        验证整条哈希链的完整性
        
        对每条日志:
          1. 验证其hash字段是否与计算一致
          2. 验证其prev_hash是否等于上一条的hash
        """
        errors = []
        verified = 0
        
        for i, entry in enumerate(self._chain):
            # 验证自身哈希
            computed_hash = self._compute_hash(entry)
            if computed_hash != entry.get("hash", ""):
                errors.append(f"索引{i}: 哈希不匹配")
                continue
            
            # 验证链式连接
            if i > 0:
                prev_entry = self._chain[i - 1]
                if entry.get("prev_hash", "") != prev_entry.get("hash", ""):
                    errors.append(f"索引{i}: 链断裂(prev_hash不匹配上一条的hash)")
                    continue
            
            verified += 1
        
        return {
            "ts": NOW().isoformat(),
            "total_entries": len(self._chain),
            "verified": verified,
            "errors": len(errors),
            "chain_integrity": "ok" if len(errors) == 0 else "broken",
            "error_details": errors[:10],  # 只显示前10个错误
        }

    def query(self, action_filter: Optional[str] = None,
              category_filter: Optional[str] = None,
              limit: int = 100) -> List[dict]:
        """查询审计日志"""
        results = self._chain
        
        if action_filter:
            results = [e for e in results if action_filter in e.get("action", "")]
        if category_filter:
            results = [e for e in results if e.get("category") == category_filter]
        
        return results[-limit:]

    def summary(self) -> dict:
        """审计摘要"""
        if not self._chain:
            return {"total": 0, "by_category": {}, "by_result": {}}
        
        by_category = {}
        by_result = {}
        for entry in self._chain:
            cat = entry.get("category", "unknown")
            by_category[cat] = by_category.get(cat, 0) + 1
            
            res = entry.get("result", "unknown")
            by_result[res] = by_result.get(res, 0) + 1
        
        return {
            "ts": NOW().isoformat(),
            "total": len(self._chain),
            "first_entry": self._chain[0]["ts"],
            "last_entry": self._chain[-1]["ts"],
            "by_category": by_category,
            "by_result": by_result,
            "integrity": self.verify_chain()["chain_integrity"],
        }


# ===== 单例 =====
_auditor_instance: Optional[HashChainAuditor] = None


def get_auditor() -> HashChainAuditor:
    global _auditor_instance
    if _auditor_instance is None:
        _auditor_instance = HashChainAuditor()
    return _auditor_instance


if __name__ == "__main__":
    auditor = get_auditor()
    
    cmd = sys.argv[1] if len(sys.argv) > 1 else "summary"
    
    if cmd == "log":
        action = sys.argv[2] if len(sys.argv) > 2 else "test"
        detail = sys.argv[3] if len(sys.argv) > 3 else ""
        result = auditor.log(action, detail)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    
    elif cmd == "verify":
        print(json.dumps(auditor.verify_chain(), ensure_ascii=False, indent=2))
    
    elif cmd == "query":
        action_f = sys.argv[2] if len(sys.argv) > 2 else None
        cat_f = sys.argv[3] if len(sys.argv) > 3 else None
        results = auditor.query(action_f, cat_f)
        print(json.dumps(results, ensure_ascii=False, indent=2))
    
    else:
        print(json.dumps(auditor.summary(), ensure_ascii=False, indent=2))
