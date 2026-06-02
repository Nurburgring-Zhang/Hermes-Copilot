#!/usr/bin/env python3
import sqlite3
from datetime import datetime

conn = sqlite3.connect('/home/administrator/.hermes/intelligence.db')
cur = conn.cursor()

# Get table schema
cur.execute("PRAGMA table_info(cleaned_intelligence)")
print("cleaned_intelligence columns:", [r[1] for r in cur.fetchall()])

cur.execute("PRAGMA table_info(push_records)")
print("push_records columns:", [r[1] for r in cur.fetchall()])

# 24h raw count
cur.execute("SELECT COUNT(*) FROM raw_intelligence WHERE collected_at > datetime('now', '-24 hours')")
raw_total = cur.fetchone()[0]
print(f'\nRaw 24h: {raw_total}')

# Platform breakdown
cur.execute("SELECT platform, COUNT(*) as cnt FROM raw_intelligence WHERE collected_at > datetime('now', '-24 hours') GROUP BY platform ORDER BY cnt DESC LIMIT 15")
print('Platforms:')
for row in cur.fetchall():
    print(f'  {row[0]}: {row[1]}')

# Check if cleaned_intelligence has a date column we can use
try:
    cur.execute("SELECT COUNT(*) FROM cleaned_intelligence")
    cleaned_total = cur.fetchone()[0]
    print(f'Cleaned total: {cleaned_total}')
except Exception as e:
    print(f'Cleaned check error: {e}')

# Push records
try:
    cur.execute("SELECT push_channel, push_status, COUNT(*) FROM push_records WHERE 1=1 GROUP BY push_channel, push_status")
    print('Push status (all):')
    for row in cur.fetchall():
        print(f'  {row[0]} [{row[1]}]: {row[2]}')
except Exception as e:
    print(f'Push check error: {e}')

# Check recent push
try:
    cur.execute("SELECT id, push_channel, push_status, created_at FROM push_records ORDER BY created_at DESC LIMIT 5")
    print('Recent pushes:')
    for row in cur.fetchall():
        print(f'  {row[1]} [{row[2]}] at {row[3]}')
except Exception as e:
    print(f'Recent push error: {e}')

conn.close()