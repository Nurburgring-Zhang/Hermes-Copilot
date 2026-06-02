#!/usr/bin/env python3
"""
Hermes 上下文守卫 (Context Guardian) v1.0
=========================================
三重保障:会话崩溃自动恢复 + 审计结果写文件 + 断点续跑

每次对话醒来时自动执行:检查中断 → 读审计快照 → 从断点继续
所有审计过程数据写入文件,对话只传控制指令和最终结果。
"""
import json, os, sqlite3, sys, hashlib
from datetime import datetime, timezone, timedelta
from pathlib import Path

HERMES = Path("/home/administrator/.hermes")
STATE_DB = HERMES / "state.db"
INTEL_DB = HERMES / "intelligence.db"
MEMORY_DB = HERMES / "active_memory.db"
TZ = timezone(timedelta(hours=8))
now = lambda: datetime.now(TZ)

# ===== G4互审: 验证G3的检查点文件完整性 =====
_gear_signed = False

def _gear_sign(task_id="auto", claim_detail="") -> dict:
    """向G0齿轮注册中心签到"""
    try:
        import subprocess as sp
        r = sp.run([sys.executable, str(HERMES / "scripts/gear_vault.py"), "sign",
                    "G4", task_id, json.dumps({"action": "snapshot", "detail": claim_detail})],
                   capture_output=True, timeout=10, text=True)
        return {"signed": True, "output": r.stdout[:200]}
    except Exception as e:
        return {"signed": False, "error": str(e)}

def _verify_g3_checkpoints() -> dict:
    """G4验证G3(gear_context_compressor)的检查点文件时效性"""
    result = {"verified": True, "checks": []}
    for name, path_str in [("task_current", "task_current.json"), 
                          ("gear_checkpoint", "reports/gear_checkpoint.json")]:
        path = HERMES / path_str
        if not path.exists():
            result["checks"].append(f"{name}: 文件不存在")
            result["verified"] = False
            continue
        try:
            data = json.loads(path.read_text())
            ts_str = data.get("ts", "")
            if ts_str:
                ts = datetime.fromisoformat(ts_str)
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=TZ)
                diff = now() - ts
                hours = diff.total_seconds() / 3600
                result["checks"].append(f"{name}: {hours:.1f}h前更新")
                if hours > 24:
                    result["verified"] = False
                    result["checks"][-1] += " (陈旧)"
        except Exception as e:
            result["checks"].append(f"{name}: 读取失败 {e}")
            result["verified"] = False
    return result

# ============ 保险一:审计结果写文件 ============
AUDIT_SNAPSHOT = HERMES / "reports" / "audit_snapshot.json"
TASK_FILE = HERMES / "task_current.json"
TRACKER_FILE = HERMES / "task_tracker.json"

def take_snapshot():
    """保险1:把数据库全量状态拍到文件中,对话中不传输原始数据"""
    snap = {
        "ts": datetime.now().isoformat(),
        "intel": {},
        "memory": {},
        "state": {}
    }
    try:
        db = sqlite3.connect(str(INTEL_DB))
        snap["intel"] = {
            "raw": db.execute("SELECT COUNT(*) FROM raw_intelligence").fetchone()[0],
            "clean": db.execute("SELECT COUNT(*) FROM cleaned_intelligence").fetchone()[0],
            "push": db.execute("SELECT COUNT(*) FROM push_records").fetchone()[0],
            "push_today": db.execute("SELECT COUNT(*) FROM push_records WHERE push_time>=datetime('now','-1 day','localtime')").fetchone()[0],
            "push_fail": db.execute("SELECT COUNT(*) FROM push_records WHERE push_status='failed'").fetchone()[0],
            "last_raw": str(db.execute("SELECT MAX(collected_at) FROM raw_intelligence").fetchone()[0] or ""),
            "last_push": str(db.execute("SELECT MAX(push_time) FROM push_records").fetchone()[0] or ""),
            "empty_raw": db.execute("SELECT COUNT(*) FROM raw_intelligence WHERE content IS NULL OR content=''").fetchone()[0],
            "empty_clean": db.execute("SELECT COUNT(*) FROM cleaned_intelligence WHERE content IS NULL OR content=''").fetchone()[0],
            "empty_push": db.execute("SELECT COUNT(*) FROM push_records WHERE content IS NULL OR content='' OR content='(无内容)'").fetchone()[0],
            "unscored": db.execute("SELECT COUNT(*) FROM cleaned_intelligence WHERE ai_score_total=0").fetchone()[0],
            "dup": db.execute("SELECT COUNT(*) FROM (SELECT title FROM cleaned_intelligence GROUP BY title HAVING COUNT(*)>1)").fetchone()[0],
            "score_max": db.execute("SELECT MAX(ai_score_total) FROM cleaned_intelligence").fetchone()[0],
            "score_avg": round(db.execute("SELECT AVG(ai_score_total) FROM cleaned_intelligence").fetchone()[0] or 0, 1),
            "sources": db.execute("SELECT COUNT(DISTINCT source) FROM raw_intelligence").fetchone()[0],
        }
        db.close()
    except Exception as e:
        snap["intel"]["error"] = str(e)

    try:
        db = sqlite3.connect(str(MEMORY_DB))
        snap["memory"] = {
            "entries": db.execute("SELECT COUNT(*) FROM memory_entries").fetchone()[0],
            "episodic": db.execute("SELECT COUNT(*) FROM memory_episodic").fetchone()[0],
            "semantic": db.execute("SELECT COUNT(*) FROM memory_semantic").fetchone()[0],
            "procedural": db.execute("SELECT COUNT(*) FROM memory_procedural").fetchone()[0],
            "reflexive": db.execute("SELECT COUNT(*) FROM memory_reflexive").fetchone()[0],
            "vectors": db.execute("SELECT COUNT(*) FROM memory_vectors").fetchone()[0],
            "keywords": db.execute("SELECT COUNT(*) FROM keyword_weights").fetchone()[0],
        }
        db.close()
    except: pass

    HERMES.joinpath("reports").mkdir(exist_ok=True)
    with open(AUDIT_SNAPSHOT, "w") as f:
        json.dump(snap, f, indent=2)

