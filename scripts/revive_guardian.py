#!/usr/bin/env python3
"""
Hermes 永恒守护神复活脚本 v2.0 — 被OS cron每5分钟调用。
添加完整异常捕获 + 日志轮转 + 自保护
"""
import subprocess, os, sys, traceback
from pathlib import Path
from datetime import datetime, timedelta

HERMES = Path("/home/administrator/.hermes")
LOG_FILE = HERMES / "logs/revive.log"
MAX_LOG_BYTES = 1024 * 1024  # 1MB轮转

def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] ♻️ {msg}"
    print(line)
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        # 日志轮转
        if LOG_FILE.exists() and LOG_FILE.stat().st_size > MAX_LOG_BYTES:
            old = LOG_FILE.with_suffix(".log.old")
            LOG_FILE.rename(old)
        with open(LOG_FILE, "a") as f:
            f.write(line + "\n")
    except Exception as e:
        print(f"[WARN] 日志写入失败: {e}")

def is_alive():
    """检查eternal_loop.py是否活着"""
    try:
        r = subprocess.run(
            ["pgrep", "-f", "python3 scripts/eternal_loop.py"],
            capture_output=True, text=True, timeout=5
        )
        pids = [p.strip() for p in r.stdout.strip().split('\n') if p.strip()]
        return len(pids) >= 1
    except subprocess.TimeoutExpired:
        log("pgrep超时,假设进程活着避免误杀")
        return True
    except Exception as e:
        log(f"检查存活失败: {e}")
        return True  # 保守策略,不确定就当活着

def revive():
    """复活eternal_loop.py"""
    log("⚠️ eternal_loop 挂了,正在复活...")
    try:
        r = subprocess.run(
            ["tmux", "new-session", "-d", "-s", "hermes-eternal",
             f"cd {HERMES} && python3 scripts/eternal_loop.py"],
            capture_output=True, text=True, timeout=10
        )
        if r.returncode == 0:
            try:
                pid = subprocess.run(
                    ["pgrep", "-f", "python3 scripts/eternal_loop.py"],
                    capture_output=True, text=True, timeout=5
                ).stdout.strip()
            except:
                pid = "unknown"
            log(f"✅ 已复活, PID={pid}")
            (HERMES / "cron/eternal_heartbeat.txt").write_text(datetime.now().isoformat())
            (HERMES / "cron/eternal_started.txt").write_text(datetime.now().isoformat())
            return True
        else:
            log(f"❌ 复活失败: {r.stderr[:200]}")
    except Exception as e:
        log(f"❌ 复活异常: {e}")
    return False

def main():
    try:
        if is_alive():
            try:
                (HERMES / "cron/eternal_heartbeat.txt").write_text(datetime.now().isoformat())
            except:
                pass
            return
        
        for attempt in range(3):
            if revive():
                return
            import time
            time.sleep(2)
        log("❌ 3次复活均失败")
    except Exception as e:
        log(f"❌ 致命异常: {traceback.format_exc()}")

if __name__ == "__main__":
    main()
