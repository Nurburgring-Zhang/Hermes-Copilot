#!/usr/bin/env python3
"""
Hermes 复盘全链路验证 v1.0
验证复盘引擎、cron调度、候选消费、AGENTS.md规则是否全部正常
"""
import sys, os
sys.path.insert(0, os.path.expanduser("~/.hermes/scripts"))
import json, sqlite3
from pathlib import Path

HERMES = Path.home() / ".hermes"
errors = []
passes = []

def check(name, condition, detail=""):
    if condition:
        passes.append(f"✅ {name}")
    else:
        errors.append(f"❌ {name}: {detail}")

print("=" * 50)
print("Hermes 复盘全链路验证")
print("=" * 50)

# 1. 复盘引擎文件存在
retro_file = HERMES / "scripts" / "hermes_retrospect.py"
check("复盘引擎脚本存在", retro_file.exists())
if retro_file.exists():
    check("复盘引擎>10KB", retro_file.stat().st_size > 10000, f"实际{retro_file.stat().st_size}字节")

# 2. state.db有retrospectives表
db_path = HERMES / "state.db"
if db_path.exists():
    conn = sqlite3.connect(str(db_path))
    tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    check("state.db有retrospectives表", "retrospectives" in tables)
    if "retrospectives" in tables:
        count = conn.execute("SELECT COUNT(*) FROM retrospectives").fetchone()[0]
        check("retrospectives表有数据", count > 0, f"当前{count}条")
    conn.close()
else:
    check("state.db存在", False)

# 3. 复盘引擎可导入
try:
    import importlib
    spec = importlib.util.spec_from_file_location("hermes_retrospect", str(retro_file))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    check("复盘引擎可导入", True)
    check("HermesRetrospect类存在", hasattr(mod, "HermesRetrospect"))
    check("daily_summary函数存在", hasattr(mod, "daily_summary"))
except Exception as e:
    check("复盘引擎导入", False, str(e))

# 4. 进化候选队列文件状态
candidate_file = HERMES / "data" / "retro_candidates.jsonl"
if candidate_file.exists():
    with open(candidate_file) as f:
        lines = [l for l in f if l.strip()]
    check("进化候选队列非空", len(lines) > 0, f"当前{len(lines)}条")
else:
    check("进化候选队列存在", False, "文件未创建")

# 5. AGENTS.md规则检查
agents_md = HERMES / "AGENTS.md"
if agents_md.exists():
    content = agents_md.read_text()
    check("AGENTS.md包含复盘规则", "复盘反思规则" in content)
    check("AGENTS.md包含质量墙规则", "执行质量墙规则" in content)
    check("AGENTS.md包含长期任务规则", "长期任务执行保障规则" in content)
    check("AGENTS.md包含格林主人固化标记", "2026-05-31 固化" in content)
    check("AGENTS.md包含强制声明", "所有对话、所有任务全部通用" in content)
    check("AGENTS.md包含自动执行", "完全自动执行、强制执行" in content)

# 6. writing-plans skill已有规划模板
plans_skill = HERMES / "skills" / "software-development" / "writing-plans" / "SKILL.md"
if plans_skill.exists():
    content = plans_skill.read_text()
    check("writing-plans包含Complexity字段", "Complexity" in content)
    check("writing-plans包含Strategy字段", "Strategy:" in content)
    check("writing-plans包含ReAct策略", "ReAct" in content)
    check("writing-plans包含Plan-and-Solve", "Plan-and-Solve" in content)

# 7. cron任务检查
cron_file = HERMES / "cron" / "jobs.json"
if cron_file.exists() and cron_file.stat().st_size > 10:
    with open(cron_file) as f:
        raw = json.load(f)
    jobs = raw if isinstance(raw, list) else raw.get("jobs", [])
    retro_jobs = [j for j in jobs if "复盘" in j.get("name", "")]
    check("复盘cron任务存在", len(retro_jobs) > 0, f"找到{len(retro_jobs)}个")
    if retro_jobs:
        for j in retro_jobs:
            check(f"  复盘任务[{j['name']}]已启用", j.get("enabled", False))

# 8. 自进化集群已集成复盘候选消费
evolve_file = HERMES / "scripts" / "hermes_self_evolve_cluster.py"
if evolve_file.exists():
    content = evolve_file.read_text()
    check("自进化集群包含consume_retro_candidates", "consume_retro_candidates" in content)
    check("自进化集群包含模块6", "模块6: 复盘候选消费" in content)

# 9. 复盘报告目录可写
retro_dir = HERMES / "reports" / "retrospectives"
check("复盘报告目录存在", retro_dir.exists())
if retro_dir.exists():
    reports = list(retro_dir.glob("*.json"))
    check("复盘报告已有产出", len(reports) > 0, f"当前{len(reports)}个文件")

# 汇总
print()
print("=" * 50)
print(f"验证结果: {len(passes)}个通过 / {len(passes)+len(errors)}个总检查")
if errors:
    print(f"⚠️ {len(errors)}个失败:")
    for e in errors:
        print(f"  {e}")
print("=" * 50)
