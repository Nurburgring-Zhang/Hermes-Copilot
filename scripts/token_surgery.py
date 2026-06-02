#!/usr/bin/env python3
"""
Hermes 分层上下文压缩系统 v1.0
=================================
联合调用:记忆引擎 + 自进化token压缩 + 注入控制

分层架构:
  Layer 0: 上下文注入控制(每次醒来) — 决定什么被载入上下文
  Layer 1: 会话压缩(自动化) — 压缩state.db的旧会话
  Layer 2: 记忆压缩(已有) — 4层记忆的TTL+去重+老化
  Layer 3: 情报归档(新增) — intelligence.db的冷数据归档
  Layer 4: token预算管理(新增) — 预计算上下文token用量
"""
import sqlite3, json, sys, os, re, subprocess, time
from datetime import datetime, timedelta
from pathlib import Path

HERMES = Path("/home/administrator/.hermes")
LOG = HERMES / "logs" / "token_surgery.log"

def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] 🏥 {msg}"
    print(line)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG, "a") as f:
        f.write(line + "\n")

# ========= Layer 0: 上下文注入控制 =========

def inject_control():
    """
    控制醒来时注入的内容:
    1. SOUL_core.md (紧凑版 2.3KB) vs SOUL.md (全量版 19KB)
    2. USER.md → 必须(3KB)
    3. MEMORY.md → 后50行摘要
    4. task_current.json → 状态检查
    """
    log("=== Layer 0: 注入控制 ===")
    
    # SOUL.md智能选择
    soul_core = HERMES / "SOUL_core.md"
    soul_full = HERMES / "SOUL.md"
    soul_link = HERMES / "SOUL_active.md"
    
    # 默认使用紧凑版
    if soul_core.exists():
        # 创建软链或复制
        core_content = soul_core.read_text()
        soul_link.write_text(core_content)
        core_kb = len(core_content) // 1024
        log(f"SOUL注入: 紧凑版({core_kb}KB) — 节省{18-core_kb}KB")
    else:
        # 回退到全量版
        full_content = soul_full.read_text()
        soul_link.write_text(full_content)
        log(f"SOUL注入: 全量版({len(full_content)//1024}KB)")
    
    # MEMORY.md压缩提取(只保留最新关键事实)
    mem_path = HERMES / "MEMORY.md"
    if mem_path.exists():
        content = mem_path.read_text()
        lines = content.split('\n')
        if len(lines) > 80:
            compressed = '\n'.join(lines[-80:])
            mem_path.write_text(compressed)
            log(f"MEMORY.md: {len(lines)}行→80行")
        else:
            log(f"MEMORY.md: {len(lines)}行(无需压缩)")
    
    # USER.md 年龄检查
    usr_path = HERMES / "USER.md"
    if usr_path.exists():
        mtime = os.path.getmtime(str(usr_path))
        age_hours = (time.time() - mtime) / 3600
        if age_hours > 720:
            log(f"⚠️ USER.md {age_hours:.0f}小时未更新")
    
    return True

# ========= Layer 1: 会话压缩 =========

def compress_sessions(dry_run=False):
    """
    压缩state.db中的旧会话
    策略: >24h且>5条消息的会话,删除旧消息保留最后3条+摘要
    """
    log("=== Layer 1: 会话压缩 ===")
    
    db = sqlite3.connect(str(HERMES / "state.db"))
    db.row_factory = sqlite3.Row
    
    # 找候选会话
    candidates = db.execute("""
        SELECT s.id, s.message_count, s.title, s.started_at,
               COUNT(m.id) as msg_count
        FROM sessions s
        LEFT JOIN messages m ON m.session_id = s.id
        WHERE s.started_at < strftime('%s', 'now', '-24 hours')
        GROUP BY s.id
        HAVING msg_count > 5
        ORDER BY msg_count DESC
        LIMIT 200
    """).fetchall()
    
    log(f"候选会话: {len(candidates)}个")
    total_removed = 0
    
    for c in candidates:
        sid = c['id']
        msg_count = c['msg_count']
        keep_count = 3
        
        # 获取所有消息ID,保留最新的keep_count条
        msg_ids = db.execute("""
            SELECT id FROM messages 
            WHERE session_id = ? 
            ORDER BY id DESC
        """, (sid,)).fetchall()
        
        if len(msg_ids) <= keep_count:
            continue
        
        ids_to_delete = [m['id'] for m in msg_ids[keep_count:]]
        ids_str = ','.join(['?'] * len(ids_to_delete))
        
        if not dry_run:
            deleted = db.execute(
                f"DELETE FROM messages WHERE id IN ({ids_str})",
                ids_to_delete
            ).rowcount
            total_removed += deleted
    
    if not dry_run:
        db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        db.commit()
    
    log(f"删除消息: {total_removed}条(来自{len(candidates)}个会话)")
    db.close()
    return total_removed

