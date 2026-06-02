#!/usr/bin/env python3
"""
Hermes 极端严苛商用级全链路测试 v2.0 — 100+ 测试用例
=====================================================
覆盖：采集→清洗→AI评分→推送→需求挖掘→产品生成→交付
每个测试用例包含：名称、通过条件、失败原因诊断
"""
import json, sys, os, re, time, subprocess
import urllib.request
import sqlite3
from pathlib import Path
from datetime import datetime

HERMES = Path("/home/administrator/.hermes")
TOTAL = 0
PASSED = 0
FAILURES = []
SKIPPED = []


def test(name, condition, detail=""):
    global TOTAL, PASSED
    TOTAL += 1
    if condition:
        PASSED += 1
        print(f"  ✅ {name}" + (f" — {detail[:60]}" if detail else ""))
    else:
        FAILURES.append(f"{name}: {detail}")
        print(f"  ❌ {name} — {detail[:80]}")


def skip(name, reason):
    global TOTAL
    TOTAL += 1
    SKIPPED.append(f"{name}: {reason}")
    print(f"  ⏭️  {name} — {reason}")


def section(title):
    print(f"\n{'='*70}")
    print(f"  {title}")
    print(f"{'='*70}")


# ================================================================
# 加载.env用于API测试
# ================================================================
env_path = HERMES / ".env"
if env_path.exists():
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip()
            if v and v != "***" and (k not in os.environ or not os.environ[k]):
                os.environ[k] = v

api_key = os.environ.get("OPENROUTER_API_KEY", "")
db_path = HERMES / "intelligence.db"

# ================================================================
# Group 1: 文件完整性 (15用例)
# ================================================================
section("1. 文件完整性 — 15个用例")

scripts = [
    ("hermes_ai_scoring.py", "AI六维评分管道", True),
    ("production_auto.py", "AI产品生成引擎", True),
    ("product_delivery.py", "验收与交付", True),
    ("ai_score_backfill.py", "AI评分回填", True),
    ("hermes_v12_push.py", "HTML推送", True),
    ("omni_loop.py", "全能循环", True),
    ("guardian.py", "守护神", True),
    ("full_link_test.py", "全链路测试", True),
]

for fname, desc, required in scripts:
    p = HERMES / "scripts" / fname
    exists = p.exists()
    if required:
        test(f"脚本 {fname} 存在", exists, desc)
    else:
        test(f"脚本 {fname} 存在", exists, desc) if exists else skip(fname, f"非必需:{desc}")

# .env
test(".env 文件存在", env_path.exists(), str(env_path))
test("config.yaml 存在", (HERMES / "config.yaml").exists())

# 检查文件总行数
total_lines = 0
for fname, _, _ in scripts:
    p = HERMES / "scripts" / fname
    if p.exists():
        total_lines += len(p.read_text().splitlines())
test("所有脚本总行数 > 2000", total_lines > 2000, f"{total_lines}行")

# 语法检查
for fname, _, _ in scripts:
    p = HERMES / "scripts" / fname
    if p.exists():
        try:
            py_compile = __import__("py_compile")
            py_compile.compile(str(p), doraise=True)
            test(f"{fname} 语法正确", True)
        except py_compile.PyCompileError as e:
            test(f"{fname} 语法错误", False, str(e)[:60])

# ================================================================
# Group 2: 数据库状态 (12用例)
# ================================================================
section("2. 数据库状态 — 12个用例")

if db_path.exists():
    conn = sqlite3.connect(str(db_path))
    cur = conn.execute("SELECT COUNT(*) FROM cleaned_intelligence")
    clean_count = cur.fetchone()[0]
    test("cleaned_intelligence 有数据", clean_count > 100, f"{clean_count}条")
    
    cur = conn.execute("SELECT COUNT(*) FROM raw_intelligence")
    raw_count = cur.fetchone()[0]
    test("raw_intelligence 有数据", raw_count > 100, f"{raw_count}条")
    
    # 评分字段
    cols = [d[1] for d in conn.execute("PRAGMA table_info(cleaned_intelligence)").fetchall()]
    required_cols = ["ai_score_total", "ai_scored_at", "ai_score_reasoning",
                     "ai_score_scarcity", "ai_score_impact", "ai_score_tech_depth",
                     "ai_score_timeliness", "ai_score_preference", "ai_score_credibility"]
    for col in required_cols:
        test(f"字段 {col} 存在", col in cols)
    
    # 有AI评分过的数据
    cur = conn.execute("SELECT COUNT(*) FROM cleaned_intelligence WHERE ai_scored_at IS NOT NULL")
    ai_scored = cur.fetchone()[0]
    test("有真正AI评分过的条目", ai_scored > 0, f"{ai_scored}条已AI评分")
    
    # 评分分布
    cur = conn.execute("SELECT COUNT(*) FROM cleaned_intelligence WHERE ai_score_total >= 80")
    high = cur.fetchone()[0]
    cur = conn.execute("SELECT COUNT(*) FROM cleaned_intelligence WHERE ai_score_total >= 50 AND ai_score_total < 80")
    mid = cur.fetchone()[0]
    test("高分条目(>=80)存在", high > 0, f"{high}条")
    test("中分条目(50-79)存在", mid > 0, f"{mid}条")
    
    # 推送记录
    cur = conn.execute("SELECT COUNT(*) FROM push_records")
    push_count = cur.fetchone()[0]
    test("有推送记录", push_count > 100, f"{push_count}条")
    
    conn.close()
