#!/usr/bin/env python3
"""Reflex Fabric 心跳维护脚本 — 直接连接 state.db,绕过 agents_company import 链"""
import sqlite3
from datetime import datetime

DB_PATH = "/home/administrator/.hermes/state.db"
STALE_TIMEOUT = 300  # seconds
DELETE_OLD_DELIVERED_AFTER = 3600  # 1 hour

def main():
    db = sqlite3.connect(DB_PATH)
    cur = db.cursor()
    now_ts = datetime.now().isoformat()

    # --- 1. Detect stale nodes ---
    total_nodes = cur.execute('SELECT COUNT(*) FROM reflex_nodes').fetchone()[0]
    online_nodes = cur.execute("SELECT COUNT(*) FROM reflex_nodes WHERE status='online'").fetchone()[0]
    stale_nodes = cur.execute("""
        SELECT agent_id, name, last_heartbeat
        FROM reflex_nodes
        WHERE status='online'
          AND last_heartbeat != ''
          AND (julianday(?) - julianday(last_heartbeat)) * 86400 > ?
    """, (now_ts, STALE_TIMEOUT)).fetchall()

    for agent_id, name, last_hb in stale_nodes:
        cur.execute("UPDATE reflex_nodes SET status='offline', load=0.0 WHERE agent_id=?", (agent_id,))

    # --- 2. Clean expired undelivered messages ---
    cur.execute("""
        UPDATE reflex_messages
        SET delivered=1, delivered_at=?
        WHERE delivered=0
          AND (julianday(?) - julianday(created_at)) * 86400 > ttl_seconds
    """, (now_ts, now_ts))
    expired_cleaned = cur.rowcount

    # --- 3. Prune old delivered messages ---
    cur.execute("""
        DELETE FROM reflex_messages
        WHERE delivered=1
          AND delivered_at != ''
          AND (julianday(?) - julianday(delivered_at)) * 86400 > ?
    """, (now_ts, DELETE_OLD_DELIVERED_AFTER))
    pruned_count = cur.rowcount

    # --- 4. Self-register heartbeat ---
    cur.execute("""
        INSERT OR REPLACE INTO reflex_nodes (agent_id, name, agent_type, status, last_heartbeat, registered_at)
        VALUES ('fabric_heartbeat', 'Fabric Heartbeat', 'system', 'online', ?,
                COALESCE((SELECT registered_at FROM reflex_nodes WHERE agent_id='fabric_heartbeat'), ?))
    """, (now_ts, now_ts))

    db.commit()

    # --- 5. Final stats ---
    total_after = cur.execute('SELECT COUNT(*) FROM reflex_nodes').fetchone()[0]
    online_after = cur.execute("SELECT COUNT(*) FROM reflex_nodes WHERE status='online'").fetchone()[0]
    offline_after = cur.execute("SELECT COUNT(*) FROM reflex_nodes WHERE status='offline'").fetchone()[0]
    total_msgs = cur.execute('SELECT COUNT(*) FROM reflex_messages').fetchone()[0]
    undelivered = cur.execute('SELECT COUNT(*) FROM reflex_messages WHERE delivered=0').fetchone()[0]
    hb_time = cur.execute("SELECT last_heartbeat FROM reflex_nodes WHERE agent_id='fabric_heartbeat'").fetchone()[0]

    db.close()

    # --- Report ---
    print("=== Reflex Fabric 心跳维护报告 ===")
    print(f"⏱  时间:       {now_ts}")
    print()
    print("📊 节点统计")
    print(f"    注册:       {total_after}")
    print(f"    在线:       {online_after}")
    print(f"    离线:       {offline_after}")
    print()
    print("📋 维护操作")
    print(f"    超时下线:   {len(stale_nodes)}")
    for a_id, name, lhb in stale_nodes:
        print(f"      - {name} ({a_id}) last_hb={lhb}")
    print(f"    过期消息清理: {expired_cleaned}")
    print(f"    旧消息删除:   {pruned_count}")
    print()
    print("📨 消息统计")
    print(f"    总数:       {total_msgs}")
    print(f"    未投递:     {undelivered}")
    print()
    print("✅ Fabric 自注册心跳")
    print(f"    心跳时间:   {hb_time}")

if __name__ == "__main__":
    main()
