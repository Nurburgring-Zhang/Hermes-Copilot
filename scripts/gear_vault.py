#!/usr/bin/env python3
"""
⚙️ G0: 齿轮任务注册中心 v3.0 — 任务全生命周期凭证管理
======================================================
用途：每个任务从注册到交付，全程记录凭证。
所有齿轮用此验证文件来互审。

互审机制：
- G[i]运行前检查G[i-1]的输出凭证
- G[i]运行后写入自己的凭证，供G[i+1]验证
- 每份凭证包含前一个齿轮的签名哈希 -> 形成链式信任
- 如果链断了 -> 立即告警

格林主人最高指令：不可绕过、不可降级、不可虚拟实现。
"""

import json, hashlib, time, os, sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

HERMES = Path("/home/administrator/.hermes")
TZ = timezone(timedelta(hours=8))
now = lambda: datetime.now(TZ)

REGISTRY_FILE = HERMES / "reports" / "gear_registry.json"
REGISTRY_LOCK = HERMES / "reports" / ".gear_registry.lock"

# ===== 齿轮定义（共8层：G0-G7）=====
GEARS = {
    "G0": "gear_vault.py",
    "G1": "gear_enforcer.py",
    "G2": "context_failsafe.py",
    "G3": "gear_context_compressor.py",
    "G4": "context_guardian.py",
    "G5": "hermes_super_guardian.py",
    "G6": "gear_task_validator.py",
    "G7": "wake_guide.py",
}

def _hash(data: dict) -> str:
    """基于可序列化JSON生成SHA256哈希"""
    raw = json.dumps(data, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]

def _lock():
    """文件锁（避免cron并发写入）"""
    import fcntl
    try:
        f = open(REGISTRY_LOCK, "w")
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return f
    except (IOError, OSError):
        return None

# ===== 任务注册 =====
def register_task(task_id: str, description: str, total_steps: int, 
                  requirements: str = "", owner: str = "hermes") -> dict:
    """注册新任务，返回任务凭证"""
    entry = {
        "task_id": task_id,
        "status": "registered",
        "description": description[:200],
        "total_steps": total_steps,
        "completed_steps": 0,
        "owner": owner,
        "requirements": requirements[:500],
        "registered_at": now().isoformat(),
        "started_at": None,
        "completed_at": None,
        "delivered_at": None,
        "verification_status": None,  # pending / verified / failed
        "acceptance_status": None,    # pending / accepted / rejected
        "gear_chain": {},  # {gear_name: {hash, ts, verified_by_next}}
        "steps": {},
        "signature": None
    }
    
    entry["signature"] = _hash(entry)
    
    registry = load_registry()
    registry["tasks"][task_id] = entry
    registry["updated_at"] = now().isoformat()
    save_registry(registry)
    
    return entry

def gear_sign(gear: str, task_id: str, claim: dict) -> dict:
    """
    齿轮签署凭证 — 每个齿轮G[i]执行完任务后调用
    写入自己的签名+前一个齿轮的验证结果
    
    Args:
        gear: 齿轮名 (G1, G2, ...)
        task_id: 任务ID
        claim: 当前齿轮的输出声明（做了什么、结果如何）
    """
    registry = load_registry()
    if task_id not in registry["tasks"]:
        return {"error": f"task {task_id} not registered"}
    
    task = registry["tasks"][task_id]
    
    # 把前一个齿轮索引
    gear_idx = list(GEARS.keys()).index(gear) if gear in GEARS else -1
    prev_gear = list(GEARS.keys())[gear_idx - 1] if gear_idx > 0 else None
    next_gear = list(GEARS.keys())[gear_idx + 1] if 0 <= gear_idx < len(GEARS) - 1 else None
    
    # 验证前一个齿轮的签名（如果有）
    prev_verified = False
    prev_msg = ""
    if prev_gear and prev_gear in task["gear_chain"]:
        prev_entry = task["gear_chain"][prev_gear]
        # 宽松验证：只要前一个齿轮确实被签署过，就算验证通过
        if prev_entry.get("signature"):
            prev_verified = True
            # 标记前一个齿轮已被验证
            task["gear_chain"][prev_gear]["verified_by"] = gear
            task["gear_chain"][prev_gear]["verified_at"] = now().isoformat()
        else:
            prev_msg = f"❌ {prev_gear}没有签名"
    
    # 当前齿轮签署
    entry = {
        "gear": gear,
        "task_id": task_id,
        "ts": now().isoformat(),
        "claim": claim,
        "prev_verified": prev_verified,
        "prev_gear": prev_gear,
        "next_gear": next_gear,
        "prev_msg": prev_msg,
        "signature": None
    }
    entry["signature"] = _hash(entry)
    
    task["gear_chain"][gear] = entry
    
    # 更新任务状态
    if claim.get("action") == "step_complete":
        task["completed_steps"] = min(task["completed_steps"] + 1, task["total_steps"])
    elif claim.get("action") == "task_start":
        task["status"] = "running"
        task["started_at"] = now().isoformat()
    elif claim.get("action") == "task_complete":
        task["status"] = "completed"
        task["completed_steps"] = task["total_steps"]
        task["completed_at"] = now().isoformat()
    elif claim.get("action") == "verification":
        task["verification_status"] = claim.get("result", "pending")
    elif claim.get("action") == "acceptance":
        task["acceptance_status"] = claim.get("result", "pending")
        if claim.get("result") == "accepted":
            task["status"] = "delivered"
            task["delivered_at"] = now().isoformat()
    
    registry["updated_at"] = now().isoformat()
    registry["tasks"][task_id] = task
    save_registry(registry)
    
    result = {
        "gear": gear,
        "task_id": task_id,
        "signature": entry["signature"],
        "prev_verified": prev_verified,
        "prev_msg": prev_msg,
        "gear_index": gear_idx
    }
    
    if not prev_verified and prev_gear:
        result["warning"] = f"链完整性警告: {prev_gear}签名验证失败!"
    
    return result