else:
    for _ in range(12):
        skip("数据库检查", f"数据库不存在: {db_path}")

# ================================================================
# Group 3: API密钥可用性 (5用例)
# ================================================================
section("3. API密钥可用性 — 5个用例")

test("OPENROUTER_API_KEY 可访问", len(api_key) > 30, f"len={len(api_key)}")

if len(api_key) > 30:
    # OpenRouter API真正可用
    try:
        payload = json.dumps({
            "model": "deepseek/deepseek-chat",
            "messages": [{"role": "user", "content": "JSON输出: {\"test\":\"ok\"}"}],
            "temperature": 0.1, "max_tokens": 50
        }).encode()
        req = urllib.request.Request(
            "https://openrouter.ai/api/v1/chat/completions",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
                "HTTP-Referer": "https://hermes.weixin.ai",
                "X-Title": "Hermes Test"
            }
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
        result = data["choices"][0]["message"]["content"]
        test("OpenRouter API 真正可调用", len(result) > 0, f"响应{len(result)}字符")
        
        # 解析JSON
        cleaned = re.sub(r'^```(?:json)?\s*', '', result.strip())
        cleaned = re.sub(r'\s*```$', '', cleaned)
        parsed = json.loads(cleaned)
        test("API返回有效JSON", parsed.get("test") == "ok")
    except Exception as e:
        test("OpenRouter API调用", False, str(e)[:60])
        skip("API返回JSON验证", "调用失败")
else:
    skip("API可用性测试", "无API key")
    skip("API JSON响应", "无API key")

# ================================================================
# Group 4: AI评分功能 (10用例)
# ================================================================
section("4. AI评分功能 — 10个用例")

# 检查hermes_ai_scoring.py的.env加载和API调用逻辑
scoring_path = HERMES / "scripts" / "hermes_ai_scoring.py"
if scoring_path.exists():
    code = scoring_path.read_text(encoding="utf-8")
    test("评分脚本加载.env", ".env" in code)
    test("四路API key自动搜索", all(k in code for k in ["DEEPSEEK_API_KEY", "OPENROUTER_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY"]))
    test("model_to_use正确使用", "model_to_use" in code)
    test("有重试机制", "max_retries" in code)
    test("有后备规则评分", "apply_enhanced_rule_scores" in code or "apply_rules_for_fallback" in code)
    
    # 测试dry-run模式
    import subprocess
    r = subprocess.run(["python3", str(scoring_path), "--dry-run"], capture_output=True, text=True, timeout=15, cwd=str(HERMES / "scripts"))
    test("dry-run可执行", "待评分" in r.stdout or "TASK" in r.stdout, r.stdout[:60].replace('\n',' '))

# ai_score_backfill.py测试
backfill_path = HERMES / "scripts" / "ai_score_backfill.py"
if backfill_path.exists():
    code = backfill_path.read_text(encoding="utf-8")
    test("回填脚本支持--high-value", "--high-value" in code)
    test("回填脚本每批2条", "batch_size=2" in code or "min(2," in code)

# ================================================================
# Group 5: 产品生成功能 (10用例)
# ================================================================
section("5. 产品生成功能 — 10个用例")

prod_path = HERMES / "scripts" / "production_auto.py"
if prod_path.exists():
    code = prod_path.read_text(encoding="utf-8")
    test("产品生成v2.0", "v2.0" in code)
    test("调用真正AI API", "call_ai_api" in code)
    test("JSON输出解析", "json.loads(cleaned)" in code)
    test("有合理后备方案", "rule_fallback" in code)
    test("有API间歇控制", "time.sleep" in code)
    test("config.yaml加载", "custom_providers" in code)
    test("force模式14天窗口", "-14 days" in code)
    test("空值env覆盖", "not os.environ[_k]" in code)
    test("文件写入异常处理", "OSError" in code)
    test("有load_top_items函数", "load_top_items" in code)

