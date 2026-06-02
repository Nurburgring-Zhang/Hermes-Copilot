#!/usr/bin/env python3
"""检查数据时效性"""
import sqlite3
from datetime import datetime

conn = sqlite3.connect('/home/administrator/.hermes/intelligence.db')
now = datetime.now()
today = now.strftime('%Y-%m-%d')
cutoff24h = now.strftime('%Y-%m-%d %H:%M:%S')

print('='*70)
print(f'数据时效性检查 @ {now.strftime("%Y-%m-%d %H:%M")}')
print('='*70)

# 1. 今日采集按小时分布
rows = conn.execute("""
    SELECT strftime('%H', collected_at) as h, COUNT(*) as c
    FROM raw_intelligence
    WHERE DATE(collected_at) = ?
    GROUP BY h
    ORDER BY h
""", (today,)).fetchall()
print('\n今日采集入库时间分布:')
total_raw = 0
for h, c in rows:
    print(f'  {h}:00-{int(h)+1}:00 → {c}条')
    total_raw += c
print(f'  今日raw总计: {total_raw}条')

# 2. 最新10条cleaned的发布时间
print('\n最新10条清洗数据:')
rows2 = conn.execute("""
    SELECT id, title, platform, published_at, collected_at
    FROM cleaned_intelligence
    ORDER BY cleaned_at DESC
    LIMIT 10
""").fetchall()
for r in rows2:
    pub = (r[3] or '无发布时间')[:19]
    col = (r[4] or '无')[:19]
    print(f'  #{r[0]} [{r[2]:<15}] 发布={pub} 采集={col} | {r[1][:45]}')

# 3. 各平台最新数据距现在多久
print('\n各平台最新数据时效:')
platforms = conn.execute("SELECT DISTINCT platform FROM raw_intelligence ORDER BY platform").fetchall()
for (p,) in platforms:
    r = conn.execute("""
        SELECT published_at, collected_at
        FROM raw_intelligence
        WHERE platform = ? AND published_at IS NOT NULL AND published_at != ''
        ORDER BY collected_at DESC
        LIMIT 1
    """, (p,)).fetchone()
    if r:
        pub_raw = r[0][:19] if r[0] else '无'
        col_raw = r[1][:19] if r[1] else '无'
        print(f'  {p:<20} 发布={pub_raw} 采集={col_raw}')

# 4. 以B站/抖音为代表的噪音占比
print('\n噪音平台占比:')
noise = conn.execute("""
    SELECT COUNT(*) FROM raw_intelligence
    WHERE DATE(collected_at) = ?
      AND (platform LIKE '%bilibili%' OR platform = 'douyin' OR platform = 'kuaishou')
""", (today,)).fetchone()[0]
tech = conn.execute("""
    SELECT COUNT(*) FROM raw_intelligence
    WHERE DATE(collected_at) = ?
      AND platform NOT LIKE '%bilibili%' AND platform != 'douyin' AND platform != 'kuaishou'
""", (today,)).fetchone()[0]
print(f'  噪音(B站/抖音/快手): {noise}条 ({noise/(noise+tech)*100:.0f}%)')
print(f'  技术平台: {tech}条 ({tech/(noise+tech)*100:.0f}%)')

conn.close()
print('\n检查完毕')
