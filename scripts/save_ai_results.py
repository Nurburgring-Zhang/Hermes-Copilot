#!/usr/bin/env python3
"""保存真实AI评分结果到数据库"""
import sqlite3, json
from datetime import datetime
from pathlib import Path

db = sqlite3.connect(str(Path.home() / ".hermes/intelligence.db"))
now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

scores = json.loads(open(Path.home() / ".hermes/reports/_ai_scoring_results.json").read())
saved = 0

for s in scores:
    total = s["scarcity"] + s["impact"] + s["tech_depth"] + s["timeliness"] + s["preference"] + s["credibility"]
    total = min(total, 100)
    
    reasoning = json.dumps({
        "scarcity_reason": s["scarcity_reason"],
        "impact_reason": s["impact_reason"],
        "tech_depth_reason": s["tech_depth_reason"],
        "timeliness_reason": s["timeliness_reason"],
        "preference_reason": s["preference_reason"],
        "credibility_reason": s["credibility_reason"],
        "summary": s["summary"],
        "real_ai": True
    }, ensure_ascii=False)
    
    db.execute("""UPDATE cleaned_intelligence SET
        ai_score_scarcity=?, ai_score_impact=?, ai_score_tech_depth=?,
        ai_score_timeliness=?, ai_score_preference=?, ai_score_credibility=?,
        ai_score_total=?, importance_score=?,
        ai_score_reasoning=?, ai_scored_at=?
        WHERE id=?""",
        (s["scarcity"], s["impact"], s["tech_depth"],
         s["timeliness"], s["preference"], s["credibility"],
         total, round(total/10.0, 2),
         reasoning, now, s["id"]))
    saved += 1
    print(f"  #{s['id']} -> {total}分 | {s['summary'][:50]}")

db.commit()
db.close()
print(f"\n已保存 {saved} 条真实AI评分 ✅")