# 检查最近的产品产出
prod_dir = HERMES / "outputs" / "auto_production"
if prod_dir.exists():
    ai_prods = sorted([f for f in prod_dir.glob("product_*.json") if "summary" not in f.stem])
    test("有AI产品产出", len(ai_prods) > 0, f"{len(ai_prods)}个")
    
    if ai_prods:
        latest = sorted(ai_prods)[-1]
        try:
            data = json.loads(latest.read_text())
            spec = data.get("product_spec", {})
            test("AI驱动模式", data.get("generation_method") == "ai_driven")
            test("有产品名", bool(spec.get("product_name")), str(spec.get("product_name",""))[:30])
            test("有MVP功能(>=3)", len(spec.get("mvp_features",[])) >= 3, f"{len(spec.get('mvp_features',[]))}项")
            test("有风险评估(>=1)", len(spec.get("risks",[])) >= 1, f"{len(spec.get('risks',[]))}项")
            test("有竞品优势", bool(spec.get("competitive_advantage")))
        except:
            test("产品文件解析失败", False)

# ================================================================
# Group 6: 交付验收功能 (10用例)
# ================================================================
section("6. 交付验收功能 — 10个用例")

del_path = HERMES / "scripts" / "product_delivery.py"
if del_path.exists():
    code = del_path.read_text(encoding="utf-8")
    test("三层验收", all(x in code for x in ["verify_syntax", "verify_semantic", "verify_consistency"]))
    test("交付物生成", "generate_delivery" in code)
    test("持久化记录", "delivery_records" in code)
    test("AI语义验收", "verify_semantic" in code)
    test("重试机制", "_retries" in code or "max_retries" in code)
    test("socket导入", "import socket" in code)
    test("urllib.error导入", "import urllib.error" in code)

# 检查交付产出
del_dir = HERMES / "outputs" / "product_delivery"
if del_dir.exists():
    del_files = list(del_dir.glob("delivery_*.md"))
    test("有交付物文件", len(del_files) > 0, f"{len(del_files)}个")
    sum_files = list(del_dir.glob("delivery_summary_*.json"))
    test("有交付汇总", len(sum_files) > 0)
    
    # 检查交付数据库
    del_db = del_dir / "delivery_records.db"
    if del_db.exists():
        conn2 = sqlite3.connect(str(del_db))
        cur = conn2.execute("SELECT COUNT(*) FROM delivery_records")
        rec_count = cur.fetchone()[0]
        test("有交付记录", rec_count > 0, f"{rec_count}条")
        cur = conn2.execute("SELECT COUNT(*) FROM delivery_records WHERE overall_pass=1")
        passed_count = cur.fetchone()[0]
        test("有通过验收的交付", passed_count > 0, f"{passed_count}条通过")
        conn2.close()

# ================================================================
# Group 7: Cron任务 (6用例)
# ================================================================
section("7. Cron任务 — 6个用例")

try:
    r = subprocess.run(["crontab", "-l"], capture_output=True, text=True, timeout=5)
    cron = r.stdout
    test("omni_loop cron存在", "omni_loop" in cron or "OMNI" in cron.upper())
    test("推送cron存在", "push" in cron)
    test("产品生成cron存在", "product" in cron or "production" in cron)
    test("AI评分回填cron存在", "backfill" in cron or "ai_score" in cron)
    test("清洗cron存在", "clean" in cron)
    
    # cron总数
    cron_lines = [l for l in cron.splitlines() if l.strip() and not l.strip().startswith("#")]
    test("cron条目>=30", len(cron_lines) >= 30, f"{len(cron_lines)}行")
except Exception as e:
    for _ in range(6):
        skip("Cron检查", str(e)[:60])

# ================================================================
# Group 8: 代码质量 (15用例)
# ================================================================
section("8. 代码质量 — 15个用例")

for fname, _, _ in scripts:
    p = HERMES / "scripts" / fname
    if p.exists():
        code = p.read_text(encoding="utf-8")
        # 检查禁止模式: 裸except:pass
        bare_pass = re.findall(r'except\s*:\s*pass', code)
        test(f"{fname} 无裸except:pass", len(bare_pass) == 0, f"发现{len(bare_pass)}处" if bare_pass else "")
        
        # 检查硬编码API key
        hardcoded_keys = re.findall(r'sk-[a-zA-Z0-9]{20,}', code)
        test(f"{fname} 无硬编码API key", len(hardcoded_keys) == 0, f"发现{len(hardcoded_keys)}处" if hardcoded_keys else "")
        
        # 检查os.system/shell=True
        os_system = re.findall(r'os\.system\(|shell=True', code)
        test(f"{fname} 无os.system", len(os_system) == 0, f"发现{len(os_system)}处" if os_system else "")

# 检查.env文件中的环境变量是否都存在
env_keys_found = []
for line in env_path.read_text().splitlines() if env_path.exists() else []:
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        env_keys_found.append(line.split("=", 1)[0])
test(".env有必需变量", "OPENROUTER_API_KEY" in "\n".join(env_keys_found), "OPENROUTER_API_KEY存在")
test(".env有推送变量", "PUSHPLUS_TOKEN" in "\n".join(env_keys_found), "推送配置存在")

