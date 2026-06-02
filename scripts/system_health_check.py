#!/usr/bin/env python3
"""
Hermes 系统健康自检 (System Health Check)
每天运行,检查所有子系统状态并报告问题
"""
import sqlite3, json, logging
from datetime import datetime, timedelta
from pathlib import Path

HERMES = Path("/home/administrator/.hermes")

def check_db(db_path, name):
    if not db_path.exists():
        return {"name": name, "status": "missing", "size": 0}
    size_mb = db_path.stat().st_size / 1024 / 1024
    try:
        conn = sqlite3.connect(str(db_path), timeout=5)
        conn.execute("SELECT 1")
        conn.close()
        return {"name": name, "status": "ok", "size_mb": round(size_mb, 1)}
    except Exception as e:
        return {"name": name, "status": f"error: {e}", "size_mb": round(size_mb, 1)}

def check_cron():
    jobs_file = HERMES / "cron" / "jobs.json"
    if not jobs_file.exists():
        return {"status": "no_jobs_file"}
    data = json.loads(jobs_file.read_text())
    jobs = data.get("jobs", data if isinstance(data, list) else [])
    enabled = [j for j in jobs if j.get("enabled")]
    errors = [j for j in jobs if j.get("last_status") == "error"]
    never_run = [j for j in jobs if j.get("enabled") and j.get("last_run_at") is None]
    return {
        "total": len(jobs), "enabled": len(enabled),
        "errors": len(errors), "never_run": len(never_run)
    }

def main():
    results = {}
    
    # DB健康
    dbs = [
        (HERMES / "intelligence.db", "intelligence"),
        (HERMES / "memory/main.sqlite", "memory"),
        (HERMES / "auto_run/intelligence_pipeline/rag_memory_index.db", "rag_index"),
        (HERMES / "state.db", "state"),
    ]
    results['databases'] = [check_db(p, n) for p, n in dbs]
    
    # 采集状态
    try:
        conn = sqlite3.connect(str(HERMES / "intelligence.db"), timeout=5)
        today_raw = conn.execute("SELECT COUNT(*) FROM raw_intelligence WHERE DATE(collected_at)=DATE('now')").fetchone()[0]
        total_raw = conn.execute("SELECT COUNT(*) FROM raw_intelligence").fetchone()[0]
        total_cleaned = conn.execute("SELECT COUNT(*) FROM cleaned_intelligence").fetchone()[0]
        last_collected = conn.execute("SELECT MAX(collected_at) FROM raw_intelligence").fetchone()[0]
        conn.close()
        results['collection'] = {"today": today_raw, "total_raw": total_raw, "total_cleaned": total_cleaned, "last": last_collected}
    except Exception as e:
        results['collection'] = {"error": str(e)}
    
    # Cron状态
    results['cron'] = check_cron()
    
    # Gateway状态
    gateway_pid = HERMES / "gateway.pid"
    results['gateway'] = "running" if gateway_pid.exists() else "stopped"
    
    # 推送状态
    try:
        conn = sqlite3.connect(str(HERMES / "intelligence.db"), timeout=5)
        last_push = conn.execute("SELECT MAX(pushed_at) FROM push_log").fetchone()[0]
        conn.close()
        results['last_push'] = last_push
    except:
        results['last_push'] = None
    
    # 输出摘要
    print(f"\n{'='*50}")
    print(f"  Hermes 系统健康自检 — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*50}")
    
    for db in results['databases']:
        status = "✅" if db['status'] == 'ok' else "❌"
        print(f"  {status} {db['name']}: {db.get('size_mb', 0):.1f}MB [{db['status']}]")
    
    coll = results.get('collection', {})
    print(f"  📊 采集: 今日{coll.get('today', '?')}条, 总计{coll.get('total_raw', '?')}条, 已清洗{coll.get('total_cleaned', '?')}条")
    print(f"  ⏱ 最后采集: {coll.get('last', 'N/A')}")
    
    cron = results.get('cron', {})
    print(f"  ⏰ Cron: {cron.get('enabled', 0)}启用/{cron.get('total', 0)}总计")
    if cron.get('never_run', 0) > 0:
        print(f"  ⚠️  有 {cron.get('never_run')} 个cron从未执行!")
    if cron.get('errors', 0) > 0:
        print(f"  ❌ 有 {cron.get('errors')} 个cron有错误!")
    
    print(f"  🚪 Gateway: {'✅ 运行中' if results['gateway'] == 'running' else '❌ 已停止'}")
    print(f"  📨 最后推送: {results.get('last_push', 'N/A')}")
    print(f"{'='*50}\n")
    
    # 问题汇总
    issues = []
    for db in results['databases']:
        if db['status'] != 'ok':
            issues.append(f"DB {db['name']}: {db['status']}")
    if results.get('gateway') == 'stopped':
        issues.append("Gateway未运行,cron不会触发")
    if cron.get('never_run', 0) > 0:
        issues.append(f"{cron.get('never_run')}个cron从未执行")
    if cron.get('errors', 0) > 0:
        issues.append(f"{cron.get('errors')}个cron有错误")
    
    print(f"发现 {len(issues)} 个问题:")
    for i in issues:
        print(f"  ❌ {i}")
    if not issues:
        print("  ✅ 一切正常!")
    
    # 写入报告
    report = HERMES / "reports" / f"health_{datetime.now().strftime('%Y%m%d')}.json"
    HERMES / "reports" or None
    Path(HERMES / "reports").mkdir(exist_ok=True)
    report.write_text(json.dumps(results, indent=2, default=str))
    
    return len(issues) == 0

if __name__ == "__main__":
    main()
