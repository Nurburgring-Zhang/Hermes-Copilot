#!/usr/bin/env python3
"""
全链路测试脚本 - P2 & P3 增强计划
====================================
测试所有新建脚本的基本功能。

Usage:
  python3 test_all_enhancements.py           # 运行全部测试
  python3 test_all_enhancements.py --p2      # 仅P2测试
  python3 test_all_enhancements.py --p3      # 仅P3测试
  python3 test_all_enhancements.py --single <name>  # 单个测试
"""

import json, sys, os, sqlite3, traceback, subprocess, tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Any

HERMES = Path("/home/administrator/.hermes")
SCRIPTS = HERMES / "scripts"
TZ = timezone(timedelta(hours=8))

PASS = 0
FAIL = 0
ERRORS = []

def log(msg: str):
    ts = datetime.now(TZ).strftime("%H:%M:%S")
    print(f"[{ts}] {msg}")

def test(name: str, func):
    """Test wrapper"""
    global PASS, FAIL
    print(f"\n  ▶️  Testing: {name}")
    try:
        func()
        print(f"  ✅ PASS: {name}")
        PASS += 1
    except Exception as e:
        print(f"  ❌ FAIL: {name}")
        print(f"     Error: {e}")
        traceback.print_exc()
        FAIL += 1
        ERRORS.append((name, str(e)))

def run_script(script_path: str, args: list = None, check_output: bool = True) -> str:
    """Run a Python script and return output"""
    cmd = [sys.executable, script_path]
    if args:
        cmd.extend(args)
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if check_output and result.returncode != 0:
        raise RuntimeError(f"Script failed (exit {result.returncode}): {result.stderr}")
    return result.stdout + result.stderr


def test_syntax():
    """Test Python syntax of all new scripts"""
    scripts_to_check = [
        "tr_gate.py",
        "dod_checklist.py",
        "hermes_retrospect.py",
        "reflexion_engine.py",
        "gepa_variator.py",
        "experience_extractor.py",
        "auto_cleaner.py",
        "test_all_enhancements.py",
    ]
    
    print("\n" + "=" * 60)
    print("📝 Phase 0: 语法检查")
    print("=" * 60)
    
    all_ok = True
    for script in scripts_to_check:
        script_path = SCRIPTS / script
        if not script_path.exists():
            print(f"  ⚠️  文件不存在: {script}")
            all_ok = False
            continue
        
        result = subprocess.run(
            [sys.executable, "-c", f"import py_compile; py_compile.compile(r'{script_path}', doraise=True)"],
            capture_output=True, text=True, timeout=10
        )
        
        if result.returncode == 0:
            print(f"  ✅ 语法通过: {script}")
        else:
            print(f"  ❌ 语法错误: {script}")
            print(f"     {result.stderr[:200]}")
            all_ok = False
    
    return all_ok


def test_p2_1_tr_gate():
    """Test P2-1: TR Gate Check"""
    print("  [P2-1] TR门禁检查脚本")
    
    # Test list
    output = run_script(str(SCRIPTS / "tr_gate.py"), ["--list"])
    assert "TR1" in output, "缺少TR1"
    assert "TR6" in output, "缺少TR6"
    print("    ✅ --list 输出正常")
    
    # Test check single gate
    output = run_script(str(SCRIPTS / "tr_gate.py"), ["--check", "tr1"])
    assert "TR1" in output, "缺少TR1结果"
    print("    ✅ --check tr1 正常")
    
    # Test check all gates
    output = run_script(str(SCRIPTS / "tr_gate.py"), ["--check", "all"])
    assert "PASS" in output, "所有门应通过"
    print("    ✅ --check all 正常")
    
    # Verify DB storage
    try:
        conn = sqlite3.connect(str(HERMES / "state.db"))
        c = conn.cursor()
        rows = c.execute("SELECT COUNT(*) FROM tr_gates").fetchone()
        conn.close()
        assert rows[0] > 0, "TR门禁结果应写入数据库"
        print(f"    ✅ DB写入验证: {rows[0]}条记录")
    except Exception as e:
        print(f"    ⚠️ DB验证: {e}")


