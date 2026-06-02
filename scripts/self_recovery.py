#!/usr/bin/env python3
"""
Hermes 自恢复引擎 — 从备份目录自动恢复全部增强能力
=====================================================
功能: 
  1. 自动扫描所有可能的备份位置(M:/D:/C:)
  2. 找到最新的增强能力备份(20260601+版本)
  3. 对比本地文件与备份文件，找出缺失/损坏的
  4. 自动恢复缺失文件
  5. 自动恢复cron条目
  6. 运行测试验证
  7. 报告恢复结果

用法:
  python3 scripts/self_recovery.py           # 自动恢复
  python3 scripts/self_recovery.py --check   # 只检查不恢复
  python3 scripts/self_recovery.py --backup  # 先备份当前状态再恢复

所有路径使用 Path.home()，跨平台兼容。
"""

import os, sys, json, shutil, hashlib, subprocess, datetime
from pathlib import Path
from typing import List, Tuple, Optional

# ─── 配置 ─────────────────────────────────────────────
HERMES = Path.home() / ".hermes"
BACKUP_CANDIDATES = [
    Path("/mnt/m/Hermes"),
    Path("/mnt/d/Hermes"),
    Path("/mnt/c/Hermes"),
    Path("/mnt/e/Hermes"),
    Path("/mnt/f/Hermes"),
    Path.home() / "Hermes",
    Path.home() / "备份",
]
# 备份目录命名模式: YYYYMMDD 或包含 enhancement/enhance/pack 关键词
KEYWORD_PATTERNS = ["enhancement", "enhance", "pack", "增强"]

# 需要恢复的文件清单 (源路径在备份中的相对路径 → 目标路径)
RECOVERY_MANIFEST = {
    # P0 基础层
    "agent/monitor.py": "agent/monitor.py",
    "agent/reflector.py": "agent/reflector.py",
    "agent/model_router.py": "agent/model_router.py",
    "tools/progress_tool.py": "tools/progress_tool.py",
    # 上下文压缩 (6个)
    "scripts/context_packer.py": "scripts/context_packer.py",
    "scripts/surgical_context_slicer.py": "scripts/surgical_context_slicer.py",
    "scripts/context_auto_assoc.py": "scripts/context_auto_assoc.py",
    "scripts/context_index_system.py": "scripts/context_index_system.py",
    "scripts/cross_session_cache.py": "scripts/cross_session_cache.py",
    "scripts/context_reconstructor.py": "scripts/context_reconstructor.py",
    # P1-P3 增强 (12个)
    "scripts/tr_gate.py": "scripts/tr_gate.py",
    "scripts/dod_checklist.py": "scripts/dod_checklist.py",
    "scripts/reflexion_engine.py": "scripts/reflexion_engine.py",
    "scripts/gepa_variator.py": "scripts/gepa_variator.py",
    "scripts/experience_extractor.py": "scripts/experience_extractor.py",
    "scripts/auto_cleaner.py": "scripts/auto_cleaner.py",
    "scripts/checkpoint_recorder.py": "scripts/checkpoint_recorder.py",
    "scripts/layered_planner.py": "scripts/layered_planner.py",
    "scripts/llm_bridge.py": "scripts/llm_bridge.py",
    "scripts/wake_injector.py": "scripts/wake_injector.py",
    "scripts/hermes_retrospect.py": "scripts/hermes_retrospect.py",
    "scripts/gear_enforcer.py": "scripts/gear_enforcer.py",
    # 无限对话 (3个)
    "scripts/segment_manager.py": "scripts/segment_manager.py",
    "scripts/consistency_guard.py": "scripts/consistency_guard.py",
    "scripts/auto_healer.py": "scripts/auto_healer.py",
    # L3画像
    "scripts/l3_persona_scheduler.py": "scripts/l3_persona_scheduler.py",
    # 测试
    "scripts/test_all_enhancements.py": "scripts/test_all_enhancements.py",
}

# 需要恢复的cron条目
CRON_ENTRIES = [
    # 上下文系统 (每1分钟)
    ("* * * * *", "context_packer.py general", "context_packer"),
    ("* * * * *", "surgical_context_slicer.py", "surgical_context_slicer"),
    ("* * * * *", "context_auto_assoc.py", "context_auto_assoc"),
    ("* * * * *", "cross_session_cache.py", "cross_session_cache"),
    # 独立增强模块
    ("*/30 * * * *", "tools/progress_tool.py", "progress_tool"),
    ("0 * * * *", "scripts/tr_gate.py check", "tr_gate"),
    ("0 * * * *", "scripts/dod_checklist.py check", "dod_checklist"),
    ("*/30 * * * *", "scripts/reflexion_engine.py", "reflexion_engine"),
    ("0 * * * *", "scripts/experience_extractor.py", "experience_extractor"),
    ("0 * * * *", "scripts/auto_cleaner.py dry-run", "auto_cleaner"),
]


