#!/usr/bin/env python3
"""
手动AI评分升级 — 第三批：第41-57条（共57条，最后17条）
"""
import sqlite3
import json

DB_PATH = "/home/administrator/.hermes/intelligence.db"
OUTPUT = "/home/administrator/.hermes/reports/_batch3_ai_score_input.json"

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

batch = rows[40:]
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

# 也检查一下：已经评分过的可以识别出来
# 看看还剩几条真正没AI升级过的
conn2 = sqlite3.connect(DB_PATH)
cur2 = conn2.execute("""
    SELECT COUNT(*) FROM cleaned_intelligence
    WHERE 
      (ai_score_reasoning LIKE '%规则%')
      OR 
      (ai_score_reasoning NOT LIKE '%评分%'
       AND ai_score_reasoning NOT LIKE '%summary%'
       AND LENGTH(COALESCE(content,'')) > 100
       AND importance_score > 3)
""")
remain = cur2.fetchone()[0]
conn2.close()

print(f"DB中仍有 {remain} 条待AI评分（按原始查询条件）")
print(f"本批取前{len(items)}条（从第41条到第{len(rows)}条）")

with open(OUTPUT, 'w', encoding='utf-8') as f:
    json.dump(items, f, ensure_ascii=False, indent=2)

print(f"共 {len(items)} 条写入 {OUTPUT}")
for i in items:
    print(f"  ID={i['id']} | score={i['current_score']:>5.0f} | imp={i['importance']:>6.1f} | {i['title'][:50]}")
