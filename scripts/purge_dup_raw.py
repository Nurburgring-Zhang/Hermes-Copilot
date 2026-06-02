#!/usr/bin/env python3
"""清理raw_intelligence中标题已存在于cleaned_intelligence的重复项"""
import sqlite3
from pathlib import Path

HERMES = Path("/home/administrator/.hermes")
db = sqlite3.connect(str(HERMES / "intelligence.db"))
c = db.cursor()
c.execute("DELETE FROM raw_intelligence WHERE id NOT IN (SELECT COALESCE(raw_id,0) FROM cleaned_intelligence) AND TRIM(COALESCE(title,'')) IN (SELECT title FROM cleaned_intelligence)")
n = c.rowcount
db.commit()
print(f"Purged {n} duplicate raw items")
db.close()