def mark_task(task_id, status, detail="", round_="", next_action="", done=[]):
    """保险2:记录任务状态,中断后恢复用"""
    data = {
        "task_id": task_id,
        "status": status,  # running / interrupted / completed
        "detail": detail[:200],
        "round": round_,
        "next_action": next_action,
        "done": done,
        "updated_at": datetime.now().isoformat()
    }
    with open(TASK_FILE, "w") as f:
        json.dump(data, f, indent=2)

def get_resume_point():
    """保险3:读取中断点,返回从哪里继续"""
    if not TASK_FILE.exists():
        return None
    with open(TASK_FILE) as f:
        data = json.load(f)
    if data.get("status") in ("interrupted", "running"):
        return data
    return None


# ============ 保险二:自动恢复钩子 ============
# 这个函数在每次Hermes醒来时被调用(通过cron每5分钟+SOUL.md§19)
# 它输出高度精炼的恢复指令,不会撑爆上下文

def resume_check(verbose=False):
    """输出恢复信息到stdout——简短,精确,不会撑爆上下文"""
    # 检查中断任务
    task = get_resume_point()
    if task:
        print(f"[RESUME] ⚠️ task={task['task_id']} status={task['status']} round={task.get('round','')}")
        print(f"[RESUME] 📋 {task.get('detail','')[:100]}")
        print(f"[RESUME] ➡️ next={task.get('next_action','')}")
        print(f"[RESUME] ✅ done={len(task.get('done',[]))}项")
        return task
    
    # 没有中断任务:只输出快照摘要
    if AUDIT_SNAPSHOT.exists():
        with open(AUDIT_SNAPSHOT) as f:
            snap = json.load(f)
        intel = snap.get("intel", {})
        mem = snap.get("memory", {})
        ok = all(intel.get(k,0)==0 for k in ["empty_raw","empty_clean","empty_push","unscored","dup"])
        print(f"[HEALTHY] 📡 raw={intel.get('raw','?')} clean={intel.get('clean','?')} push={intel.get('push','?')}")
        print(f"[HEALTHY] ✅ content={intel.get('empty_raw',0)}/{intel.get('empty_clean',0)}/{intel.get('empty_push',0)} score={intel.get('unscored',0)} dup={intel.get('dup',0)}")
        print(f"[HEALTHY] 🧠 epi={mem.get('episodic','?')} sem={mem.get('semantic','?')} pro={mem.get('procedural','?')} ref={mem.get('reflexive','?')}")
    else:
        print("[FIRST] 首次运行,无快照")
    
    return None

# ============ 保险三:cron心跳 + 自动快照 ============

def heartbeat():
    """写入心跳,供外部监控检查Hermes是否存活"""
    hb = HERMES / "logs" / "context_guardian_heartbeat.txt"
    hb.parent.mkdir(parents=True, exist_ok=True)
    hb.write_text(datetime.now().isoformat())

def full_cycle():
    """完整运行一次:拍照+心跳+恢复检查+G0互审"""
    heartbeat()
    take_snapshot()
    
    # ===== G0互审 =====
    global _gear_signed
    if not _gear_signed:
        v = _verify_g3_checkpoints()
        _gear_sign("context_guardian_cron", f"g3_ok={v.get('verified')} checks={len(v.get('checks',[]))}")
        _gear_signed = True
        print(f"[GUARDIAN-G4] G3检查点验证: {'✅' if v.get('verified') else '❌'}")
        for c in v.get("checks", []):
            print(f"[GUARDIAN-G4]   {c}")
    
    task = get_resume_point()
    if task and task.get("status") == "interrupted":
        print(f"[GUARDIAN] ⚠️ 有中断任务等待恢复: {task['task_id']}")
        print(f"[GUARDIAN] ➡️ 读取 {AUDIT_SNAPSHOT} 获取完整快照")
    return task


# ============ 主入口 ============

if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else "check"
    
    if action == "check":
        resume_check(verbose=True)
    elif action == "snapshot":
        take_snapshot()
        print(f"✅ 快照已保存 -> {AUDIT_SNAPSHOT}")
    elif action == "mark":
        # mark <task_id> <status> [detail]
        task_id = sys.argv[2] if len(sys.argv) > 2 else "unknown"
        status = sys.argv[3] if len(sys.argv) > 3 else "running"
        detail = sys.argv[4] if len(sys.argv) > 4 else ""
        mark_task(task_id, status, detail)
        print(f"✅ 任务已标记: {task_id}={status}")
    elif action == "cycle":
        full_cycle()
    else:
        print(f"用法: {sys.argv[0]} [check|snapshot|mark|cycle]")
