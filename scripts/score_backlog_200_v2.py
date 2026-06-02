#!/usr/bin/env python3
"""
批量升级cleaned_intelligence中只有简略评分（如{"summary": "AI内容评分:35分"}）的积压数据。
使用score_backlog_200.py的规则引擎，一次处理200条，升级为完整的六维评分。
"""
import sqlite3
import json
import re
import sys
from datetime import datetime, date

HERMES = "/home/administrator/.hermes"
DB_PATH = HERMES + "/data/intelligence.db"
LOG_DIR = HERMES + "/logs"

def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}")
    with open(LOG_DIR + f"/score_backlog_v2_{date.today().strftime('%Y%m%d')}.log", "a") as f:
        f.write(f"[{ts}] {msg}\n")

def score_item(title, content, source, platform):
    """基于batch2_ai_scorer.py的规则引擎评分"""
    combined = (f"{title} {content}").lower()
    
    # --- 1. SCARCITY (0-30) ---
    scarcity = 10
    scarcity_reason = ""
    if any(kw in combined for kw in ['全球首', '业界首款', '第一个', '全球首个', '独家', 'world first', 'only one']):
        scarcity = 26
        scarcity_reason = "全球首发/独家报道"
    elif any(kw in combined for kw in ['首款', '首次', '首发', '里程碑', '首个']):
        scarcity = 18
        scarcity_reason = "首款/首次/里程碑"
    elif any(kw in combined for kw in ['泄露', '曝光', '独家', '提前', 'reveals', 'leak']):
        scarcity = 20
        scarcity_reason = "泄露/提前曝光"
    elif any(kw in combined for kw in ['报告', '调研', '白皮书']):
        scarcity = 14
        scarcity_reason = "行业报告/调研"
    else:
        scarcity = 10
        scarcity_reason = "常规信息"
    
    # --- 2. IMPACT (0-30) ---
    impact = 8
    impact_reason = ""
    if any(kw in combined for kw in ['改变格局', '颠覆', '变革', '全球最强', '没有之一', '引领', '跃迁']):
        impact = 24
        impact_reason = "改变格局/引领变革"
    elif any(kw in combined for kw in ['认证', '标准', '通过']) and any(kw in combined for kw in ['安全', 'I 级', '国家']):
        impact = 18
        impact_reason = "国家级认证/标准"
    elif any(kw in combined for kw in ['大定', '突破', '万台', '大卖', '畅销', '销量']):
        impact = 16
        impact_reason = "市场热销/突破"
    elif any(kw in combined for kw in ['欧盟', '立法', '监管', '政策', 'regulation']):
        impact = 18
        impact_reason = "政策/法规/监管"
    elif any(kw in combined for kw in ['发布', '推出', '新品']):
        if any(kw in combined for kw in ['AI', '人工智能', '芯片', '处理器', '自动驾驶', 'gpu']):
            impact = 14
            impact_reason = "AI/芯片新品发布"
        else:
            impact = 8
            impact_reason = "普通产品发布"
    elif any(kw in combined for kw in ['合作', '协议', '采购']):
        impact = 12
        impact_reason = "商业合作"
    elif any(kw in combined for kw in ['竞争', '差距', '超越', '碾压', '领先']):
        impact = 20
        impact_reason = "竞争格局分析"
    else:
        impact = 8
        impact_reason = "常规信息"
    
    # --- 3. TECH_DEPTH (0-20) ---
    tech_depth = 4
    tech_depth_reason = ""
    tech_terms_count = 0
    for kw in ['nm', 'ghz', 'tops', 'tbps', 'gflops', 'tflops', '800v', '5c', 'cltc',
               '7nm', '5nm', 'fp16', 'int8', '算力', '工艺', '制程',
               '架构', '体系结构', 'architecture', '算法', '代码', '开源',
               'sdk', 'api', '框架', '协议', '接口', 'pcie', 'usb', 'ddr', 'hbm',
               '碳化硅', 'sic', '氮化镓', 'gan', 'chiplet', '芯粒', '异构',
               '双腔', 'CDC', '线控', 'dsp', 'risc-v']:
        if kw in combined:
            tech_terms_count += 1
    
    has_architecture = any(kw in combined for kw in ['架构', '体系', 'architecture', '设计', '原理', '机制', '算法'])
    has_perf_numbers = any(kw in combined for kw in ['tops', 'ghz', 'tbps', 'gflops', 'tflops', 'watt', '功耗'])
    
    if has_architecture and has_perf_numbers and tech_terms_count >= 5:
        tech_depth = 18
        tech_depth_reason = "架构+性能参数+技术术语"
    elif has_architecture and has_perf_numbers:
        tech_depth = 15
        tech_depth_reason = "架构+性能参数"
    elif has_architecture or tech_terms_count >= 5:
        tech_depth = 12
        tech_depth_reason = f"含{tech_terms_count}项技术细节"
    elif tech_terms_count >= 3:
        tech_depth = 8
        tech_depth_reason = f"含{tech_terms_count}项技术术语"
    elif tech_terms_count >= 1:
        tech_depth = 6
        tech_depth_reason = "少量技术术语"
    else:
        tech_depth = 4
        tech_depth_reason = "无技术细节"
    
    # --- 4. TIMELINESS (0-10) ---
    timeliness = 5
    timeliness_reason = ""
    found_date = False
    date_patterns = [
        (r'5月29日', 10, "今天"),
        (r'5月28日', 9, "昨天"),
        (r'5月27日', 8, "2天前"),
        (r'5月26日', 7, "3天前"),
        (r'5月25日', 6, "4天前"),
        (r'5月2[0-4]日', 6, "5-9天前"),
        (r'5月1[5-9]日', 4, "约2周前"),
        (r'5月[1-9]日', 3, "约3周前"),
        (r'4月', 2, "约1月前"),
        (r'2025年', 1, "超过1年前"),
    ]
    for pattern, score, label in date_patterns:
        if re.search(pattern, content):
            timeliness = score
            timeliness_reason = label
            found_date = True
            break
    if not found_date:
        if 'today' in combined or '今天' in content or '今晚' in content:
            timeliness = 9
            timeliness_reason = "当天"
        elif 'yesterday' in combined or '昨日' in content or '昨天' in content:
            timeliness = 8
            timeliness_reason = "昨日"
        else:
            timeliness = 5
            timeliness_reason = "无明确日期"
    
    # --- 5. PREFERENCE (0-10) ---
    preference = 5
    preference_reason = ""
    ai_score = 0
    for kw in ['ai', '人工智能', '大模型', 'llm', '机器学习', '深度学习', '神经网络', 'transformer', 'gpt', 'chatgpt', 'claude', 'gemini']:
        if kw in combined: ai_score += 2
    for kw in ['芯片', '处理器', 'gpu', 'cpu', '昇腾', 'risc-v', '半导体', '英伟达', 'nvidia', '华为', '达摩院', '寒武纪']:
        if kw in combined: ai_score += 2
    for kw in ['新能源', '储能', '光伏', '碳化硅', '电池', '电动汽车', 'ev', '氮化镓']:
        if kw in combined: ai_score += 1.5
    for kw in ['汽车', '智能', '手机', '科技', '开源', 'robot', '机器人', '自动驾驶', '智驾']:
        if kw in combined: ai_score += 1
    if ai_score >= 5:
        preference = 9
        preference_reason = "AI/芯片/新能源核心领域"
    elif ai_score >= 3:
        preference = 7
        preference_reason = "科技/技术领域"
    elif ai_score >= 1.5:
        preference = 5
        preference_reason = "相关科技领域"
    else:
        preference = 3
        preference_reason = "非科技领域"
    
    # --- 6. CREDIBILITY (0-10) ---
    src = source.strip().lower() if source else ""
    pl = platform.strip().lower() if platform else ""
    credibility_map = {
        'ithome': 8, '36kr': 8, 'hackernews': 8, 'hacker news': 8,
        'sina_tech': 7, 'sina': 7, 'techcrunch': 8, 'theverge': 8,
        'weibo': 4, '微博': 4, 'tieba': 3, '贴吧': 3,
        'toutiao': 6, '今日头条': 6, 'zhihu': 7, '知乎': 7,
        '微信公众号': 7, 'wechat': 7, 'bilibili': 6,
        'rss': 6, 'github': 8, 'arxiv': 8,
    }
    credibility = credibility_map.get(src, credibility_map.get(pl, 6))
    
    citation_bonus = 0
    if any(kw in combined for kw in ['据介绍', '报告显示', '数据显示', '根据', '引用', '报道称', '援引', 'source:', '据']):
        citation_bonus = 1
    if any(kw in combined for kw in ['%', '万', '亿', 'million', 'billion']):
        citation_bonus = max(citation_bonus, 1)
    credibility = min(10, credibility + citation_bonus)
    credibility_reason = f"{source or platform or 'unknown'}({credibility}分)"
    
    total = scarcity + impact + tech_depth + timeliness + preference + credibility
    total = min(total, 100)
    
    reasoning = {
        "scarcity_reason": scarcity_reason,
        "impact_reason": impact_reason,
        "tech_depth_reason": tech_depth_reason,
        "timeliness_reason": timeliness_reason,
        "preference_reason": preference_reason,
        "credibility_reason": credibility_reason,
        "summary": f"总分{total}: 独家{scarcity} 影响{impact} 技术{tech_depth} 时效{timeliness} 偏好{preference} 可信{credibility}"
    }
    
    return {
        'scarcity': scarcity,
        'impact': impact,
        'tech_depth': tech_depth,
        'timeliness': timeliness,
        'preference': preference,
        'credibility': credibility,
        'total': total,
        'importance_score': round(total / 10.0, 1),
        'reasoning_json': json.dumps(reasoning, ensure_ascii=False),
    }

