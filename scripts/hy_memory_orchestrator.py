#!/usr/bin/env python3
"""
🔴🔴🔴 反幻觉铁律：严禁任何不加核实的猜想、胡编乱造、自己瞎编！
必须核实才能说/必须验证才能写/必须确认才能断言/不知道就说不知道
这是最高优先级规则，凌驾于所有其他规则之上。
"""

"""
hy_memory_orchestrator.py — Hy-Memory 全链路编排引擎 v2.0 (LLM增强版)
======================================================================
对标 Hy-Memory: TdaiCore + pipeline-factory + pipeline-manager 的调度中枢

v2.0 新增:
  - L1 LLM提取调度 (自动检测新增事实量)
  - L2 场景归纳调度 (delegate_task + 本地LLM)
  - L3 画像生成调度 (四层深度扫描)
  - 全链路自校验

调度模式:
  all     — 全链路编排 (醒来/每小时)
  check   — 检查所有触发条件 (不执行)
  l1      — 仅执行L1 LLM提取
  l2      — 仅执行L2场景归纳
  l3      — 仅执行L3画像生成
  cleanup — 清理过期数据
  audit   — 全链路审计
"""

import sys
import json
import time
import subprocess
from pathlib import Path

SCRIPTS_DIR = Path.home() / ".hermes" / "scripts"
REPORTS_DIR = Path.home() / ".hermes" / "reports"


def _import_script(name: str):
    """动态导入脚本"""
    sys.path.insert(0, str(SCRIPTS_DIR))
    return __import__(name.replace('.py', ''))


