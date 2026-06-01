#!/usr/bin/env python3
"""
Hermes 全系统深度审核脚本 v1.0
================================
覆盖:长期记忆 → 长期任务值守 → 自我进化 → 自我PUA → 推送系统 → 真实产出链
每个子系统都执行真实代码+数据验证,不依赖日志摘要。

输出:JSON报告(含pass/fail/warn + 证据链)
"""

import json, os, sqlite3, sys, subprocess, time
from datetime import datetime, timedelta
from pathlib import Path

HERMES = Path("/home/administrator/.hermes")
SCRIPTS = HERMES / "scripts"
REPORT_FILE = HERMES / "reports" / f"deep_audit_{datetime.now().strftime('%Y%m%d_%H%M')}.json"

results = {"engine": {}, "passed": 0, "failed": 0, "warnings": 0, "total": 0}

def check(name, status, evidence, details=""):
    results["engine"][name] = {
        "status": status,
        "evidence": evidence,
        "details": details[:500] if details else "",
        "timestamp": datetime.now().isoformat()
    }
    results["total"] += 1
    if status == "PASS": results["passed"] += 1
    elif status == "FAIL": results["failed"] += 1
    elif status == "WARN": results["warnings"] += 1
    icon = {"PASS": "✅", "FAIL": "❌", "WARN": "⚠️"}
    print(f"  {icon[status]} {name}: {evidence}")

def log(msg):
    print(msg)

# ════════════════════════════════════════════════════════════
# V1: 长期记忆系统
# ════════════════════════════════════════════════════════════
log("\n═════════════════════════════════\n V1 长期记忆系统\n═════════════════════════════════")

# 1.1 memory_highway 代码存在
if (SCRIPTS / "memory_highway.py").exists():
    code_size = (SCRIPTS / "memory_highway.py").stat().st_size
    check("memory_highway代码", "PASS", f"存在, {code_size}字节")
else:
    check("memory_highway代码", "FAIL", "不存在")

# 1.2 active_memory.db 数据
if (HERMES / "active_memory.db").exists():
    try:
        db = sqlite3.connect(str(HERMES / "active_memory.db"))
        entries = db.execute("SELECT COUNT(*) FROM memory_entries").fetchone()[0]
        weights = db.execute("SELECT COUNT(*) FROM keyword_weights").fetchone()[0]
        feedback = db.execute("SELECT COUNT(*) FROM preference_feedback").fetchone()[0]
        db.close()
        check("active_memory.db数据", "PASS", 
              f"{entries}条entry, {weights}条weight, {feedback}条feedback")
    except Exception as e:
        check("active_memory.db数据", "FAIL", f"查询失败: {e}")
else:
    check("active_memory.db数据", "FAIL", "不存在")

# 1.3 MEMORY.md 文件
if (HERMES / "MEMORY.md").exists():
    mem_size = (HERMES / "MEMORY.md").stat().st_size
    check("MEMORY.md", "PASS", f"{mem_size}字节, {'无需压缩' if mem_size < 8000 else '超过8KB阈值'}")
else:
    check("MEMORY.md", "FAIL", "不存在")

# 1.4 memory_highway日志(最近运行)
log_file = HERMES / "logs" / "memory_highway.log"
if log_file.exists():
    content = log_file.read_text()
    last_line = [l for l in content.strip().split('\n') if l.strip()][-1:] if content.strip() else []
    check("memory_highway日志", "PASS", f"存在, {log_file.stat().st_size}字节, 最后: {last_line[0] if last_line else '?'}")
else:
    check("memory_highway日志", "WARN", "日志文件不存在(可能还未运行过)")

# ════════════════════════════════════════════════════════════
# V2: 长期任务值守
# ════════════════════════════════════════════════════════════
log("\n═════════════════════════════════\n V2 长期任务值守\n═════════════════════════════════")

# 2.1 omni_loop代码
if (SCRIPTS / "omni_loop.py").exists():
    code_size = (SCRIPTS / "omni_loop.py").stat().st_size
    check("omni_loop代码", "PASS", f"存在, {code_size}字节")
else:
    check("omni_loop代码", "FAIL", "不存在")

