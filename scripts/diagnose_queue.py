#!/usr/bin/env python3
"""诊断清洗积压问题"""
import sqlite3
from datetime import datetime, timedelta

conn = sqlite3.connect('/home/administrator/.hermes/intelligence.db')
today = datetime.now().strftime('%Y-%m-%d')
yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')

print('='*70)
print(f'清洗积压诊断 @ {datetime.now().strftime("%Y-%m-%d %H:%M")}')
print('='*70)

# 1. 积压总量
pending = conn.execute("""
    SELECT COUNT(*) FROM raw_intelligence r 
    WHERE r.id NOT IN (SELECT COALESCE(raw_id,0) FROM cleaned_intelligence WHERE raw_id IS NOT NULL)
""").fetchone()[0]
total_raw = conn.execute("SELECT COUNT(*) FROM raw_intelligence").fetchone()[0]
total_cleaned = conn.execute("SELECT COUNT(*) FROM cleaned_intelligence").fetchone()[0]
print(f'\n总raw: {total_raw}条')
print(f'总cleaned: {total_cleaned}条')
print(f'积压未清洗: {pending}条')

# 2. 今日raw - 每日分布
print(f'\n今日raw分布:')
raw_today = conn.execute("SELECT platform, COUNT(*) as c FROM raw_intelligence WHERE DATE(collected_at) = ? GROUP BY platform ORDER BY c DESC LIMIT 15", (today,)).fetchall()
total_today = 0
for p, c in raw_today:
    print(f'  {p}: {c}条')
    total_today += c
print(f'  今日raw总计: {total_today}条')

# 3. 已清洗的今日数据
cleaned_today = conn.execute("SELECT COUNT(*) FROM cleaned_intelligence WHERE DATE(cleaned_at) = ?", (today,)).fetchone()[0]
print(f'\n今日已清洗(cleaned_at=today): {cleaned_today}条')

# 4. 积压数据按平台分布
print(f'\n积压数据按平台分布:')
pending_by_plat = conn.execute("""
    SELECT r.platform, COUNT(*) as c
    FROM raw_intelligence r
    WHERE r.id NOT IN (SELECT COALESCE(raw_id,0) FROM cleaned_intelligence WHERE raw_id IS NOT NULL)
    GROUP BY r.platform
    ORDER BY c DESC
    LIMIT 20
""").fetchall()
for p, c in pending_by_plat:
    print(f'  {p}: {c}条')

# 5. 积压数据按日期分布
print(f'\n积压数据按采集日期分布:')
pending_by_date = conn.execute("""
    SELECT DATE(collected_at) as d, COUNT(*) as c
    FROM raw_intelligence r
    WHERE r.id NOT IN (SELECT COALESCE(raw_id,0) FROM cleaned_intelligence WHERE raw_id IS NOT NULL)
    GROUP BY d
    ORDER BY d DESC
    LIMIT 15
""").fetchall()
for d, c in pending_by_date:
    print(f'  {d}: {c}条')

# 6. 最新cleaned时间
latest_cleaned = conn.execute("SELECT MAX(cleaned_at) FROM cleaned_intelligence").fetchone()[0]
print(f'\n最新cleaned时间: {latest_cleaned}')

conn.close()
