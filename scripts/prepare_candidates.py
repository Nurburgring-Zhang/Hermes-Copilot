#!/usr/bin/env python3
"""生成推送候选集(每平台前10条保底)"""
import sqlite3, json
from datetime import datetime
from collections import defaultdict

conn = sqlite3.connect('/home/administrator/.hermes/intelligence.db')
today = datetime.now().strftime('%Y-%m-%d')

# 已推送的记录
pushed_ids = set()
try:
    rows = conn.execute("""
        SELECT DISTINCT cleaned_id FROM push_records 
        WHERE push_status = 'success'
          AND datetime(push_time) >= datetime('now', '-48 hours')
          AND cleaned_id IS NOT NULL
    """).fetchall()
    pushed_ids = {r[0] for r in rows}
except:
    pass

# 获取所有平台
platforms = conn.execute("""
    SELECT DISTINCT platform FROM cleaned_intelligence 
    WHERE DATE(cleaned_at) = ? OR DATE(collected_at) = ?
    ORDER BY platform
""", (today, today)).fetchall()

skip_platforms = {'bilibili','bilibili_全站','douyin','kuaishou'}

candidates = []
for (plat,) in platforms:
    if any(s in plat for s in skip_platforms):
        continue
    
    rows = conn.execute("""
        SELECT id, title, COALESCE(content, '') as content,
               platform, source, importance_score,
               ai_score_total, published_at
        FROM cleaned_intelligence
        WHERE (DATE(cleaned_at) = ? OR DATE(collected_at) = ?)
          AND platform = ?
          AND LENGTH(COALESCE(content, '')) > 10
          AND title IS NOT NULL AND title != ''
        ORDER BY importance_score DESC
        LIMIT 10
    """, (today, today, plat)).fetchall()
    
    for r in rows:
        if r[0] not in pushed_ids:
            candidates.append({
                'id': r[0],
                'title': r[1],
                'content': (r[2] or '')[:400],
                'platform': r[3],
                'source': r[4],
                'importance_score': r[5],
                'ai_score_total': r[6] or 0,
                'published_at': r[7],
            })

print(f"候选集: {len(candidates)}条 (来自{len(platforms)}个平台)")
print(f"已有AI评分: {sum(1 for c in candidates if c['ai_score_total'] > 0)}条")

plat_count = defaultdict(int)
for c in candidates:
    plat_count[c['platform']] += 1
print("平台分布:")
for p, cnt in sorted(plat_count.items(), key=lambda x: -x[1])[:20]:
    print(f"  {p}: {cnt}条")

with open('scripts/push_candidates.json', 'w', encoding='utf-8') as f:
    json.dump(candidates, f, ensure_ascii=False, indent=2, default=str)

print(f"\n已保存到 push_candidates.json")
conn.close()