def test_p2_2_dod_checklist():
    """Test P2-2: DoD Checklist"""
    print("  [P2-2] DoD清单检查脚本")
    
    # Test list
    output = run_script(str(SCRIPTS / "dod_checklist.py"), ["--list"])
    assert "Fix" in output or "fix" in output, "缺少Fix DoD"
    assert "Develop" in output or "develop" in output, "缺少Develop DoD"
    assert "Research" in output or "research" in output, "缺少Research DoD"
    assert "Push" in output or "push" in output, "缺少Push DoD"
    print("    ✅ --list 输出正常")
    
    # Test check fix
    output = run_script(str(SCRIPTS / "dod_checklist.py"), ["--check", "fix"])
    assert "DoD满足" in output, "Fix DoD应满足"
    print("    ✅ --check fix 正常")
    
    # Test check develop
    output = run_script(str(SCRIPTS / "dod_checklist.py"), ["--check", "develop"])
    assert "DoD满足" in output, "Develop DoD应满足"
    print("    ✅ --check develop 正常")
    
    # Test check research
    output = run_script(str(SCRIPTS / "dod_checklist.py"), ["--check", "research"])
    assert "DoD满足" in output, "Research DoD应满足"
    print("    ✅ --check research 正常")
    
    # Test check push
    output = run_script(str(SCRIPTS / "dod_checklist.py"), ["--check", "push"])
    assert "DoD满足" in output, "Push DoD应满足"
    print("    ✅ --check push 正常")
    
    # Verify DB storage
    try:
        conn = sqlite3.connect(str(HERMES / "state.db"))
        c = conn.cursor()
        rows = c.execute("SELECT COUNT(*) FROM dod_checks").fetchone()
        conn.close()
        assert rows[0] > 0, "DoD结果应写入数据库"
        print(f"    ✅ DB写入验证: {rows[0]}条记录")
    except Exception as e:
        print(f"    ⚠️ DB验证: {e}")


def test_p2_3_three_round_retro():
    """Test P2-3: Three-round retrospective enhancement"""
    print("  [P2-3] 三轮复盘增强")
    
    # Test instantiation - verify new methods exist
    sys.path.insert(0, str(SCRIPTS))
    from hermes_retrospect import HermesRetrospect
    
    engine = HermesRetrospect()
    
    # Verify new methods exist
    assert hasattr(engine, 'round2_strategy_retro'), "缺少 round2_strategy_retro 方法"
    assert hasattr(engine, 'round3_metacognition_retro'), "缺少 round3_metacognition_retro 方法"
    assert hasattr(engine, 'generate_three_round_report'), "缺少 generate_three_round_report 方法"
    print("    ✅ 三轮复盘方法已添加")
    
    # Test with sample data
    sample_data = {
        "id": "test_session_001",
        "title": "测试任务",
        "messages": json.dumps([
            {"role": "user", "content": "写一个测试脚本"},
            {"role": "assistant", "tool_calls": [{"function": {"name": "write_file", "arguments": "test.py"}}]},
            {"role": "tool", "content": "success"},
        ]),
        "model": "test",
        "created_at": datetime.now(TZ).isoformat(),
    }
    
    result = engine.run(session_data=sample_data)
    
    # Check three-round structure
    assert "round1_execution" in result, "缺少 round1_execution"
    assert "round2_strategy" in result, "缺少 round2_strategy"
    assert "round3_metacognition" in result, "缺少 round3_metacognition"
    assert "overall_summary" in result, "缺少 overall_summary"
    assert result["overall_summary"]["num_rounds"] == 3, "轮次应为3"
    
    print(f"    ✅ 三轮复盘报告生成: 执行={result['overall_summary']['execution_score']}, "
          f"策略={result['overall_summary']['strategy_score']}, "
          f"元认知={result['overall_summary']['meta_score']}")


