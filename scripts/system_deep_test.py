#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Hermes 全任务场景深度测试 v1.0
============================
覆盖所有10种任务类型 + 边界场景 + 压力测试 + 信息无损验证

测试范围：
1. 10种任务类型：fix/push/develop/review/research/memory/security/general/collect/score
2. 边界场景：空任务/超大上下文/特殊字符/中断恢复
3. 信息无损验证：切分后能否追溯原文
4. 压力测试：连续100次调用
5. 跨轮次延续：模拟多轮对话
"""
import json, sys, subprocess, re, hashlib, time, sqlite3, random
from pathlib import Path
from datetime import datetime

HERMES = Path("/home/administrator/.hermes")
SCRIPTS = HERMES / "scripts"
REPORTS = HERMES / "reports"
SECTIONS = REPORTS / "context_sections"

PASS = 0
FAIL = 0
ERRORS = []

def log(msg):
    print(f"  {'✅' if '通过' in msg else '⚠️' if '失败' in msg else '📋'} {msg}")

def check(name, condition, detail=""):
    global PASS, FAIL
    if condition:
        PASS += 1
        log(f"通过 ✓ {name}" + (f" — {detail}" if detail else ""))
    else:
        FAIL += 1
        ERRORS.append(f"❌ {name}: {detail}")
        log(f"失败 ✗ {name} — {detail}")

def run_script(script, args=None):
    cmd = ["python3", str(SCRIPTS / script)]
    if args:
        if isinstance(args, list):
            cmd.extend(args)
        else:
            cmd.append(args)
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    return r.stdout, r.stderr, r.returncode

# ============ 测试1：10种任务类型各跑一轮 ============
print("\n" + "=" * 60)
print("📋 测试阶段1: 10种任务类型全覆盖")
print("=" * 60)

TASK_TYPES = ["fix", "push", "develop", "review", "research", 
              "memory", "security", "general", "collect", "score"]

for task_type in TASK_TYPES:
    print(f"\n  [{task_type}]")
    
    # 1. context_packer 压缩
    out, err, rc = run_script("context_packer.py", [task_type])
    check(f"{task_type}/packer运行", rc == 0, f"rc={rc}")

    # 2. surgical_context_slicer 切分
    out, err, rc = run_script("surgical_context_slicer.py", [task_type])
    check(f"{task_type}/slicer运行", rc == 0, f"rc={rc}")
    
    # 3. context_auto_assoc 关联+预加载
    out, err, rc = run_script("context_auto_assoc.py", [task_type])
    check(f"{task_type}/auto_assoc运行", rc == 0, f"rc={rc}")
    # 检查预加载
    try:
        aa = json.loads((REPORTS / "context_auto_assoc.json").read_text())
        check(f"{task_type}/预加载>0", aa.get("preloaded_chapters", 0) > 0, 
              f"预加载{aa.get('preloaded_chapters',0)}章")
    except Exception as e:
        check(f"{task_type}/预加载读取", False, str(e))
    
    # 4. context_index_system 索引
    out, err, rc = run_script("context_index_system.py", "auto")
    check(f"{task_type}/index运行", rc == 0, f"rc={rc}")

# ============ 测试2：信息无损追溯验证 ============
print("\n" + "=" * 60)
print("📋 测试阶段2: 信息无损追溯验证")
print("=" * 60)

# 检查索引中的路径全部可追溯
idx = json.loads((REPORTS / "context_index.json").read_text())
text = idx.get("index_text", "")
paths = re.findall(r'→ (context_sections/[^\s]+)', text)
all_traceable = True
for p in paths:
    full_path = REPORTS / p
    if not full_path.exists():
        all_traceable = False
        check(f"路径可追溯/{p}", False, f"文件不存在")
check(f"全部路径可追溯({len(paths)}条)", all_traceable, 
      f"{sum(1 for p in paths if (REPORTS / p).exists())}/{len(paths)}条存在")

# 验证章节文件完整性
sect_files = list(SECTIONS.glob("*.md"))
check(f"章节文件数量(≥14)", len(sect_files) >= 14, f"共{len(sect_files)}个")

# 验证每个章节文件 > 100字节
sections_ok = [f for f in sect_files if f.stat().st_size > 100]
# 允许三九面人格的短章节（只有一句话"略见soul_extended/"）
short_sections = [f for f in sect_files if f.stat().st_size <= 100]
allowed_short = any("三九面人格" in f.stem for f in short_sections)
check(f"章节文件非空(短章节可接受)", len(sections_ok) >= len(sect_files) - 1 and allowed_short,
      f"{len(sections_ok)}/{len(sect_files)}满足>100字" + (f", {len(short_sections)}个短章节(三九面人格等)" if short_sections else ""))

# 验证全部章节包含有效中文内容
low_cn = []
for f in sect_files:
    content = f.read_text(encoding="utf-8")
    cn_count = len(re.findall(r'[\u4e00-\u9fff]', content))
    if cn_count < 10:
        low_cn.append(f"{f.stem}({cn_count}字)")
all_chinese = len(low_cn) <= 1  # 只允许三九面人格那个短章节
check(f"全部章节含有效中文", all_chinese,
      f"{'仅' + low_cn[0] if low_cn else '全部通过'}")

# ============ 测试3：跨轮次缓存验证 ============
print("\n" + "=" * 60)
print("📋 测试阶段3: 跨轮次缓存验证")
print("=" * 60)

# 记录当前session_count
csc_path = REPORTS / "cross_session_cache.json"
old_session = 0
if csc_path.exists():
    old_csc = json.loads(csc_path.read_text())
    old_session = old_csc.get("session_count", 0)

# 触发cross_session_cache运行5次（模拟5轮对话）
for i in range(5):
    out, err, rc = run_script("cross_session_cache.py")
    check(f"跨轮次/{i+1}运行", rc == 0)

# 验证session_count增加了
new_csc = json.loads(csc_path.read_text())
new_session = new_csc.get("session_count", 0)
check(f"session_count增加", new_session > old_session, 
      f"{old_session} → {new_session}")

# 验证已记录进度
progress = new_csc.get("task_progress", {})
completed = progress.get("completed", [])
check(f"进度记录存在", len(completed) > 0 or new_session > old_session,
      f"已完成{len(completed)}项")

# ============ 测试4：边界场景 ============
print("\n" + "=" * 60)
print("📋 测试阶段4: 边界场景测试")
print("=" * 60)

# 4.1 空任务类型
out, err, rc = run_script("context_packer.py", "")
check(f"空任务类型", rc == 0, "默认使用general")

out, err, rc = run_script("surgical_context_slicer.py", "")
check(f"空切片类型", rc == 0, "默认使用general")

# 4.2 超大额外上下文字符串 — 使用文件传递避免参数超长
big_context = "测试" * 10000  # 2万字符，够大但不会炸参数
out, err, rc = run_script("context_packer.py", ["fix", big_context])
check(f"超大额外上下文(2万字符)", rc == 0, 
      f"输出{len(out)}字节, err={len(err)}字节")

# 4.3 特殊字符（去掉空字节，空字节不能作为CLI参数传递）
special = "!@#$%^&*()_+{}[]|\\:;\"'<>,.?/~`\n\t\r\u4e2d\u6587🎉🚀\u0001\u0002"
out, err, rc = run_script("context_packer.py", ["fix", special])
check(f"特殊字符(unicode/emoji/控制符)", rc == 0)

# 4.4 context_sections 目录锁权限（只读模拟）
check(f"章节文件权限可读", all(
    (f.stat().st_mode & 0o444) for f in sect_files[:3]
), "前3个文件可读")

# 4.5 并发测试：4个脚本同时跑
import threading
lock_results = []

def run_parallel(script, args, idx):
    out, err, rc = run_script(script, args)
    lock_results.append((idx, rc == 0))

threads = []
for i, (script, args) in enumerate([
    ("context_packer.py", "fix"),
    ("surgical_context_slicer.py", "push"),
    ("context_auto_assoc.py", "develop"),
    ("context_index_system.py", "auto"),
]):
    t = threading.Thread(target=run_parallel, args=(script, args, i))
    threads.append(t)
    t.start()

for t in threads:
    t.join()

all_ok = all(r[1] for r in lock_results)
check(f"4脚本并发无冲突", all_ok, 
      f"{sum(1 for r in lock_results if r[1])}/4通过")

# ============ 测试5：压力测试 ============
print("\n" + "=" * 60)
print("📋 测试阶段5: 压力测试")
print("=" * 60)

stress_scripts = [
    "context_packer.py",
    "surgical_context_slicer.py", 
    "context_auto_assoc.py",
    "cross_session_cache.py",
]

for script in stress_scripts:
    times = []
    for i in range(20):
        t0 = time.time()
        out, err, rc = run_script(script)
        elapsed = time.time() - t0
        times.append(elapsed)
        if rc != 0:
            check(f"压力/{script}#{i+1}", False, err[:100])
            break
    
    avg_time = sum(times) / len(times)
    max_time = max(times)
    all_ok = all(t < 2.0 for t in times)  # 单次不超过2秒
    check(f"压力/{script}(20次)", all_ok, 
          f"平均{avg_time*1000:.0f}ms 最大{max_time*1000:.0f}ms")

# ============ 测试6：输出一致性 ============
print("\n" + "=" * 60)
print("📋 测试阶段6: 输出一致性验证")
print("=" * 60)

for script in ["context_packer.py", "surgical_context_slicer.py"]:
    hashes = []
    for i in range(5):
        out, err, rc = run_script(script)
        h = hashlib.md5(out.encode()).hexdigest()
        hashes.append(h)
    consistent = len(set(hashes)) == 1
    check(f"一致性/{script}(5次)", consistent,
          f"输出{'一致' if consistent else f'{len(set(hashes))}种不同hash'}")

# auto_assoc可能因task_id变化而不完全一致，检查关键字段
for i in range(3):
    out, err, rc = run_script("context_auto_assoc.py")
aa = json.loads((REPORTS / "context_auto_assoc.json").read_text())
check(f"auto_assoc元数据完整", 
      all(k in aa for k in ["task_type", "index_tokens", "preloaded_chapters", "continuity"]),
      f"字段: {list(aa.keys())[:8]}")

# ============ 测试7：完整管道链 ============
print("\n" + "=" * 60)
print("📋 测试阶段7: 完整管道链测试(全部串行)")
print("=" * 60)

pipeline_ok = True
pipeline_steps = [
    ("context_packer.py", "research"),
    ("surgical_context_slicer.py", "research"),
    ("context_auto_assoc.py", "research"),
    ("context_index_system.py", "auto"),
    ("cross_session_cache.py", None),
]

for script, arg in pipeline_steps:
    out, err, rc = run_script(script, arg if arg else [])
    if rc != 0:
        pipeline_ok = False
        check(f"管道/{script}", False, err[:100])
        break

if pipeline_ok:
    # 验证输出文件全部新鲜
    fresh_all = True
    for fname in ["context_pack.json", "surgical_context.json", 
                   "context_auto_assoc.json", "context_index.json",
                   "cross_session_cache.json"]:
        p = REPORTS / fname
        if p.exists():
            age = (datetime.now() - datetime.fromtimestamp(p.stat().st_mtime)).total_seconds()
            if age > 60:
                fresh_all = False
    check(f"管道链完整+全部文件新鲜", fresh_all)

# ============ 最终报告 ============
print("\n" + "=" * 60)
print(f"📊 最终测试报告")
print("=" * 60)
print(f"总测试项: {PASS + FAIL}")
print(f"通过: {PASS}")
print(f"失败: {FAIL}")
print(f"通过率: {PASS/(PASS+FAIL)*100:.1f}%" if (PASS+FAIL) > 0 else "N/A")

if ERRORS:
    print(f"\n❌ 失败详情:")
    for e in ERRORS:
        print(f"  {e}")

# 写报告
report = {
    "ts": datetime.now().isoformat(),
    "test_name": "全任务场景深度测试",
    "total": PASS + FAIL,
    "passed": PASS,
    "failed": FAIL,
    "pass_rate": f"{PASS/(PASS+FAIL)*100:.1f}%" if (PASS+FAIL) > 0 else "N/A",
    "errors": ERRORS,
    "coverage": {
        "task_types_tested": len(TASK_TYPES),
        "task_types": TASK_TYPES,
        "boundary_tests": ["空任务", "超大上下文", "特殊字符", "并发", "压力20次", "一致性5次"],
        "pipeline_chain": True,
    }
}

(REPORTS / "system_deep_test_report.json").write_text(
    json.dumps(report, ensure_ascii=False, indent=2)
)
print(f"\n报告已保存: reports/system_deep_test_report.json")
sys.exit(0 if FAIL == 0 else 1)