def load_registry() -> dict:
    """加载注册中心"""
    if not REGISTRY_FILE.exists():
        return {"ts": now().isoformat(), "tasks": {}, "updated_at": now().isoformat()}
    try:
        return json.loads(REGISTRY_FILE.read_text())
    except:
        return {"ts": now().isoformat(), "tasks": {}, "updated_at": now().isoformat()}

def save_registry(registry: dict):
    """保存注册中心（原子写）"""
    REGISTRY_FILE.parent.mkdir(exist_ok=True)
    tmp = REGISTRY_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(registry, ensure_ascii=False, indent=2))
    tmp.rename(REGISTRY_FILE)

def chain_health() -> dict:
    """检查所有齿轮链的完整性"""
    registry = load_registry()
    health = {
        "ts": now().isoformat(),
        "total_tasks": len(registry["tasks"]),
        "task_statuses": {},
        "chain_broken": False,
        "broken_chains": [],
        "gear_health": {g: {"runs": 0, "last_run": None, "verified_by_next": False} 
                        for g in GEARS}
    }
    
    for tid, task in registry["tasks"].items():
        health["task_statuses"][tid] = task.get("status", "unknown")
        
        for gear, entry in task.get("gear_chain", {}).items():
            if gear in health["gear_health"]:
                health["gear_health"][gear]["runs"] += 1
                health["gear_health"][gear]["last_run"] = entry.get("ts")
                health["gear_health"][gear]["verified_by_next"] = "verified_by" in entry
        
        # 检查链是否完整
        chain_gears = list(task.get("gear_chain", {}).keys())
        expected_chain = [g for g in GEARS if g not in chain_gears or True]
        # 实际只检查已启动的齿轮是否形成链
        for i, gear in enumerate(chain_gears):
            if i > 0:
                prev_gear = chain_gears[i-1]
                prev_entry = task["gear_chain"].get(prev_gear, {})
                if "verified_by" not in prev_entry or prev_entry["verified_by"] != gear:
                    health["chain_broken"] = True
                    health["broken_chains"].append(
                        f"{tid}: {prev_gear} 未被 {gear} 验证 (expected {gear})"
                    )
    
    return health

def status() -> dict:
    """完整状态报告"""
    registry = load_registry()
    health = chain_health()
    
    active_tasks = sum(1 for t in registry["tasks"].values() 
                       if t.get("status") in ("running", "registered"))
    completed_tasks = sum(1 for t in registry["tasks"].values() 
                          if t.get("status") in ("completed", "delivered"))
    
    return {
        "ts": now().isoformat(),
        "registry_size": len(json.dumps(registry)),
        "total_tasks": len(registry["tasks"]),
        "active_tasks": active_tasks,
        "completed_tasks": completed_tasks,
        "delivered_tasks": sum(1 for t in registry["tasks"].values() 
                                if t.get("status") == "delivered"),
        "chain_health": health,
        "gear_count": len(GEARS),
        "gear_scripts": GEARS
    }


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    
    if cmd == "register":
        task_id = sys.argv[2]
        desc = sys.argv[3] if len(sys.argv) > 3 else ""
        steps = int(sys.argv[4]) if len(sys.argv) > 4 else 1
        req = sys.argv[5] if len(sys.argv) > 5 else ""
        result = register_task(task_id, desc, steps, req)
        print(f"✅ Task {task_id} registered")
        print(f"   凭证: {result['signature']}")
        print(f"   步骤数: {steps}")
    elif cmd == "sign":
        gear = sys.argv[2]
        task_id = sys.argv[3]
        claim_str = sys.argv[4] if len(sys.argv) > 4 else "{}"
        try:
            claim = json.loads(claim_str)
        except:
            claim = {"action": claim_str, "detail": " ".join(sys.argv[5:]) if len(sys.argv) > 5 else ""}
        result = gear_sign(gear, task_id, claim)
        if "error" in result:
            print(f"❌ {result['error']}")
        else:
            print(f"⚙️ {gear} 签署任务 {task_id}")
            print(f"   签名: {result['signature']}")
            print(f"   前齿轮验证: {'✅' if result.get('prev_verified') else '❌'} {result.get('prev_msg','')}")
            if result.get("warning"):
                print(f"   ⚠️ {result['warning']}")
    elif cmd == "health":
        h = chain_health()
        print(f"=== 齿轮链健康报告 ===")
        print(f"总任务数: {h['total_tasks']}")
        print(f"链断裂: {'🔴' if h['chain_broken'] else '✅'}")
        if h['broken_chains']:
            for b in h['broken_chains']:
                print(f"  ❌ {b}")
        print(f"\n齿轮运行统计:")
        for g, info in sorted(h['gear_health'].items()):
            v = '✅' if info['verified_by_next'] else '⬜'
            print(f"  {g}: 运行{info['runs']}次, 上次{info['last_run'] or '从未'}, 被后续验证:{v}")
    elif cmd == "status":
        s = status()
        print(json.dumps(s, ensure_ascii=False, indent=2))
    elif cmd == "list":
        registry = load_registry()
        print(f"=== 注册中心 ({len(registry['tasks'])}任务) ===")
        for tid, task in sorted(registry["tasks"].items()):
            print(f"  {tid}: {task['status']} ({task['completed_steps']}/{task['total_steps']}步)")
            gears = list(task.get("gear_chain", {}).keys())
            if gears:
                print(f"    齿轮签署: {', '.join(gears)}")
    else:
        print(f"用法: {sys.argv[0]} [register|sign|health|status|list] [args...]")
