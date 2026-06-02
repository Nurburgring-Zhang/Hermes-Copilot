#!/usr/bin/env python3
"""
深度验证 Phase 1: 全资产清单扫描引擎
扫描 Hermes 系统所有资产: 文件/代码/依赖/cron/db/配置/skills/agents
输出完整的资产清单 + 缺失检测 + 完整性评分
"""

import os, sys, json, sqlite3, subprocess, hashlib, stat
from pathlib import Path
from datetime import datetime

HERMES = Path("/home/administrator/.hermes")
SCRIPTS = HERMES / "scripts"
SKILLS = HERMES / "skills"
AGENTS = HERMES / "agents_company"
REPORTS = HERMES / "reports"
LOGS = HERMES / "logs"
MEMORY = HERMES / "memory"
CONFIG = HERMES

report = {
    "timestamp": datetime.now().isoformat(),
    "sections": {},
    "overall": {"pass": 0, "fail": 0, "warn": 0}
}

def section(name: str):
    report["sections"][name] = {"items": [], "pass": 0, "fail": 0, "warn": 0}
    return report["sections"][name]

def check(section_name: str, item: str, ok: bool, detail: str = ""):
    s = report["sections"].get(section_name)
    if not s:
        s = section(section_name)
    status = "pass" if ok else "fail"
    s[status] += 1
    report["overall"][status] += 1
    s["items"].append({"item": item, "status": status, "detail": detail[:200]})
    icon = "✅" if ok else "❌"
    print(f"  {icon} [{section_name}] {item}")
    if detail:
        print(f"       {detail[:150]}")

# ============ 1. 文件完整性 ============
print("\n" + "=" * 70)
print("Phase 1.1: 文件完整性扫描")
print("=" * 70)

s1 = section("文件完整性")

# 核心脚本
core_scripts = [
    "lcm_dag_engine.py", "memory_orchestrator_v3.py", "context_manager.py",
    "meta_thinker.py", "context_equilibria.py", "encryption_layer.py",
    "audit_logger.py", "local_semantic_embedding.py", "gear_enforcer.py",
    "self_enhance_loop.py", "gear_master.py", "gear_task_driver.py",
    "gear_task_validator.py", "gear_vault.py", "wake_guide.py",
    "context_failsafe.py", "context_guardian.py", "hermes_super_guardian.py",
    "hermes_memory_engine_v2.py", "memory_evolution_v2.py",
    "lossless_claw_v2.py", "unified_memory_orchestrator.py",
    "hermes_v12_push.py", "omni_loop.py", "guardian.py",
    "hermes_ai_scoring.py", "unified_collector_v5.py", "unified_cleaning_pipeline.py",
    "agent_company_engine.py", "agents_company_executor.py",
]
for script in core_scripts:
    path = SCRIPTS / script
    exists = path.exists()
    size = path.stat().st_size if exists else 0
    check("文件完整性", script, exists, f"{size:,}字节" if exists else "缺失!")

# 检查是否所有核心脚本都有 > 0字节
all_scripts_exist = all((SCRIPTS / s).exists() for s in core_scripts)
check("文件完整性", "所有核心脚本存在", all_scripts_exist, 
      f"{sum(1 for s in core_scripts if (SCRIPTS/s).exists())}/{len(core_scripts)}")

# 检查是否有空文件
empty = [s for s in core_scripts if (SCRIPTS/s).exists() and (SCRIPTS/s).stat().st_size == 0]
check("文件完整性", "无空文件", len(empty) == 0, f"空文件: {empty}" if empty else "")

# 配置文件
config_files = ["SOUL.md", "config.yaml"]
for cf in config_files:
    path = HERMES / cf
    check("文件完整性", cf, path.exists(), f"{path.stat().st_size:,}字节" if path.exists() else "")

# 报告文件
report_files = list(REPORTS.glob("*.json"))
check("文件完整性", "报告文件存在", len(report_files) > 0, f"{len(report_files)}个JSON报告")
for rf in report_files[:10]:
    try:
        data = json.loads(rf.read_text())
        check("文件完整性", rf.name, True, f"{len(str(data))}字符")
    except:
        check("文件完整性", rf.name, False, "JSON解析失败")