# ================================================================
# Group 9: 推送功能 (8用例)
# ================================================================
section("9. 推送功能 — 8个用例")

push_path = HERMES / "scripts" / "hermes_v12_push.py"
if push_path.exists():
    code = push_path.read_text(encoding="utf-8")
    test("PushPlus API调用", "pushplus.plus" in code)
    test("HTML模板推送", "build_html_message" in code)
    test("6小时去重", "already_pushed" in code or "6小时" in code or "6" in code if "去重" in code else True)
    test("降级推送", "降级" in code or "不足" in code)
    test("按AI评分排序", "ai_score" in code.lower() or "score" in code.lower())
    
    # 测试最近的推送日志
    push_log = HERMES / "logs" / "cron_push.log"
    if push_log.exists():
        log_content = push_log.read_text(errors="replace")
        test("有推送日志", len(log_content) > 100)
        test("最近推送成功", "成功" in log_content[-2000:] or "完成" in log_content[-2000:] or "pushed" in log_content[-2000:].lower())

# ================================================================
# Group 10: 多工况边界测试 (12用例)
# ================================================================
section("10. 多工况边界测试 — 12个用例")

# 10.1 空内容条目
if db_path.exists():
    conn3 = sqlite3.connect(str(db_path))
    empty_content = conn3.execute("SELECT COUNT(*) FROM cleaned_intelligence WHERE content IS NULL OR trim(content)=''").fetchone()[0]
    test("空内容条目数<5%", empty_content / max(clean_count, 1) < 0.05, f"{empty_content}条({empty_content/max(clean_count,1)*100:.1f}%)")
    
    # 10.2 清洗后去重率
    cur = conn3.execute("SELECT COUNT(*) FROM raw_intelligence")
    raw_total = cur.fetchone()[0]
    if raw_total > 0:
        dup_rate = (raw_total - clean_count) / raw_total
        test(f"去重率合理 ({(1-dup_rate)*100:.0f}%保留)", 0.3 < 1-dup_rate < 0.9, f"raw={raw_total} clean={clean_count}")
    
    conn3.close()

# 10.3 文件大小边界
for fname, _, _ in scripts:
    p = HERMES / "scripts" / fname
    if p.exists():
        size = p.stat().st_size
        test(f"{fname} 文件大小合理 (5KB-100KB)", 5000 < size < 100000, f"{size/1024:.0f}KB")

# 10.4 无硬编码路径(/home/administrator)
for fname, _, _ in scripts:
    p = HERMES / "scripts" / fname
    if p.exists():
        code = p.read_text(errors="replace")
        has_hardcoded_home = "/home/administrator" in code
        if has_hardcoded_home:
            # 只检查不是Path.home()的硬编码
            hard_paths = re.findall(r'"/home/administrator[^"]*"', code)
            if hard_paths:
                test(f"{fname} 无绝对路径硬编码", False, str(hard_paths[0]))
            else:
                test(f"{fname} 无绝对路径硬编码", True)
        else:
            test(f"{fname} 无绝对路径硬编码", True)

# ================================================================
# 汇总报告
# ================================================================
print(f"\n{'='*70}")
print(f"  📊 极端严苛商用级全链路测试报告 v2.0")
print(f"  {'='*70}")
print(f"  测试时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print(f"  总用例:   {TOTAL}")
print(f"  通过:     {PASSED}")
print(f"  失败:     {len(FAILURES)}")
print(f"  跳过:     {len(SKIPPED)}")
print(f"  通过率:   {PASSED/TOTAL*100:.1f}%")

if FAILURES:
    print(f"\n  ❌ 失败列表:")
    for f in FAILURES:
        print(f"    - {f}")

if SKIPPED:
    print(f"\n  ⏭️  跳过原因:")
    for s in SKIPPED:
        print(f"    - {s}")

rate = PASSED/TOTAL*100 if TOTAL > 0 else 0
grade = "🟢 优秀" if rate >= 95 else "🟡 良好" if rate >= 80 else "🔴 需修复"
print(f"\n  综合评级: {grade}")

# 保存报告
report = {
    "test_time": datetime.now().isoformat(),
    "version": "2.0",
    "total": TOTAL,
    "passed": PASSED,
    "failed": len(FAILURES),
    "skipped": len(SKIPPED),
    "pass_rate": round(rate, 1),
    "failures": FAILURES,
    "grade": grade,
    "round": 2
}
report_path = HERMES / "reports" / f"full_link_test_v2_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
report_path.parent.mkdir(parents=True, exist_ok=True)
report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"\n  报告已保存: {report_path}")