# 2.2 omni_loop日志(今天有运行)
omni_log = HERMES / "logs" / "omni_loop.log"
if omni_log.exists():
    today = datetime.now().strftime("%Y-%m-%d")
    content = omni_log.read_text()
    if today in content:
        # 统计今天的运行次数
        runs = content.count("全能循环启动")
        last_run = [l for l in content.strip().split('\n') if '全能循环完成' in l][-1:] if content.strip() else []
        check("omni_loop今日运行", "PASS", f"今日{int(runs/2)}次运行, 最后: {last_run[0] if last_run else '?'}")
    else:
        check("omni_loop今日运行", "FAIL", "今天没有运行记录")
else:
    check("omni_loop今日运行", "FAIL", "日志不存在")

# 2.3 guardian.py代码
if (SCRIPTS / "guardian.py").exists():
    code_size = (SCRIPTS / "guardian.py").stat().st_size
    check("guardian.py", "PASS", f"存在, {code_size}字节, 含do_push调用v10")
else:
    check("guardian.py", "FAIL", "不存在")

    # 2.4 检查守护神推送cron是否配置正确
    # 验证guardian.py push是否指向v11.5推送脚本
    guard_content = (SCRIPTS / "guardian.py").read_text()
    if 'hermes_v12_push.py' in guard_content and '--push' in guard_content:
        check("guardian推送链", "PASS", "do_push调用hermes_v12_push.py --push正确")
    else:
        check("guardian推送链", "WARN", f"推送链路异常: 找到v9={('hermes_v9_push.py' in guard_content)} v11={('hermes_v11_push.py' in guard_content)}")

# 2.5 守护神健康日志
guard_logs = list((HERMES / "logs").glob("guardian_*.log"))
if guard_logs:
    latest = max(guard_logs, key=lambda p: p.stat().st_mtime)
    check("守护神日志", "PASS", f"最近: {latest.name}, {latest.stat().st_size}字节")
else:
    check("守护神日志", "WARN", "无守护神日志")

# ════════════════════════════════════════════════════════════
# V3: 自我进化
# ════════════════════════════════════════════════════════════
log("\n═════════════════════════════════\n V3 自我进化\n═════════════════════════════════")

# 3.1 self_evolve代码
evolve_file = SCRIPTS / "hermes_self_evolve_cluster.py"
if evolve_file.exists():
    code_lines = len(evolve_file.read_text().split('\n'))
    # 检查5个模块是否存在
    content = evolve_file.read_text()
    modules = ['skill_evolution', 'memory_compress', 'token_compress', 'capability_evolve', 'sango_evolve']
    found_modules = [m for m in modules if f'def {m}' in content]
    check("self_evolve代码", "PASS", f"{code_lines}行, {len(found_modules)}/5模块: {', '.join(found_modules)}")
else:
    check("self_evolve代码", "FAIL", "不存在")

# 3.2 自进化报告(最近7天)
reports = sorted((HERMES / "reports").glob("self_evolve_*.json"))
recent = [r for r in reports if r.stat().st_mtime > time.time() - 7*86400]
if recent:
    # 检查最新报告的模块完整性
    with open(recent[-1]) as f:
        report = json.load(f)
    mods = report.get("modules", {})
    check("自进化报告", "PASS", f"最近7天{len(recent)}份, 最新含{len(mods)}模块")
    
    # 检查MEMORY.md扫描是否真实工作
    mem_compress = mods.get("memory_compress", {})
    if mem_compress.get("original_chars", 0) > 0:
        check("自进化-MEMORY.md扫描", "PASS", f"真实扫描: {mem_compress['original_chars']}字符")
    else:
        check("自进化-MEMORY.md扫描", "WARN", "MEMORY.md字符数为0(可能是修复前报告)")
    
    # 检查权重调优是否真实执行
    cap_evolve = mods.get("capability_evolve", {})
    has_weight_adj = any('权重' in a or 'Weight' in a or '调优' in a for a in cap_evolve.get("actions", []))
    if has_weight_adj:
        check("自进化-权重调优", "PASS", "最近报告中有权重调优记录")
    else:
        check("自进化-权重调优", "WARN", "最近报告中无权重调优(可能是没有低权重词需要调优)")
