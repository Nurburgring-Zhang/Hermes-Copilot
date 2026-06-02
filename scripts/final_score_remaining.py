#!/usr/bin/env python3
"""处理最后3条积压：1条未评分 + 2条规则评分"""
import sqlite3
import json
from datetime import datetime

DB_PATH = "/home/administrator/.hermes/intelligence.db"
conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row

# 1. ID=804102 ClaudeOpus4.8发布 - 内容太短但重要度高
# 内容: "Label:新 Score:139030" — 这是微博源，实际内容不完整
# 直接给它一个基础评分

now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

# 处理完全未评分 804102
cur = conn.execute('SELECT * FROM cleaned_intelligence WHERE id = 804102')
row = cur.fetchone()
if row:
    # 微博推文，内容短但重要性高（1390分）
    scarcity = 5    # 常规新闻，非独家
    impact = 28     # ClaudeOpus 4.8发布，AI行业重大事件
    tech_depth = 8  # 标题级信息，无技术细节
    timeliness = 9  # 几乎当天
    preference = 10  # AI模型发布，高度匹配
    credibility = 3  # 微博来源，可信度低
    
    total = min(100.0, scarcity + impact + tech_depth + timeliness + preference + credibility)
    importance = round(total / 10.0, 1)
    
    reasoning = json.dumps({
        "scarcity_reason": "常规社媒发布(5分)，虽为ClaudeOpus新版本但仅微博发布",
        "impact_reason": "高影响力(28分)，ClaudeOpus 4.8发布影响AI编码领域",
        "tech_depth_reason": "标题级信息(8分)，无技术细节内容",
        "timeliness_reason": "最新发布(9分)",
        "preference_reason": "AI模型高度匹配(10分)",
        "credibility_reason": "微博来源，可信度低(3分)",
        "summary": "ClaudeOpus 4.8发布，高影响力AI事件但来源可信度低"
    }, ensure_ascii=False)
    
    conn.execute('''UPDATE cleaned_intelligence SET
        ai_score_scarcity=?, ai_score_impact=?, ai_score_tech_depth=?,
        ai_score_timeliness=?, ai_score_preference=?, ai_score_credibility=?,
        ai_score_total=?, importance_score=?, ai_score_reasoning=?, ai_scored_at=?
        WHERE id=?''',
        (scarcity, impact, tech_depth, timeliness, preference, credibility,
         total, importance, reasoning, now, 804102))
    print(f"✓ 804102 ClaudeOpus 4.8 → {total}/100 (加分完成)")

# 2. 规则评分 193792 - 迪士尼优速通
cur2 = conn.execute('SELECT * FROM cleaned_intelligence WHERE id = 193792')
row2 = cur2.fetchone()
if row2:
    # 贴吧，娱乐新闻
    scarcity = 2
    impact = 2
    tech_depth = 0
    timeliness = 2
    preference = 1
    credibility = 2
    
    total = scarcity + impact + tech_depth + timeliness + preference + credibility
    importance = round(total / 10.0, 1)
    
    reasoning = json.dumps({
        "scarcity_reason": "非独家(2分)，贴吧普通用户发布",
        "impact_reason": "低影响力(2分)，仅涉及个别游乐项目",
        "tech_depth_reason": "无技术内容(0分)",
        "timeliness_reason": "非近期事件(2分)",
        "preference_reason": "低偏好(1分)，纯娱乐内容",
        "credibility_reason": "贴吧来源，可信度极低(2分)",
        "summary": "迪士尼优速通乌龙事件，纯娱乐内容，低价值"
    }, ensure_ascii=False)
    
    conn.execute('''UPDATE cleaned_intelligence SET
        ai_score_scarcity=?, ai_score_impact=?, ai_score_tech_depth=?,
        ai_score_timeliness=?, ai_score_preference=?, ai_score_credibility=?,
        ai_score_total=?, importance_score=?, ai_score_reasoning=?, ai_scored_at=?
        WHERE id=?''',
        (scarcity, impact, tech_depth, timeliness, preference, credibility,
         total, importance, reasoning, now, 193792))
    print(f"✓ 193792 迪士尼优速通 → {total}/100")

# 3. 规则评分 313359 - HIPAA Security Rule Update
cur3 = conn.execute('SELECT * FROM cleaned_intelligence WHERE id = 313359')
row3 = cur3.fetchone()
if row3:
    scarcity = 10
    impact = 16
    tech_depth = 12
    timeliness = 2
    preference = 6
    credibility = 8
    
    total = scarcity + impact + tech_depth + timeliness + preference + credibility
    importance = round(total / 10.0, 1)
    
    reasoning = json.dumps({
        "scarcity_reason": "中等独家(10分)，HackerNews报道技术法规更新",
        "impact_reason": "中等影响(16分)，影响医疗IT行业合规要求",
        "tech_depth_reason": "有一定技术含量(12分)，涉及安全规则更新细节",
        "timeliness_reason": "较旧(2分)，非近期讨论热点",
        "preference_reason": "中等偏好(6分)，安全/合规类技术内容",
        "credibility_reason": "HackerNews来源，可信度高(8分)",
        "summary": "HIPAA安全规则更新，影响医疗IT合规，时效性低但内容有参考价值"
    }, ensure_ascii=False)
    
    conn.execute('''UPDATE cleaned_intelligence SET
        ai_score_scarcity=?, ai_score_impact=?, ai_score_tech_depth=?,
        ai_score_timeliness=?, ai_score_preference=?, ai_score_credibility=?,
        ai_score_total=?, importance_score=?, ai_score_reasoning=?, ai_scored_at=?
        WHERE id=?''',
        (scarcity, impact, tech_depth, timeliness, preference, credibility,
         total, importance, reasoning, now, 313359))
    print(f"✓ 313359 HIPAA Security Rule Update → {total}/100")

conn.commit()
conn.close()
print("\n所有3条处理完成")