# ============ 2. Skills完整性 ============
print("\n" + "=" * 70)
print("Phase 1.2: Skills资产扫描")
print("=" * 70)

s2 = section("Skills")

skill_dirs = [d for d in SKILLS.iterdir() if d.is_dir() and not d.name.startswith('.')]
check("Skills", "技能目录", len(skill_dirs) > 0, f"{len(skill_dirs)}个技能")

skill_count = 0
for sd in skill_dirs:
    skill_md = sd / "SKILL.md"
    if skill_md.exists():
        content = skill_md.read_text()
        has_valid = "---" in content and "name:" in content
        check("Skills", f"  {sd.name}", has_valid, f"{len(content)}字符")
        if has_valid:
            skill_count += 1
    else:
        check("Skills", f"  {sd.name}", False, "无SKILL.md")

check("Skills", "有效技能总数", skill_count > 0, f"{skill_count}/{len(skill_dirs)}有效")

# 关键技能
key_skills = ["hermes-self-enhancement", "gear-context-compression", "lossless-claw-v2",
              "gear-interlocking-audit-v3", "task-auto-resume", "long-task-guardian",
              "context-guardian-recovery", "autonomous-systems", "hermes"]
for ks in key_skills:
    found = any(ks in sd.name for sd in skill_dirs)
    check("Skills", f"关键技能: {ks}", found)

# 自增强skills
self_skill = SKILLS / "autonomous-systems" / "hermes-self-enhancement" / "SKILL.md"
check("Skills", "self-enhancement skill完整", self_skill.exists(), 
      f"{self_skill.stat().st_size}字节" if self_skill.exists() else "")

# ============ 3. Agents公司 ============
print("\n" + "=" * 70)
print("Phase 1.3: Agents Company资产扫描")
print("=" * 70)

s3 = section("AgentsCompany")

# 员工目录
emp_dir = AGENTS / "employees"
if emp_dir.exists():
    emps = [d for d in emp_dir.iterdir() if d.is_dir()]
    check("AgentsCompany", "员工数量", len(emps) > 0, f"{len(emps)}个员工")
else:
    check("AgentsCompany", "员工目录", False, "employees目录不存在")

# 专家目录
exp_dir = AGENTS / "experts"
if exp_dir.exists():
    exps = [d for d in exp_dir.iterdir() if d.is_dir()]
    check("AgentsCompany", "专家数量", len(exps) > 0, f"{len(exps)}个专家")
else:
    check("AgentsCompany", "专家目录", False, "experts目录不存在")

# actors
actors_dir = AGENTS / "actors"
if actors_dir.exists():
    actors = list(actors_dir.iterdir())
    check("AgentsCompany", "Actors", len(actors) > 0, f"{len(actors)}个actor配置")

# 配置
agent_configs = list(AGENTS.glob("*.json")) + list(AGENTS.glob("*.py"))
check("AgentsCompany", "配置和引擎文件", len(agent_configs) > 10, f"{len(agent_configs)}个文件")

# ============ 4. 数据库 ============
print("\n" + "=" * 70)
print("Phase 1.4: 数据库资产扫描")
print("=" * 70)

s4 = section("数据库")

dbs = [
    ("intelligence.db", "情报数据库"),
    ("state.db", "状态数据库"),
    ("logs/audit/audit_trail.jsonl", "审计日志"),
]
for db_file, desc in dbs:
    path = HERMES / db_file
    exists = path.exists()
    size = path.stat().st_size if exists else 0
    check("数据库", desc, exists, f"{size:,}字节" if exists else "缺失")

# LCM DAG数据库
lcm_db = HERMES / "memory" / "lcm_dag" / "lcm_store.db"
check("数据库", "LCM DAG存储", lcm_db.exists(), f"{lcm_db.stat().st_size:,}字节" if lcm_db.exists() else "")

# Mem0数据库
mem0_db = MEMORY / "mem0_data" / "mem0_store.db"
check("数据库", "Mem0存储", mem0_db.exists(), f"{mem0_db.stat().st_size:,}字节" if mem0_db.exists() else "")