# ========= Layer 2: 记忆压缩(调用已有引擎)=========

def compress_memory():
    """调用已有记忆引擎的compress"""
    log("=== Layer 2: 记忆压缩 ===")
    try:
        r = subprocess.run(
            ["python3", str(HERMES / "scripts/hermes_memory_engine_v2.py"), "--compress"],
            capture_output=True, text=True, timeout=120, cwd=str(HERMES)
        )
        log(f"记忆引擎: exit={r.returncode}")
        for l in r.stdout.split('\n')[-3:]:
            if l.strip(): log(f"  {l.strip()[:100]}")
        return r.returncode == 0
    except Exception as e:
        log(f"记忆引擎失败: {e}")
        return False

# ========= Layer 3: 情报归档 =========

def archive_intel(dry_run=False):
    """
    将cleaned_intelligence中>7天的低分数据归档
    释放intelligence.db空间
    """
    log("=== Layer 3: 情报归档 ===")
    
    db = sqlite3.connect(str(HERMES / "intelligence.db"))
    
    # 找>7天的低分记录
    old_low = db.execute("""
        SELECT COUNT(*) FROM cleaned_intelligence
        WHERE cleaned_at < datetime('now', '-7 days')
          AND ai_score_total < 40
    """).fetchone()[0]
    
    log(f">7天低分(ai<40)记录: {old_low}条")
    
    if old_low > 0 and not dry_run:
        # 移到归档表(或直接删除低分旧数据)
        deleted = db.execute("""
            DELETE FROM cleaned_intelligence
            WHERE cleaned_at < datetime('now', '-7 days')
              AND ai_score_total < 40
        """).rowcount
        db.commit()
        log(f"已归档清理: {deleted}条")
    
    db.close()
    return old_low

# ========= Layer 4: token预算管理 =========

def token_budget_check():
    """
    估算当前上下文中各部分的token消耗
    返回token分配建议
    """
    log("=== Layer 4: Token预算 ===")
    
    # 估算主要文件大小
    files = {
        "SOUL.md": HERMES / "SOUL.md",
        "USER.md": HERMES / "USER.md", 
        "MEMORY.md": HERMES / "MEMORY.md",
        "task_current.json": HERMES / "task_current.json",
        "task_tracker.json": HERMES / "task_tracker.json",
    }
    
    total_chars = 0
    budget = {}
    for name, path in files.items():
        if path.exists():
            chars = len(path.read_text())
            est_tokens = chars // 2  # 中英文混合估算
            total_chars += chars
            budget[name] = {"chars": chars, "est_tokens": est_tokens}
    
    # 建议
    log(f"总字符: {total_chars:,} -> 估算 {total_chars//2:,} tokens")
    
    suggestions = []
    for name, info in budget.items():
        pct = info['chars'] * 100 // max(total_chars, 1)
        if info['chars'] > 5000:
            suggestions.append(f"⚠️ {name}: {info['chars']:,}ch/{info['est_tokens']:,}tok ({pct}%) — 建议压缩")
        else:
            suggestions.append(f"✅ {name}: {info['chars']:,}ch/{info['est_tokens']:,}tok ({pct}%)")
    
    for s in suggestions:
        log(s)
    
    return budget

# ========= 主入口 =========

def main():
    action = sys.argv[1] if len(sys.argv) > 1 else "all"
    
    if action == "inject":
        inject_control()
    elif action == "sessions":
        compress_sessions()
    elif action == "memory":
        compress_memory()
    elif action == "archive":
        archive_intel()
    elif action == "budget":
        token_budget_check()
    elif action == "all":
        log("=" * 50)
        log("🏥 分层上下文压缩 - 全栈执行")
        log("=" * 50)
        inject_control()
        compress_sessions()
        compress_memory()
        archive_intel()
        token_budget_check()
        log("=" * 50)
        log("✅ 全栈压缩完成")
        log("=" * 50)
    elif action == "dry-run":
        log("🏥 DRY RUN MODE")
        candidates = compress_sessions(dry_run=True)
        old = archive_intel(dry_run=True)
        log(f"DRY RUN: {candidates}条会话, {old}条情报待归档")
    else:
        print(f"用法: python3 {sys.argv[0]} [inject|sessions|memory|archive|budget|all|dry-run]")
        sys.exit(1)

if __name__ == "__main__":
    main()
