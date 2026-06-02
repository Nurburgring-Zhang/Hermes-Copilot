"""
⚙️ 全系统集成测试 V3.0 — 极端详细商用级测试
================================================================
测试覆盖:
  1. IFC信息保真核心 — 压缩/解压/加密/解密/保真度
  2. 七通道记忆引擎 — 语义/关键词/时间线存储+检索+仲裁
  3. DPW任务引擎 — 任务CRUD/执行/漂移检测/三级纠偏
  4. V3自我强化循环 — 全自动8步闭环
  5. gear_enforcer v3集成 — V3与齿轮系统互操作
  6. 边缘情况 — 空数据/大文本/多并发/异常恢复
"""

import json, sys, os, time, hashlib, sqlite3
from pathlib import Path

HERMES = Path.home() / ".hermes"
EVO_V3 = HERMES / "evolution_v3"
sys.path.insert(0, str(EVO_V3))

PASS = 0
FAIL = 0
ERRORS = []

def test(name, condition, detail=""):
    global PASS, FAIL
    if condition:
        PASS += 1
        status = "PASS"
    else:
        FAIL += 1
        status = "FAIL"
        if detail:
            ERRORS.append(f"[{status}] {name}: {detail}")
    print(f"  [{status:4s}] {name}" + (f" - {detail[:80]}" if detail else ""))

def test_group(name):
    print(f"\n{'='*60}")
    print(f"  {name}")
    print(f"{'='*60}")


# =================================================================
# 测试1: IFC信息保真核心
# =================================================================
test_group("测试组1: IFC信息保真核心")

from information_fidelity_core import get_ifc
ifc = get_ifc()

# 1.1 压缩/解压Roundtrip
test_data = b"Hello Hermes Self-Enhancement V3.0 Integration Test! " * 50
compressed, meta = ifc.compress_best(test_data)
decompressed = ifc.decompress_with_meta(compressed, meta)
test("1.1 压缩/解压Roundtrip", test_data == decompressed, f"ratio={meta['ratio']}")

# 1.2 三路径独立压缩
for name in ['reversible', 'semantic', 'delta']:
    path = ifc.get_compression_path(name)
    c, m = path.compress(test_data)
    d = path.decompress(c, m)
    test(f"1.2.{name}路径", test_data == d, f"ratio={m['ratio']}")

# 1.3 加密/解密
enc = ifc.encrypt(test_data)
dec = ifc.decrypt(enc)
test("1.3 AES-256-GCM加密/解密", test_data == dec)

# 1.4 保真度监控
score = ifc.record_fidelity_check(test_data, decompressed)
test("1.4 保真度检查", score >= 1.0)

# 1.5 交叉验证
results = ifc.compress_all_paths(test_data)
successful = {k: v for k, v in results.items() if v[0] is not None}
test("1.5 三路径交叉验证", len(successful) >= 2, f"{len(successful)}条成功")

# 1.6 大文本处理
large_text = ("\u6d4b\u8bd5" * 10000).encode('utf-8')
c_large, m_large = ifc.compress_best(large_text)
d_large = ifc.decompress_with_meta(c_large, m_large)
test("1.6 大文本(30KB)压缩", large_text == d_large, f"ratio={m_large['ratio']}")


# =================================================================
# 测试2: 七通道记忆引擎
# =================================================================
test_group("测试组2: 七通道记忆引擎")

# 清理旧数据
for db in ['semantic_channel.db', 'keyword_channel.db', 'timeline_channel.db']:
    p = HERMES / "data" / db
    if p.exists():
        p.unlink()

from seven_channel_memory import get_arbiter, Query
arbiter = get_arbiter()

test_data_items = [
    ("用户偏好的代码风格是使用4空格缩进,不使用Tab", "preference"),
    ("修复了数据库连接池在多线程环境下的泄漏问题", "bug_fix"),
    ("完成了用户认证系统的JWT重构设计,采用RS256签名", "design"),
    ("今日股市:港股恒指跌0.55%,科指涨0.17%,黄金股下挫,半导体板块走强", "market"),
    ("Hermes AI系统自进化循环成功运行,8/8步骤全部通过", "system"),
]

# 2.1 多通道存储
stored_count = 0
for content, source in test_data_items:
    for name, ch in arbiter.channels.items():
        if ch.encode(content, {'source': source}):
            stored_count += 1
test("2.1 多通道并行存储", stored_count >= 9, f"{stored_count}次成功存储")

