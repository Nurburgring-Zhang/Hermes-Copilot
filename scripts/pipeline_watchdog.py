#!/usr/bin/env python3
"""pipeline_watchdog.py - 监控pipeline执行状态,如果停滞则告警"""
import json, os
from datetime import datetime

checkpoint_path = "/mnt/d/Hermes/status/pipeline_checkpoint.json"
summary_path = "/mnt/d/Hermes/sales/production_summary.json"

report = {
    "check_time": datetime.now().isoformat(),
    "alerts": [],
    "status": "ok"
}

# 检查checkpoint
if os.path.exists(checkpoint_path):
    with open(checkpoint_path) as f:
        cp = json.load(f)
    completed = cp.get("completed", [])
    report["checkpoint"] = cp
    report["completed_phases"] = len(completed)
    if len(completed) < 12:
        report["alerts"].append(f"Pipeline未完成: 已完{len(completed)}/12阶段, 当前: {cp.get('phase', '未知')}")
        report["status"] = "incomplete"
else:
    report["checkpoint"] = None
    report["completed_phases"] = 0
    report["alerts"].append("Pipeline未启动或无checkpoint")

# 检查关键产出
key_dirs = [
    ("01_operations", "运营部"),
    ("02_design", "设计部"),
    ("03_product", "产品部"),
    ("04_rd", "研发部"),
    ("05_pmo", "项目管理部"),
    ("06_dev", "项目开发部"),
    ("07_support_proj", "项目支持部"),
    ("08_engineering", "工程部"),
    ("09_qa", "测试与交付部"),
    ("10_media", "宣传媒体部"),
    ("11_support", "支持部"),
    ("12_sales", "销售部")
]
present = 0
for d, name in key_dirs:
    p = f"/mnt/d/Hermes/{d}"
    if os.path.isdir(p):
        files = [f for f in os.listdir(p) if f.endswith('.json') or f.endswith('.py')]
        if files:
            present += 1
            report.setdefault("dirs", {})[name] = len(files)

report["departments_with_output"] = present

# 产生告警
if present < 12:
    report["alerts"].append(f"仅有{present}/12个部门有产出文件")
    report["status"] = "incomplete"
if not report["alerts"]:
    report["status"] = "all_good"

os.makedirs("/mnt/d/Hermes/status", exist_ok=True)
with open("/mnt/d/Hermes/status/watchdog_last.json", "w") as f:
    json.dump(report, f, ensure_ascii=False, indent=2)

print(f"Watchdog: {report['status']}")
for a in report["alerts"]:
    print(f"  ⚠️ {a}")
print(f"  部门产出: {present}/12")
