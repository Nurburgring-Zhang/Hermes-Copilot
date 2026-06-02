#!/usr/bin/env python3
"""
hermes_tools.py — Hermes 工具调用模拟接口 (tool_wrapper.py 缺失的底层模块)
=======================================================================
为 tool_wrapper.py 提供 read_file/write_file/terminal/search_files/patch 的
文件系统级实现，使 T.* 方法能真实运行而无需依赖 hermes_tools 模块。

创建日期: 2026-05-29
对应: tool_wrapper.py 的从 hermes_tools import ... 语句
"""

import os
import re
import json
import shlex
import subprocess
import time
from pathlib import Path


HOME = str(Path.home())
CWD = os.getcwd()


def read_file(path: str, offset: int = 1, limit: int = 500) -> dict:
    """读取文件内容"""
    # 展开路径
    if path.startswith('~/'):
        path = os.path.join(HOME, path[2:])
    path = os.path.abspath(path)

    if not os.path.exists(path):
        return {"error": f"File not found: {path}", "content": "", "total_lines": 0}

    try:
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            lines = f.readlines()

        total = len(lines)
        start = max(0, offset - 1)
        end = min(total, start + limit)
        content = ''.join(lines[start:end])

        return {
            "content": content,
            "total_lines": total,
            "file_size": os.path.getsize(path),
            "truncated": end < total,
        }
    except Exception as e:
        return {"error": str(e), "content": "", "total_lines": 0}


def write_file(path: str, content: str) -> dict:
    """写入文件"""
    if path.startswith('~/'):
        path = os.path.join(HOME, path[2:])
    path = os.path.abspath(path)

    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(content)
        return {"bytes_written": len(content), "dirs_created": True}
    except Exception as e:
        return {"error": str(e), "bytes_written": 0}


def terminal(command: str, timeout: int = 180, workdir: str = None) -> dict:
    """执行终端命令"""
    try:
        if workdir:
            cwd = workdir if os.path.isabs(workdir) else os.path.join(CWD, workdir)
        else:
            cwd = CWD

        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd,
        )
        output = result.stdout
        if result.stderr:
            output += "\n" + result.stderr

        return {
            "output": output.strip(),
            "exit_code": result.returncode,
            "error": result.stderr.strip() if result.returncode != 0 else None,
        }
    except subprocess.TimeoutExpired:
        return {"output": "", "exit_code": -1, "error": "Command timed out"}
    except Exception as e:
        return {"output": "", "exit_code": -1, "error": str(e)}


def search_files(pattern: str, target: str = "content", path: str = ".", file_glob: str = None, limit: int = 50) -> dict:
    """搜索文件内容或文件名"""
    search_path = path
    if search_path.startswith('~/'):
        search_path = os.path.join(HOME, search_path[2:])
    search_path = os.path.abspath(search_path)

    try:
        if target == "files":
            # 文件名搜索：用 glob
            import glob
            matches = glob.glob(os.path.join(search_path, "**", pattern), recursive=True)
            matches = [m.replace(search_path + "/", "") for m in matches[:limit]]
            return {"matches": matches, "total_count": min(len(matches), limit)}
        else:
            # 内容搜索：用 grep
            cmd_parts = ["grep", "-rn", "--include", file_glob or "*", pattern, search_path]
            cmd_parts = [shlex.quote(p) if ' ' in p else p for p in cmd_parts]
            cmd = " ".join(cmd_parts)
            result = subprocess.run(
                cmd, shell=True, capture_output=True, text=True, timeout=30
            )
            lines = result.stdout.strip().split('\n') if result.stdout.strip() else []
            limited = lines[:limit]
            matches = []
            for line in limited:
                parts = line.split(':', 2)
                if len(parts) >= 2:
                    fpath = parts[0].replace(search_path + "/", "")
                    lnum = parts[1]
                    text = parts[2] if len(parts) > 2 else ""
                    matches.append(f"{fpath}:{lnum}: {text[:200]}")
            return {"matches": matches, "total_count": len(matches)}
    except Exception as e:
        return {"matches": [], "error": str(e)}


def patch(path: str, old_string: str, new_string: str, replace_all: bool = False) -> dict:
    """查找替换文件内容"""
    if path.startswith('~/'):
        path = os.path.join(HOME, path[2:])
    path = os.path.abspath(path)

    if not os.path.exists(path):
        return {"error": f"File not found: {path}"}

    try:
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()

        if replace_all:
            new_content = content.replace(old_string, new_string)
        else:
            if old_string not in content:
                return {"error": f"old_string not found in {path}"}
            new_content = content.replace(old_string, new_string, 1)

        with open(path, 'w', encoding='utf-8') as f:
            f.write(new_content)

        return {
            "success": True,
            "diff": f"Replaced {len(old_string)} chars with {len(new_string)} chars",
        }
    except Exception as e:
        return {"error": str(e)}