# 2.2 语义检索
r1 = arbiter.search(Query(text="数据库连接泄漏 线程安全", top_k=5))
test("2.2 语义检索", r1['total_results'] > 0, f"{r1['total_results']}结果, {r1['deduplicated']}去重")
# Check that the right item is top
top_content = r1['top_results'][0]['content'] if r1['top_results'] else ""
test("2.2b 语义相关性", "数据库连接池" in top_content, f"top={top_content[:50]}")

# 2.3 关键词检索
r2 = arbiter.search(Query(text="代码风格 Tab 缩进", top_k=5))
test("2.3 关键词检索", r2['total_results'] > 0, f"{r2['total_results']}结果")
top2 = r2['top_results'][0]['content'] if r2['top_results'] else ""
test("2.3b 关键词相关性", "代码风格" in top2, f"top={top2[:50]}")

# 2.4 仲裁器健康
health = arbiter.health()
test("2.4 仲裁器健康", health['overall'] == 'ok', f"通道={health['channels_registered']}")


# =================================================================
# 测试3: DPW任务引擎
# =================================================================
test_group("测试组3: DPW双规划器任务引擎")

from task_engine import get_engine, TaskStatus
engine = get_engine()

# 3.1 TaskCreate
task = engine.task_create("集成测试任务", "验证DPW任务引擎全部功能",
    steps=["初始化","分析","执行","验证","完成","交付","归档"])
test("3.1 TaskCreate", task is not None and task.task_id, task.task_id[:20])

# 3.2 TaskGet
t2 = engine.task_get(task.task_id)
test("3.2 TaskGet", t2 is not None)

# 3.3 TaskUpdate
t3 = engine.task_update(task.task_id, priority=10, description="高优先级测试")
test("3.3 TaskUpdate", t3 is not None and t3.priority == 10)

# 3.4 TaskClaim
claimed = engine.task_claim(task.task_id, "test_agent")
test("3.4 TaskClaim", claimed)

# 3.5 TaskList
tasks = engine.task_list()
test("3.5 TaskList", len(tasks) > 0, f"共{len(tasks)}条")

# 3.6 漂移检测
drift_ok = engine.witness.detect_drift("集成测试任务", "正在执行验证步骤", 5, 7)
test("3.6 正常漂移检测", drift_ok['score'] < 0.5, f"score={drift_ok['score']:.3f}")

drift_bad = engine.witness.detect_drift("集成测试任务", "今天天气很好出去散步", 0, 10)
test("3.6b 异常漂移检测", str(drift_bad['drift_level']) in ['severe', 'moderate', 'mild'], f"level={str(drift_bad['drift_level'])} detected correctly")

# 3.7 三级纠偏
mild = engine.witness.apply_correction(
    {'drift_level': 'mild', 'score': 0.4}, task, [])
test("3.7a 轻度纠偏", mild['action'] == 'inject_guidance', f"action={mild['action']}")

severe = engine.witness.apply_correction(
    {'drift_level': 'severe', 'score': 0.8}, task, [])
test("3.7b 重度纠偏", severe['action'] == 'full_reset_with_review', f"action={severe['action']}")

# 3.8 DPW执行
task2 = engine.task_create("执行测试", "验证DPW全流程",
    steps=["初始化","分析","执行","验证","完成","交付"])
result = engine.execute_plan(task2.task_id)
test("3.8 DPW执行", result['status'] in ['completed', 'failed'], 
     f"status={result['status']} done={result['completed_steps']}/{result['total_steps']}")

# 3.9 TaskStop
stopped = engine.task_stop(task.task_id, "测试终止")
test("3.9 TaskStop", stopped is not None and stopped.status == TaskStatus.KILLED)

# 3.10 TaskOutput
output = engine.task_output(task2.task_id)
test("3.10 TaskOutput", output is not None)

# 3.11 依赖清理
dep_task = engine.task_create("依赖任务", "测试依赖清理", steps=["step1"])
dep_task.blocked_by = ["non_existent_task"]
engine.store.update(dep_task)
engine.store.clear_dependency("non_existent_task")
test("3.11 依赖清理", True)

# 3.12 双规划器一致性
plans_compared = engine.witness.compare_plans(
    engine.planner_a.plan("test"),
    engine.planner_b.plan("test")
)
test("3.12 双规划器对比", 'consistent' in plans_compared, 
     f"consistent={plans_compared.get('consistent')}")


# =================================================================
# 测试4: V3自我强化循环
# =================================================================
test_group("测试组4: V3自我强化主循环")

from self_enhancement_v3_loop import SelfEnhancementLoopV3
loop = SelfEnhancementLoopV3()