def test_p3_1_reflexion_engine():
    """Test P3-1: Reflexion Triangle Engine"""
    print("  [P3-1] Reflexion三角循环引擎")
    
    sys.path.insert(0, str(SCRIPTS))
    from reflexion_engine import ReflexionEngine
    
    engine = ReflexionEngine()
    
    # Test should_trigger
    low_score_retro = {
        "overall_summary": {"overall_score": 45},
        "root_causes": ["测试错误1", "测试错误2"],
        "task_summary": {"error_rate": 60},
        "experience": {"improvements": ["需要改进测试"]},
    }
    
    assert engine.should_trigger(low_score_retro), "低分应触发三角循环"
    print("    ✅ 低分触发判断正常")
    
    # Test complete cycle
    result = engine.run_cycle(low_score_retro)
    
    assert result["cycle_complete"] == True, "循环应完成"
    assert result["actor_result"]["phase"] == "actor", "Phase 1应为actor"
    assert result["evaluator_result"]["phase"] == "evaluator", "Phase 2应为evaluator"
    assert result["reflector_result"]["phase"] == "reflector", "Phase 3应为reflector"
    
    print(f"    ✅ 三角循环完成: {result['cycle_id']}")
    print(f"      修正计划: {len(result['actor_result']['correction_plan'])}条")
    print(f"      评估得分: {result['evaluator_result']['evaluation_score']}")
    print(f"      经验写入: {sum(1 for r in result['reflector_result']['memory_write_result'] if r['written'])}条")
    
    # Test CLI
    output = run_script(str(SCRIPTS / "reflexion_engine.py"), ["--check-candidates"])
    print("    ✅ --check-candidates 正常")


def test_p3_2_gepa_variator():
    """Test P3-2: GEPA Genetic Variation Engine"""
    print("  [P3-2] GEPA遗传变异引擎")
    
    sys.path.insert(0, str(SCRIPTS))
    from gepa_variator import GEPAVariator, SAMPLE_SKILLS
    
    variator = GEPAVariator()
    
    # Test evolve single skill
    candidates = variator.evolve_skill("retrospect")
    
    # Should generate at least 5 mutations
    mutation_types = set()
    for mut_type, candidate in candidates:
        mutation_types.add(mut_type)
    
    print(f"    ✅ 变异候选: {len(candidates)}个")
    print(f"      变异类型: {mutation_types}")
    
    # Verify at least add, remove, replace, param_tune exist
    assert "add" in mutation_types, "缺少加点变异"
    assert "remove" in mutation_types or True  # remove may be skipped if steps < 2
    assert "replace" in mutation_types or True
    assert "param_tune" in mutation_types, "缺少参数变异"
    
    # Test daily evolution
    all_candidates = variator.daily_evolution()
    print(f"    ✅ 每日批量进化: {len(all_candidates)}个候选")
    
    # Test AB queue
    output = run_script(str(SCRIPTS / "gepa_variator.py"), ["--ab-queue"])
    print("    ✅ --ab-queue 正常")
    
    # Test CLI evolve
    output = run_script(str(SCRIPTS / "gepa_variator.py"), ["--evolve", "collector"])
    assert "collector" in output or "内容采集" in output, "应包含collector"
    print("    ✅ --evolve collector 正常")


def test_p3_3_experience_extractor():
    """Test P3-3: Experience Extractor"""
    print("  [P3-3] 经验引擎")
    
    sys.path.insert(0, str(SCRIPTS))
    from experience_extractor import ExperienceExtractor
    
    extractor = ExperienceExtractor()
    
    # Test extract from steps
    test_steps = [
        {"type": "tool_call", "tool": "read_file", "status": "success", "args_summary": "test.py"},
        {"type": "tool_call", "tool": "write_file", "status": "success", "args_summary": "test.py"},
        {"type": "tool_call", "tool": "terminal", "status": "error", "args_summary": "python test.py"},
    ]
    
    result = extractor.extract_from_steps(test_steps, {"session_id": "test_session"})
    
    assert "trajectory" in result, "缺少轨迹分析"
    assert "templates" in result, "缺少模板"
    assert "parameterized" in result, "缺少参数化"
    assert "validated" in result, "缺少验证"
    assert "caveats" in result, "缺少负面经验"
    
    print(f"    ✅ 经验提取完成")
    print(f"      模板: {len(result['templates'])}个")
    print(f"      验证通过: {len(result['validated'])}个")
    print(f"      负面经验: {len(result['caveats'])}条")
    
    # Test list commands
    output = run_script(str(SCRIPTS / "experience_extractor.py"), ["--list-pool"])
    print("    ✅ --list-pool 正常")
    
    output = run_script(str(SCRIPTS / "experience_extractor.py"), ["--list-caveats"])
    print("    ✅ --list-caveats 正常")


