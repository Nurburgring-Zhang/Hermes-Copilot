#!/usr/bin/env python3
"""
Hermes 全量增强 一键恢复脚本
=============================
从 hermes-full-enhancement-pack 恢复所有增强文件。
支持 --dry-run 预览，--restore 实际恢复，--check 验证完整性。

用法:
  python3 deploy.py --check      检查备份完整性
  python3 deploy.py --dry-run    预览恢复(不实际写文件)
  python3 deploy.py --restore    实际恢复所有文件
  python3 deploy.py --help       帮助
"""

import json, os, sys, hashlib, shutil
from pathlib import Path

BACKUP_DIR = Path(__file__).parent.resolve()
HERMES_DIR = Path("/home/administrator/.hermes")
MANIFEST_FILE = BACKUP_DIR / "manifest.json"


def load_manifest():
    if not MANIFEST_FILE.exists():
        print(f"❌ 清单文件不存在: {MANIFEST_FILE}")
        print(f"   备份目录: {BACKUP_DIR}")
        sys.exit(1)
    return json.loads(MANIFEST_FILE.read_text())


def verify_integrity():
    """验证所有备份文件的完整性(SHA256)"""
    manifest = load_manifest()
    ok = 0
    fail = 0
    missing = 0
    
    for entry in manifest:
        path = entry["path"]
        expected_sha = entry["sha256"]
        fp = BACKUP_DIR / path
        
        if not fp.exists():
            print(f"  ❌ {path} — 文件缺失")
            missing += 1
            continue
        
        actual_sha = hashlib.sha256(fp.read_bytes()).hexdigest()[:16]
        if actual_sha == expected_sha:
            ok += 1
        else:
            print(f"  ❌ {path} — SHA256不匹配")
            fail += 1
    
    total = len(manifest)
    print(f"\n完整性检查: {ok}/{total} 通过")
    if fail:
        print(f"  {fail} 个文件损坏")
    if missing:
        print(f"  {missing} 个文件缺失")
    return ok == total


def dry_run():
    """预览恢复操作"""
    manifest = load_manifest()
    total_size = sum(e["size"] for e in manifest)
    
    print(f"备份目录: {BACKUP_DIR}")
    print(f"目标目录: {HERMES_DIR}")
    print(f"文件总数: {len(manifest)}个")
    print(f"总大小: {total_size/1024:.1f}KB")
    print()
    
    # 按目录分组
    dirs = {}
    for entry in manifest:
        d = os.path.dirname(entry["path"]) or "."
        dirs.setdefault(d, []).append(entry)
    
    for d in sorted(dirs):
        items = dirs[d]
        size = sum(e["size"] for e in items)
        print(f"  {d}/: {len(items)}个文件, {size/1024:.1f}KB")
        for e in items[:3]:
            print(f"    {os.path.basename(e['path'])} ({e['size']}b)")
        if len(items) > 3:
            print(f"    ... 还有{len(items)-3}个")
    
    print(f"\n👉 执行 --restore 来实际恢复所有文件")


def restore():
    """实际恢复所有文件"""
    manifest = load_manifest()
    
    # 先备份现有的run_agent.py
    rag = HERMES_DIR / "hermes-agent" / "run_agent.py"
    if rag.exists():
        bak_name = f"run_agent.py.pre_restore.{rag.stat().st_mtime:.0f}"
        bak_path = rag.parent / bak_name
        shutil.copy2(rag, bak_path)
        print(f"📦 备份当前 run_agent.py → {bak_name}")
    
    ok = 0
    fail = 0
    skipped = 0
    
    for entry in manifest:
        rel_path = entry["path"]
        src = BACKUP_DIR / rel_path
        dst = HERMES_DIR / rel_path
        
        if not src.exists():
            print(f"  ❌ {rel_path} — 源文件缺失")
            fail += 1
            continue
        
        # 创建目标目录
        dst.parent.mkdir(parents=True, exist_ok=True)
        
        # 写文件
        try:
            dst.write_bytes(src.read_bytes())
            ok += 1
        except Exception as e:
            print(f"  ❌ {rel_path} — {e}")
            fail += 1
    
    # 恢复crontab
    cron_file = BACKUP_DIR / "crontab.txt"
    if cron_file.exists():
        try:
            cron_content = cron_file.read_text()
            import subprocess
            r = subprocess.run(["crontab", "-"], input=cron_content, 
                             capture_output=True, text=True, timeout=10)
            if r.returncode == 0:
                print(f"  ✅ crontab.txt — 已恢复 ({len(cron_content.split(chr(10)))}行)")
                ok += 1
            else:
                print(f"  ❌ crontab.txt — 恢复失败: {r.stderr[:100]}")
                fail += 1
        except Exception as e:
            print(f"  ❌ crontab.txt — {e}")
            fail += 1
    
    total = len(manifest)
    print(f"\n恢复完成: {ok}/{total+1} 成功")
    if fail:
        print(f"  {fail} 个失败")
    
    # 验证语法
    print(f"\n验证核心脚本语法...")
    scripts_to_check = ["scripts/forced_executor.py", "scripts/agent_enhancement_manager.py",
                        "scripts/segment_manager.py", "scripts/task_queue_manager.py",
                        "scripts/checkpoint_recorder.py", "scripts/gear_enforcer.py",
                        "hermes-agent/run_agent.py"]
    for rel in scripts_to_check:
        fp = HERMES_DIR / rel
        if fp.exists():
            r = subprocess.run(["python3", "-m", "py_compile", str(fp)],
                             capture_output=True, text=True, timeout=10)
            status = "✅" if r.returncode == 0 else "❌"
            print(f"  {status} {rel}")


def main():
    if len(sys.argv) < 2 or "--help" in sys.argv:
        print(__doc__)
        return
    
    cmd = sys.argv[1]
    if cmd == "--check":
        verify_integrity()
    elif cmd == "--dry-run":
        dry_run()
    elif cmd == "--restore":
        confirm = input("确认恢复所有增强文件到 ~/.hermes/? (yes/no): ")
        if confirm.lower() == "yes":
            restore()
        else:
            print("已取消")
    else:
        print(f"未知命令: {cmd}")
        print("用法: python3 deploy.py --check|--dry-run|--restore")


if __name__ == "__main__":
    main()
