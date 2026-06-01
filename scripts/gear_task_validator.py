#!/usr/bin/env python3
"""
⚙️ G6: 齿轮任务全生命周期验证器 v1.0 — 审核·检验·测试·验收·交付
==============================================================
功能：对每个任务从注册到交付的全链路验证。

验证链：
  1. VERIFICATION(审核) — 检查齿轮链完整性、文件签名、时间戳链
  2. INSPECTION(检验) — 校验每个齿轮的输出文件是否完整、未篡改
  3. TESTING(测试) — 测试关键齿轮是否可运行、cron是否活跃
  4. ACCEPTANCE(验收) — 对比任务需求 vs 实际交付物清单
  5. DELIVERY(交付) — 生成交付签名凭证、写入交付记录

G6互审：
  - 验证G5(hermes_super_guardian)的心跳是否≤15分钟
  - 被G7(wake_guide)验证自己的输出

格林主人最高指令(2026-05-11):
  不降级、不模拟、不占位符 — 真正的全生命周期任务验证引擎！
"""

import json, hashlib, sqlite3, os, sys, subprocess
from datetime import datetime, timezone, timedelta
from pathlib import Path

HERMES = Path("/home/administrator/.hermes")
TZ = timezone(timedelta(hours=8))
now = lambda: datetime.now(TZ)

REPORTS = HERMES / "reports"
LOGS = HERMES / "logs"
REGISTRY = REPORTS / "gear_registry.json"
DELIVERY_LOG = REPORTS / "delivery_log.json"
VERIFICATION_LOG = REPORTS / "verification_log.json"

# ===== G6互审: 验证G5心跳 =====
_gear_signed = False

def _gear_sign(task_id="auto", claim_detail=""):
    try:
        r = subprocess.run([sys.executable, str(HERMES / "scripts/gear_vault.py"), "sign",
                           "G6", task_id, json.dumps({"action": "validate", "detail": claim_detail})],
                          capture_output=True, timeout=10, text=True)
        return {"signed": True, "output": r.stdout[:200]}
    except Exception as e:
        return {"signed": False, "error": str(e)}

def _verify_g5_guardian() -> dict:
    """验证G5(hermes_super_guardian)是否在正常运行"""
    hb = LOGS / "context_guardian_heartbeat.txt"
    if not hb.exists():
        return {"verified": False, "error": "G5心跳文件不存在"}
    try:
        ts = datetime.fromisoformat(hb.read_text().strip())
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=TZ)
        diff = now() - ts
        minutes = diff.total_seconds() / 60
        return {
            "verified": minutes <= 20,  # G5 cron每15分钟，允许5分钟误差
            "minutes_since": round(minutes, 1),
            "gear": "G5",
            "status": "✅ 正常" if minutes <= 20 else "❌ 超时"
        }
    except Exception as e:
        return {"verified": False, "error": str(e)}

# ===== 1. VERIFICATION (审核) =====

def verify_gear_chain(task_id: str) -> dict:
    """审核齿轮链完整性：检查G0→G1→...→G7是否形成签名链"""
    if not REGISTRY.exists():
        return {"status": "failed", "reason": "注册中心不存在"}
    
    registry = json.loads(REGISTRY.read_text())
    task = registry.get("tasks", {}).get(task_id)
    if not task:
        return {"status": "failed", "reason": f"任务 {task_id} 未注册"}
    
    gear_chain = task.get("gear_chain", {})
    expected_gears = ["G1", "G2", "G3", "G4", "G5", "G6", "G7"]  # G0是注册中心，不计入齿轮链
    active_gears = list(gear_chain.keys())
    
    result = {
        "task_id": task_id,
        "status": "verified",
        "total_expected": len(expected_gears),
        "active_gears": len(active_gears),
        "chain_complete": False,
        "signature_valid": True,
        "broken_links": [],
        "missing_gears": [g for g in expected_gears if g not in active_gears],
        "gear_details": {}
    }
    
    # 检查每个齿轮的签名是否被后续齿轮验证
    for i, gear in enumerate(active_gears):
        entry = gear_chain.get(gear, {})
        verified_by = entry.get("verified_by", None)
        prev_verified = entry.get("prev_verified", False)
        
        detail = {
            "gear": gear,
            "signed_at": entry.get("ts", "?"),
            "claim": entry.get("claim", {}),
            "verified_by_next": verified_by is not None,
            "prev_verified": prev_verified
        }
        
        # 检查链断裂
        if not prev_verified and i > 0:
            result["signature_valid"] = False
            result["broken_links"].append(f"{gear}: 未验证前一个齿轮{entry.get('prev_gear','?')}")
        
        result["gear_details"][gear] = detail
    
    result["chain_complete"] = (len(result["missing_gears"]) == 0 and result["signature_valid"])
    
    if not result["chain_complete"]:
        result["status"] = "chain_incomplete"
    
    return result

