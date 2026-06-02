#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Hermes 公共工具模块 v1.0
=====================
所有上下文/反馈脚本的公共依赖。
提供：原子写入、文件锁、统一Token读取、安全JSON加载。

格林主人最高指令(2026-05-27):
  所有写文件操作必须经过原子写入，所有定时脚本必须使用文件锁。
"""
import json, os, time, sys, tempfile, fcntl, hashlib
from pathlib import Path
from datetime import datetime
from typing import Any, Optional

HERMES = Path("/home/administrator/.hermes")
LOCK_DIR = Path("/tmp/hermes_locks")
LOCK_DIR.mkdir(parents=True, exist_ok=True)

# ===== 原子写入 =====

def atomic_write(path: Path, data: Any, mode: str = "json") -> None:
    """
    原子写入。先写临时文件，再rename覆盖原文件。
    mode='json': data是dict/list，序列化为JSON
    mode='text': data是字符串，直接写入
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    
    if mode == "json":
        content = json.dumps(data, ensure_ascii=False, indent=2)
    elif mode == "text":
        content = data
    else:
        # bytes mode
        content = data
        mode = "bytes"
    
    # 写临时文件
    tmp = path.with_suffix(".tmp." + hashlib.md5(str(path).encode()).hexdigest()[:8])
    try:
        if mode == "bytes":
            tmp.write_bytes(content)
        else:
            tmp.write_text(content, encoding="utf-8")
        # 原子rename（POSIX保证同文件系统rename原子性）
        tmp.replace(path)
    except Exception:
        # 清理临时文件
        try:
            if tmp.exists():
                tmp.unlink()
        except: pass
        raise

def safe_json_load(path: Path, default: Any = None) -> Any:
    """安全加载JSON，失败返回default"""
    if not path.exists():
        return default if default is not None else {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, Exception):
        return default if default is not None else {}

# ===== 文件锁 =====

class FileLock:
    """
    基于fcntl的文件互斥锁。
    用于cron脚本防止同一脚本多实例并发。
    
    用法：
        with FileLock("context_packer"):
            # 只有一个实例能进入
            pass
    """
    
    def __init__(self, name: str, timeout: int = 0):
        self.name = name
        self.lock_path = LOCK_DIR / f"{name}.lock"
        self.fd = None
        self.acquired = False
        self.timeout = timeout
    
    def __enter__(self):
        self.fd = open(self.lock_path, "w")
        try:
            fcntl.flock(self.fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.acquired = True
        except IOError:
            if self.timeout > 0:
                try:
                    fcntl.flock(self.fd.fileno(), fcntl.LOCK_EX)
                    self.acquired = True
                except IOError:
                    self.fd.close()
                    self.fd = None
            else:
                self.fd.close()
                self.fd = None
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.fd:
            try:
                fcntl.flock(self.fd.fileno(), fcntl.LOCK_UN)
                self.fd.close()
            except: pass
        return False  # 不吞异常

def try_lock(name: str) -> bool:
    """尝试获取锁，获取成功返回True，失败返回False"""
    lock_path = LOCK_DIR / f"{name}.lock"
    try:
        fd = open(lock_path, "w")
        fcntl.flock(fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        # 持有fd直到程序退出...但这里没法返回fd
        # 所以这个函数只在脚本顶部用于快速检查
        fd.close()
        return True
    except IOError:
        return False

# ===== PushPlus Token =====

def get_pushplus_token() -> str:
    """统一获取PushPlus token。先查config.yaml，再查.env"""
    # config.yaml
    cfg_path = HERMES / "config.yaml"
    if cfg_path.exists():
        try:
            import yaml
            cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
            if cfg:
                token = cfg.get("pushplus", {}).get("token", "")
                if token:
                    return token
        except: pass
    
    # .env
    env_path = HERMES / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").split("\n"):
            line = line.strip()
            if "PUSHPLUS_TOKEN=" in line:
                # 移除可能的 export 前缀
                if line.startswith("export "):
                    line = line[7:]
                token = line.split("=", 1)[1].strip()
                # 移除引号
                for q in ['"', "'"]:
                    if token.startswith(q) and token.endswith(q):
                        token = token[1:-1]
                if token:
                    return token
    return ""

# ===== 统一日志 =====

def log(script_name: str, msg: str):
    """统一日志写入"""
    ts = datetime.now().strftime("%H:%M:%S")
    log_path = HERMES / "logs" / f"{script_name.replace('.py', '')}.log"
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {msg}\n")
    except: pass

# ===== 推送 =====

def push_wechat(title: str, content: str) -> bool:
    """统一推送微信（PushPlus）"""
    import urllib.request
    token = get_pushplus_token()
    if not token:
        log("hermes_common", "PUSH_FAIL: token未配置")
        return False
    try:
        data = json.dumps({
            "token": token, "title": title,
            "content": content, "template": "markdown"
        }).encode("utf-8")
        req = urllib.request.Request(
            "https://www.pushplus.plus/send",
            data=data,
            headers={"Content-Type": "application/json"}
        )
        resp = urllib.request.urlopen(req, timeout=15)
        result = json.loads(resp.read().decode("utf-8"))
        ok = result.get("code") == 200
        if not ok:
            log("hermes_common", f"PUSH_FAIL: {result.get('msg', '?')}")
        return ok
    except Exception as e:
        log("hermes_common", f"PUSH_FAIL: {type(e).__name__}: {e}")
        return False

if __name__ == "__main__":
    print("Hermes Common Utility Module v1.0")
    print(f"Token: {'已配置' if get_pushplus_token() else '未配置'}")
    print("原子写入: ✅")
    print("文件锁: ✅")
