#!/usr/bin/env python3
"""批量修复cleaned_intelligence的value_level映射——基于ai_score_total"""
import sqlite3, json
from datetime import datetime

DB = "/home/administrator/.hermes/intelligence.db"
LOG = "/home/administrator/.hermes/logs"

def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}")
    with open(f"{LOG}/value_level_backfill_{datetime.now().strftime('%Y%m%d')}.log", "a") as f:
        f.write(f"[{ts}] {msg}\n")

log("=" * 70)
log("🔧 批量修复cleaned_intelligence value_level映射")

conn = sqlite3.connect(DB)
c = conn.cursor()

# 1. 修复前分布
c.execute("SELECT value_level, COUNT(*) FROM cleaned_intelligence GROUP BY value_level ORDER BY value_level")
before = dict(c.fetchall())
log(f"修复前分布: {json.dumps(before)}")

# 2. 基于ai_score_total映射value_level
mapping = [
    (5, "极高价值(>=80分,即时推送)", "ai_score_total >= 80"),
    (4, "高价值(65-79分,推荐推送)", "ai_score_total >= 65 AND ai_score_total < 80"),
    (3, "中价值(50-64分)",          "ai_score_total >= 50 AND ai_score_total < 65"),
    (2, "一般(35-49分)",            "ai_score_total >= 35 AND ai_score_total < 50"),
    (1, "低价值(20-34分)",          "ai_score_total >= 20 AND ai_score_total < 35"),
    (0, "垃圾(<20分)",              "ai_score_total < 20"),
]

total_updated = 0
for level, reason, condition in mapping:
    sql = f"UPDATE cleaned_intelligence SET value_level=?, value_reasons=? WHERE {condition}"
    c.execute(sql, (level, reason))
    affected = c.rowcount
    if affected > 0:
        log(f"  value_level={level}: 更新{affected}条")
        total_updated += affected

conn.commit()

# 3. 修复后分布
c.execute("SELECT value_level, COUNT(*) FROM cleaned_intelligence GROUP BY value_level ORDER BY value_level")
after = dict(c.fetchall())
log(f"修复后分布: {json.dumps(after)}")

# 4. 验证
c.execute("""
    SELECT value_level,
           ROUND(MIN(ai_score_total),1),
           ROUND(MAX(ai_score_total),1),
           ROUND(AVG(ai_score_total),1),
           COUNT(*)
    FROM cleaned_intelligence
    GROUP BY value_level
    ORDER BY value_level
""")
log("\n📊 验证: 各level的score分布")
log(f"  {'Level':<8} {'Min':<8} {'Max':<8} {'Avg':<8} {'Count':<8}")
log(f"  {'-'*40}")
for row in c.fetchall():
    log(f"  {row[0]:<8} {row[1]:<8} {row[2]:<8} {row[3]:<8} {row[4]:<8}")

# 5. 管道可用数据
c.execute("SELECT COUNT(*) FROM cleaned_intelligence WHERE value_level >= 3")
ready = c.fetchone()[0]
c.execute("SELECT COUNT(*) FROM cleaned_intelligence WHERE value_level >= 4")
push = c.fetchone()[0]
c.execute("SELECT COUNT(*) FROM cleaned_intelligence WHERE value_level >= 5")
top = c.fetchone()[0]
log(f"\n📊 管道可用数据:")
log(f"  中价值以上(>=3级): {ready}条")
log(f"  高价值以上(>=4级): {push}条")
log(f"  极高价值(>=5级): {top}条")

conn.close()
log("\n✅ value_level修复完成")

print(f"TOTAL_UPDATED:{total_updated}")
print(f"VALUE_LEVEL_5:{after.get(5,0)}")
print(f"VALUE_LEVEL_4:{after.get(4,0)}")
print(f"VALUE_LEVEL_3:{after.get(3,0)}")
print(f"VALUE_LEVEL_2:{after.get(2,0)}")
print(f"VALUE_LEVEL_1:{after.get(1,0)}")
print(f"VALUE_LEVEL_0:{after.get(0,0)}")
