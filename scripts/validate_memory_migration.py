#!/usr/bin/env python3
"""
验证记忆数据库迁移
检查 OpenClaw → Hermes 记忆数据的一致性
"""

import sqlite3
from pathlib import Path
import hashlib

def verify_database(db_path):
    """验证数据库完整性"""
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # 检查表结构
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = [t[0] for t in cursor.fetchall()]
        
        stats = {}
        for table in tables:
            cursor.execute(f"SELECT COUNT(*) FROM {table};")
            count = cursor.fetchone()[0]
            stats[table] = count
        
        conn.close()
        return True, stats, None
    except Exception as e:
        return False, {}, str(e)

def compare_databases(openclaw_db, hermes_db):
    """对比两个数据库"""
    print(f"🔍 对比: {openclaw_db.name} vs {hermes_db.name}")
    
    ok1, stats1, err1 = verify_database(openclaw_db)
    ok2, stats2, err2 = verify_database(hermes_db)
    
    if not ok1:
        print(f"❌ OpenClaw DB 错误: {err1}")
        return False
    
    if not ok2:
        print(f"❌ Hermes DB 错误: {err2}")
        return False
    
    print(f"  OpenClaw: {stats1}")
    print(f"  Hermes:   {stats2}")
    
    # 对比关键表
    for table in ['files', 'chunks', 'chunks_fts']:
        if table in stats1 and table in stats2:
            if stats1[table] != stats2[table]:
                print(f"  ⚠️  表 {table} 记录数不匹配: {stats1[table]} vs {stats2[table]}")
                return False
    
    print("  ✅ 数据库一致")
    return True

def main():
    openclaw_memory = Path("/mnt/c/Users/Administrator/.openclaw/memory")
    hermes_memory = Path.home() / ".hermes/memory"
    
    databases = [
        "main.sqlite",
        "security-expert.sqlite", 
        "research-expert.sqlite",
        "analyst-expert.sqlite",
        "dev-expert.sqlite"
    ]
    
    all_ok = True
    for db_name in databases:
        openclaw_db = openclaw_memory / db_name
        hermes_db = hermes_memory / db_name
        
        if openclaw_db.exists() and hermes_db.exists():
            if not compare_databases(openclaw_db, hermes_db):
                all_ok = False
        else:
            print(f"❌ 缺少数据库: {db_name}")
            all_ok = False
    
    if all_ok:
        print("✅ 所有记忆数据库验证通过")
    else:
        print("❌ 验证失败,请检查")
    
    return all_ok

if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)
