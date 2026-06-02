#!/usr/bin/env python3
"""从 intelligence.db 导出高价值数据为 hot_topics_daily 格式"""
import sqlite3, json, sys
from datetime import datetime
from pathlib import Path

HERMES = Path("/home/administrator/.hermes")
WS = HERMES / "workspace" / "workspace"
DB_PATH = HERMES / "intelligence.db"
OUT = WS / "hot_topics_daily"

db = sqlite3.connect(str(DB_PATH))
c = db.execute("""
SELECT c.title, c.content, c.url, c.platform, c.importance_score, c.value_level, 
       c.personal_match_score, c.is_ai_related, c.language, c.collected_at,
       c.category, c.source, c.cleaned_at
FROM cleaned_intelligence c
WHERE c.cleaned_at >= datetime('now', '-48 hours')
  AND c.importance_score >= 1.0
ORDER BY c.importance_score DESC, c.personal_match_score DESC
LIMIT 500
""")

items = []
for row in c.fetchall():
    items.append({
        'title': row[0],
        'content': (row[1] or '')[:500],
        'url': row[2],
        'platform': row[3],
        'source': row[11] or row[3],
        'score': row[4],
        'value_level': row[5],
        'personal_match': row[6],
        'category': row[10] or 'General',
        'language': row[8],
        'published': row[9],
        'collect_time': row[12]
    })
db.close()

OUT.mkdir(parents=True, exist_ok=True)
ts = datetime.now().strftime('%Y%m%d_%H%M')

multichannel = {
    'timestamp': datetime.now().isoformat(),
    'source': 'hermes_intelligence_db',
    'total': len(items),
    'items': items
}

(OUT / f'multichannel_{ts}.json').write_text(
    json.dumps(multichannel, ensure_ascii=False, indent=2), encoding='utf-8')
(OUT / 'multichannel_latest.json').write_text(
    json.dumps(multichannel, ensure_ascii=False, indent=2), encoding='utf-8')
(OUT / 'merged_latest.json').write_text(
    json.dumps(multichannel, ensure_ascii=False, indent=2), encoding='utf-8')

# Agent Export 格式
geo_items = [{
    'title': i['title'],
    'source': i['source'],
    'pub': i['platform'],
    'category': i['category'],
    'score': i['score'],
    'language': i['language'],
    'url': i['url']
} for i in items]
(OUT / 'latest_geo.json').write_text(
    json.dumps(geo_items, ensure_ascii=False, indent=2), encoding='utf-8')

print(f'OK: {len(items)} items -> {OUT}')
print(f'  multichannel_{ts}.json')
print(f'  multichannel_latest.json')
print(f'  merged_latest.json')
print(f'  latest_geo.json')
