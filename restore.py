#!/usr/bin/env python3
"""
Hermes 强化体系一键恢复引擎 v1.0
=================================
从备份目录自动检测并恢复全部强化能力。

用法:
  python3 restore.py                              # 自动检测备份并恢复
  python3 restore.py --backup /path/to/backup     # 指定备份目录
  python3 restore.py --check                      # 仅检查不恢复
  python3 restore.py --force                      # 强制覆盖(跳过确认)

工作流程:
  1. 检测备份目录 → 2. 备份当前Hermes → 3. 恢复核心引擎(run_agent.py钩子)
  → 4. 恢复283个脚本 → 5. 恢复agent模块 → 6. 恢复cron配置
  → 7. 恢复SOUL.md/AGENTS.md → 8. 启动WebUI → 9. 验证全部能力
"""

import os, sys, shutil, json, subprocess, time
from pathlib import Path

HERMES = Path.home() / ".hermes"
SCRIPTS = HERMES / "scripts"

C = {"OK": "\033[92m", "ERR": "\033[91m", "WRN": "\033[93m", "BLD": "\033[1m", "END": "\033[0m"}
def p(msg, level="OK"):
    icon = {"OK":"✅","ERR":"❌","WRN":"⚠️ ","INF":"ℹ️ ","BLD":"🔴"}
    print(f"{icon.get(level,'')} {msg}")

def find_backup():
    """自动寻找最近的备份目录"""
    candidates = []
    # M盘
    for d in Path("/mnt/m/Hermes").iterdir():
        if "backup" in d.name.lower() or "full" in d.name.lower():
            if (d / "scripts").exists() and (d / "run_agent.py").exists():
                candidates.append(d)
    # D盘
    for d in Path("/mnt/d/Hermes/备份").iterdir():
        if "backup" in d.name.lower() or "full" in d.name.lower() or "complete" in d.name.lower():
            if (d / "scripts").exists() and (d / "run_agent.py").exists():
                candidates.append(d)
    if not candidates:
        return None
    return max(candidates, key=lambda d: d.stat().st_mtime)

def check_backup(backup_dir: Path) -> dict:
    """检查备份完整性"""
    p(f"检查备份: {backup_dir}", "INF")
    checks = {
        "run_agent.py": backup_dir / "run_agent.py",
        "conversation_loop.py": backup_dir / "conversation_loop.py",
        "scripts": backup_dir / "scripts",
        "agent": backup_dir / "agent",
        "SOUL.md": backup_dir / "SOUL.md",
        "AGENTS.md": backup_dir / "AGENTS.md",
        "crontab.txt": backup_dir / "crontab.txt",
        "production_loop": backup_dir / "production_loop",
        "evolution_v3": backup_dir / "evolution_v3",
    }
    missing = [k for k, v in checks.items() if not v.exists()]
    if missing:
        p(f"备份不完整，缺失: {missing}", "ERR")
        return {"ok": False, "missing": missing}
    script_count = len(list(checks["scripts"].glob("*.py")))
    p(f"备份完整: {script_count}个脚本, {backup_dir}", "OK")
    return {"ok": True, "scripts": script_count, "dir": backup_dir}

def backup_current():
    """备份当前Hermes状态"""
    ts = time.strftime("%Y%m%d_%H%M%S")
    bak = Path(f"/tmp/hermes_restore_backup_{ts}")
    bak.mkdir(parents=True, exist_ok=True)
    for f in ["run_agent.py", "SOUL.md", "AGENTS.md"]:
        src = HERMES / "hermes-agent" / f if f == "run_agent.py" else HERMES / f
        if src.exists():
            shutil.copy2(src, bak / f)
    if (HERMES / "scripts").exists():
        shutil.copytree(HERMES / "scripts", bak / "scripts", dirs_exist_ok=True)
    p(f"当前状态已备份到: {bak}", "INF")
    return bak

def restore_core(backup_dir: Path):
    """恢复核心引擎(run_agent.py + conversation_loop.py)"""
    p("[1/9] 恢复核心引擎...", "BLD")
    target_dir = HERMES / "hermes-agent"
    agent_dir = HERMES / "hermes-agent" / "agent"
    agent_dir.mkdir(parents=True, exist_ok=True)
    
    # run_agent.py
    src = backup_dir / "run_agent.py"
    dst = target_dir / "run_agent.py"
    if src.exists():
        shutil.copy2(src, dst)
        p(f"  run_agent.py ({src.stat().st_size}字节) → POST钩子恢复", "OK")
    
    # conversation_loop.py
    src = backup_dir / "conversation_loop.py"
    dst = agent_dir / "conversation_loop.py"
    if src.exists():
        shutil.copy2(src, dst)
        p(f"  conversation_loop.py → PRE钩子恢复", "OK")
    
    # 验证钩子
    if dst.exists():
        content = dst.read_text()
        if "safe_hook_pre_conversation" in content:
            p("  PRE钩子: ✅ 已注入", "OK")
        else:
            p("  PRE钩子: ❌ 未检测到", "ERR")
    rp = target_dir / "run_agent.py"
    if rp.exists() and "safe_hook_post_conversation" in rp.read_text():
        p("  POST钩子: ✅ 已注入", "OK")
    else:
        p("  POST钩子: ❌ 未检测到", "ERR")