def log(msg: str):
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}")


def find_backup_dir() -> Optional[Path]:
    """在所有候选位置寻找最新的增强备份目录"""
    best = None
    best_date = ""
    
    for parent in BACKUP_CANDIDATES:
        if not parent.exists():
            continue
        for item in parent.iterdir():
            if not item.is_dir():
                continue
            name = item.name
            # 匹配 YYYYMMDD 或 YYYYMMDD_HHMMSS 格式
            if (len(name) >= 8 and name[:8].isdigit()) or \
               any(kw in name.lower() for kw in KEYWORD_PATTERNS):
                # 检查目录内是否有增强文件的特征
                has_agent = (item / "agent" / "monitor.py").exists()
                has_scripts = (item / "scripts" / "segment_manager.py").exists()
                if has_agent or has_scripts:
                    # 用日期比较，取最新的
                    date_part = name[:8] if name[:8].isdigit() else "00000000"
                    if date_part >= best_date:
                        best_date = date_part
                        best = item
    
    return best


def check_file_integrity(backup: Path, rel_path: str) -> Tuple[bool, bool]:
    """
    检查文件完整性
    返回: (备份是否存在, 本地是否一致)
    """
    backup_file = backup / rel_path
    local_file = HERMES / rel_path
    
    if not backup_file.exists():
        return False, False
    
    with open(backup_file, "rb") as f:
        backup_hash = hashlib.md5(f.read()).hexdigest()
    
    if not local_file.exists():
        return True, False
    
    with open(local_file, "rb") as f:
        local_hash = hashlib.md5(f.read()).hexdigest()
    
    return True, backup_hash == local_hash


def restore_file(backup: Path, rel_path: str, dst_rel: str) -> bool:
    """从备份恢复单个文件"""
    src = backup / rel_path
    dst = HERMES / dst_rel
    
    if not src.exists():
        log(f"  ❌ 备份中不存在: {rel_path}")
        return False
    
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(src), str(dst))
        log(f"  ✅ 恢复: {dst_rel}")
        return True
    except Exception as e:
        log(f"  ❌ 恢复失败 {dst_rel}: {e}")
        return False


def restore_crons(backup_dir: Optional[Path] = None) -> Tuple[int, int]:
    """恢复cron条目"""
    current_cron = subprocess.run(
        ["crontab", "-l"], capture_output=True, text=True, timeout=5
    ).stdout
    
    restored = 0
    skipped = 0
    
    for schedule, script, name in CRON_ENTRIES:
        # 检查是否已在cron中
        if name in current_cron or script.split("/")[-1] in current_cron:
            skipped += 1
            continue
        
        entry = f"{schedule} cd {HERMES} && python3 {script} >> logs/{name}.log 2>&1"
        
        # 添加到当前crontab
        new_cron = current_cron + entry + "\n"
        try:
            subprocess.run(
                ["bash", "-c", f'crontab <<EOF\n{new_cron}\nEOF'],
                capture_output=True, text=True, timeout=5, check=True
            )
            current_cron = new_cron
            log(f"  ✅ 添加cron: {name} ({schedule})")
            restored += 1
        except Exception as e:
            log(f"  ❌ 添加cron失败 {name}: {e}")
    
    return restored, skipped


def run_verification() -> Tuple[int, int]:
    """运行测试验证"""
    test_script = HERMES / "scripts" / "test_all_enhancements.py"
    if not test_script.exists():
        log("  ⚠️ 测试脚本不存在, 跳过验证")
        return 0, 1
    
    try:
        result = subprocess.run(
            ["python3", str(test_script)],
            capture_output=True, text=True, timeout=60,
            cwd=str(HERMES)
        )
        passed = "全部通过" in result.stdout or "100.0%" in result.stdout
        if passed:
            log("  ✅ 全链路测试通过")
            return 1, 0
        else:
            log("  ⚠️ 测试有失败项")
            log(result.stdout[-500:] if len(result.stdout) > 500 else result.stdout)
            return 0, 1
    except Exception as e:
        log(f"  ❌ 测试执行失败: {e}")
        return 0, 1


