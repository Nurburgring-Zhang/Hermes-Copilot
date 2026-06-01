#!/usr/bin/env python3
"""
🔥 上下文防摔保险 v1.0 — 物理强制层
===================================
作用：在对话层（Hermes自己的逻辑）之外建立一道物理强制墙。
不管Hermes记不记得做压缩，这个脚本每5分钟运行一次，
把当前所有断点文件合并成一个完整的"恢复包"。

三层防护：
1. 每5分钟 → 合并 task_current + gear_checkpoint + audit_snapshot → recovery_pack.json
2. 每次醒来时检查 recovery_pack.json，如果有未完成任务直接恢复
3. 如果所有断点文件都被删了，还能从 recovery_pack.json 恢复

这就是物理防线——不依赖Hermes记得执行任何事。
"""
import json, os, sys, time, shutil
from datetime import datetime, timezone, timedelta
from pathlib import Path

HERMES = Path("/home/administrator/.hermes")
TZ = timezone(timedelta(hours=8))
now = lambda: datetime.now(TZ)

RECOVERY_PACK = HERMES / "reports" / "recovery_pack.json"
RECOVERY_HISTORY = HERMES / "reports" / "recovery_history.log"

# ===== G2互审: 验证G1的心跳和印章 =====
_prev_verified = False

def _verify_g1_heartbeat() -> dict:
    """G2验证G1(gear_enforcer)是否在正常运行——检查心跳新鲜度"""
    hb = HERMES / "logs" / "gear_heartbeat.txt"
    if not hb.exists():
        return {"verified": False, "error": "G1心跳文件不存在"}
    try:
        hb_time = datetime.fromisoformat(hb.read_text().strip())
        diff = now() - hb_time.replace(tzinfo=TZ)
        minutes = diff.total_seconds() / 60
        if minutes > 3:
            return {"verified": False, "warning": f"G1心跳已{minutes:.0f}分钟未更新(>3分钟)", "minutes": minutes}
        return {"verified": True, "minutes_since": minutes}
    except Exception as e:
        return {"verified": False, "error": str(e)}

def _gear_sign(task_id="auto", claim_detail="") -> dict:
    """G0签到"""
    try:
        import subprocess as sp
        r = sp.run([sys.executable, str(HERMES / "scripts/gear_vault.py"), "sign", 
                    "G2", task_id, json.dumps({"action": "recovery_pack", "detail": claim_detail})],
                   capture_output=True, timeout=10, text=True)
        return {"signed": True, "output": r.stdout[:200]}
    except Exception as e:
        return {"signed": False, "error": str(e)}

def _hash_file(path) -> str:
    """文件哈希——用于完整性校验"""
    import hashlib
    if not Path(path).exists():
        return "NONE"
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:16]

def _integrity_check() -> dict:
    """完整性校验：检查关键文件是否被篡改"""
    files = {
        "task_current": HERMES / "task_current.json",
        "gear_checkpoint": HERMES / "reports" / "gear_checkpoint.json",
        "audit_snapshot": HERMES / "reports" / "audit_snapshot.json",
    }
    hashes = {}
    for name, path in files.items():
        hashes[name] = _hash_file(str(path)) if path.exists() else "MISSING"
    
    # 验证gear_checkpoint和task_current的一致性
    consistency = "unknown"
    try:
        tc = json.loads((HERMES / "task_current.json").read_text())
        gc = json.loads((HERMES / "reports/gear_checkpoint.json").read_text())
        tc_id = tc.get("task_id", "")
        gc_id = gc.get("task_id", "")
        if tc_id == gc_id or not tc_id or not gc_id:
            consistency = "consistent"
        else:
            consistency = f"MISMATCH: tc={tc_id} vs gc={gc_id}"
    except:
        consistency = "check_error"
    
    return {"hashes": hashes, "consistency": consistency}

# ===== 互审结束 =====

def build_recovery_pack():
    """收集所有断点文件，合并成恢复包"""
    pack = {
        "ts": now().isoformat(),
        "task_current": None,
        "gear_checkpoint": None,
        "audit_snapshot": None,
        "gear_heartbeat": None,
        "deadline": None,
        "status": "healthy"
    }
    
    # task_current.json
    tc = HERMES / "task_current.json"
    if tc.exists():
        try:
            data = json.loads(tc.read_text())
            pack["task_current"] = data
            if data.get("status") in ("running", "interrupted"):
                pack["status"] = "interrupted"
        except: pass
    
    # gear_checkpoint.json
    gc = HERMES / "reports" / "gear_checkpoint.json"
    if gc.exists():
        try:
            data = json.loads(gc.read_text())
            pack["gear_checkpoint"] = data
            if data.get("status") == "running" and pack["status"] == "healthy":
                pack["status"] = "interrupted"
        except: pass
    
    # audit_snapshot.json
    au = HERMES / "reports" / "audit_snapshot.json"
    if au.exists():
        try:
            pack["audit_snapshot"] = json.loads(au.read_text())
        except: pass
    
    # gear_heartbeat
    hb = HERMES / "logs" / "gear_heartbeat.txt"
    if hb.exists():
        pack["gear_heartbeat"] = hb.read_text().strip()
        # 检查心跳是否过期
        try:
            hb_time = datetime.fromisoformat(pack["gear_heartbeat"])
            minutes = (now() - hb_time.replace(tzinfo=TZ)).total_seconds() / 60
            if minutes > 10:
                pack["status"] = "stale_heartbeat"
        except: pass
    
    # 写入恢复包
    RECOVERY_PACK.write_text(json.dumps(pack, ensure_ascii=False, indent=2))
    
    return pack