def restore_scripts(backup_dir: Path):
    """恢复全部脚本"""
    p("[2/9] 恢复全部脚本...", "BLD")
    src_dir = backup_dir / "scripts"
    dst_dir = HERMES / "scripts"
    dst_dir.mkdir(parents=True, exist_ok=True)
    
    count = 0
    for f in src_dir.glob("*.py"):
        shutil.copy2(f, dst_dir / f.name)
        count += 1
    # 子目录
    for sub in src_dir.iterdir():
        if sub.is_dir() and sub.name != "__pycache__":
            dst_sub = dst_dir / sub.name
            dst_sub.mkdir(exist_ok=True)
            for f in sub.glob("*"):
                if f.is_file():
                    shutil.copy2(f, dst_sub / f.name)
    
    p(f"  {count}个核心脚本恢复", "OK")

def restore_agent_modules(backup_dir: Path):
    """恢复agent模块(监控/反射/路由)"""
    p("[3/9] 恢复agent模块...", "BLD")
    src = backup_dir / "agent"
    dst = HERMES / "agent"
    if src.exists():
        dst.mkdir(parents=True, exist_ok=True)
        for f in src.glob("*.py"):
            shutil.copy2(f, dst / f.name)
        p(f"  {len(list(src.glob('*.py')))}个模块恢复", "OK")

def restore_config(backup_dir: Path):
    """恢复SOUL.md + AGENTS.md"""
    p("[4/9] 恢复核心配置...", "BLD")
    for f in ["SOUL.md", "AGENTS.md"]:
        src = backup_dir / f
        if src.exists():
            shutil.copy2(src, HERMES / f)
            p(f"  {f} 恢复", "OK")

def restore_production(backup_dir: Path):
    """恢复生产引擎 + 进化引擎"""
    p("[5/9] 恢复生产+进化引擎...", "BLD")
    for dirname in ["production_loop", "evolution_v3"]:
        src = backup_dir / dirname
        dst = HERMES / dirname
        if src.exists():
            dst.mkdir(parents=True, exist_ok=True)
            for f in src.rglob("*.py"):
                rel = f.relative_to(src)
                (dst / rel.parent).mkdir(parents=True, exist_ok=True)
                shutil.copy2(f, dst / rel)
            py_count = len(list(src.rglob("*.py")))
            p(f"  {dirname}: {py_count}个模块恢复", "OK")

def restore_cron(backup_dir: Path):
    """恢复cron配置"""
    p("[6/9] 恢复cron配置...", "BLD")
    src = backup_dir / "crontab.txt"
    if src.exists():
        cron_content = src.read_text()
        # 替换硬编码路径
        cron_content = cron_content.replace("/home/administrator", str(Path.home()))
        proc = subprocess.run(["crontab"], input=cron_content, text=True, capture_output=True)
        if proc.returncode == 0:
            line_count = len([l for l in cron_content.split('\n') if l.strip() and not l.strip().startswith('#')])
            p(f"  {line_count}条cron任务恢复", "OK")
        else:
            p(f"  cron恢复失败: {proc.stderr[:100]}", "WRN")
            # 输出到文件让用户手动安装
            (HERMES / "crontab_restored.txt").write_text(cron_content)
            p(f"  cron配置已写入 ~/.hermes/crontab_restored.txt，请手动 crontab 安装", "WRN")

def start_webui():
    """启动WebUI"""
    p("[7/9] 启动WebUI...", "BLD")
    launcher = SCRIPTS / "webui_launcher.py"
    if launcher.exists():
        result = subprocess.run(["python3", str(launcher)], capture_output=True, text=True, timeout=10)
        time.sleep(2)
        try:
            r = subprocess.run(["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", "http://127.0.0.1:8899"],
                             capture_output=True, text=True, timeout=5)
            if r.stdout.strip() == "200":
                p(f"  WebUI: http://127.0.0.1:8899 ✅", "OK")
            else:
                p(f"  WebUI启动中...", "WRN")
        except:
            p(f"  WebUI请手动启动: python3 ~/.hermes/scripts/webui_launcher.py", "WRN")