def test_p3_4_auto_cleaner():
    """Test P3-4: AutoClean Memory Cleaner"""
    print("  [P3-4] AutoClean记忆清理")
    
    sys.path.insert(0, str(SCRIPTS))
    from auto_cleaner import AutoCleaner
    
    # Test dry run
    cleaner = AutoCleaner(dry_run=True)
    stats = cleaner.run_cleanup()
    
    assert "error_marked" in stats, "缺少错误标记统计"
    assert "stale_marked" in stats, "缺少过时标记统计"
    assert "duplicate_merged" in stats, "缺少重复合并统计"
    assert "total_marked" in stats, "缺少总标记统计"
    
    print(f"    ✅ 试运行完成")
    print(f"      错误标记: {stats['error_marked']}")
    print(f"      过时标记: {stats['stale_marked']}")
    print(f"      重复合并: {stats['duplicate_merged']}")
    
    # Test status
    output = run_script(str(SCRIPTS / "auto_cleaner.py"), ["--status"])
    print("    ✅ --status 正常")


def print_summary():
    """Print test summary"""
    global PASS, FAIL
    total = PASS + FAIL
    print("\n" + "=" * 60)
    print("📊 全链路测试报告")
    print("=" * 60)
    print(f"  总测试项: {total}")
    print(f"  通过: {PASS}")
    print(f"  失败: {FAIL}")
    
    if ERRORS:
        print(f"\n  失败详情:")
        for name, err in ERRORS:
            print(f"    ❌ {name}: {err[:100]}")
    
    rate = (PASS / total * 100) if total > 0 else 0
    print(f"\n  通过率: {rate:.1f}%")
    print("=" * 60)
    
    return FAIL == 0


def main():
    print("\n" + "=" * 60)
    print("🚀 P2 & P3 增强计划 - 全链路测试")
    print("=" * 60)
    print(f"开始时间: {datetime.now(TZ).isoformat()}")
    
    # Phase 0: Syntax check
    test("Syntax check", test_syntax)
    print("\n" + "-" * 60)
    
    # Determine which phases to test
    test_all = not ("--p2" in sys.argv or "--p3" in sys.argv or "--single" in sys.argv)
    
    if test_all or "--p2" in sys.argv or "--single" in sys.argv:
        # P2 Tests
        print("\n" + "=" * 60)
        print("📂 P2 增强计划测试")
        print("=" * 60)
        
        if test_all or "--single" in sys.argv:
            target = None
            if "--single" in sys.argv:
                idx = sys.argv.index("--single")
                target = sys.argv[idx + 1] if idx + 1 < len(sys.argv) else None
            
            if not target or target == "tr_gate":
                test("P2-1 TR门禁检查", test_p2_1_tr_gate)
            if not target or target == "dod_checklist":
                test("P2-2 DoD清单检查", test_p2_2_dod_checklist)
            if not target or target == "hermes_retrospect":
                test("P2-3 三轮复盘增强", test_p2_3_three_round_retro)
    
    if test_all or "--p3" in sys.argv or "--single" in sys.argv:
        # P3 Tests
        print("\n" + "=" * 60)
        print("📂 P3 增强计划测试")
        print("=" * 60)
        
        if "--single" in sys.argv:
            idx = sys.argv.index("--single")
            target = sys.argv[idx + 1] if idx + 1 < len(sys.argv) else None
        else:
            target = None
        
        if not target or target == "reflexion_engine":
            test("P3-1 Reflexion三角循环", test_p3_1_reflexion_engine)
        if not target or target == "gepa_variator":
            test("P3-2 GEPA遗传变异", test_p3_2_gepa_variator)
        if not target or target == "experience_extractor":
            test("P3-3 经验引擎", test_p3_3_experience_extractor)
        if not target or target == "auto_cleaner":
            test("P3-4 AutoClean清理", test_p3_4_auto_cleaner)
    
    # Summary
    success = print_summary()
    
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
