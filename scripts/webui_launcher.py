#!/usr/bin/env python3
"""Hermes WebUI 自动启动/保活脚本"""
import os, sys, subprocess, time, json, signal

HERMES_HOME = os.path.expanduser("~/.hermes")
WEBUI_DIR = os.path.join(HERMES_HOME, "webui")
PORT = "8899"
PID_FILE = os.path.join(HERMES_HOME, "webui.pid")

def is_running():
    if os.path.exists(PID_FILE):
        with open(PID_FILE) as f:
            pid = int(f.read().strip())
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            pass
    return False

def start():
    if is_running():
        print("WebUI 已在运行")
        return
    env = os.environ.copy()
    env["HERMES_HOME"] = HERMES_HOME
    env["HERMES_WEBUI_PORT"] = PORT
    proc = subprocess.Popen(
        [sys.executable, "server.py"],
        cwd=WEBUI_DIR, env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    with open(PID_FILE, "w") as f:
        f.write(str(proc.pid))
    print(f"WebUI 已启动 (PID: {proc.pid}), 端口 {PORT}")

def stop():
    if os.path.exists(PID_FILE):
        with open(PID_FILE) as f:
            pid = int(f.read().strip())
        try:
            os.kill(pid, signal.SIGTERM)
            os.remove(PID_FILE)
            print(f"WebUI 已停止 (PID: {pid})")
        except OSError:
            os.remove(PID_FILE)
            print("WebUI 未在运行")

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "stop":
        stop()
    else:
        start()
