#!/usr/bin/env python3
"""
HERMES 任务断点续跑系统 (Task Resumer) v1.1
===========================================
修复:上下文溢出恢复机制。所有审计报告写到文件,醒来时读文件而不是重新查询全部数据。

每次Hermes醒来自动执行(通过cron 每5分钟 + 会话启动时):
1. 检查 task_current.json -> 如果有中断任务,输出恢复指令
2. 读取上次审计快照 -> 不需要重新查询
3. 输出最小化的恢复信息到stdout(主脚本引用来决定做什么)
"""
import json, os, sqlite3, subprocess, sys
from datetime import datetime
from pathlib import Path

HERMES = Path("/home/administrator/.hermes")
STATE_DB = HERMES / "state.db"
INTEL_DB = HERMES / "intelligence.db"
MEMORY_DB = HERMES / "active_memory.db"
TASK_CURRENT = HERMES / "task_current.json"
AUDIT_SNAPSHOT = HERMES / "reports" / "audit_snapshot.json"
TASK_TRACKER = HERMES / "task_tracker.json"
CHECKPOINT = HERMES / "task_checkpoint.json"

def check_interrupted_task():
    """检查是否有中断任务需要恢复"""
    if not TASK_CURRENT.exists():
        return None
    with open(TASK_CURRENT) as f:
        tc = json.load(f)
    if tc.get("status") in ("interrupted_by_context_overflow", "in_progress"):
        return tc
    return None

def read_audit_snapshot():
    """读取上次审计快照,避免重新查询全部数据"""
    if not AUDIT_SNAPSHOT.exists():
        return None
    with open(AUDIT_SNAPSHOT) as f:
        return json.load(f)

def save_audit_snapshot():
    """保存子系统状态快照到文件(供中断恢复时读取)"""
    snapshot = {
        "timestamp": datetime.now().isoformat(),
        "intelligence_db": {},
        "memory": {},
        "state_db": {},
        "agents": {}
    }
    
    # intelligence.db快照
    try:
        db = sqlite3.connect(str(INTEL_DB))
        snapshot["intelligence_db"] = {
            "raw_count": db.execute("SELECT COUNT(*) FROM raw_intelligence").fetchone()[0],
            "cleaned_count": db.execute("SELECT COUNT(*) FROM cleaned_intelligence").fetchone()[0],
            "push_count": db.execute("SELECT COUNT(*) FROM push_records").fetchone()[0],
            "push_today": db.execute("SELECT COUNT(*) FROM push_records WHERE push_time >= datetime('now','-1 day','localtime')").fetchone()[0],
            "push_failed": db.execute("SELECT COUNT(*) FROM push_records WHERE push_status='failed'").fetchone()[0],
            "last_raw_time": str(db.execute("SELECT MAX(collected_at) FROM raw_intelligence").fetchone()[0] or ""),
            "last_push_time": str(db.execute("SELECT MAX(push_time) FROM push_records").fetchone()[0] or ""),
            "empty_content_raw": db.execute("SELECT COUNT(*) FROM raw_intelligence WHERE content IS NULL OR content=''").fetchone()[0],
            "empty_content_clean": db.execute("SELECT COUNT(*) FROM cleaned_intelligence WHERE content IS NULL OR content=''").fetchone()[0],
            "empty_content_push": db.execute("SELECT COUNT(*) FROM push_records WHERE content IS NULL OR content='' OR content='(无内容)'").fetchone()[0],
            "unscored": db.execute("SELECT COUNT(*) FROM cleaned_intelligence WHERE ai_score_total=0").fetchone()[0],
            "duplicates": db.execute("SELECT COUNT(*) FROM (SELECT title FROM cleaned_intelligence GROUP BY title HAVING COUNT(*)>1)").fetchone()[0],
        }
        db.close()
    except: pass
    
    # memory快照
    try:
        db = sqlite3.connect(str(MEMORY_DB))
        snapshot["memory"] = {
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
    
    # state.db快照
    try:
        db = sqlite3.connect(str(STATE_DB))
        snapshot["state_db"] = {
            "sessions": db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0],
            "messages": db.execute("SELECT COUNT(*) FROM messages").fetchone()[0],
            "event_log": db.execute("SELECT COUNT(*) FROM event_log").fetchone()[0],
        }
        db.close()
    except: pass
    
    HERMES.joinpath("reports").mkdir(exist_ok=True)
    with open(AUDIT_SNAPSHOT, "w") as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=2)
    
    return snapshot

def update_task_current(task_id, status, last_round, detail, next_action):
    """更新任务断点状态"""
    data = {
        "task_id": task_id,
        "status": status,
        "last_completed_round": last_round,
        "last_detail": detail,
        "next_action": next_action,
        "updated_at": datetime.now().isoformat()
    }
    with open(TASK_CURRENT, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def main():
    print("=" * 60)
    print("  HERMES 任务断点续跑系统 v1.1")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    
    # 1. 检查中断任务
    tc = check_interrupted_task()
    if tc:
        print(f"\n⚠️ 发现未完成任务: {tc['task_id']}")
        print(f"   进度: {tc.get('last_completed_round', '未知')}")
        print(f"   下一步: {tc.get('next_action', '未知')}")
        print(f"\n   💡 格林主人说'继续'即可续跑")
    
    # 2. 读取审计快照
    snap = read_audit_snapshot()
    if snap:
        ts = snap.get('ts') or snap.get('timestamp', '未知')
        print(f"\n📋 上次审计快照: {str(ts)[:19]}")
        idb = snap.get('intelligence_db', {})
        print(f"   📡 raw:{idb.get('raw_count','?')} clean:{idb.get('cleaned_count','?')} push:{idb.get('push_count','?')}")
        mem = snap.get('memory', {})
        print(f"   🧠 episodic:{mem.get('episodic','?')} semantic:{mem.get('semantic','?')} proc:{mem.get('procedural','?')} ref:{mem.get('reflexive','?')}")
        print(f"   ✅ 空content:raw={idb.get('empty_content_raw','?')} clean={idb.get('empty_content_clean','?')} push={idb.get('empty_content_push','?')}")
    else:
        print("\n📋 无审计快照(首次运行或快照被清除)")
    
    # 3. 员工+专家完成状态
    tracker_path = TASK_TRACKER
    if tracker_path.exists():
        with open(tracker_path) as f:
            tr = json.load(f)
        emps = tr.get('employees', {})
        exps = tr.get('experts', {})
        print(f"\n👥 员工: {emps.get('complete',0)}/{emps.get('total',0)} | 专家: {exps.get('complete',0)}/{exps.get('total',0)}")
    
    # 4. 保存新的审计快照
    save_audit_snapshot()
    print("\n💾 审计快照已保存 -> reports/audit_snapshot.json")
    
    print("\n" + "=" * 60)
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
