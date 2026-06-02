#!/usr/bin/env python3
"""
agents_company.db - 代理公司员工数据库网关
直接复制employees.sqlite和departments.sqlite的表结构+数据。
"""
import sqlite3
from pathlib import Path

AGENTS_DIR = Path.home() / '.hermes' / 'agents_company'
DATA_DIR = AGENTS_DIR / 'data'
DB_PATH = Path.home() / '.hermes' / 'data' / 'agents_company.db'

def copy_table(src_path, table_name, dest_conn):
    """Copy a table (schema + data) from src db to dest conn."""
    if not src_path.exists():
        print(f"  Source {src_path} not found, skipping")
        return False
    src = sqlite3.connect(str(src_path))
    
    # Get CREATE TABLE statement
    schema = src.execute(f"SELECT sql FROM sqlite_master WHERE type='table' AND name='{table_name}'").fetchone()
    if not schema:
        print(f"  Table {table_name} not found in {src_path}")
        src.close()
        return False
    
    # Drop existing if any
    dest_conn.execute(f"DROP TABLE IF EXISTS {table_name}")
    dest_conn.execute(schema[0])
    
    # Copy data
    cols_info = src.execute(f"PRAGMA table_info({table_name})").fetchall()
    col_names = [c[1] for c in cols_info]
    placeholders = ','.join(['?'] * len(col_names))
    col_str = ','.join(col_names)
    
    rows = src.execute(f"SELECT * FROM {table_name}").fetchall()
    for row in rows:
        dest_conn.execute(f"INSERT INTO {table_name} ({col_str}) VALUES ({placeholders})", row)
    
    dest_conn.commit()
    src.close()
    print(f"  Copied {len(rows)} rows into {table_name}")
    return True

def init_db():
    conn = sqlite3.connect(str(DB_PATH))
    
    print("Copying tables:")
    copy_table(DATA_DIR / 'employees.sqlite', 'employees', conn)
    copy_table(DATA_DIR / 'departments.sqlite', 'departments', conn)
    
    # Create collaboration_network table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS collaboration_network (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_a_id TEXT,
            employee_b_id TEXT,
            collaboration_count INTEGER DEFAULT 1,
            last_collaboration TEXT,
            strength REAL DEFAULT 0.5
        )
    """)
    conn.commit()
    
    # Verify
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = cursor.fetchall()
    print(f"\nagents_company.db verified:")
    for t in tables:
        cnt = cursor.execute(f"SELECT COUNT(*) FROM [{t[0]}]").fetchone()[0]
        print(f"  Table {t[0]}: {cnt} rows")
    conn.close()

if __name__ == '__main__':
    init_db()
