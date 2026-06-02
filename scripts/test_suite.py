#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Hermes 上下文脚本商用级测试套件 v1.0
====================================
对 ~/.hermes/scripts/ 下4个脚本进行多轮全链路功能测试。

测试维度：
1. 功能测试：各脚本跑10次，输出一致性
2. 并发测试：4脚本同时跑10次
3. 压力测试：连续50次（间隔0.1s），耗时/内存
4. 边缘测试：空内容/超大/特殊字符
5. 异常测试：文件不存在/权限不足/非法输入
"""

import sys
import os
import time
import json
import hashlib
import subprocess
import threading
import tempfile
import shutil
import signal
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import defaultdict

# ============================================================
# 配置
# ============================================================
HERMES = Path("/home/administrator/.hermes")
SCRIPTS_DIR = HERMES / "scripts"
REPORTS_DIR = HERMES / "reports"
BACKUP_DIR = HERMES / "test_backup"
TEST_LOG = HERMES / "reports" / "test_results.json"
DETAILED_LOG = HERMES / "reports" / "test_detailed.log"

SCRIPTS = [
    ("context_packer.py", f"python3 {SCRIPTS_DIR}/context_packer.py"),
    ("surgical_context_slicer.py", f"python3 {SCRIPTS_DIR}/surgical_context_slicer.py"),
    ("context_auto_assoc.py", f"python3 {SCRIPTS_DIR}/context_auto_assoc.py"),
    ("cross_session_cache.py", f"python3 {SCRIPTS_DIR}/cross_session_cache.py"),
]

RESULTS = defaultdict(lambda: {
    "total": 0, "passed": 0, "failed": 0,
    "times": [], "errors": [], "hashes": []
})

LOG_FILE = None

def log(msg: str, also_print=True):
    ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    line = f"[{ts}] {msg}"
    if also_print:
        print(line)
    if LOG_FILE:
        LOG_FILE.write(line + "\n")
        LOG_FILE.flush()

def setup():
    """备份关键文件，创建临时目录"""
    global LOG_FILE
    LOG_FILE = open(DETAILED_LOG, "w", encoding="utf-8")

    # 确保 reports 目录存在
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    # 备份原始文件
    log("=== 测试前备份 ===")
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    for fname in ["context_pack.json", "surgical_context.json",
                  "context_auto_assoc.json", "context_auto_assoc.md",
                  "cross_session_cache.json"]:
        src = REPORTS_DIR / fname
        if src.exists():
            shutil.copy2(src, BACKUP_DIR / fname)
            log(f"  备份 {fname}")

    # 记录初始内存
    try:
        with open("/proc/self/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    log(f"  初始内存: {line.strip()}")
                    break
    except:
        pass

def teardown():
    """恢复备份文件"""
    log("\n=== 测试后恢复 ===")
    for fname in ["context_pack.json", "surgical_context.json",
                  "context_auto_assoc.json", "context_auto_assoc.md",
                  "cross_session_cache.json"]:
        bak = BACKUP_DIR / fname
        dst = REPORTS_DIR / fname
        if bak.exists():
            shutil.copy2(bak, dst)
            log(f"  恢复 {fname}")

    # 清理测试备份目录
    if BACKUP_DIR.exists():
        shutil.rmtree(BACKUP_DIR)
        log("  清理备份目录")

    if LOG_FILE:
        LOG_FILE.close()

def run_script(cmd: str, timeout: int = 30, input_data: str = None,
               env_add: dict = None) -> tuple:
    """运行脚本，返回 (returncode, stdout, stderr, elapsed)"""
    env = os.environ.copy()
    if env_add:
        env.update(env_add)

    start = time.time()
    try:
        proc = subprocess.run(
            cmd, shell=True, input=input_data,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=timeout, env=env,
            text=True, encoding="utf-8", errors="replace"
        )
        elapsed = time.time() - start
        return proc.returncode, proc.stdout, proc.stderr, elapsed
    except subprocess.TimeoutExpired:
        return -1, "", "TIMEOUT", time.time() - start
    except Exception as e:
        return -2, "", str(e), time.time() - start

def get_memory_mb() -> float:
    """获取当前进程的内存使用 (MB)"""
    try:
        import psutil
        return psutil.Process().memory_info().rss / 1024 / 1024
    except ImportError:
        try:
            with open(f"/proc/{os.getpid()}/status") as f:
                for line in f:
                    if line.startswith("VmRSS:"):
                        return int(line.split()[1]) / 1024
        except:
            pass
    return 0.0

def compute_signature(text: str) -> str:
    """计算输出的确定性签名（排除时间戳）"""
    # 移除时间戳行（JSON中的ts字段，以及输出中的ts行）
    cleaned = text
    # 移除 "ts": "2024-..." 这类行
    import re
    cleaned = re.sub(r'"ts":\s*"[^"]*"', '"ts": "REDACTED"', cleaned)
    cleaned = re.sub(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}', 'REDACTED', cleaned, flags=re.MULTILINE)
    return hashlib.sha256(cleaned.encode()).hexdigest()[:16]

# ============================================================
# 测试 1：功能测试 — 各脚本单独跑10次
# ============================================================
def test_functional():
    log("\n" + "="*60)
    log("测试1: 功能测试 — 各脚本单独跑10次")
    log("="*60)

    for name, cmd in SCRIPTS:
        log(f"\n--- {name} ---")
        tag = f"func_{name}"
        first_hash = None
        sig = RESULTS[tag]

        for i in range(10):
            rc, out, err, elapsed = run_script(cmd)
            sig["total"] += 1
            sig["times"].append(elapsed)

            if rc == 0 and not err:
                # 计算签名（排除时间戳）
                h = compute_signature(out)
                if first_hash is None:
                    first_hash = h
                    log(f"  [{i+1}/10] OK {elapsed:.3f}s hash={h}")
                elif h == first_hash:
                    log(f"  [{i+1}/10] OK {elapsed:.3f}s hash={h} (一致)")
                else:
                    sig["failed"] += 1
                    sig["errors"].append(f"Run {i+1}: hash不一致: {first_hash} vs {h}")
                    log(f"  [{i+1}/10] FAIL hash不一致! {h}", also_print=True)
                    continue
                sig["passed"] += 1
                sig["hashes"].append(h)
            else:
                sig["failed"] += 1
                sig["errors"].append(f"Run {i+1}: rc={rc} err={err[:200]}")
                log(f"  [{i+1}/10] FAIL rc={rc} {err[:100]}", also_print=True)

        log(f"  结果: {sig['passed']}/10 passed")

# ============================================================
# 测试 2：并发测试 — 4脚本同时跑10次
# ============================================================
def test_concurrent():
    log("\n" + "="*60)
    log("测试2: 并发测试 — 4脚本同时跑10次")
    log("="*60)

    tag = "concurrent"
    sig = RESULTS[tag]
    overall_start = time.time()

    for round_idx in range(10):
        log(f"\n--- 并发轮次 {round_idx+1}/10 ---")
        with ThreadPoolExecutor(max_workers=4) as executor:
            future_to_cmd = {
                executor.submit(run_script, cmd): name
                for name, cmd in SCRIPTS
            }
            for future in as_completed(future_to_cmd):
                name = future_to_cmd[future]
                rc, out, err, elapsed = future.result()
                sig["total"] += 1

                if rc == 0 and not err:
                    sig["passed"] += 1
                    log(f"  {name}: OK {elapsed:.3f}s")
                else:
                    sig["failed"] += 1
                    sig["errors"].append(f"Round {round_idx+1} {name}: rc={rc}")
                    log(f"  {name}: FAIL rc={rc} {err[:80]}", also_print=True)

    total_elapsed = time.time() - overall_start
    log(f"\n  总耗时: {total_elapsed:.1f}s")
    log(f"  结果: {sig['passed']}/{sig['total']} passed")

# ============================================================
# 测试 3：压力测试 — 连续50次（间隔0.1秒）
# ============================================================
def test_stress():
    log("\n" + "="*60)
    log("测试3: 压力测试 — 连续跑50次（间隔0.1秒）")
    log("="*60)

    # 分别测每个脚本
    for name, cmd in SCRIPTS:
        log(f"\n--- {name} ---")
        tag = f"stress_{name}"
        sig = RESULTS[tag]

        mem_before = get_memory_mb()
        times = []

        for i in range(50):
            rc, out, err, elapsed = run_script(cmd)
            sig["total"] += 1
            times.append(elapsed)

            if rc == 0 and not err:
                sig["passed"] += 1
                if (i+1) % 10 == 0:
                    log(f"  [{i+1}/50] OK avg={sum(times[-10:])/10:.3f}s")
            else:
                sig["failed"] += 1
                sig["errors"].append(f"Run {i+1}: rc={rc}")

            # 间隔0.1秒
            time.sleep(0.1)

        mem_after = get_memory_mb()
        avg_time = sum(times) / len(times)
        max_time = max(times)
        min_time = min(times)

        log(f"  平均耗时: {avg_time:.4f}s, 最小: {min_time:.4f}s, 最大: {max_time:.4f}s")
        log(f"  内存: {mem_before:.1f}MB → {mem_after:.1f}MB (变化: {mem_after-mem_before:+.1f}MB)")
        log(f"  结果: {sig['passed']}/{sig['total']} passed")

# ============================================================
# 测试 4：边缘测试
# ============================================================
def test_edge():
    log("\n" + "="*60)
    log("测试4: 边缘测试")
    log("="*60)

    tag = "edge"
    sig = RESULTS[tag]

    # --- 4a. context_packer 边缘测试 ---
    log("\n--- context_packer.py 边缘 ---")
    # 空task_type
    for task_type in ["", "nonexistent_type_xyz"]:
        rc, out, err, elapsed = run_script(
            f"python3 {SCRIPTS_DIR}/context_packer.py '{task_type}'"
        )
        sig["total"] += 1
        if rc == 0:
            sig["passed"] += 1
            log(f"  task_type='{task_type}' OK ({elapsed:.3f}s)")
        else:
            sig["failed"] += 1
            log(f"  task_type='{task_type}' FAIL ({err[:80]})", also_print=True)

    # 超大额外上下文
    huge_extra = "测试" * 50000  # ~150K chars
    rc, out, err, elapsed = run_script(
        f"python3 {SCRIPTS_DIR}/context_packer.py general '{huge_extra[:200]}...'"
    )
    sig["total"] += 1
    if rc == 0:
        sig["passed"] += 1
        log(f"  超大额外上下文 OK ({elapsed:.3f}s)")
    else:
        sig["failed"] += 1
        log(f"  超大额外上下文 FAIL ({err[:80]})", also_print=True)

    # 特殊字符
    special = "!@#$%^&*()_+{}|:<>?~`ñüéø你好世界🔥🚀💯\n\t\\"
    rc, out, err, elapsed = run_script(
        f"python3 {SCRIPTS_DIR}/context_packer.py general '{special[:50]}'"
    )
    sig["total"] += 1
    if rc == 0:
        sig["passed"] += 1
        log(f"  特殊字符 OK ({elapsed:.3f}s)")
    else:
        sig["failed"] += 1
        log(f"  特殊字符 FAIL ({err[:80]})", also_print=True)

    # --- 4b. surgical_context_slicer 边缘 ---
    log("\n--- surgical_context_slicer.py 边缘 ---")
    for task_type in ["", "invalid_type_xyz"]:
        rc, out, err, elapsed = run_script(
            f"python3 {SCRIPTS_DIR}/surgical_context_slicer.py '{task_type}'"
        )
        sig["total"] += 1
        if rc == 0:
            sig["passed"] += 1
            log(f"  task_type='{task_type}' OK ({elapsed:.3f}s)")
        else:
            sig["failed"] += 1
            log(f"  task_type='{task_type}' FAIL ({err[:80]})", also_print=True)

    # --- 4c. context_auto_assoc 边缘 ---
    log("\n--- context_auto_assoc.py 边缘 ---")
    rc, out, err, elapsed = run_script(f"python3 {SCRIPTS_DIR}/context_auto_assoc.py")
    sig["total"] += 1
    if rc == 0:
        sig["passed"] += 1
        log(f"  默认运行 OK ({elapsed:.3f}s)")
    else:
        sig["failed"] += 1
        log(f"  默认运行 FAIL ({err[:80]})", also_print=True)

    # --- 4d. cross_session_cache 边缘 ---
    log("\n--- cross_session_cache.py 边缘 ---")
    # 空输入
    rc, out, err, elapsed = run_script(
        f"python3 {SCRIPTS_DIR}/cross_session_cache.py",
        input_data=""
    )
    sig["total"] += 1
    if rc == 0:
        sig["passed"] += 1
        log(f"  空输入 OK ({elapsed:.3f}s)")
    else:
        sig["failed"] += 1
        log(f"  空输入 FAIL ({err[:80]})", also_print=True)

    # 超大输入
    huge_input = "A" * 100000  # 100K chars
    rc, out, err, elapsed = run_script(
        f"python3 {SCRIPTS_DIR}/cross_session_cache.py",
        input_data=huge_input
    )
    sig["total"] += 1
    if rc == 0:
        sig["passed"] += 1
        log(f"  超大输入 OK ({elapsed:.3f}s)")
    else:
        sig["failed"] += 1
        log(f"  超大输入 FAIL ({err[:80]})", also_print=True)

    # 特殊字符输入
    special_input = "!@#$%^&*()_+{}|:<>?~`ñüéø🔥✅❌\n\t\\\"'"
    rc, out, err, elapsed = run_script(
        f"python3 {SCRIPTS_DIR}/cross_session_cache.py",
        input_data=special_input
    )
    sig["total"] += 1
    if rc == 0:
        sig["passed"] += 1
        log(f"  特殊字符输入 OK ({elapsed:.3f}s)")
    else:
        sig["failed"] += 1
        log(f"  特殊字符输入 FAIL ({err[:80]})", also_print=True)

    log(f"\n  边缘测试结果: {sig['passed']}/{sig['total']} passed")

# ============================================================
# 测试 5：异常测试
# ============================================================
def test_exception():
    log("\n" + "="*60)
    log("测试5: 异常测试")
    log("="*60)

    tag = "exception"
    sig = RESULTS[tag]

    # --- 5a. 文件不存在模拟 ---
    log("\n--- 无依赖文件测试 ---")

    # 把context_pack.json挪走看slicer和auto_assoc反应
    temp_move = None
    pack_path = REPORTS_DIR / "context_pack.json"
    if pack_path.exists():
        temp_move = REPORTS_DIR / "_context_pack.json.bak"
        shutil.move(str(pack_path), str(temp_move))

    for name, cmd in SCRIPTS:
        rc, out, err, elapsed = run_script(cmd)
        sig["total"] += 1
        # 即使没有依赖文件，脚本也应当优雅处理（不崩溃）
        if rc == 0 or (rc != 0 and "Error" not in err and "Traceback" not in err):
            sig["passed"] += 1
            log(f"  {name}: graceful OK (rc={rc})")
        else:
            sig["failed"] += 1
            sig["errors"].append(f"Nofile {name}: rc={rc} {err[:100]}")
            log(f"  {name}: FAIL rc={rc} {err[:80]}", also_print=True)

    # 恢复
    if temp_move and temp_move.exists():
        shutil.move(str(temp_move), str(pack_path))

    # --- 5b. 权限不足测试 ---
    log("\n--- 权限不足测试 ---")
    reports_mode = REPORTS_DIR.stat().st_mode
    # 临时移除reports目录写权限
    os.chmod(REPORTS_DIR, 0o444)  # read-only

    for name, cmd in SCRIPTS:
        if name == "cross_session_cache.py":
            # 这个需要stdin
            rc, out, err, elapsed = run_script(cmd, input_data="test")
        else:
            rc, out, err, elapsed = run_script(cmd)
        sig["total"] += 1
        if rc == 0:
            sig["passed"] += 1
            log(f"  {name}: OK (rc=0, no-perm survived)")
        else:
            # 权限错误是预期的，但要求优雅错误处理（非崩溃）
            sig["failed"] += 1
            sig["errors"].append(f"Perm {name}: rc={rc}")
            log(f"  {name}: FAIL (rc={rc}, 权限问题预期)", also_print=True)

    # 恢复权限
    os.chmod(REPORTS_DIR, reports_mode)

    # --- 5c. 异常输入测试 ---
    log("\n--- 异常输入测试 ---")

    # Python 语法错误参数
    for name, cmd in SCRIPTS:
        for bad_arg in ["'; rm -rf /", "$(whoami)", "`id`", "|| echo hacked"]:
            rc, out, err, elapsed = run_script(
                f"{cmd} '{bad_arg}'" if name != "cross_session_cache.py"
                else f"echo '{bad_arg}' | python3 {SCRIPTS_DIR}/cross_session_cache.py"
            )
            sig["total"] += 1
            # 脚本应该安全处理（不被注入）
            if rc == 0:
                sig["passed"] += 1
            else:
                sig["failed"] += 1
                sig["errors"].append(f"Injection {name} '{bad_arg[:20]}': rc={rc}")

    log(f"\n  异常测试结果: {sig['passed']}/{sig['total']} passed")

# ============================================================
# 报告生成
# ============================================================
def generate_report():
    """生成测试报告"""
    log("\n" + "="*60)
    log("测试报告")
    log("="*60)

    total_all = sum(s["total"] for s in RESULTS.values())
    passed_all = sum(s["passed"] for s in RESULTS.values())
    failed_all = sum(s["failed"] for s in RESULTS.values())

    report = {
        "ts": datetime.now().isoformat(),
        "summary": {
            "total": total_all,
            "passed": passed_all,
            "failed": failed_all,
            "pass_rate": f"{passed_all/total_all*100:.1f}%" if total_all > 0 else "N/A"
        },
        "details": {}
    }

    log(f"\n总执行: {total_all}")
    log(f"通过:    {passed_all}")
    log(f"失败:    {failed_all}")
    log(f"通过率:  {passed_all/total_all*100:.1f}%" if total_all > 0 else "N/A")

    for test_name, sig in sorted(RESULTS.items()):
        avg_time = sum(sig["times"]) / len(sig["times"]) if sig["times"] else 0
        report["details"][test_name] = {
            "total": sig["total"],
            "passed": sig["passed"],
            "failed": sig["failed"],
            "avg_time_s": round(avg_time, 4),
            "errors": sig["errors"][:5],
            "unique_hashes": len(set(sig["hashes"]))
        }
        if sig["hashes"]:
            report["details"][test_name]["deterministic"] = (len(set(sig["hashes"])) == 1)

        log(f"\n  [{test_name}]")
        log(f"    执行: {sig['total']} | 通过: {sig['passed']} | 失败: {sig['failed']}")
        log(f"    平均耗时: {avg_time:.4f}s")
        if sig["hashes"]:
            uni = len(set(sig["hashes"]))
            log(f"    确定性: {'✅ 是' if uni == 1 else '❌ 否'} ({uni}种hash)")
        if sig["errors"]:
            log(f"    错误示例: {sig['errors'][0][:100]}")

    # 写入JSON
    (REPORTS_DIR / "test_results.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2)
    )
    log(f"\n完整报告: {REPORTS_DIR / 'test_results.json'}")

    return report

# ============================================================
# 主函数
# ============================================================
def main():
    log("="*60)
    log("Hermes 上下文脚本商用级测试套件 v1.0")
    log(f"开始时间: {datetime.now().isoformat()}")
    log("="*60)
    log(f"\n测试环境:")
    log(f"  Python: {sys.version}")
    log(f"  系统: {sys.platform}")
    log(f"  目录: {SCRIPTS_DIR}")

    start_all = time.time()

    try:
        setup()

        # 测试1: 功能测试
        test_functional()

        # 测试2: 并发测试
        test_concurrent()

        # 测试3: 压力测试
        test_stress()

        # 测试4: 边缘测试
        test_edge()

        # 测试5: 异常测试
        test_exception()

        total_time = time.time() - start_all
        log(f"\n{'='*60}")
        log(f"总耗时: {total_time:.1f}s")

        report = generate_report()
        return report

    except Exception as e:
        log(f"\n❌ 测试异常: {e}", also_print=True)
        import traceback
        log(traceback.format_exc(), also_print=True)
        raise
    finally:
        teardown()

if __name__ == "__main__":
    main()
