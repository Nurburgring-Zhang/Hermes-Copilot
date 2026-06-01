#!/usr/bin/env python3
"""
Hermes 任务队列管理器 — 长期多进程任务状态管理
================================================
解决: delegate_task只能并行3个，且没有任务队列、状态监控、失败重试

功能:
  1. 任务队列: 先进先出, 优先级排序
  2. 并发控制: 最多N个任务同时运行
  3. 状态监控: 每个任务的状态跟踪
  4. 失败重试: 自动重试失败任务
  5. 持久化: SQLite存储任务状态

使用方式:
  python3 scripts/task_queue_manager.py submit <任务名> <命令>   # 提交任务
  python3 scripts/task_queue_manager.py status                   # 查看所有任务
  python3 scripts/task_queue_manager.py retry <task_id>          # 重试
  python3 scripts/task_queue_manager.py cancel <task_id>         # 取消
  python3 scripts/task_queue_manager.py process                  # 处理队列
"""

import json, sqlite3, time, subprocess, sys, os, threading, uuid
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, List, Any

HERMES = Path("/home/administrator/.hermes")
DB_PATH = HERMES / "reports" / "task_queue.db"
MAX_CONCURRENT = 5  # 最多5个并行
MAX_RETRIES = 3


def get_db():
    """获取数据库连接"""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            command TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            priority INTEGER DEFAULT 5,
            retries INTEGER DEFAULT 0,
            max_retries INTEGER DEFAULT 3,
            created_at TEXT DEFAULT (datetime('now')),
            started_at TEXT,
            completed_at TEXT,
            output TEXT,
            error TEXT,
            depends_on TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS task_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT,
            ts TEXT DEFAULT (datetime('now')),
            message TEXT
        )
    """)
    conn.commit()
    return conn


def submit(name: str, command: str, priority: int = 5, depends_on: str = ""):
    """提交一个新任务"""
    conn = get_db()
    task_id = str(uuid.uuid4())[:8]
    conn.execute(
        "INSERT INTO tasks (id, name, command, priority, depends_on) VALUES (?, ?, ?, ?, ?)",
        (task_id, name, command, priority, depends_on)
    )
    conn.commit()
    conn.close()
    _log_task(task_id, f"提交: {name}")
    print(f"[task_queue] ✅ 提交任务 {task_id}: {name}")
    return task_id


def process():
    """处理队列 — 启动待处理的任务"""
    conn = get_db()
    
    # 检查当前运行中的任务数
    running = conn.execute("SELECT COUNT(*) FROM tasks WHERE status='running'").fetchone()[0]
    available = MAX_CONCURRENT - running
    
    if available <= 0:
        print(f"[task_queue] 已达最大并发({MAX_CONCURRENT}), 等待中")
        conn.close()
        return
    
    # 获取待处理任务(按优先级排序)
    pending = conn.execute(
        "SELECT * FROM tasks WHERE status='pending' ORDER BY priority ASC, created_at ASC LIMIT ?",
        (available,)
    ).fetchall()
    
    for task in pending:
        task_id = task["id"]
        
        # 检查依赖是否完成
        if task["depends_on"]:
            dep_status = conn.execute(
                "SELECT status FROM tasks WHERE id=?", (task["depends_on"],)
            ).fetchone()
            if not dep_status or dep_status["status"] != "completed":
                continue  # 依赖未完成，跳过
        
        # 标记为运行中
        conn.execute(
            "UPDATE tasks SET status='running', started_at=datetime('now') WHERE id=?",
            (task_id,)
        )
        conn.commit()
        conn.close()
        
        _log_task(task_id, f"开始执行: {task['command'][:100]}")
        print(f"[task_queue] ▶️ 运行 {task_id}: {task['name']}")
        
        # 后台执行
        threading.Thread(target=_run_task, args=(task_id, task["command"]), daemon=True).start()
        
        conn = get_db()
    
    conn.close()


def _run_task(task_id: str, command: str):
    """在后台线程中执行任务"""
    try:
        result = subprocess.run(
            command, shell=True, capture_output=True, text=True, timeout=3600
        )
        output = (result.stdout or "")[:1000]
        error = (result.stderr or "")[:500]
        
        conn = get_db()
        if result.returncode == 0:
            conn.execute(
                "UPDATE tasks SET status='completed', completed_at=datetime('now'), output=? WHERE id=?",
                (output, task_id)
            )
            _log_task(task_id, f"✅ 完成")
            print(f"[task_queue] ✅ {task_id} 完成")
        else:
            # 检查重试次数
            task = conn.execute("SELECT retries, max_retries FROM tasks WHERE id=?", (task_id,)).fetchone()
            retries = task["retries"] + 1 if task else 1
            if retries <= (task["max_retries"] if task else MAX_RETRIES):
                conn.execute(
                    "UPDATE tasks SET status='pending', retries=?, error=? WHERE id=?",
                    (retries, error[:300], task_id)
                )
                _log_task(task_id, f"🔄 失败(将重试第{retries}次): {error[:100]}")
                print(f"[task_queue] 🔄 {task_id} 失败, 将重试({retries}/{(task['max_retries'] if task else MAX_RETRIES)})")
            else:
                conn.execute(
                    "UPDATE tasks SET status='failed', completed_at=datetime('now'), error=? WHERE id=?",
                    (error[:500], task_id)
                )
                _log_task(task_id, f"❌ 失败(已达最大重试): {error[:100]}")
                print(f"[task_queue] ❌ {task_id} 失败(已达最大重试)")
        conn.commit()
        conn.close()
    except subprocess.TimeoutExpired:
        conn = get_db()
        conn.execute(
            "UPDATE tasks SET status='failed', completed_at=datetime('now'), error='超时(3600s)' WHERE id=?",
            (task_id,)
        )
        conn.commit()
        conn.close()
        _log_task(task_id, "❌ 超时")
    except Exception as e:
        conn = get_db()
        conn.execute(
            "UPDATE tasks SET status='failed', completed_at=datetime('now'), error=? WHERE id=?",
            (str(e)[:500], task_id)
        )
        conn.commit()
        conn.close()
        _log_task(task_id, f"❌ 异常: {str(e)[:100]}")


def status():
    """查看所有任务状态"""
    conn = get_db()
    tasks = conn.execute("SELECT * FROM tasks ORDER BY created_at DESC LIMIT 50").fetchall()
    conn.close()
    
    if not tasks:
        print("[task_queue] 无任务")
        return
    
    # 统计
    counts = {}
    for t in tasks:
        s = t["status"]
        counts[s] = counts.get(s, 0) + 1
    
    print(f"[task_queue] 任务列表 (总计{len(tasks)}个, 运行中{counts.get('running',0)}, 待处理{counts.get('pending',0)})")
    for t in tasks:
        status_icon = {"running": "▶️", "completed": "✅", "failed": "❌", "pending": "⏳"}
        icon = status_icon.get(t["status"], "❓")
        print(f"  {icon} {t['id']:8s} {t['name'][:30]:30s} [{t['status']:9s}] 重试{t['retries']}/{t['max_retries']}")


def cancel(task_id: str):
    """取消任务"""
    conn = get_db()
    conn.execute("UPDATE tasks SET status='cancelled' WHERE id=?", (task_id,))
    conn.commit()
    conn.close()
    _log_task(task_id, "已取消")
    print(f"[task_queue] ❌ 已取消 {task_id}")


def retry_task(task_id: str):
    """重试失败任务"""
    conn = get_db()
    conn.execute("UPDATE tasks SET status='pending', retries=0, error=NULL WHERE id=?", (task_id,))
    conn.commit()
    conn.close()
    _log_task(task_id, "标记为重试")
    print(f"[task_queue] 🔄 已标记重试 {task_id}")


def _log_task(task_id: str, message: str):
    """记录任务日志"""
    try:
        conn = get_db()
        conn.execute("INSERT INTO task_log (task_id, message) VALUES (?, ?)", (task_id, message))
        conn.commit()
        conn.close()
    except:
        pass


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    
    if cmd == "submit":
        name = sys.argv[2] if len(sys.argv) > 2 else "unnamed"
        command = sys.argv[3] if len(sys.argv) > 3 else ""
        priority = int(sys.argv[4]) if len(sys.argv) > 4 else 5
        submit(name, command, priority)
    elif cmd == "process":
        process()
    elif cmd == "status":
        status()
    elif cmd == "cancel":
        cancel(sys.argv[2])
    elif cmd == "retry":
        retry_task(sys.argv[2])
    else:
        print("用法: task_queue_manager.py [submit|process|status|cancel|retry]")


if __name__ == "__main__":
    main()