def main():
    log("=" * 80)
    log("🚀 积压评分器v2启动 - 升级简略评分为完整六维评分")
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    # 获取只有简略评分的条目:
    # 1) AI内容评分 2) 内容感知 3) 纯summary格式（没有维度信息）
    rows = c.execute("""
        SELECT id, title, COALESCE(content,'') as content, 
               source, platform, published_at
        FROM cleaned_intelligence
        WHERE ai_score_total IS NOT NULL AND ai_score_total > 0
        AND (
            ai_score_reasoning LIKE '%AI内容评分%'
            OR ai_score_reasoning LIKE '%内容感知%'
            OR (ai_score_reasoning NOT LIKE '%scarcity%'
                AND ai_score_reasoning NOT LIKE '%impact%')
        )
        ORDER BY id ASC
        LIMIT 200
    """).fetchall()
    
    total_candidates = len(rows)
    log(f"📊 待升级条目(上限200): {total_candidates}条")
    
    if total_candidates == 0:
        log("✅ 无待升级数据，任务完成")
        conn.close()
        return
    
    results = []
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    processed = 0
    
    for row in rows:
        item_id = row['id']
        title = row['title'] or ''
        content = row['content'] or ''
        source = row['source'] or ''
        platform = row['platform'] or ''
        
        scores = score_item(title, content, source, platform)
        
        c.execute("""
            UPDATE cleaned_intelligence
            SET ai_score_scarcity=?,
                ai_score_impact=?,
                ai_score_tech_depth=?,
                ai_score_timeliness=?,
                ai_score_preference=?,
                ai_score_credibility=?,
                ai_score_total=?,
                importance_score=?,
                ai_score_reasoning=?,
                ai_scored_at=?
            WHERE id=?
        """, (
            scores['scarcity'], scores['impact'], scores['tech_depth'],
            scores['timeliness'], scores['preference'], scores['credibility'],
            scores['total'], scores['importance_score'],
            scores['reasoning_json'], now, item_id
        ))
        processed += 1
        results.append((item_id, scores['total'], title[:50]))
    
    conn.commit()
    conn.close()
    
    # 输出报告
    log(f"✅ 评分升级完成: {processed}条")
    totals = [r[1] for r in results]
    log(f"📊 分数统计: 最低={min(totals)} 最高={max(totals)} 平均={sum(totals)/len(totals):.1f}")
    log(f"📊 分布: <40={sum(1 for t in totals if t < 40)} 40-60={sum(1 for t in totals if 40 <= t < 60)} 60-80={sum(1 for t in totals if 60 <= t < 80)} >=80={sum(1 for t in totals if t >= 80)}")
    
    # 输出高价值(top 10)和低价值(bottom 5)条目
    sorted_desc = sorted(results, key=lambda x: -x[1])
    log(f"\n🏆 最高分TOP10:")
    for i, (item_id, total, title) in enumerate(sorted_desc[:10], 1):
        log(f"  {i:2d}. ID={item_id:>7} {total:3d}分 | {title}")
    
    sorted_asc = sorted(results, key=lambda x: x[1])
    log(f"\n👇 最低分BOTTOM5:")
    for i, (item_id, total, title) in enumerate(sorted_asc[:5], 1):
        log(f"  {i:2d}. ID={item_id:>7} {total:3d}分 | {title}")
    
    print(f"\n{'='*80}")
    print(f"SCORE_BACKLOG_V2_RESULT:{processed}")
    print(f"SCORE_MIN:{min(totals)}")
    print(f"SCORE_MAX:{max(totals)}")
    print(f"SCORE_AVG:{sum(totals)/len(totals):.1f}")

if __name__ == '__main__':
    main()
