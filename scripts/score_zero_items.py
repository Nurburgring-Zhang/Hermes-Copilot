#!/usr/bin/env python3
"""Score 7 zero-score items manually"""
import sqlite3, json
from datetime import datetime

DB_PATH = "/home/administrator/.hermes/intelligence.db"
now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

scores = {
    805096: {"scarcity": 2, "impact": 2, "tech_depth": 0, "timeliness": 5, "preference": 1, "credibility": 3,
             "reason": '{"scarcity_reason":"社媒常规内容(2分)","impact_reason":"社会热点但影响力有限(2分)","tech_depth_reason":"无技术内容(0分)","timeliness_reason":"无明确日期(5分)","preference_reason":"非科技领域(1分)","credibility_reason":"抖音(3分)","summary":"社会纪录片，低价值内容"}'},
    805104: {"scarcity": 14, "impact": 14, "tech_depth": 6, "timeliness": 10, "preference": 7, "credibility": 8,
             "reason": '{"scarcity_reason":"行业报告/召回信息(14分)","impact_reason":"汽车安全召回影响品牌(14分)","tech_depth_reason":"少量技术术语(6分)","timeliness_reason":"今天(10分)","preference_reason":"科技/汽车领域(7分)","credibility_reason":"ithome(8分)","summary":"奔驰汽车召回信息"}'},
    805105: {"scarcity": 14, "impact": 14, "tech_depth": 6, "timeliness": 10, "preference": 7, "credibility": 8,
             "reason": '{"scarcity_reason":"行业报告/召回信息(14分)","impact_reason":"汽车安全召回影响品牌(14分)","tech_depth_reason":"少量技术术语(6分)","timeliness_reason":"今天(10分)","preference_reason":"科技/汽车领域(7分)","credibility_reason":"ithome(8分)","summary":"现代汽车召回信息"}'},
    805106: {"scarcity": 18, "impact": 22, "tech_depth": 10, "timeliness": 9, "preference": 9, "credibility": 8,
             "reason": '{"scarcity_reason":"首次/首款(18分)","impact_reason":"芯片行业战略合作(22分)","tech_depth_reason":"含技术术语(10分)","timeliness_reason":"当天(9分)","preference_reason":"AI/芯片核心领域(9分)","credibility_reason":"techmeme(8分)","summary":"联发科采用英特尔先进封装，芯片行业重大合作"}'},
    805107: {"scarcity": 2, "impact": 2, "tech_depth": 0, "timeliness": 5, "preference": 1, "credibility": 3,
             "reason": '{"scarcity_reason":"常规游戏运营(2分)","impact_reason":"游戏常规更新(2分)","tech_depth_reason":"无技术内容(0分)","timeliness_reason":"无明确日期(5分)","preference_reason":"非科技领域(1分)","credibility_reason":"抖音(3分)","summary":"游戏赛季更新信息"}'},
    805108: {"scarcity": 18, "impact": 14, "tech_depth": 15, "timeliness": 10, "preference": 9, "credibility": 8,
             "reason": '{"scarcity_reason":"首款/首次(18分)","impact_reason":"AI芯片新品发布(14分)","tech_depth_reason":"架构+性能参数(15分)","timeliness_reason":"今天(10分)","preference_reason":"AI/芯片核心领域(9分)","credibility_reason":"ithome(8分)","summary":"谷歌Coral Board单板计算机发布，1TOPS本地运行Gemma3"}'},
    805109: {"scarcity": 14, "impact": 20, "tech_depth": 4, "timeliness": 9, "preference": 8, "credibility": 7,
             "reason": '{"scarcity_reason":"官方表态(14分)","impact_reason":"国际军事政治(20分)","tech_depth_reason":"无技术细节(4分)","timeliness_reason":"当日(9分)","preference_reason":"科技/军事领域(8分)","credibility_reason":"toutiao(7分)","summary":"美日军演距台110公里，国防部回应"}'},
}

conn = sqlite3.connect(DB_PATH)
c = conn.cursor()
for item_id, s in scores.items():
    total = min(100, s['scarcity'] + s['impact'] + s['tech_depth'] + s['timeliness'] + s['preference'] + s['credibility'])
    c.execute("""UPDATE cleaned_intelligence SET
        ai_score_scarcity=?, ai_score_impact=?, ai_score_tech_depth=?,
        ai_score_timeliness=?, ai_score_preference=?, ai_score_credibility=?,
        ai_score_total=?, importance_score=?, ai_score_reasoning=?, ai_scored_at=?
        WHERE id=?""",
        (s['scarcity'], s['impact'], s['tech_depth'], s['timeliness'], s['preference'], s['credibility'],
         total, round(total/10.0, 1), s['reason'], now, item_id))
    print(f"  ID={item_id:>7} -> {total:2d}分")

conn.commit()
conn.close()
print("Done: 7 zero-score items scored")