def mode_all():
    """全链路编排: 唤醒/每小时执行"""
    print("=" * 60)
    print("🔴 Hy-Memory 全链路编排启动")
    print(f"   时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    
    results = {}
    
    # Step 0: 工具卸载维护
    print("\n--- [Step 0] 工具卸载维护 ---")
    try:
        from tool_unloader import ToolUnloader
        unloader = ToolUnloader()
        cleaned = unloader.cleanup_expired()
        print(f"  清理: {cleaned} 个过期ref")
        results["tool_unloader"] = {"cleaned": cleaned}
    except Exception as e:
        print(f"  失败: {e}")
        results["tool_unloader"] = {"error": str(e)}
    
    # Step 1: 情景记忆注入
    print("\n--- [Step 1] 情景记忆注入 ---")
    try:
        result = subprocess.run(
            ["python3", str(SCRIPTS_DIR / "episodic_injector.py")],
            capture_output=True, text=True, timeout=30
        )
        print(f"  输出: {result.stdout.strip()[:200]}")
        results["episodic"] = {"exit_code": result.returncode}
    except Exception as e:
        print(f"  失败: {e}")
        results["episodic"] = {"error": str(e)}
    
    # Step 2: 检查L1触发条件
    print("\n--- [Step 2] L1 LLM提取检查 ---")
    try:
        result = subprocess.run(
            ["python3", str(SCRIPTS_DIR / "l1_extractor.py"), "--auto"],
            capture_output=True, text=True, timeout=300
        )
        print(f"  输出: {result.stdout.strip()[:300]}")
        results["l1"] = {"exit_code": result.returncode}
    except Exception as e:
        print(f"  失败: {e}")
        results["l1"] = {"error": str(e)}
    
    # Step 3: L2场景归纳检查
    print("\n--- [Step 3] L2场景归纳检查 ---")
    try:
        result = subprocess.run(
            ["python3", str(SCRIPTS_DIR / "l2_scene_scheduler.py")],
            capture_output=True, text=True, timeout=300
        )
        print(f"  输出: {result.stdout.strip()[:300]}")
        results["l2"] = json.loads(result.stdout) if result.stdout else {}
    except Exception as e:
        print(f"  失败: {e}")
        results["l2"] = {"error": str(e)}
    
    # Step 4: L3画像生成检查
    print("\n--- [Step 4] L3画像生成检查 ---")
    try:
        result = subprocess.run(
            ["python3", str(SCRIPTS_DIR / "l3_persona_scheduler.py")],
            capture_output=True, text=True, timeout=300
        )
        print(f"  输出: {result.stdout.strip()[:300]}")
        results["l3"] = json.loads(result.stdout) if result.stdout else {}
    except Exception as e:
        print(f"  失败: {e}")
        results["l3"] = {"error": str(e)}
    
    # Step 5: 更新wake_injector
    print("\n--- [Step 5] 更新wake_injector ---")
    try:
        result = subprocess.run(
            ["python3", str(SCRIPTS_DIR / "wake_injector.py")],
            capture_output=True, text=True, timeout=30
        )
        print(f"  输出: {result.stdout.strip()[:200]}")
        results["wake"] = {"output": result.stdout.strip()[:200]}
    except Exception as e:
        print(f"  失败: {e}")
        results["wake"] = {"error": str(e)}
    
    print("\n" + "=" * 60)
    print("✅ Hy-Memory 全链路编排完成")
    print(f"   L1: {results.get('l1', {}).get('exit_code', '?')}")
    print(f"   L2: {'触发' if results.get('l2', {}).get('triggered') else '跳过'}")
    print(f"   L3: {'触发' if results.get('l3', {}).get('triggered') else '跳过'}")
    print("=" * 60)
    
    return results


def mode_check():
    """仅检查触发条件"""
    print("=" * 60)
    print("🔴 Hy-Memory 触发条件检查")
    print("=" * 60)
    
    # L1
    print("\n## L1 触发条件")
    try:
        import sqlite3
        db = sqlite3.connect(str(Path.home() / ".hermes" / "active_memory.db"))
        cur = db.cursor()
        cur.execute("SELECT COUNT(*) FROM memory_semantic WHERE active=1")
        total = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM memory_episodic")
        total_episodic = cur.fetchone()[0]
        print(f"  总事实: {total}")
        print(f"  情景记录: {total_episodic}")
        db.close()
    except Exception as e:
        print(f"  DB错误: {e}")
    
    # L2
    print("\n## L2 触发条件")
    try:
        result = subprocess.run(
            ["python3", str(SCRIPTS_DIR / "l2_scene_scheduler.py"), "check"],
            capture_output=True, text=True, timeout=15
        )
        print(f"  {result.stdout.strip()}")
    except Exception as e:
        print(f"  检查失败: {e}")
    
    # L3
    print("\n## L3 触发条件")
    try:
        result = subprocess.run(
            ["python3", str(SCRIPTS_DIR / "l3_persona_scheduler.py"), "check"],
            capture_output=True, text=True, timeout=15
        )
        print(f"  {result.stdout.strip()}")
    except Exception as e:
        print(f"  检查失败: {e}")


def mode_audit():
    """全链路审计"""
    print("=" * 60)
    print("🔴 Hy-Memory 全链路审计")
    print("=" * 60)
    
    import sqlite3
    db = sqlite3.connect(str(Path.home() / ".hermes" / "active_memory.db"))
    cur = db.cursor()
    
    print("\n## 数据库表状态")
    for table in ["memory_semantic", "memory_episodic", "memory_scene", "memory_profile"]:
        cur.execute(f"SELECT COUNT(*) FROM {table}")
        count = cur.fetchone()[0]
        print(f"  {table}: {count} 条记录")
    
    print("\n## 事实分类分布")
    cur.execute("SELECT cat, COUNT(*) FROM memory_semantic WHERE active=1 GROUP BY cat ORDER BY COUNT(*) DESC")
    for r in cur.fetchall():
        print(f"  {r[0]}: {r[1]}")
    
    print("\n## L2场景")
    cur.execute("SELECT name, frequency, confidence FROM memory_scene ORDER BY frequency DESC")
    for r in cur.fetchall():
        print(f"  {r[0]}: freq={r[1]}, conf={r[2]}")
    
    print("\n## L3画像")
    cur.execute("SELECT name, profile_type, updated_at FROM memory_profile ORDER BY updated_at DESC")
    for r in cur.fetchall():
        print(f"  {r[0]} ({r[1]}): {r[2]}")
    
    print("\n## 工具卸载状态")
    offload_path = Path.home() / ".hermes" / "offload_entries.jsonl"
    if offload_path.exists():
        with open(offload_path) as f:
            lines = [l for l in f if l.strip()]
        print(f"  offload_entries: {len(lines)} 条")
    
    refs_dir = Path.home() / ".hermes" / "refs"
    if refs_dir.exists():
        files = list(refs_dir.glob("*.md"))
        total_size = sum(f.stat().st_size for f in files)
        print(f"  refs文件: {len(files)} 个 ({total_size/1024:.1f} KB)")
    
    print("\n## cron任务")
    import subprocess
    result = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    hy_crons = [l for l in result.stdout.split('\n') 
                if 'hy_memory' in l.lower() or 'l1_' in l.lower() or 'l2_' in l.lower() or 'l3_' in l.lower()]
    for job in hy_crons:
        print(f"  {job}")
    
    db.close()


def mode_cleanup():
    """清理过期数据"""
    print("🔴 Hy-Memory 数据清理")
    try:
        # 清理tool_unloader
        from tool_unloader import ToolUnloader
        unloader = ToolUnloader()
        cleaned_refs = unloader.cleanup_expired()
        print(f"  refs清理: {cleaned_refs}")
    except Exception as e:
        print(f"  refs清理失败: {e}")
    
    # 清理过期的offload条目
    offload_path = Path.home() / ".hermes" / "offload_entries.jsonl"
    if offload_path.exists() and offload_path.stat().st_size > 1024*1024:  # >1MB压缩
        print(f"  offload_entries: {offload_path.stat().st_size/1024:.1f} KB — 超过1MB需要压缩")
        # 保留最近100条
        with open(offload_path) as f:
            lines = [l for l in f if l.strip()]
        with open(offload_path, 'w') as f:
            for line in lines[-100:]:
                f.write(line + '\n')
        print(f"  压缩后: {min(len(lines), 100)} 条")


if __name__ == "__main__":
    modes = {
        "all": mode_all,
        "check": mode_check,
        "l1": lambda: _run_script("l1_extractor.py", ["--auto"]),
        "l2": lambda: _run_script("l2_scene_scheduler.py"),
        "l3": lambda: _run_script("l3_persona_scheduler.py"),
        "cleanup": mode_cleanup,
        "audit": mode_audit,
    }
    
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"
    
    if mode in modes:
        results = modes[mode]()
        if isinstance(results, dict):
            print(f"\n=== 结果概要 ===")
            print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        print(f"未知模式: {mode}")
        print("可用模式: all|check|l1|l2|l3|cleanup|audit")


def _run_script(script: str, extra_args: list = None):
    """运行子脚本"""
    extra = extra_args or []
    result = subprocess.run(
        ["python3", str(SCRIPTS_DIR / script)] + extra,
        capture_output=True, text=True, timeout=300
    )
    print(result.stdout.strip()[:500])
    return {"exit_code": result.returncode}
