import sqlite3, os
db_path = os.path.expanduser("~/.hermes/intelligence.db")
print("DB path:", db_path)
print("DB exists:", os.path.exists(db_path))
conn = sqlite3.connect(db_path)
c = conn.cursor()
c.execute("SELECT name FROM sqlite_master WHERE type='table'")
print("Tables:", c.fetchall())
try:
    c.execute("SELECT COUNT(*) FROM cleaned_intelligence")
    print("cleaned_intelligence count:", c.fetchone()[0])
except Exception as e:
    print("cleaned_intelligence error:", e)
try:
    c.execute("SELECT COUNT(*) FROM raw_intelligence")
    print("raw_intelligence count:", c.fetchone()[0])
except Exception as e:
    print("raw_intelligence error:", e)
conn.close()