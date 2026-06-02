#!/usr/bin/env python3
"""
Hermes 全自动化生产流水线 — 一键入口
======================================
整合:采集 → 清洗 → Agent Export(分析) → AI日报 → Agent Company(12部门) → Agent Export(报告) → 推送微信

调用方式:
  python3 full_auto_pipeline.py              # 完整全链路
  python3 full_auto_pipeline.py --daily-only # 仅日报
  python3 full_auto_pipeline.py --status     # 查看系统状态
"""
import sys, os, subprocess, json
from datetime import datetime, date
from pathlib import Path

HERMES = Path("/home/administrator/.hermes")
SCRIPTS = HERMES / "scripts"
HERMES_ROOT = Path("/mnt/d/Hermes")

C = {"OK": "\033[92m", "ERR": "\033[91m", "WRN": "\033[93m", "INFO": "\033[94m", "END": "\033[0m"}

def log(msg, level="INFO"):
    prefix = {"OK": f"{C['OK']}[OK]{C['END']}", "ERR": f"{C['ERR']}[ERR]{C['END']}", 
              "WRN": f"{C['WRN']}[WRN]{C['END']}", "INFO": f"{C['INFO']}[INFO]{C['END']}"}
    print(f"{prefix.get(level, '[--]')} {datetime.now().strftime('%H:%M:%S')} {msg}")

def run(name, script, args=None, timeout=300):
    cmd = [sys.executable, str(SCRIPTS / script)]
    if args:
        cmd.extend(args if isinstance(args, list) else [args])
    log(f"▶ {name}...")
    start = datetime.now()
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        elapsed = (datetime.now() - start).total_seconds()
        if result.returncode == 0:
            log(f"✅ {name} 完成 ({elapsed:.1f}s)", "OK")
            return True, result.stdout
        else:
            log(f"❌ {name} 失败: {result.stderr[-200:]}", "ERR")
            return False, result.stderr
    except subprocess.TimeoutExpired:
        log(f"❌ {name} 超时", "ERR")
        return False, "timeout"

def get_db_stats():
    try:
        import sqlite3
        db = sqlite3.connect(str(HERMES / "intelligence.db"), timeout=5)
        t = db.execute("SELECT COUNT(*) FROM raw_intelligence").fetchone()[0]
        c = db.execute("SELECT COUNT(*) FROM cleaned_intelligence").fetchone()[0]
        p = db.execute("SELECT COUNT(*) FROM push_records").fetchone()[0]
        db.close()
        return {"raw": t, "cleaned": c, "pushed": p}
    except:
        return {"raw": 0, "cleaned": 0, "pushed": 0}

def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "full"
    
    if mode == "--status":
        stats = get_db_stats()
        print(f"\n📊 Hermes 系统状态")
        print(f"  raw_intelligence: {stats['raw']}条")
        print(f"  cleaned_intelligence: {stats['cleaned']}条")
        print(f"  push_records: {stats['pushed']}条")
        return
    
    print(f"\n{'='*60}")
    print(f"🏭 Hermes 全自动化生产流水线")
    print(f"📅 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}")
    
    stats_before = get_db_stats()
    log(f"初始DB: raw={stats_before['raw']} cleaned={stats_before['cleaned']}")
    
    # === Step 1: 采集(使用现有v6系统)===
    run("v6全量采集", "master_v6_pipeline.py", ["--collect"])
    
    # === Step 2: 清洗 ===
    run("清洗管道", "unified_cleaning_pipeline.py", ["--batch", "2000"])
    
    # === Step 3: Agent Export 分析 ===
    run("Agent Export 情报分析", "agent_export_engine.py")
    
    # === Step 4: AI日报(第一单产品)===
    run("AI日报生成", "ai_daily_engine.py")
    
    # === Step 5: Agent Company 全流水线 ===
    if mode != "--daily-only":
        run("Agent Company 运营", "agent_company_runner.py")
    
    # === Step 6: 推送日报到微信 ===
    # 检查是否有今天的日报
    daily_dir = HERMES_ROOT / "daily_report"
    today_files = sorted(daily_dir.glob(f"daily_{date.today().isoformat()}.md"))
    if today_files:
        log(f"日报已就绪: {today_files[0]}")
    else:
        log("今日日报未生成", "WRN")
    
    stats_after = get_db_stats()
    delta_raw = stats_after['raw'] - stats_before['raw']
    delta_cleaned = stats_after['cleaned'] - stats_before['cleaned']
    
    print(f"\n{'='*60}")
    log("全流水线完成!", "OK")
    log(f"新增: raw+{delta_raw}, cleaned+{delta_cleaned}", "OK")
    log(f"最终: raw={stats_after['raw']}, cleaned={stats_after['cleaned']}", "OK")
    print(f"{'='*60}")

if __name__ == "__main__":
    main()