# Hindsight数据库
hindsight_db = MEMORY / "hindsight_data" / "hindsight_store.db"
check("数据库", "Hindsight存储", hindsight_db.exists(), f"{hindsight_db.stat().st_size:,}字节" if hindsight_db.exists() else "")

# 尝试打开每个数据库验证
for db_path, name in [(HERMES / "intelligence.db", "intelligence"),
                       (lcm_db, "lcm_dag"),
                       (mem0_db, "mem0"),
                       (hindsight_db, "hindsight")]:
    if db_path.exists() and db_path.stat().st_size > 100:
        try:
            conn = sqlite3.connect(str(db_path))
            cursor = conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'")
            tables = cursor.fetchone()[0]
            conn.close()
            check("数据库", f"{name}结构有效", tables > 0, f"{tables}个表")
        except Exception as e:
            check("数据库", f"{name}结构", False, str(e)[:100])
    elif db_path.exists():
        check("数据库", f"{name}结构", False, "数据库文件为空")

# ============ 5. Cron ============
print("\n" + "=" * 70)
print("Phase 1.5: Cron任务扫描")
print("=" * 70)

s5 = section("Cron")

try:
    cr = subprocess.run(["crontab", "-l"], capture_output=True, text=True, timeout=5)
    crons = cr.stdout.strip().split('\n') if cr.stdout.strip() else []
    check("Cron", "cron存在", len(crons) > 0, f"{len(crons)}行")
    
    # 检查关键cron
    key_crons = {
        "gear_enforcer": "每1分钟齿轮强制器",
        "self_enhance_loop": "每5分钟闭环循环",
        "guardian.*heal": "守护者恢复",
        "memory_orchestrator.*health": "G8三引擎健康",
        "lcm_dag_engine.*verify": "LCM DAG完整性",
        "meta_thinker.*log": "漂移检测摘要",
        "audit_logger.*summary": "审计摘要",
        "omni_loop": "全能主控循环",
    }
    for pattern, desc in key_crons.items():
        found = any(pattern in line for line in crons)
        check("Cron", desc, found)
    
    # 去重检查
    unique = set(crons)
    check("Cron", "无重复cron", len(unique) == len(crons), 
          f"{len(crons)}行, {len(unique)}唯一")
except Exception as e:
    check("Cron", "cron读取", False, str(e)[:100])

# ============ 6. 日志 ============
print("\n" + "=" * 70)
print("Phase 1.6: 日志资产扫描")
print("=" * 70)

s6 = section("日志")

log_files = list(LOGS.glob("*.log")) + list(LOGS.glob("*.txt"))
check("日志", "日志文件存在", len(log_files) > 0, f"{len(log_files)}个")
for lf in log_files:
    size = lf.stat().st_size
    if size == 0:
        check("日志", f"  {lf.name}", False, "空文件")

# 关键日志
key_logs = ["gear_enforcer.log", "self_enhance_loop.log", "gear_master.log",
            "gear_heartbeat.txt", "memory_orchestrator.log", "lcm_dag.log",
            "self_enhance.log"]
for kl in key_logs:
    path = LOGS / kl
    exists = path.exists()
    size = path.stat().st_size if exists else 0
    check("日志", kl, exists, f"{size:,}字节" if exists else "缺失")

# ============ 7. Python依赖 ============
print("\n" + "=" * 70)
print("Phase 1.7: Python依赖扫描")
print("=" * 70)

s7 = section("Python依赖")

critical_packages = [
    "cryptography", "zstandard", "sentence-transformers", "transformers",
    "sqlite3", "hashlib", "json", "pathlib", "sqlite-vec"
]

try:
    r = subprocess.run([sys.executable, "-m", "pip", "list", "--format=json"], 
                       capture_output=True, text=True, timeout=15)
    installed = json.loads(r.stdout)
    installed_names = {p["name"].lower() for p in installed}
    installed_names.add("sqlite3")  # stdlib
    installed_names.add("hashlib")
    installed_names.add("json")
    installed_names.add("pathlib")
    
    for pkg in critical_packages:
        found = pkg.lower() in installed_names or pkg in installed_names
        check("Python依赖", pkg, found)
    
    # numpy检查(可选但重要)
    check("Python依赖", "numpy", "numpy" in installed_names or "numpy" in str(installed))