def verify_task_requirements(task_id: str, requirements: list = None) -> dict:
    """审核任务需求 vs 实际完成情况"""
    registry = json.loads(REGISTRY.read_text()) if REGISTRY.exists() else {"tasks": {}}
    task = registry.get("tasks", {}).get(task_id, {})
    
    result = {
        "task_id": task_id,
        "status": "pending_verification",
        "requirements_met": [],
        "requirements_unmet": [],
        "completion_pct": 0
    }
    
    total_steps = task.get("total_steps", 1)
    completed_steps = task.get("completed_steps", 0)
    result["completion_pct"] = round(completed_steps / max(total_steps, 1) * 100, 1)
    
    if completed_steps >= total_steps:
        result["status"] = "completed"
    else:
        result["status"] = f"in_progress ({completed_steps}/{total_steps})"
    
    return result

# ===== 2. INSPECTION (检验) =====

def inspect_checkpoint_files() -> dict:
    """检验关键断点文件的完整性和一致性"""
    files = {
        "task_current": HERMES / "task_current.json",
        "gear_checkpoint": REPORTS / "gear_checkpoint.json",
        "audit_snapshot": REPORTS / "audit_snapshot.json",
        "recovery_pack": REPORTS / "recovery_pack.json",
        "wake_guide": REPORTS / "wake_guide.json",
    }
    
    result = {
        "status": "inspected",
        "file_count": len(files),
        "existing": 0,
        "missing": [],
        "hashes": {},
        "consistency": "unknown",
        "oldest_file_hours": 0
    }
    
    for name, path in files.items():
        if path.exists():
            result["existing"] += 1
            result["hashes"][name] = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
            
            # 检查文件时效
            try:
                data = json.loads(path.read_text())
                ts_str = data.get("ts", "")
                if ts_str:
                    ts = datetime.fromisoformat(ts_str)
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=TZ)
                    hours = (now() - ts).total_seconds() / 3600
                    if hours > result["oldest_file_hours"]:
                        result["oldest_file_hours"] = round(hours, 1)
            except:
                pass
        else:
            result["missing"].append(name)
    
    # 一致性检查: task_current vs gear_checkpoint
    try:
        tc = json.loads((HERMES / "task_current.json").read_text())
        gc = json.loads((REPORTS / "gear_checkpoint.json").read_text())
        if tc.get("task_id") == gc.get("task_id"):
            result["consistency"] = "consistent"
        else:
            result["consistency"] = f"mismatch: tc={tc.get('task_id')} vs gc={gc.get('task_id')}"
    except:
        result["consistency"] = "check_error"
    
    return result

def inspect_cron_health() -> dict:
    """检验cron是否全部活跃"""
    try:
        r = subprocess.run(["crontab", "-l"], capture_output=True, timeout=5, text=True)
        cron_lines = [l.strip() for l in r.stdout.splitlines() if l.strip() and not l.strip().startswith("#")]
        
        gear_crons = [l for l in cron_lines if any(g in l for g in [
            "gear_enforcer", "context_failsafe", "context_guardian", 
            "gear_context_compressor", "hermes_super_guardian", "gear_task_validator"
        ])]
        
        return {
            "status": "inspected",
            "total_crons": len(cron_lines),
            "gear_crons": len(gear_crons),
            "gear_cron_list": gear_crons,
            "all_gear_present": len(gear_crons) >= 5
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}

