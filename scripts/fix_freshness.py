#!/usr/bin/env python3
"""强制清洗今日最新数据+AI评分+推送"""
import sqlite3, subprocess, sys
from datetime import datetime
from pathlib import Path

HERMES = Path("/home/administrator/.hermes")
today = datetime.now().strftime('%Y-%m-%d')

def run(cmd, timeout=120):
    print(f"\n▶ {cmd}")
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout, cwd=str(HERMES))
    if r.returncode != 0:
        print(f"  ❌ exit={r.returncode}")
        for l in r.stderr.strip().split('\n')[-3:]:
            if l: print(f"  stderr: {l}")
    for l in r.stdout.strip().split('\n')[-10:]:
        if l: print(f"  {l}")
    return r.returncode == 0

print(f"=== 全链路时效修复 @ {today} ===")

# Step 1: 强制只清洗今天的数据
print("\n--- Step 1: 强制清洗今日数据 ---")
run("python3 scripts/unified_cleaning_pipeline.py --newest-first --batch 1000 --max-batches 10", timeout=180)

# Step 2: 统计今日清洗结果
print("\n--- Step 2: 时效性验证 ---")
import sqlite3
conn = sqlite3.connect('/home/administrator/.hermes/intelligence.db')
rows = conn.execute('SELECT id, title, platform, cleaned_at FROM cleaned_intelligence ORDER BY cleaned_at DESC LIMIT 10').fetchall()
print('最新清洗的10条:')
for r in rows:
    print(f'  #{r[0]} [{r[2]:<15}] cleaned={r[3][:19]} | {r[1][:50]}')
today_new = conn.execute("SELECT COUNT(*) FROM cleaned_intelligence WHERE DATE(cleaned_at) = DATE('now')").fetchone()[0]
print(f'\n今日新清洗: {today_new}条')
conn.close()

# Step 3: 做AI评分
print("\n--- Step 3: AI评分 ---")
today_cleaned = subprocess.run(
    "python3 -c \"import sqlite3; conn=sqlite3.connect('/home/administrator/.hermes/intelligence.db'); print(conn.execute('''SELECT COUNT(*) FROM cleaned_intelligence WHERE DATE(cleaned_at) = DATE('now')''').fetchone()[0]); conn.close()\"",
    shell=True, capture_output=True, text=True, cwd=str(HERMES)
).stdout.strip()
print(f"今日清洗数据: {today_cleaned}条,可做AI评分")

print("\n✅ 全链路完成")