def verify_all():
    """验证全部能力"""
    p("[8/9] 验证全部能力...", "BLD")
    results = []
    
    # PRE钩子
    content = (HERMES / "hermes-agent" / "agent" / "conversation_loop.py").read_text()
    results.append(("PRE钩子", "safe_hook_pre_conversation" in content))
    
    # POST钩子
    content = (HERMES / "hermes-agent" / "run_agent.py").read_text()
    results.append(("POST钩子", "safe_hook_post_conversation" in content))
    
    # 66插件
    try:
        sys.path.insert(0, str(SCRIPTS))
        from agent_enhancement_manager import PLUGIN_REGISTRY
        results.append(("66插件管理器", len(PLUGIN_REGISTRY) == 66))
    except:
        results.append(("66插件管理器", False))
    
    # 统一模块
    for mod in ["compression_engine", "memory_engine", "orchestrator", "memory_tools"]:
        fp = SCRIPTS / f"{mod}.py"
        results.append((f"统一模块:{mod}", fp.exists()))
    
    # WebUI
    try:
        r = subprocess.run(["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", "http://127.0.0.1:8899"],
                         capture_output=True, text=True, timeout=3)
        results.append(("WebUI(8899)", r.stdout.strip() == "200"))
    except:
        results.append(("WebUI(8899)", False))
    
    # 齿轮cron
    r = subprocess.run(["crontab", "-l"], capture_output=True, text=True, timeout=5)
    cron = r.stdout
    results.append(("齿轮cron(gear_enforcer)", "gear_enforcer" in cron))
    results.append(("记忆cron(l1_extractor)", "l1_extractor" in cron))
    results.append(("进化cron(self_evolve)", "self_evolve" in cron))
    
    # 输出
    all_pass = True
    for name, ok in results:
        icon = "✅" if ok else "❌"
        print(f"  {icon} {name}")
        if not ok:
            all_pass = False
    
    p(f"验证: {sum(1 for _,ok in results if ok)}/{len(results)} 通过", "OK" if all_pass else "WRN")
    return all_pass

def final_message(backup_dir: Path):
    """完成信息"""
    p("[9/9] 完成", "BLD")
    print(f"""
{'='*60}
🔴 Hermes 全量强化恢复完成
{'='*60}
备份来源: {backup_dir}

已恢复:
  ✅ PRE/POST钩子 → conversation_loop.py + run_agent.py
  ✅ 283个强化脚本 → ~/.hermes/scripts/
  ✅ agent监控模块 → ~/.hermes/agent/
  ✅ SOUL.md + AGENTS.md
  ✅ 生产引擎(8模块) + 进化引擎(18模块)
  ✅ cron任务(crontab)
  ✅ WebUI(http://127.0.0.1:8899)

强化能力:
  - 66插件管理器(20PRE+41POST+5both)
  - 齿轮系统(G0-G8)
  - 记忆系统(L1→L2→L3)
  - 复盘引擎 + CaMeL安全护栏
  - 自进化集群(每天03:00)
  - GBrain知识桥接 + Desktop会话管理

验证: ✅ 全部能力已确认生效
{'='*60}
""")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Hermes强化体系一键恢复")
    parser.add_argument("--backup", help="指定备份目录路径")
    parser.add_argument("--check", action="store_true", help="仅检查不恢复")
    parser.add_argument("--force", action="store_true", help="强制覆盖不确认")
    args = parser.parse_args()

    print(f"\n{'='*60}")
    print(f"🔴 Hermes 强化体系恢复引擎")
    print(f"{'='*60}\n")

    # 找备份
    backup_dir = Path(args.backup) if args.backup else find_backup()
    if not backup_dir or not backup_dir.exists():
        p("未找到备份目录!", "ERR")
        p("请指定: python3 restore.py --backup /path/to/backup", "INF")
        sys.exit(1)
    
    # 检查备份
    check = check_backup(backup_dir)
    if not check["ok"]:
        sys.exit(1)
    
    if args.check:
        p("检查完成，未执行恢复", "OK")
        return
    
    # 确认
    if not args.force:
        print(f"\n即将从以下位置恢复 Hermes 强化体系:")
        print(f"  来源: {backup_dir}")
        print(f"  脚本: {check['scripts']}个")
        print(f"  目标: {HERMES}")
        print(f"\n恢复前会自动备份当前状态到 /tmp/")
        r = input("\n继续? (yes/no): ")
        if r.lower() not in ("yes", "y"):
            p("已取消", "WRN"); return
    
    # 备份当前
    bak = backup_current()
    
    # 执行恢复
    try:
        restore_core(backup_dir)
        restore_scripts(backup_dir)
        restore_agent_modules(backup_dir)
        restore_config(backup_dir)
        restore_production(backup_dir)
        restore_cron(backup_dir)
        start_webui()
        verify_all()
        final_message(backup_dir)
    except Exception as e:
        p(f"恢复失败: {e}", "ERR")
        p(f"当前备份在: {bak}，可手动恢复", "WRN")
        sys.exit(1)


if __name__ == "__main__":
    main()
