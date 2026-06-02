#!/usr/bin/env python3
"""Generate final report for AI scoring task."""
import sqlite3
import json
from datetime import datetime

conn = sqlite3.connect("/home/administrator/.hermes/intelligence.db")
c = conn.cursor()

c.execute("""
SELECT 
  COUNT(*) as total,
  AVG(ai_score_total) as avg_total,
  MIN(ai_score_total) as min_total,
  MAX(ai_score_total) as max_total,
  AVG(ai_score_scarcity) as avg_scarcity,
  AVG(ai_score_impact) as avg_impact,
  AVG(ai_score_tech_depth) as avg_tech,
  AVG(ai_score_timeliness) as avg_time,
  AVG(ai_score_preference) as avg_pref,
  AVG(ai_score_credibility) as avg_cred,
  AVG(importance_score) as avg_imp
FROM cleaned_intelligence 
WHERE ai_score_reasoning LIKE '%内容感知AI评分%'
""")
r = c.fetchone()

c.execute("""SELECT ai_score_total FROM cleaned_intelligence 
WHERE ai_score_reasoning LIKE '%内容感知AI评分%'""")
totals = [x[0] for x in c.fetchall()]

buckets = {"0-19":0, "20-39":0, "40-59":0, "60-79":0, "80-100":0}
for s in totals:
    if s < 20: buckets["0-19"] += 1
    elif s < 40: buckets["20-39"] += 1
    elif s < 60: buckets["40-59"] += 1
    elif s < 80: buckets["60-79"] += 1
    else: buckets["80-100"] += 1

report = f"""============================================================
AI Six-Dimension Scoring Report
============================================================
Timestamp: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

1. EXECUTION SUMMARY
   Processed: {r[0]} entries (top 200 by old importance_score)
   Method: Content-aware AI scoring (pattern-based semantic analysis)
   Database: ~/.hermes/intelligence.db → cleaned_intelligence table

2. OVERALL STATISTICS
   Average Total Score:  {r[1]:.2f} / 100
   Min Score:            {r[2]:.1f}
   Max Score:            {r[3]:.1f}
   Average Importance:   {r[10]:.2f} / 10

3. DIMENSION AVERAGES
   Scarcity (0-30):      {r[4]:.2f}
   Impact (0-30):        {r[5]:.2f}
   Tech Depth (0-20):    {r[6]:.2f}
   Timeliness (0-10):    {r[7]:.2f}
   Preference (0-10):    {r[8]:.2f}
   Credibility (0-10):   {r[9]:.2f}

4. SCORE DISTRIBUTION
   0-19:   {buckets['0-19']:3d}  {"█" * (buckets['0-19'] * 40 // max(buckets.values()) if max(buckets.values()) > 0 else 1)}
   20-39:  {buckets['20-39']:3d}  {"█" * (buckets['20-39'] * 40 // max(buckets.values()) if max(buckets.values()) > 0 else 1)}
   40-59:  {buckets['40-59']:3d}  {"█" * (buckets['40-59'] * 40 // max(buckets.values()) if max(buckets.values()) > 0 else 1)}
   60-79:  {buckets['60-79']:3d}  {"█" * (buckets['60-79'] * 40 // max(buckets.values()) if max(buckets.values()) > 0 else 1)}
   80-100: {buckets['80-100']:3d}  {"█" * (buckets['80-100'] * 40 // max(buckets.values()) if max(buckets.values()) > 0 else 1)}

5. UPDATED FIELDS PER ENTRY
   - ai_score_scarcity, ai_score_impact, ai_score_tech_depth
   - ai_score_timeliness, ai_score_preference, ai_score_credibility
   - ai_score_total (sum of 6 dims, capped at 100)
   - importance_score (total / 10)
   - ai_score_reasoning (JSON with per-dimension explanations)
   - ai_scored_at (current timestamp)

6. DATABASE
   Database: ~/.hermes/intelligence.db
   Table: cleaned_intelligence
   Entries still needing AI scoring (content>100): 12905
"""

print(report)

# Save report to file
with open("/home/administrator/.hermes/reports/ai_sixdim_score_report.txt", "w") as f:
    f.write(report)

print("Report saved to: reports/ai_sixdim_score_report.txt")

conn.close()
