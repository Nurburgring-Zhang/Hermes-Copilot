#!/usr/bin/env python3
"""
手动AI评分升级 — 第二批：第21-40条（共57条）
"""
import sqlite3
import json
import sys
import os

DB_PATH = "/home/administrator/.hermes/intelligence.db"
OUTPUT = "/home/administrator/.hermes/reports/_batch2_ai_score_input.json"

conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row

cur = conn.execute("""
    SELECT id, title, content, source, url,
           ai_score_total as current_score,
           ai_score_reasoning as current_reasoning,
           importance_score
    FROM cleaned_intelligence
    WHERE 
      (ai_score_reasoning LIKE '%规则%')
      OR 
      (ai_score_reasoning NOT LIKE '%评分%'
       AND ai_score_reasoning NOT LIKE '%summary%'
       AND LENGTH(COALESCE(content,'')) > 100
       AND importance_score > 3)
    ORDER BY importance_score DESC
""")

rows = cur.fetchall()
conn.close()

batch = rows[20:40]
items = []
for r in batch:
    items.append({
        'id': r['id'],
        'title': r['title'],
        'content': (r['content'] or '')[:500],
        'source': r['source'],
        'current_score': r['current_score'],
        'importance': r['importance_score']
    })

with open(OUTPUT, 'w', encoding='utf-8') as f:
    json.dump(items, f, ensure_ascii=False, indent=2)

print(f"第二批 {len(items)} 条已写入 {OUTPUT}")
for i in items:
    print(f"  ID={i['id']} | score={i['current_score']:>5.0f} | imp={i['importance']:>6.1f} | {i['title'][:50]}")
