import sqlite3
from datetime import datetime, timedelta

conn = sqlite3.connect('/home/administrator/.hermes/intelligence.db')
c = conn.cursor()

# Get recent raw items for bilibili and github (the terminal sources)
window_start = (datetime.now() - timedelta(hours=48)).isoformat()

# Check raw_intelligence 
c.execute("SELECT COUNT(*) FROM raw_intelligence WHERE collected_at >= ?", (window_start,))
print("raw_intelligence in 48h:", c.fetchone()[0])

# Check what platforms we have
c.execute("SELECT platform, COUNT(*) FROM raw_intelligence WHERE collected_at >= ? GROUP BY platform", (window_start,))
print("raw by platform:", c.fetchall())

# Check bilibili data specifically 
c.execute("SELECT id, title, url, platform, collected_at FROM raw_intelligence WHERE platform='bilibili' AND collected_at >= ? ORDER BY collected_at DESC LIMIT 3", (window_start,))
print("\nBilibili recent:")
for row in c.fetchall():
    print(f"  id={row[0]}, title={str(row[1])[:50]}, url={row[2][:60]}, platform={row[3]}, collected={row[4]}")

# Check github data
c.execute("SELECT id, title, url, platform, collected_at FROM raw_intelligence WHERE platform='github' AND collected_at >= ? ORDER BY collected_at DESC LIMIT 3", (window_start,))
print("\nGitHub recent:")
for row in c.fetchall():
    print(f"  id={row[0]}, title={str(row[1])[:50]}, url={row[2][:60]}, platform={row[3]}, collected={row[4]}")

conn.close()