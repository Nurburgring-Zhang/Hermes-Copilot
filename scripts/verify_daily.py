import sqlite3
from datetime import datetime, timedelta
conn = sqlite3.connect('/home/administrator/.hermes/intelligence.db')
c = conn.cursor()

# Check today's push records again
today = datetime.today().isoformat()
c.execute("SELECT id, title, push_level, push_status, push_response, created_at FROM push_records ORDER BY id DESC LIMIT 10")
print("Recent push records:")
for row in c.fetchall():
    print(f"  id={row[0]}, title={str(row[1])[:50]}, level={row[2]}, status={row[3]}, response={str(row[4])[:100]}, created={row[5]}")

# Check the actual daily report - find latest daily
c.execute("SELECT title, content, push_status FROM push_records WHERE title LIKE '%日报%' OR title LIKE '%智能情报%' ORDER BY id DESC LIMIT 5")
print("\nDaily reports:")
for row in c.fetchall():
    print(f"  title={str(row[0])[:60]}, status={row[2]}")
    print(f"  content_preview={str(row[1])[:200]}")
    print()

conn.close()