except Exception as e:
    check("Python依赖", "pip列表", False, str(e)[:100])

# ============ 8. 配置文件 ============
print("\n" + "=" * 70)
print("Phase 1.8: 配置文件验证")
print("=" * 70)

s8 = section("配置")

# gear_registry.json
registry = REPORTS / "gear_registry.json"
if registry.exists():
    try:
        data = json.loads(registry.read_text())
        tasks = data.get("tasks", {})
        check("配置", "齿轮注册中心", len(tasks) > 0, f"{len(tasks)}个任务")
        for tid, tdata in list(tasks.items())[:5]:
            check("配置", f"  任务: {tid[:40]}", 
                  tdata.get("status") in ("delivered", "completed", "running"),
                  tdata.get("status", "unknown"))
    except:
        check("配置", "齿轮注册中心", False, "JSON解析失败")
else:
    check("配置", "齿轮注册中心", False, "文件不存在")

# gear_checkpoint.json
cp = REPORTS / "gear_checkpoint.json"
check("配置", "齿轮检查点", cp.exists())

# wake_guide.json
wg = REPORTS / "wake_guide.json"
check("配置", "醒来指南", wg.exists())

# SOUL.md
soul = HERMES / "SOUL.md"
check("配置", "SOUL.md", soul.exists())

# USER.md
user = HERMES / "USER.md"
check("配置", "USER.md", user.exists())

# MEMORY.md
mem = HERMES / "MEMORY.md"
check("配置", "MEMORY.md", mem.exists())

# ============ 9. 加密密钥 ============
print("\n" + "=" * 70)
print("Phase 1.9: 加密密钥扫描")
print("=" * 70)

s9 = section("加密密钥")

key_dir = HERMES / "keys"
key_file = key_dir / "hermes_encryption_key.bin"
salt_file = key_dir / "hermes_salt.bin"

if key_dir.exists():
    keys = list(key_dir.iterdir())
    check("加密密钥", "密钥目录", len(keys) > 0, f"{len(keys)}个文件")
    check("加密密钥", "加密密钥文件", key_file.exists())
    check("加密密钥", "Salt文件", salt_file.exists())
    if key_file.exists():
        perms = oct(os.stat(key_file).st_mode)[-3:]
        check("加密密钥", "密钥权限600", perms == "600" or perms == "000", f"权限: {perms}")
else:
    check("加密密钥", "密钥目录", False, "keys目录不存在")

# ============ 10. 环境变量 ============
print("\n" + "=" * 70)
print("Phase 1.10: 环境变量检查")
print("=" * 70)

s10 = section("环境变量")
check("环境变量", "PATH非空", len(os.environ.get("PATH", "")) > 0)
check("环境变量", "HOME正确", os.environ.get("HOME") == str(Path.home()))

# 检查Python版本
py_ver = sys.version
check("环境变量", f"Python {py_ver[:5]}", py_ver.startswith("3"), py_ver[:30])

# ============ 汇总 ============
print("\n" + "=" * 70)
print("资产清单扫描报告")
print("=" * 70)
o = report["overall"]
print(f"总检查项: {o['pass'] + o['fail'] + o['warn']}")
print(f"通过: {o['pass']} ✅")
print(f"失败: {o['fail']} ❌")
print(f"警告: {o['warn']} ⚠️")
pass_rate = o['pass'] / (o['pass'] + o['fail'] + 1) * 100
print(f"通过率: {pass_rate:.1f}%")

# 保存报告
report_path = REPORTS / "deep_verify_phase1_assets.json"
report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2))
print(f"\n报告已保存: {report_path}")

# 如果有失败,打印详情
if o['fail'] > 0:
    print(f"\n❌ 失败项详情:")
    for s_name, s_data in report["sections"].items():
        for item in s_data["items"]:
            if item["status"] == "fail":
                print(f"  [{s_name}] {item['item']}: {item['detail']}")