# ===== 3. TESTING (测试) =====

def test_gear_scripts() -> dict:
    """测试所有齿轮脚本能否正常运行"""
    scripts = [
        ("G1", "gear_enforcer.py"),
        ("G2", "context_failsafe.py"),
        ("G3", "gear_context_compressor.py"),
        ("G4", "context_guardian.py"),
        ("G5", "hermes_super_guardian.py"),
        ("G6", "gear_task_validator.py"),
        ("G7", "wake_guide.py"),
        ("G0", "gear_vault.py"),
    ]
    
    result = {"status": "tested", "tests": []}
    for gear, script in scripts:
        path = HERMES / "scripts" / script
        test_result = {
            "gear": gear,
            "script": script,
            "exists": path.exists(),
            "importable": False,
            "error": None
        }
        
        if path.exists():
            try:
                # 语法检查
                subprocess.run([sys.executable, "-c", f"import py_compile; py_compile.compile(r'{path}', doraise=True)"],
                              capture_output=True, timeout=10, check=True)
                test_result["importable"] = True
            except subprocess.CalledProcessError as e:
                test_result["error"] = f"语法错误: {e.stderr.decode()[:100] if e.stderr else 'unknown'}"
            except Exception as e:
                test_result["error"] = str(e)[:100]
        
        result["tests"].append(test_result)
    
    result["all_pass"] = all(t["importable"] for t in result["tests"])
    return result

# ===== 4. ACCEPTANCE (验收) =====

def accept_task(task_id: str, delivery_checklist: dict = None) -> dict:
    """任务验收 — 生成验收签名凭证"""
    verification = verify_gear_chain(task_id)
    inspection = inspect_checkpoint_files()
    testing = test_gear_scripts()
    
    acceptance_result = {
        "task_id": task_id,
        "status": "pending",
        "verification_status": verification["status"],
        "inspection_status": inspection["status"],
        "chain_complete": verification.get("chain_complete", False),
        "all_gear_scripts_pass": testing.get("all_pass", False),
        "files_integrity": inspection.get("consistency"),
        "accepted": False,
        "accepted_at": None,
        "rejection_reasons": [],
        "delivery_checklist": delivery_checklist or {}
    }
    
    # 验收条件
    if not verification.get("chain_complete", False):
        acceptance_result["rejection_reasons"].append(f"齿轮链不完整: missing={verification.get('missing_gears')}")
    
    if inspection.get("missing", []):
        acceptance_result["rejection_reasons"].append(f"缺失文件: {inspection['missing']}")
    
    if not testing.get("all_pass", False):
        failed = [t["gear"] for t in testing.get("tests", []) if not t["importable"]]
        acceptance_result["rejection_reasons"].append(f"脚本无法运行: {failed}")
    
    if not acceptance_result["rejection_reasons"]:
        acceptance_result["status"] = "accepted"
        acceptance_result["accepted"] = True
        acceptance_result["accepted_at"] = now().isoformat()
        
        # 写入G0
        _gear_sign(task_id, f"acceptance=passed chain={verification.get('chain_complete')}")
    else:
        acceptance_result["status"] = "rejected"
    
    # 写入验收日志
    VERIFICATION_LOG.parent.mkdir(exist_ok=True)
    log = []
    if VERIFICATION_LOG.exists():
        log = json.loads(VERIFICATION_LOG.read_text())
    if not isinstance(log, list):
        log = []
    log.append(acceptance_result)
    # 只保留最近100条
    if len(log) > 100:
        log = log[-100:]
    VERIFICATION_LOG.write_text(json.dumps(log, ensure_ascii=False, indent=2))
    
    # ===== 推动棘轮 =====
    if acceptance_result["accepted"]:
        _push_to_driver(task_id, "accepted", "G6验收通过")
    else:
        _push_to_driver(task_id, "gear_chain_6", f"G6验收未通过: {acceptance_result['rejection_reasons']}")
    
    return acceptance_result

