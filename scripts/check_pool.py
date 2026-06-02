import sqlite3
from datetime import date

conn = sqlite3.connect('/home/administrator/.hermes/intelligence.db')
c = conn.cursor()

today = date.today().isoformat()

# 检查今日中文池(value_level >= 3)
c.execute("SELECT COUNT(*) FROM cleaned_intelligence WHERE DATE(cleaned_at)=? AND value_level>=3 AND language='zh'", (today,))
cn_count = c.fetchone()[0]

# 检查今日英文池(value_level >= 3)
c.execute("SELECT COUNT(*) FROM cleaned_intelligence WHERE DATE(cleaned_at)=? AND value_level>=3 AND language='en'", (today,))
en_count = c.fetchone()[0]

print(f'今日中文池(⭐3+): {cn_count}条')
print(f'今日英文池(⭐3+): {en_count}条')
print(f'是否满足推送条件(21中文+9英文): {"是" if cn_count>=21 and en_count>=9 else "否"}')

# 如果不满足,检查原始数据量
if cn_count < 21 or en_count < 9:
    c.execute("SELECT DATE(cleaned_at), language, COUNT(*) FROM cleaned_intelligence WHERE DATE(cleaned_at)=? GROUP BY DATE(cleaned_at), language", (today,))
    print("\n今日各语言池详细:")
    for row in c.fetchall():
        print(f"  {row[0]} {row[1]}: {row[2]}条")