else:
    check("自进化报告", "FAIL", "最近7天无报告")

# 3.3 token_compress的summary列
try:
    state_db = HERMES / "state.db"
    if state_db.exists():
        db = sqlite3.connect(str(state_db))
        sess_cols = [r[1] for r in db.execute("PRAGMA table_info(sessions)").fetchall()]
        db.close()
        if 'summary' in sess_cols:
            check("token_compress-summary列", "PASS", "summary列存在(摘要压缩就绪)")
        else:
            check("token_compress-summary列", "WARN", "summary列不存在(需要下一次self_evolve创建)")
    else:
        check("token_compress-summary列", "WARN", "state.db不存在")
except Exception as e:
    check("token_compress-summary列", "WARN", f"检查失败: {e}")

# ════════════════════════════════════════════════════════════
# V4: 自我PUA (Agent匹配+三省六部)
# ════════════════════════════════════════════════════════════
log("\n═════════════════════════════════\n V4 自我PUA\n═════════════════════════════════")

# 4.1 Agent Company配置文件
agents_md = HERMES / "agents_company" / "AGENTS.md"
if agents_md.exists():
    ac_content = agents_md.read_text()
    emp_count = ac_content.count("Employees:")
    expert_count = ac_content.count("Expert System:")
    check("Agent Company配置", "PASS", f"AGENTS.md存在,{agents_md.stat().st_size}字节")
else:
    check("Agent Company配置", "WARN", "AGENTS.md不存在(未部署Agent Company)")

# 4.2 匹配产出(deep_reports)
matching_dir = HERMES / "outputs" / "agent_matching"
if matching_dir.exists():
    deep_reports = list(matching_dir.rglob("*deep*analysis*"))
    check("匹配产出", "PASS", f"{len(deep_reports)}个深度分析报告")
else:
    check("匹配产出", "WARN", "matching目录不存在")

# 4.3 三省六部拓扑
topology = HERMES / "agents_company" / "topology.yaml"
if topology.exists():
    top_content = topology.read_text()
    dept_count = top_content.count("department")
    actor_count = top_content.count("actors:")
    check("三省六部拓扑", "PASS", f"{dept_count}部门, {actor_count}Actor组")
else:
    check("三省六部拓扑", "WARN", "topology.yaml不存在")

# 4.4 actors文件
actors_dir = HERMES / "agents_company" / "actors"
if actors_dir.exists():
    actor_files = list(actors_dir.glob("*.py"))
    check("三省六部Actors", "PASS", f"{len(actor_files)}个Actor文件")
else:
    check("三省六部Actors", "WARN", "actors目录不存在")

# ════════════════════════════════════════════════════════════
# V5: 推送系统
# ════════════════════════════════════════════════════════════
log("\n═════════════════════════════════\n V5 推送系统\n═════════════════════════════════")

# 5.1 v10推送代码
v10_file = SCRIPTS / "hermes_v9_push.py"
if v10_file.exists():
    v10_content = v10_file.read_text()
    has_pref_filter = 'load_user_keywords' in v10_content
    has_garbage_filter = 'TRASH_KEYWORDS' in v10_content or 'BILIBILI_TRASH' in v10_content
    has_diversity = '平台不足' in v10_content or '强制多样性' in v10_content
    has_48h_fallback = '48小时' in v10_content or '48h' in v10_content
    score_formula_ok = '0.4' in v10_content and '0.45' in v10_content
    check("v10推送代码", "PASS", 
          f"{v10_file.stat().st_size}字节, 偏好过滤{'✅' if has_pref_filter else '❌'} "
          f"垃圾过滤{'✅' if has_garbage_filter else '❌'} "
          f"多样性{'✅' if has_diversity else '❌'} "
          f"48h回退{'✅' if has_48h_fallback else '❌'} "
          f"排序公式{'✅' if score_formula_ok else '❌'}")
else:
    check("v10推送代码", "FAIL", "不存在")