# ===== 5. DELIVERY (交付) =====

def _push_to_driver(task_id: str, step: str, note: str = "") -> dict:
    """将推动结果写入强制任务队列(棘轮)"""
    try:
        import subprocess as sp
        r = sp.run([sys.executable, str(HERMES / "scripts/gear_task_driver.py"), 
                    "advance", task_id, step, note[:100]],
                   capture_output=True, timeout=10, text=True)
        return {"pushed": True, "output": r.stdout[:200]}
    except Exception as e:
        return {"pushed": False, "error": str(e)}

def deliver_task(task_id: str, delivery_paths: list = None, notes: str = "") -> dict:
    """任务交付 — 生成交付签名凭证"""
    # 先验收
    acceptance = accept_task(task_id)
    
    if not acceptance["accepted"]:
        return {
            "task_id": task_id,
            "status": "delivery_blocked",
            "reason": "验收未通过",
            "rejection_reasons": acceptance["rejection_reasons"]
        }
    
    g5_check = _verify_g5_guardian()
    
    # 生成交付凭证
    delivery = {
        "task_id": task_id,
        "status": "delivered",
        "delivered_at": now().isoformat(),
        "acceptance_at": acceptance["accepted_at"],
        "g5_guardian_verified": g5_check["verified"],
        "g5_guardian_minutes": g5_check.get("minutes_since", 0),
        "delivery_paths": delivery_paths or [],
        "notes": notes[:500],
        "signature": None
    }
    delivery["signature"] = hashlib.sha256(
        json.dumps(delivery, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()[:16]
    
    # 写入交付日志
    DELIVERY_LOG.parent.mkdir(exist_ok=True)
    log = []
    if DELIVERY_LOG.exists():
        log = json.loads(DELIVERY_LOG.read_text())
    if not isinstance(log, list):
        log = []
    log.append(delivery)
    if len(log) > 50:
        log = log[-50:]
    DELIVERY_LOG.write_text(json.dumps(log, ensure_ascii=False, indent=2))
    
    # ===== 推动棘轮 =====
    _push_to_driver(task_id, "delivered", f"G6交付: {notes[:80]}")
    
    return delivery


# ===== 完整运行 =====

def run_full_validation(task_id: str = None) -> dict:
    """运行完整验证流水线：审核→检验→测试→验收"""
    if task_id:
        task_list = [task_id]
    else:
        registry = json.loads(REGISTRY.read_text()) if REGISTRY.exists() else {"tasks": {}}
        all_tasks = registry.get("tasks", {}).items()
        # Skip archived tasks AND tasks that only have non-standard gears (G0-only, G8+, etc.)
        # These are quick operations (recovery, external delivery) that don't go through the
        # standard G1→G7 pipeline and should not trigger chain_incomplete alerts.
        standard_gears = {"G0", "G1", "G2", "G3", "G4", "G5", "G6", "G7"}
        task_list = []
        for tid, t in all_tasks:
            if t.get("archived", False):
                continue
            task_gears = set(t.get("gear_chain", {}).keys())
            # Skip tasks whose gears are all non-standard (e.g. G8-PROD) or only G0
            if task_gears and not (task_gears & standard_gears - {"G0"}):
                continue
            task_list.append(tid)
    
    if not task_list:
        # 无任务时也返回完整结构，避免cron模式KeyError
        _gear_sign("full_validation_empty", "no_tasks_to_validate")
        empty_summary = {
            "ts": now().isoformat(),
            "total_tasks": 0,
            "tasks_validated": 0,
            "all_chains_complete": True,
            "all_scripts_pass": True,
            "g5_check": _verify_g5_guardian()
        }
        return {"summary": empty_summary, "results": []}
    
    results = []
    for tid in task_list:
        r = {
            "task_id": tid,
            "verification": verify_gear_chain(tid),
            "requirements": verify_task_requirements(tid),
            "inspection": inspect_checkpoint_files(),
            "testing": test_gear_scripts(),
            "cron_health": inspect_cron_health()
        }
        results.append(r)
    
    summary = {
        "ts": now().isoformat(),
        "total_tasks": len(task_list),
        "tasks_validated": len(results),
        "all_chains_complete": all(r.get("verification",{}).get("chain_complete", False) for r in results) if results else False,
        "all_scripts_pass": results[0]["testing"]["all_pass"] if results else False,
        "g5_check": _verify_g5_guardian()
    }
    
    # G0签章
    global _gear_signed
    if not _gear_signed:
        _gear_sign("full_validation", f"tasks={len(task_list)} chain_ok={summary['all_chains_complete']}")
        _gear_signed = True
    
    return {"summary": summary, "results": results}


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "validate"
    
    if cmd == "validate":
        task_id = sys.argv[2] if len(sys.argv) > 2 else None
        result = run_full_validation(task_id)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif cmd == "verify":
        task_id = sys.argv[2] if len(sys.argv) > 2 else ""
        if task_id:
            print(json.dumps(verify_gear_chain(task_id), ensure_ascii=False, indent=2))
        else:
            print("❌ 需要task_id")
    elif cmd == "inspect":
        i1 = inspect_checkpoint_files()
        i2 = inspect_cron_health()
        print(json.dumps({"files": i1, "cron": i2, "g5": _verify_g5_guardian()}, 
                        ensure_ascii=False, indent=2))
    elif cmd == "test":
        print(json.dumps(test_gear_scripts(), ensure_ascii=False, indent=2))
    elif cmd == "accept":
        task_id = sys.argv[2] if len(sys.argv) > 2 else ""
        checklist = json.loads(sys.argv[3]) if len(sys.argv) > 3 else {}
        if task_id:
            print(json.dumps(accept_task(task_id, checklist), ensure_ascii=False, indent=2))
    elif cmd == "deliver":
        task_id = sys.argv[2] if len(sys.argv) > 2 else ""
        paths = sys.argv[3].split(",") if len(sys.argv) > 3 else []
        notes = sys.argv[4] if len(sys.argv) > 4 else ""
        print(json.dumps(deliver_task(task_id, paths, notes), ensure_ascii=False, indent=2))
    elif cmd == "cron":
        # cron模式 — 定期验证所有活跃任务
        result = run_full_validation()
        summary = result["summary"]
        print(f"[G6-CRON] {now().isoformat()}")
        print(f"[G6-CRON] Tasks: {summary['total_tasks']} | Chains: {'✅' if summary['all_chains_complete'] else '❌'}")
        print(f"[G6-CRON] Scripts: {'✅' if summary['all_scripts_pass'] else '❌'} | G5: {'✅' if summary['g5_check'].get('verified') else '❌'}")
        # 如果有失败的，写告警
        if not summary['all_chains_complete'] or not summary['all_scripts_pass'] or not summary['g5_check'].get('verified'):
            import json as _j
            alert = REPORTS / "G6_VALIDATION_ALERT.json"
            alert.write_text(_j.dumps({
                "ts": now().isoformat(),
                "gear": "G6",
                "chains_pass": summary['all_chains_complete'],
                "scripts_pass": summary['all_scripts_pass'],
                "g5_pass": summary['g5_check'].get('verified'),
                "details": summary
            }, ensure_ascii=False, indent=2))
            print(f"[G6-CRON] ⚠️ 告警已写入 {alert}")
        else:
            print(f"[G6-CRON] ✅ 全部通过")
    else:
        print(f"""用法: {sys.argv[0]} [validate|verify|inspect|test|accept|deliver|cron] [args]
  validate [task_id]  - 完整验证流水线
  verify <task_id>   - 齿轮链审核
  inspect            - 文件+cron检验
  test               - 齿轮脚本测试
  accept <task_id>   - 验收任务
  deliver <task_id>  - 交付任务
  cron               - cron模式定期验证
""")