def check_recovery():
    """检查恢复包，输出恢复指令"""
    if not RECOVERY_PACK.exists():
        return "FIRST_RUN"
    
    try:
        pack = json.loads(RECOVERY_PACK.read_text())
    except:
        return "CORRUPTED"
    
    if pack.get("status") == "interrupted":
        tc = pack.get("task_current") or {}
        gc = pack.get("gear_checkpoint") or {}
        task_id = gc.get("task_id") or tc.get("task_id") or "?"
        next_action = gc.get("next_action") or tc.get("next_action") or "?"
        detail = gc.get("detail") or tc.get("detail") or ""
        
        return {
            "status": "interrupted",
            "task_id": task_id,
            "next_action": next_action,
            "detail": detail,
            "ts": pack["ts"]
        }
    
    return "HEALTHY"

def maintain():
    """主维护函数+G0互审签到"""
    pack = build_recovery_pack()
    
    # ===== G2互审:验证G1心跳+文件完整性 =====
    v = _verify_g1_heartbeat()
    ic = _integrity_check()
    pack["_g1_heartbeat_check"] = v
    pack["_integrity_check"] = ic
    
    _gear_sign("context_failsafe_cron", f"status={pack['status']} g1_ok={v.get('verified')}")
    
    # 如果G1心跳异常,写入告警
    if not v.get("verified"):
        alert = HERMES / "reports" / "G1_HEARTBEAT_ALERT.json"
        alert.write_text(json.dumps({
            "ts": now().isoformat(),
            "gear": "G2",
            "alert": f"G1心跳验证失败: {v.get('warning', v.get('error', 'unknown'))}",
            "recovery": "检查gear_enforcer.py cron是否运行: crontab -l | grep gear_enforcer"
        }, ensure_ascii=False, indent=2))
        pack["_alert_written"] = True
    
    
    # 记录历史
    with open(RECOVERY_HISTORY, "a") as f:
        f.write(f"[{now().isoformat()}] status={pack['status']} | tc={pack['task_current'] is not None} gc={pack['gear_checkpoint'] is not None}\n")
    
    # 只保留最近100行历史
    if RECOVERY_HISTORY.exists():
        lines = RECOVERY_HISTORY.read_text().splitlines()
        if len(lines) > 100:
            RECOVERY_HISTORY.write_text("\n".join(lines[-100:]) + "\n")
    
    return pack

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "maintain"
    
    if cmd == "maintain":
        pack = maintain()
        print(f"RECOVERY_PACK updated: status={pack['status']}")
    elif cmd == "check":
        result = check_recovery()
        if isinstance(result, dict):
            print(f"⚠️ INTERRUPTED: task={result['task_id']} next={result['next_action']}")
            print(f"   detail: {result['detail']}")
            print(f"   ts: {result['ts']}")
            print("   → python3 ~/.hermes/scripts/gear_context_compressor.py resume_guide")
        else:
            print(f"✅ {result}")
    elif cmd == "inject":
        # 从外部注入任务状态（由Hermes对话中调用）
        task_id = sys.argv[2] if len(sys.argv) > 2 else "?"
        status = sys.argv[3] if len(sys.argv) > 3 else "running"
        next_action = sys.argv[4] if len(sys.argv) > 4 else ""
        detail = " ".join(sys.argv[5:]) if len(sys.argv) > 5 else ""
        
        # 写入task_current
        data = {"task_id": task_id, "status": status, "next_action": next_action, "detail": detail, "ts": now().isoformat()}
        (HERMES / "task_current.json").write_text(json.dumps(data, ensure_ascii=False, indent=2))
        
        # 也写入gear_checkpoint
        (HERMES / "reports/gear_checkpoint.json").write_text(json.dumps(data, ensure_ascii=False, indent=2))
        
        # 立即构建恢复包
        maintain()
        print(f"✅ 任务状态已注入: {task_id} -> {status}")
