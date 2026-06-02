import sqlite3
conn = sqlite3.connect('intelligence.db')
c = conn.cursor()
c.execute("SELECT name FROM sqlite_master WHERE type='table'")
print("Tables:", c.fetchall())
# Check raw_intelligence
try:
    c.execute("SELECT COUNT(*) FROM raw_intelligence")
    print("raw_intelligence count:", c.fetchone()[0])
except:
    print("raw_intelligence: does not exist")
conn.close()