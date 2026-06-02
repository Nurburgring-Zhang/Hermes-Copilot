#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Hermes cron锁包装器 v1.0
=====================
由crontab调用，在真实脚本前后加文件锁+原子写入。

Crontab用法：
  * * * * * python3 scripts/cron_wrapper.py context_packer.py fix
  
包装器功能：
  1. 文件锁（fcntl flock防止同一脚本多实例并发）
  2. 执行超时代理命令
  3. 统一日志记录
  4. 原子写入（通过hermes_common）
"""
import sys, os, subprocess, time, json
from pathlib import Path

HERMES = Path("/home/administrator/.hermes")
LOCK_DIR = Path("/tmp/hermes_locks")
LOCK_DIR.mkdir(parents=True, exist_ok=True)

def main():
    if len(sys.argv) < 2:
        print(f"用法: {sys.argv[0]} <script_name> [args...]")
        sys.exit(1)
    
    script_name = sys.argv[1]
    script_path = HERMES / "scripts" / script_name
    lock_name = script_name.replace(".py", "")
    lock_path = LOCK_DIR / f"{lock_name}.lock"
    lock_fd = None
    
    # 1. 文件锁
    try:
        lock_fd = open(lock_path, "w")
        import fcntl
        try:
            fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except IOError:
            print(f"[cron_wrapper] {lock_name} 已有实例在运行，跳过")
            sys.exit(0)
    except Exception as e:
        print(f"[cron_wrapper] 锁失败: {e}")
        sys.exit(1)
    
    try:
        # 2. 执行脚本
        args = ["python3", str(script_path)] + sys.argv[2:]
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=120,
            cwd=str(HERMES)
        )
        
        # 3. 日志
        ts = time.strftime("%H:%M:%S")
        log_path = HERMES / "logs" / f"cron_wrapper.log"
        with open(log_path, "a") as f:
            f.write(f"[{ts}] {lock_name}: rc={result.returncode} out={len(result.stdout)}b err={len(result.stderr)}b\n")
            if result.stderr and result.returncode != 0:
                f.write(f"[{ts}] {lock_name} ERR: {result.stderr[:200]}\n")
        
        # 4. 输出
        if result.stdout:
            print(result.stdout[:1000])
        if result.stderr:
            print(result.stderr[:500], file=sys.stderr)
        
        sys.exit(result.returncode)
        
    except subprocess.TimeoutExpired:
        print(f"[cron_wrapper] {lock_name} 执行超时(120s)")
        sys.exit(124)
    except Exception as e:
        print(f"[cron_wrapper] {lock_name} 异常: {e}")
        sys.exit(1)
    finally:
        if lock_fd:
            try:
                import fcntl
                fcntl.flock(lock_fd.fileno(), fcntl.LOCK_UN)
                lock_fd.close()
            except: pass

if __name__ == "__main__":
    main()
