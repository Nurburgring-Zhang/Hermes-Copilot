import sqlite3
from datetime import datetime, timedelta

conn = sqlite3.connect('/home/administrator/.hermes/intelligence.db')
c = conn.cursor()

# Get ALL URLs in cleaned_intelligence from terminal sources (bilibili, github)
window_start = (datetime.now() - timedelta(hours=72)).isoformat()
c.execute("""
    SELECT url, title, platform, cleaned_at FROM cleaned_intelligence 
    WHERE platform IN ('bilibili', 'github') 
    AND cleaned_at >= ?
    ORDER BY cleaned_at DESC
    LIMIT 20
""", (window_start,))
print("Recent bilibili/github in cleaned_intelligence (72h):")
for row in c.fetchall():
    print(f"  {row[2]}: {str(row[1])[:50]} | {row[0][:60]} | {row[3]}")

# Check if bilibili is working at all - look at latest bilibili raw
c.execute("SELECT id, title, url, collected_at FROM raw_intelligence WHERE platform='bilibili' ORDER BY collected_at DESC LIMIT 5")
print("\nLatest bilibili raw:")
for row in c.fetchall():
    print(f"  id={row[0]}, title={str(row[1])[:40]}, url={row[2][:60]}, collected={row[3]}")

# Check if github is working - look at latest github raw
c.execute("SELECT id, title, url, collected_at FROM raw_intelligence WHERE platform='github' ORDER BY collected_at DESC LIMIT 5")
print("\nLatest github raw:")
for row in c.fetchall():
    print(f"  id={row[0]}, title={str(row[1])[:50]}, url={row[2][:60]}, collected={row[3]}")

conn.close()