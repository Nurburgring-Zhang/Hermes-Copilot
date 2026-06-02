#!/usr/bin/env python3
import sqlite3

conn = sqlite3.connect('/home/administrator/.hermes/intelligence.db')
cur = conn.cursor()

# Cleaned 24h
try:
    cur.execute("SELECT COUNT(*) FROM cleaned_intelligence WHERE cleaned_at > datetime('now', '-24 hours')")
    print(f'Cleaned 24h: {cur.fetchone()[0]}')
except:
    cur.execute("SELECT COUNT(*) FROM cleaned_intelligence WHERE collected_at > datetime('now', '-24 hours')")
    print(f'Cleaned 24h (via collected_at): {cur.fetchone()[0]}')

# Language ratio in cleaned 24h
try:
    cur.execute("SELECT language, COUNT(*) FROM cleaned_intelligence WHERE cleaned_at > datetime('now', '-24 hours') GROUP BY language")
    print('Language ratio (cleaned 24h):')
    for row in cur.fetchall():
        print(f'  {row[0]}: {row[1]}')
except Exception as e:
    print(f'Language ratio error: {e}')

# Check push records 24h
cur.execute("SELECT COUNT(*) FROM push_records WHERE created_at > datetime('now', '-24 hours')")
print(f'Push records 24h: {cur.fetchone()[0]}')

# Last push time
cur.execute("SELECT created_at, push_channel, push_status FROM push_records ORDER BY created_at DESC LIMIT 3")
print('Last 3 pushes:')
for row in cur.fetchall():
    print(f'  {row[0]} | {row[1]} | {row[2]}')

# Cron job status - check jobs.json for next run
import json
try:
    with open('/home/administrator/.hermes/cron/jobs.json') as f:
        jobs = json.load(f)['jobs']
    for j in jobs:
        print(f"Job: {j['name']} | state: {j['state']} | last_run: {j.get('last_run_at','N/A')} | next_run: {j.get('next_run_at','N/A')} | last_status: {j.get('last_status','N/A')}")
except Exception as e:
    print(f'Cron check error: {e}')

conn.close()