def main():
    mode = "recover"
    if len(sys.argv) > 1:
        if sys.argv[1] == "--check":
            mode = "check"
        elif sys.argv[1] == "--backup":
            mode = "backup_first"
    
    log("=" * 60)
    log("Hermes 自恢复引擎 启动")
    log(f"模式: {mode}")
    log("=" * 60)
    
    # 1. 找备份
    log("\n[1/5] 扫描备份目录...")
    backup_dir = find_backup_dir()
    if not backup_dir:
        log("  ❌ 未找到增强备份目录")
        log("  请确保备份在以下位置之一:")
        for p in BACKUP_CANDIDATES:
            log(f"    - {p}/*enhancement*/")
        return
    
    log(f"  ✅ 找到备份: {backup_dir}")
    log(f"  内容: {len(list(backup_dir.glob('**/*.py')))} .py文件")
    
    # 2. 完整性检查
    log("\n[2/5] 检查文件完整性...")
    missing = []
    corrupt = []
    ok = 0
    
    for rel_path, dst_rel in RECOVERY_MANIFEST.items():
        backup_exists, local_ok = check_file_integrity(backup_dir, rel_path)
        if not backup_exists:
            continue  # 备份中可能没有这个文件
    if not local_ok:
        if not (HERMES / dst_rel).exists():
            missing.append((rel_path, dst_rel))
        else:
            # 不一致但不缺失，检查是否是脱敏差异(只差路径替换)
            # 功能上可用的不标记为损坏
            corrupt.append((rel_path, dst_rel))
    else:
            ok += 1
    
    log(f"  ✅ 完整: {ok}个")
    if missing:
        log(f"  ❌ 缺失: {len(missing)}个")
        for src, dst in missing[:5]:
            log(f"    - {dst}")
    if corrupt:
        log(f"  ⚠️ 不一致: {len(corrupt)}个")
        for src, dst in corrupt[:5]:
            log(f"    - {dst}")
    
    # 3. cron检查
    log("\n[3/5] 检查cron条目...")
    current_cron = subprocess.run(
        ["crontab", "-l"], capture_output=True, text=True, timeout=5
    ).stdout
    
    cron_ok = 0
    cron_missing = 0
    for _, script, name in CRON_ENTRIES:
        if name in current_cron or script.split("/")[-1] in current_cron:
            cron_ok += 1
        else:
            cron_missing += 1
            log(f"  ❌ 缺失cron: {name}")
    
    log(f"  ✅ 存在: {cron_ok}条")
    if cron_missing > 0:
        log(f"  ❌ 缺失: {cron_missing}条")
    
    # 如果是check模式，到这里就结束
    if mode == "check":
        log("\n" + "=" * 60)
        log("检查完成")
        total_issues = len(missing) + len(corrupt) + cron_missing
        if total_issues == 0:
            log("✅ 一切正常，无需恢复")
        else:
            log(f"⚠️ 发现 {total_issues} 个问题")
        return
    
    # 4. 执行恢复 (如果发现问题)
    total_restored = 0
    total_failed = 0
    
    if missing or corrupt:
        log("\n[4/5] 执行恢复...")
        
        # 先备份当前状态
        if mode == "backup_first" and (missing or corrupt):
            backup_before = HERMES / f"reports/pre_recovery_backup_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}"
            backup_before.mkdir(parents=True, exist_ok=True)
            for src, dst in missing + corrupt:
                local_file = HERMES / dst
                if local_file.exists():
                    shutil.copy2(str(local_file), str(backup_before / dst.replace("/", "_")))
            log(f"  ✅ 已备份当前状态到 {backup_before.name}")
        
        # 恢复文件
        for rel_path, dst_rel in missing + corrupt:
            if restore_file(backup_dir, rel_path, dst_rel):
                total_restored += 1
            else:
                total_failed += 1
    
    # 恢复cron
    if cron_missing > 0:
        log("\n  恢复cron条目...")
        r, s = restore_crons(backup_dir)
        total_restored += r
        cron_missing -= r
    
    # 5. 验证
    log("\n[5/5] 运行测试验证...")
    test_ok, test_fail = run_verification()
    
    # 报告
    log("\n" + "=" * 60)
    log("恢复完成报告")
    log("=" * 60)
    log(f"  备份来源: {backup_dir}")
    log(f"  恢复文件: {total_restored}个")
    if total_failed > 0:
        log(f"  恢复失败: {total_failed}个")
    log(f"  测试验证: {'✅ 通过' if test_ok else '⚠️ 有失败'}")
    log(f"")
    if test_ok and total_failed == 0:
        log(f"  ✅ 全部能力已恢复，系统正常运行")
    else:
        log(f"  ⚠️ 部分恢复，请检查上述日志")
    log("=" * 60)


if __name__ == "__main__":
    main()
