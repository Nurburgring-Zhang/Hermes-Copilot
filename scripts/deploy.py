#!/usr/bin/env python3
"""
Hermes 部署脚本
==============
用法: python3 deploy.py [--model-tier value|performance]

模型梯队:
  - value (通用): 日用模型,省钱方案
  - performance (强力): 高性能模型,复杂推理任务

不绑定具体模型名称，由ModelRouter根据task_type自动路由。
"""
import sys, subprocess, json, os
from pathlib import Path

HERMES = Path(os.path.expanduser("~/.hermes"))

MODEL_TIERS = {
    "value": {"name": "通用", "desc": "省钱方案, 适合日常任务"},
    "performance": {"name": "强力", "desc": "高性能方案, 适合复杂推理"},
}

def deploy(model_tier="value"):
    tier = MODEL_TIERS.get(model_tier, MODEL_TIERS["value"])
    print(f"🚀 Hermes 部署启动 — 模型梯队: {tier['name']} ({tier['desc']})")
    
    # 1. 语法检查关键脚本
    scripts_to_check = [
        "gear_enforcer.py", "segment_manager.py", "context_index_system.py",
        "reflexion_engine.py", "experience_extractor.py", "gepa_variator.py",
        "status_reporter.py", "hermes_retrospect.py", "llm_bridge.py",
        "hermes_self_evolve_cluster.py",
    ]
    for script in scripts_to_check:
        path = HERMES / "scripts" / script
        if path.exists():
            r = subprocess.run([sys.executable, "-m", "py_compile", str(path)],
                               capture_output=True, text=True)
            if r.returncode == 0:
                print(f"  ✅ {script}")
            else:
                print(f"  ❌ {script}: {r.stderr.strip()}")
    
    # 2. 检查cron任务
    cron_jobs = HERMES / "cron" / "jobs.json"
    if cron_jobs.exists():
        with open(cron_jobs) as f:
            jobs = json.load(f)
        print(f"\n📋 Cron任务: {len(jobs.get('jobs', []))} 个")
        for j in jobs.get("jobs", []):
            enabled = "✅" if j.get("enabled") else "⏸️"
            print(f"  {enabled} {j.get('name', '?')} [{j.get('schedule_display', '?')}]")
    
    # 3. 验证数据库
    for db_name in ["active_memory.db", "state.db", "intelligence.db"]:
        db_path = HERMES / db_name
        if db_path.exists():
            print(f"  ✅ 数据库 {db_name} ({db_path.stat().st_size / 1024:.0f}KB)")
        else:
            print(f"  ⚠️ 数据库 {db_name} 不存在")
    
    print(f"\n✅ 部署验证完成 — 模型梯队: {tier['name']}")
    return True

if __name__ == "__main__":
    model_tier = "value"
    if "--model-tier" in sys.argv:
        idx = sys.argv.index("--model-tier")
        if idx + 1 < len(sys.argv):
            model_tier = sys.argv[idx + 1]
    elif "--performance" in sys.argv:
        model_tier = "performance"
    
    deploy(model_tier)
