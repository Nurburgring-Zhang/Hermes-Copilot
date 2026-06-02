#!/usr/bin/env python3
"""
Vacuum state.db and optionally intelligence.db.
Steps:
1. Check current size
2. Check for old data (sessions/conversations) to purge
3. Create backup
4. Vacuum
5. Check integrity
6. Report results
"""
import os
import sys
import time
import shutil
import sqlite3
from datetime import datetime, timedelta

HOME = os.path.expanduser("~")
HERMES_DIR = os.path.join(HOME, ".hermes")
BACKUPS_DIR = os.path.join(HERMES_DIR, "backups")
STATE_DB = os.path.join(HERMES_DIR, "state.db")
INTEL_DB = os.path.join(HERMES_DIR, "intelligence.db")

def get_db_size(path):
    """Get the real file size on disk."""
    if not os.path.exists(path):
        return 0
    return os.path.getsize(path)

def get_wal_size(path):
    """Get the WAL file size if it exists."""
    wal_path = path + "-wal"
    if os.path.exists(wal_path):
        return os.path.getsize(wal_path)
    return 0

def get_shm_size(path):
    """Get the SHM file size if it exists."""
    shm_path = path + "-shm"
    if os.path.exists(shm_path):
        return os.path.getsize(shm_path)
    return 0

def human_size(bytes_val):
    """Convert bytes to human-readable string."""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if bytes_val < 1024:
            return f"{bytes_val:.2f} {unit}"
        bytes_val /= 1024
    return f"{bytes_val:.2f} TB"

def get_db_info(db_path):
    """Get database page statistics."""
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    info = {}
    try:
        c.execute("PRAGMA page_count")
        info['page_count'] = c.fetchone()[0]
        c.execute("PRAGMA page_size")
        info['page_size'] = c.fetchone()[0]
        c.execute("PRAGMA freelist_count")
        info['freelist_count'] = c.fetchone()[0]
        c.execute("PRAGMA schema_version")
        info['schema_version'] = c.fetchone()[0]
        # Check if it's in WAL mode
        c.execute("PRAGMA journal_mode")
        info['journal_mode'] = c.fetchone()[0]
    finally:
        conn.close()
    return info

def list_tables(db_path):
    """List all tables in the database."""
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    tables = [row[0] for row in c.fetchall()]
    conn.close()
    return tables

def check_old_data(db_path):
    """Check for tables with session/conversation data older than 30 days."""
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    results = {}
    
    tables = list_tables(db_path)
    session_like = [t for t in tables if any(kw in t.lower() for kw in ['session', 'conversation', 'message', 'chat', 'dialog', 'history'])]
    
    for table in session_like:
        try:
            # Check if table has a timestamp column
            c.execute(f"PRAGMA table_info(\"{table}\")")
            columns = [row[1] for row in c.fetchall()]
            
            time_cols = [col for col in columns if any(kw in col.lower() for kw in ['time', 'date', 'timestamp', 'created', 'updated', 'ts'])]
            
            if time_cols:
                col = time_cols[0]
                # Count total rows
                c.execute(f"SELECT COUNT(*) FROM \"{table}\"")
                total = c.fetchone()[0]
                # Count rows older than 30 days
                cutoff = (datetime.now() - timedelta(days=30)).isoformat()
                c.execute(f"SELECT COUNT(*) FROM \"{table}\" WHERE \"{col}\" < ?", (cutoff,))
                old_count = c.fetchone()[0]
                if old_count > 0:
                    results[table] = {'total': total, 'old': old_count, 'time_column': col, 'cutoff': cutoff}
        except Exception as e:
            pass
    
    conn.close()
    return results

def delete_old_data(db_path, old_data_info):
    """Delete old records from session/conversation tables."""
    deleted_total = 0
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    for table, info in old_data_info.items():
        try:
            c.execute(f"DELETE FROM \"{table}\" WHERE \"{info['time_column']}\" < ?", (info['cutoff'],))
            deleted = c.rowcount
            deleted_total += deleted
            print(f"  Deleted {deleted} old rows from '{table}'")
        except Exception as e:
            print(f"  Error deleting from '{table}': {e}")
    conn.commit()
    conn.close()
    return deleted_total

def vacuum_db(db_path):
    """Execute VACUUM on the database."""
    print(f"  Executing VACUUM on {db_path}...")
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("VACUUM;")
    conn.commit()
    conn.close()
    print("  VACUUM completed.")

def integrity_check(db_path):
    """Run integrity check."""
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    try:
        c.execute("PRAGMA integrity_check;")
        result = c.fetchall()
        conn.close()
        return [row[0] for row in result]
    except Exception as e:
        conn.close()
        return [f"ERROR: {e}"]

