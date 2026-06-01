#!/usr/bin/env python3
"""
Hermes run_agent.py 自动恢复脚本
==================================
如果增强后的run_agent.py导致系统异常, 执行此脚本恢复备份。
使用方式:
  python3 scripts/restore_run_agent.py          # 恢复到最近的备份
  python3 scripts/restore_run_agent.py check     # 检查备份状态
"""
import sys, shutil, os
from pathlib import Path

AGENT_DIR = Path("/home/administrator/.hermes/hermes-agent")
RUN_AGENT = AGENT_DIR / "run_agent.py"

def find_backups():
    backups = sorted(AGENT_DIR.glob("run_agent.py.bak.*"), reverse=True)
    return backups

def check():
    backups = find_backups()
    if not backups:
        print("[RESTORE] ❌ 没有找到备份文件!")
        return False
    print(f"[RESTORE] ✅ 找到 {len(backups)} 个备份:")
    for b in backups:
        size = b.stat().st_size
        print(f"  {b.name} ({size} bytes)")
    print(f"[RESTORE] 当前 run_agent.py: {RUN_AGENT.stat().st_size} bytes")
    print(f"[RESTORE] 最近备份: {backups[0].name}")
    return True

def restore(index=0):
    backups = find_backups()
    if not backups:
        print("[RESTORE] ❌ 没有备份文件, 无法恢复!")
        return False
    
    if index >= len(backups):
        print(f"[RESTORE] ❌ 备份索引 {index} 超出范围 (0-{len(backups)-1})")
        restore_help()
        return False
    
    backup = backups[index]
    try:
        shutil.copy2(backup, RUN_AGENT)
        print(f"[RESTORE] ✅ 已恢复: {backup.name} → run_agent.py")
        print(f"[RESTORE]    大小: {backup.stat().st_size} bytes")
        
        # 验证语法
        import subprocess
        r = subprocess.run([sys.executable, "-m", "py_compile", str(RUN_AGENT)],
                         capture_output=True, text=True)
        if r.returncode == 0:
            print(f"[RESTORE] ✅ 语法验证通过")
        else:
            print(f"[RESTORE] ❌ 语法验证失败: {r.stderr[:200]}")
        
        return True
    except Exception as e:
        print(f"[RESTORE] ❌ 恢复失败: {e}")
        return False

def restore_help():
    print("用法: python3 scripts/restore_run_agent.py [选项]")
    print("  无参数  恢复到最近备份")
    print("  check   检查备份状态")
    print("  list    列出所有备份")
    print("  <数字>  恢复到指定索引的备份")

if __name__ == "__main__":
    args = sys.argv[1:] if len(sys.argv) > 1 else []
    
    if not args or args[0] == "latest" or args[0] == "0":
        restore(0)
    elif args[0] == "check":
        check()
    elif args[0] == "list":
        backups = find_backups()
        for i, b in enumerate(backups):
            print(f"  [{i}] {b.name}")
    elif args[0].isdigit():
        restore(int(args[0]))
    else:
        restore_help()