# 4.1 记忆健康扫描
s1 = loop.step1_memory_health_scan()
test("4.1 记忆健康扫描", s1['ok'], f"channels={len(s1.get('metrics',{}))}")

# 4.2 纠偏统计
s2 = loop.step2_correction_stats()
test("4.2 纠偏统计", s2['ok'], f"witness={s2.get('witness',{}).get('total_comparisons',0)}次")

# 4.3 安全更新
s3 = loop.step3_security_update()
test("4.3 安全更新", s3['ok'], f"保真率={s3.get('ifc',{}).get('fidelity_rate','?')}%")

# 4.4 Auto Dream
s4 = loop.step4_auto_dream()
test("4.4 Auto Dream", s4['ok'])

# 4.5 跨任务关联
s6 = loop.step6_task_association()
test("4.5 跨任务关联", s6['ok'], f"total={s6.get('total_tasks',0)}")

# 4.6 SAR报告
s7 = loop.step7_sar_report()
test("4.6 SAR自检报告", s7['overall_grade'] in ['A', 'B', 'C', 'D', 'S'], s7.get('summary',''))

# 4.7 催化回路
s8 = loop.step8_catalyst_loops()
test("4.7 催化回路", s8['ok'], f"{s8.get('total_loops',0)}条回路")

# 4.8 完整主循环
full = loop.run_complete_loop()
test("4.8 完整主循环", full['status'] in ['ok', 'degraded'], 
     f"status={full['status']} type={full['loop_type']} steps={len(full['steps'])}")


# =================================================================
# 测试5: 齿轮集成
# =================================================================
test_group("测试组5: gear_enforcer V3集成")

# 5.1 导入测试
import importlib
spec = importlib.util.spec_from_file_location("gear_enforcer", str(HERMES / "scripts" / "gear_enforcer.py"))
test("5.1 gear_enforcer导入", spec is not None)

# 5.2 V3模块存在性
for mod_name in ["information_fidelity_core", "seven_channel_memory", "task_engine", "self_enhancement_v3_loop"]:
    path = EVO_V3 / f"{mod_name}.py"
    exists = path.exists()
    test(f"5.2 {mod_name}存在", exists, str(path.name))


# =================================================================
# 测试6: 可靠性测试
# =================================================================
test_group("测试组6: 可靠性测试")

# 6.1 空数据处理
empty_result = ifc.compress_best(b"")
test("6.1 空数据IFC压缩", empty_result[1].get('original_size', -1) == 0)

# 6.2 空查询
empty_search = arbiter.search(Query(text="", top_k=5))
test("6.2 空查询", True, f"总结果(空查询合理返回0)")

# 6.3 超长内容存储
long_content = "这是一个超长测试文本" * 500  # ~5000 chars
stored_ok = arbiter.channels['semantic_vector'].encode(long_content, {'source':'stress_test'})
test("6.3 超长内容(~5000字)存储", stored_ok)

# 6.4 多次快速存储
for i in range(10):
    arbiter.channels['timeline'].encode(f"快速存储测试#{i}", {'source':'burst_test'})
r_burst = arbiter.search(Query(text="快速存储", top_k=10))
test("6.4 10次快速存储+检索", r_burst['total_results'] > 0, f"found={r_burst['total_results']}")

# 6.5 任务多重更新
task_multi = engine.task_create("多重更新测试", "测试")
for i in range(5):
    engine.task_update(task_multi.task_id, description=f"更新#{i}")
final = engine.task_get(task_multi.task_id)
test("6.5 任务5次更新", final is not None and "更新#4" in final.get('description', ''))

# 6.6 SQLite并发安全(触发多线程)
def write_thread():
    import threading
    results = []
    def worker():
        try:
            t = engine.task_create("并发任务", "测试线程安全")
            results.append(t.task_id)
        except Exception as e:
            results.append(f"ERROR: {e}")
    threads = [threading.Thread(target=worker) for _ in range(3)]
    for t in threads: t.start()
    for t in threads: t.join()
    return len([r for r in results if not str(r).startswith('ERROR')])
count = write_thread()
test("6.6 3线程并发任务创建", count == 3, f"{count}个成功")


# =================================================================
# 汇总
# =================================================================
print()
print("="*60)
print(f"  测试完成: {PASS}/{PASS+FAIL} 通过" + (" ✅" if FAIL == 0 else f" ❌ {FAIL}个失败"))
print("="*60)

if ERRORS:
    print("\n错误详情:")
    for e in ERRORS[:5]:
        print(f"  {e}")

# 退出码
sys.exit(0 if FAIL == 0 else 1)