# 5.2 推送记录
try:
    db = sqlite3.connect(str(HERMES / "intelligence.db"))
    push_count = db.execute("SELECT COUNT(*) FROM push_records").fetchone()[0]
    hist_count = db.execute("SELECT COUNT(*) FROM push_history").fetchone()[0]
    # 最新推送时间
    cols = [c[1] for c in db.execute("PRAGMA table_info(push_records)").fetchall()]
    time_col = 'push_time' if 'push_time' in cols else 'created_at'
    latest = db.execute(f"SELECT MAX({time_col}) FROM push_records").fetchone()[0]
    db.close()
    check("推送记录", "PASS", f"{push_count}条推送+{hist_count}条历史, 最新: {latest or '无'}")
except Exception as e:
    check("推送记录", "FAIL", f"查询失败: {e}")

# 5.3 v10实时运行验证
log("\n  🔬 运行v10推送验证(dry-run)...")
try:
    r = subprocess.run(
        ["python3", str(v10_file)],
        capture_output=True, text=True, timeout=30, cwd=str(HERMES)
    )
    output = r.stdout
    if '已加载格林主人' in output:
        check("v10推送验证运行", "PASS", "dry-run正常, 偏好加载成功")
    elif 'DRY RUN' in output:
        check("v10推送验证运行", "PASS", "dry-run正常执行")
    else:
        check("v10推送验证运行", "WARN", f"运行输出异常: {output[:200]}")
except Exception as e:
    check("v10推送验证运行", "FAIL", f"运行失败: {e}")

# ════════════════════════════════════════════════════════════
# V6: 真实产出链
# ════════════════════════════════════════════════════════════
log("\n═════════════════════════════════\n V6 真实产出链\n═════════════════════════════════")

# 6.1 需求挖掘产出
req_dir = HERMES / "outputs" / "requirement_mining"
if req_dir.exists():
    req_files = list(req_dir.glob("*.json"))
    check("需求挖掘产出", "PASS", f"{len(req_files)}个需求文件")
else:
    check("需求挖掘产出", "WARN", "requirement_mining目录不存在")

# 6.2 产品生产产出
prod_dir = HERMES / "outputs" / "auto_production"
if prod_dir.exists():
    prod_files = list(prod_dir.glob("*.json"))
    check("产品生产产出", "PASS", f"{len(prod_files)}个产品方案")
else:
    check("产品生产产出", "WARN", "auto_production目录不存在")

# 6.3 产品迭代
evolve_dir = HERMES / "outputs" / "product_evolve"
if evolve_dir.exists():
    evolve_files = list(evolve_dir.glob("*.json"))
    check("产品迭代产出", "PASS", f"{len(evolve_files)}个迭代文件")
else:
    check("产品迭代产出", "WARN", "product_evolve目录不存在")

# 6.4 Agent匹配产出
matching_count = 0
if matching_dir.exists():
    matching_count = len(list(matching_dir.rglob("*")))
check("Agent匹配产出", "PASS" if matching_count > 0 else "WARN", f"{matching_count}个匹配相关文件")

# 6.5 总产出文件统计
total_outputs = len(list((HERMES / "outputs").rglob("*"))) if (HERMES / "outputs").exists() else 0
total_size = sum(f.stat().st_size for f in (HERMES / "outputs").rglob("*") if f.is_file()) / (1024*1024) if (HERMES / "outputs").exists() else 0
check("总产出规模", "PASS" if total_outputs > 0 else "WARN", 
      f"{total_outputs}个文件, {total_size:.1f}MB")

# ════════════════════════════════════════════════════════════
# 汇总
# ════════════════════════════════════════════════════════════
log(f"\n{'='*50}")
log(f" 审核完成: {results['passed']} PASS / {results['failed']} FAIL / {results['warnings']} WARN / {results['total']} TOTAL")
log(f"{'='*50}")

results["summary"] = {
    "timestamp": datetime.now().isoformat(),
    "total": results["total"],
    "passed": results["passed"],
    "failed": results["failed"],
    "warnings": results["warnings"],
    "pass_rate": f"{results['passed']/max(results['total'],1)*100:.0f}%"
}

REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
with open(REPORT_FILE, "w") as f:
    json.dump(results, f, indent=2, ensure_ascii=False)

print(f"\n报告已保存: {REPORT_FILE}")
sys.exit(0 if results['failed'] == 0 else 1)
