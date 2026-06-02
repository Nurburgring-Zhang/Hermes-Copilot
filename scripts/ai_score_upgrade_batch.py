#!/usr/bin/env python3
"""
真正AI评分升级批处理 — 将规则评分的条目升级为真正的AI六维评分
每次处理200条，分批调用DeepSeek API (每批2条)
"""
import sqlite3, json, os, sys, time
from datetime import datetime
from pathlib import Path

HERMES = Path("/home/administrator/.hermes")
DB_PATH = HERMES / "intelligence.db"

def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)

# Load .env
env_path = HERMES / ".env"
if env_path.exists():
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip()
            if v and v != "***" and (k not in os.environ or not os.environ[k]):
                os.environ[k] = v

sys.path.insert(0, str(HERMES / "scripts"))
from hermes_ai_scoring import (
    load_keyword_weights, score_items_via_openrouter
)

kw_weights = load_keyword_weights()
log(f"keyword_weights: {len(kw_weights)}条")

def get_rule_scored_items(limit=200):
    """获取有内容但规则评分的条目"""
    conn = sqlite3.connect(str(DB_PATH))
    rows = conn.execute("""
        SELECT id, title, COALESCE(content,'') as content,
               platform, source, author, tags, category,
               COALESCE(published_at,'') as published_at,
               ai_score_total, url
        FROM cleaned_intelligence
        WHERE (ai_score_reasoning LIKE '%keyword%' 
               OR ai_score_reasoning LIKE '%规则%' 
               OR ai_score_reasoning LIKE '%规则引擎评分%'
               OR ai_score_reasoning LIKE '%规则评分%')
        AND LENGTH(COALESCE(content,'')) > 100
        ORDER BY ai_score_total DESC, published_at DESC
        LIMIT ?
    """, (limit,)).fetchall()
    conn.close()
    cols = ['id','title','content','platform','source','author','tags','category','published_at','ai_score_total','url']
    return [dict(zip(cols, r)) for r in rows]

items = get_rule_scored_items(200)
log(f"待升级为真正AI评分: {len(items)}条")

if not items:
    log("✅ 没有需要升级的规则评分条目")
    sys.exit(0)

for item in items:
    clen = len(item.get("content", "") or "")
    log(f"  #{item['id']:>7} [{item.get('source','?'):<12}] {str(item.get('title',''))[:50]} | {clen}chars")

saved = score_items_via_openrouter(items, kw_weights, model="deepseek-chat", batch_size=2)
log(f"✅ 真正AI评分升级完成: {saved}条")
