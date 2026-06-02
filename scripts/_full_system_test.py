#!/usr/bin/env python3
"""
Hermes 全系统深度测试 v1.0
测试所有功能管线,cron,服务的实际产出
"""
import sqlite3, json, subprocess, time, os, sys
from pathlib import Path
from datetime import datetime

HERMES = Path("/home/administrator/.hermes")
SCRIPTS = HERMES / "scripts"
DB_PATH = HERMES / "intelligence.db"
STATE_DB = HERMES / "state.db"

results = []
pass_count = 0
fail_count = 0

def test(name, result, detail=""):
    global pass_count, fail_count
    status = "✅" if result else "❌"
    if result:
        pass_count += 1
    else:
        fail_count += 1
    results.append(f"{status} {name}: {detail}")
    print(f"{status} {name}: {detail}")

def run(cmd, timeout=30):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "timeout"
    except Exception as e:
        return -1, "", str(e)

print("=" * 60)
print("  Hermes 全系统深度测试")
print(f"  开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print("=" * 60)

# ── 1. 数据库健康 ───────────────────────────────────────────
print("\n📦 1. 数据库健康")
conn = sqlite3.connect(str(DB_PATH), timeout=5)

try:
    raw_count = conn.execute("SELECT COUNT(*) FROM raw_intelligence").fetchone()[0]
    cleaned_count = conn.execute("SELECT COUNT(*) FROM cleaned_intelligence").fetchone()[0]
    push_count = conn.execute("SELECT COUNT(*) FROM push_records").fetchone()[0]
    test("数据库可连接", True, f"raw={raw_count}, cleaned={cleaned_count}, push={push_count}")
    
    # 检查今日采集
    today_raw = conn.execute("SELECT COUNT(*) FROM raw_intelligence WHERE datetime(collected_at) >= datetime('now', '-24 hours')").fetchone()[0]
    test("今日有新采集", today_raw > 100, f"{today_raw}条(要求>100)")
    
    # 检查今日清洗
    today_cleaned = conn.execute("SELECT COUNT(*) FROM cleaned_intelligence WHERE datetime(cleaned_at) >= datetime('now', '-24 hours')").fetchone()[0]
    test("今日有新清洗", today_cleaned > 50, f"{today_cleaned}条(要求>50)")
    
    # 检查今日推送
    today_pushed = conn.execute("SELECT COUNT(*) FROM push_records WHERE datetime(push_time) >= datetime('now', '-24 hours')").fetchone()[0]
    test("今日有推送", today_pushed > 0, f"{today_pushed}条")
    
    # 各平台分布(确认多平台覆盖)
    platforms = conn.execute("SELECT platform, COUNT(*) FROM raw_intelligence WHERE datetime(collected_at) >= datetime('now', '-24 hours') GROUP BY platform ORDER BY COUNT(*) DESC").fetchall()
    test("多平台覆盖", len(platforms) >= 10, f"{len(platforms)}个平台")
    for p, c in platforms[:5]:
        print(f"    {p}: {c}条")
    
    # 检查新采集器是否有数据
    new_platforms = ["sina_tech", "zhihu_daily", "tieba"]
    for np_name in new_platforms:
        count = conn.execute("SELECT COUNT(*) FROM raw_intelligence WHERE platform=? AND datetime(collected_at) >= datetime('now', '-24 hours')", (np_name,)).fetchone()[0]
        test(f"新采集器 {np_name}", count > 0, f"{count}条")
    
except Exception as e:
    test("数据库检查", False, str(e))
finally:
    conn.close()

# ── 2. Cron任务 ─────────────────────────────────────────────
print("\n⏰ 2. Cron任务状态")
try:
    sys.path.insert(0, str(SCRIPTS))
    # 用state.db直接查cron
    sconn = sqlite3.connect(str(STATE_DB))
    try:
        cron_count = sconn.execute("SELECT COUNT(*) FROM cron_jobs").fetchone()[0]
        enabled_count = sconn.execute("SELECT COUNT(*) FROM cron_jobs WHERE enabled=1").fetchone()[0]
        ok_count = sconn.execute("SELECT COUNT(*) FROM cron_jobs WHERE last_status='ok'").fetchone()[0]
        test("Cron任务总数", cron_count >= 15, f"{cron_count}个, 启用{enabled_count}个, 最近ok{ok_count}个")
    except:
        # 尝试其他表名
        tables = sconn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        test("Cron表查询", False, f"表: {[t[0] for t in tables]}")
    sconn.close()
except Exception as e:
    test("Cron检查", False, str(e))

# ── 3. 采集器测试 ───────────────────────────────────────────
print("\n🔧 3. 采集器功能测试")
# 测试几个关键采集器能否成功调用
from importlib import import_module
try:
    sys.path.insert(0, str(SCRIPTS))
    col = __import__("hermes_collector_v6")
    
    test_collectors = [
        ("知乎日报", "collect_zhihu_daily", 0),
        ("新浪科技", "collect_sina_tech", 5),
        ("贴吧", "collect_tieba", 10),
        ("B站", "collect_bilibili", 5),
        ("爱范儿RSS", "collect_ifanr_v2", 5),
        ("36氪", "collect_36kr", 5),
    ]
    
    for name, fn_name, min_items in test_collectors:
        fn = getattr(col, fn_name, None)
        if fn:
            try:
                items = fn()
                count = len(items)
                test(f"采集器 {name}", count >= min_items, f"{count}条")
            except Exception as e:
                test(f"采集器 {name}", False, str(e)[:80])
        else:
            test(f"采集器 {name}", False, "函数不存在")
except Exception as e:
    test("采集器测试", False, str(e)[:100])

# ── 4. 清洗管道测试 ─────────────────────────────────────────
print("\n🧹 4. 清洗管道功能测试")
try:
    pipe = __import__("unified_cleaning_pipeline")
    # 小批量测试
    r = pipe.clean_batch(batch_size=200, max_batches=1)
    test("清洗管道可执行", r["total_processed"] > 0, f"处理{r['total_processed']}条, 清洗{r['new_cleaned']}条")
except Exception as e:
    test("清洗管道", False, str(e)[:100])

# ── 5. 推送测试 ─────────────────────────────────────────────
print("\n📨 5. 推送功能测试")
try:
    push = __import__("unified_pusher")
    # 检查配置文件存在
    config_file = HERMES / "config.yaml"
    test("推送配置文件存在", config_file.exists(), str(config_file))
    
    # 检查推送函数可调用
    has_push_new = hasattr(push, "push_new")
    has_push_daily = hasattr(push, "push_daily")
    test("推送函数就绪", has_push_new and has_push_daily, "push_new + push_daily")
except Exception as e:
    test("推送测试", False, str(e)[:100])

# ── 6. Active Memory ────────────────────────────────────────
print("\n🧠 6. Active Memory引擎")
try:
    am = __import__("active_memory")
    am_instance = am.ActiveMemory()
    test("ActiveMemory可加载", True, "")
    
    # 测试分类功能
    test_result = am_instance.classify("华为发布新一代麒麟芯片,AI算力提升3倍")
    cat_count = len(test_result)
    test("分类功能正常", cat_count > 0, f"分类到{cat_count}个类别")
except Exception as e:
    test("Active Memory", False, str(e)[:100])

# ── 7. 文件完整性 ───────────────────────────────────────────
print("\n📁 7. 核心文件完整性")
core_files = [
    "hermes_collector_v6.py",
    "unified_cleaning_pipeline.py",
    "unified_pusher.py",
    "active_memory.py",
    "master_v6_pipeline.py",
]
for fname in core_files:
    fpath = SCRIPTS / fname
    exists = fpath.exists()
    size = fpath.stat().st_size if exists else 0
    test(f"文件 {fname}", exists and size > 1000, f"{size}字节")

# ── 8. 智能情报价值 ─────────────────────────────────────────
print("\n💎 8. 情报价值质量检查")
conn = sqlite3.connect(str(DB_PATH), timeout=5)
try:
    quality_items = conn.execute("""
        SELECT title, importance_score, value_level, value_reasons
        FROM cleaned_intelligence
        WHERE datetime(cleaned_at) >= datetime('now', '-24 hours')
          AND importance_score > 0
        ORDER BY importance_score DESC
        LIMIT 5
    """).fetchall()
    
    test("高价值情报存在", len(quality_items) > 0, f"{len(quality_items)}条高价值情报")
    for title, score, level, reason in quality_items[:3]:
        print(f"    [{level}★] {score}: {title[:50]}... → {reason[:40]}")
except Exception as e:
    test("质量检查", False, str(e)[:80])
finally:
    conn.close()

# ── 总结 ────────────────────────────────────────────────────
print("\n" + "=" * 60)
print(f"  深度测试完成")
print(f"  {pass_count} ✅  |  {fail_count} ❌  |  总计 {pass_count + fail_count} 项")
print(f"  时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print("=" * 60)
print("\n详细结果:")
for r in results:
    print(f"  {r}")