def main():
    print("=" * 60)
    print("HERMES DATABASE VACUUM & COMPRESSION")
    print("=" * 60)
    print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    # ---- STATE.DB ----
    print("[1] STATE.DB ANALYSIS")
    print("-" * 40)
    
    if not os.path.exists(STATE_DB):
        print(f"  ERROR: state.db not found at {STATE_DB}")
        sys.exit(1)
    
    # Before sizes
    before_size = get_db_size(STATE_DB)
    before_wal = get_wal_size(STATE_DB)
    before_shm = get_shm_size(STATE_DB)
    before_total = before_size + before_wal + before_shm
    
    print(f"  Path: {STATE_DB}")
    print(f"  Database file size: {human_size(before_size)}")
    print(f"  WAL file size: {human_size(before_wal)}")
    print(f"  SHM file size: {human_size(before_shm)}")
    print(f"  Total on disk: {human_size(before_total)}")
    
    db_info = get_db_info(STATE_DB)
    print(f"  Page count: {db_info['page_count']:,}")
    print(f"  Page size: {db_info['page_size']} bytes")
    print(f"  Free pages (freelist): {db_info['freelist_count']:,}")
    print(f"  Journal mode: {db_info['journal_mode']}")
    
    if db_info['freelist_count'] > 0:
        free_mb = db_info['freelist_count'] * db_info['page_size'] / (1024*1024)
        print(f"  Estimated reclaimable: ~{human_size(db_info['freelist_count'] * db_info['page_size'])}")
    else:
        print(f"  No freelist pages - VACUUM may still compact WAL")
    
    print()
    
    # Check for old data
    print("[2] CHECKING OLD SESSION/CONVERSATION DATA")
    print("-" * 40)
    tables = list_tables(STATE_DB)
    print(f"  Tables in state.db ({len(tables)}): {', '.join(tables[:20])}{'...' if len(tables) > 20 else ''}")
    
    old_data = check_old_data(STATE_DB)
    if old_data:
        print(f"  Found {len(old_data)} table(s) with data older than 30 days:")
        for table, info in old_data.items():
            print(f"    {table}: {info['old']} old rows out of {info['total']} total (time col: {info['time_column']})")
        print("  Deleting old data before VACUUM...")
        total_deleted = delete_old_data(STATE_DB, old_data)
        print(f"  Total deleted: {total_deleted} rows")
        # Recheck db info after deletion
        db_info = get_db_info(STATE_DB)
        print(f"  Free pages after deletion: {db_info['freelist_count']:,}")
    else:
        print("  No session/conversation tables with old data found.")
        # More thorough check - look at all tables for time columns
        print("  Checking all tables for any time-based columns...")
        conn = sqlite3.connect(STATE_DB)
        c = conn.cursor()
        for table in tables:
            try:
                c.execute(f"PRAGMA table_info(\"{table}\")")
                cols = [row[1] for row in c.fetchall()]
                time_cols = [col for col in cols if any(kw in col.lower() for kw in ['time', 'date', 'timestamp', 'created', 'updated', 'ts'])]
                if time_cols:
                    c.execute(f"SELECT COUNT(*) FROM \"{table}\"")
                    total = c.fetchone()[0]
                    if total > 0:
                        print(f"    {table}: {total} rows, time cols: {time_cols}")
            except:
                pass
        conn.close()
    
    print()
    
    # Create backup
    print("[3] CREATING BACKUP")
    print("-" * 40)
    os.makedirs(BACKUPS_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = os.path.join(BACKUPS_DIR, f"state_backup_{timestamp}.db")
    
    print(f"  Copying {human_size(before_size)} to {backup_path}...")
    start = time.time()
    shutil.copy2(STATE_DB, backup_path)
    elapsed = time.time() - start
    print(f"  Backup completed in {elapsed:.2f}s")
    print(f"  Backup: {backup_path}")
    
    print()
    
    # VACUUM
    print("[4] VACUUM")
    print("-" * 40)
    
    # Check if we need to checkpoint WAL first
    if db_info['journal_mode'] == 'wal':
        print("  Database is in WAL mode - checkpointing WAL...")
        conn = sqlite3.connect(STATE_DB)
        c = conn.cursor()
        c.execute("PRAGMA wal_checkpoint(TRUNCATE);")
        result = c.fetchone()
        print(f"  Checkpoint result: {result}")
        conn.close()
    
    start = time.time()
    vacuum_db(STATE_DB)
    elapsed = time.time() - start
    print(f"  VACUUM took {elapsed:.2f}s")
    
    print()
    
    # After sizes
    print("[5] POST-VACUUM RESULTS")
    print("-" * 40)
    after_size = get_db_size(STATE_DB)
    after_wal = get_wal_size(STATE_DB)
    after_shm = get_shm_size(STATE_DB)
    after_total = after_size + after_wal + after_shm
    
    db_info_after = get_db_info(STATE_DB)
    
    print(f"  Database file size: {human_size(after_size)}")
    print(f"  WAL file size: {human_size(after_wal)}")
    print(f"  SHM file size: {human_size(after_shm)}")
    print(f"  Total on disk: {human_size(after_total)}")
    print(f"  Page count: {db_info_after['page_count']:,}")
    print(f"  Free pages (freelist): {db_info_after['freelist_count']:,}")
    print(f"  Journal mode: {db_info_after['journal_mode']}")
    
    freed_db = before_size - after_size
    freed_total = before_total - after_total
    
    print()
    print(f"  DB file reduction: {human_size(freed_db)} ({freed_db / max(before_size, 1) * 100:.1f}%)")
    print(f"  Total on-disk reduction: {human_size(freed_total)} ({freed_total / max(before_total, 1) * 100:.1f}%)")
    
    print()
    
    # Integrity check
    print("[6] INTEGRITY CHECK")
    print("-" * 40)
    integrity = integrity_check(STATE_DB)
    print(f"  Result: {'OK' if integrity == ['ok'] else 'ISSUES FOUND'}")
    if integrity != ['ok']:
        for line in integrity:
            print(f"    {line}")
    
    print()
    
    # ---- INTELLIGENCE.DB ----
    print("[7] INTELLIGENCE.DB CHECK")
    print("-" * 40)
    
    if os.path.exists(INTEL_DB):
        intel_size = get_db_size(INTEL_DB)
        print(f"  Path: {INTEL_DB}")
        print(f"  Size: {human_size(intel_size)}")
        
        if intel_size > 20 * 1024 * 1024:  # > 20MB
            intel_info = get_db_info(INTEL_DB)
            print(f"  Page count: {intel_info['page_count']:,}")
            print(f"  Free pages: {intel_info['freelist_count']:,}")
            
            freelist_bytes = intel_info['freelist_count'] * intel_info['page_size']
            intel_free_pct = freelist_bytes / max(intel_size, 1) * 100
            
            print(f"  Freelist space: {human_size(freelist_bytes)} ({intel_free_pct:.1f}% of file)")
            
            if intel_info['freelist_count'] > 0 and freelist_bytes > 1024 * 1024:  # > 1MB free
                print(f"  Significant free space detected. Running VACUUM on intelligence.db...")
                
                # Backup
                intel_backup = os.path.join(BACKUPS_DIR, f"intelligence_backup_{timestamp}.db")
                shutil.copy2(INTEL_DB, intel_backup)
                
                intel_before = intel_size
                vacuum_db(INTEL_DB)
                intel_after = get_db_size(INTEL_DB)
                
                intel_after_info = get_db_info(INTEL_DB)
                freed = intel_before - intel_after
                
                print(f"  intelligence.db: {human_size(intel_before)} -> {human_size(intel_after)}")
                print(f"  Freed: {human_size(freed)} ({freed / max(intel_before, 1) * 100:.1f}%)")
                print(f"  Free pages after: {intel_after_info['freelist_count']:,}")
                
                # Integrity check
                print(f"  Running integrity check...")
                intel_integrity = integrity_check(INTEL_DB)
                print(f"  Integrity: {'OK' if intel_integrity == ['ok'] else 'ISSUES FOUND'}")
            else:
                print(f"  Not enough free space to justify VACUUM. Skipping.")
        else:
            print(f"  Size < 20MB threshold. Skipping VACUUM.")
    else:
        print(f"  intelligence.db not found at {INTEL_DB}. Skipping.")
    
    print()
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    
    # State db summary
    print(f"state.db: {human_size(before_size)} -> {human_size(after_size)}")
    print(f"  DB freed: {human_size(freed_db)} ({freed_db / max(before_size, 1) * 100:.1f}%)")
    print(f"  Total on-disk (incl WAL): {human_size(before_total)} -> {human_size(after_total)}")
    print(f"  Integrity: {'OK' if integrity == ['ok'] else 'FAILED'}")
    
    # Intel db summary if done
    if os.path.exists(INTEL_DB) and intel_size > 20 * 1024 * 1024 and freelist_bytes > 1024 * 1024:
        print(f"intelligence.db: {human_size(intel_before)} -> {human_size(intel_after)}")
        print(f"  Freed: {human_size(freed)}")
    
    print()
    print(f"Backup saved to: {backup_path}")
    print("Done.")

if __name__ == "__main__":
    main()
