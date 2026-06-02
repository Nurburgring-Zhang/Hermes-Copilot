#!/usr/bin/env python3
"""Quick DB stats for intelligence pipeline"""
import sqlite3, os, sys

db = os.path.expanduser("~/.hermes/intelligence.db")
conn = sqlite3.connect(db, timeout=30)
conn.execute("PRAGMA cache_size=-8000")
conn.execute("PRAGMA synchronous=OFF")
cur = conn.cursor()

cur.execute("SELECT COUNT(*) FROM raw_intelligence")
tr = cur.fetchone()[0]

cur.execute("SELECT COUNT(*) FROM cleaned_intelligence")
tc = cur.fetchone()[0]

cur.execute("SELECT COUNT(*) FROM raw_intelligence r WHERE NOT EXISTS (SELECT 1 FROM cleaned_intelligence c WHERE c.raw_id = r.id)")
pending = cur.fetchone()[0]

# Latest collection time
cur.execute("SELECT MAX(collected_at) FROM raw_intelligence")
latest_collect = cur.fetchone()[0]

conn.close()
print(f"RAW={tr} CLEANED={tc} PENDING={pending} LATEST_COLLECT={latest_collect}")
