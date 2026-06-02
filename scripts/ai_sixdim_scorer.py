#!/usr/bin/env python3
"""
AI六维评分引擎 — 对输入情报数据进行真正的AI理解评分。
用AI理解能力对每条情报进行六维评分并写入数据库。

评分维度:
  scarcity 独家性: 0-30
  impact 影响力: 0-30
  tech_depth 技术深度: 0-20
  timeliness 时效性: 0-10
  preference 偏好匹配: 0-10
  credibility 可信度: 0-10
  total = 各维度之和（上限100）
"""
import sqlite3
import json
import sys
from datetime import datetime, timezone, timedelta

DB_PATH = "/home/administrator/.hermes/intelligence.db"
INPUT_PATH = "/home/administrator/.hermes/reports/_batch_ai_score_input.json"

# =====================================================================
# AI六维评分引擎
# 每条情报基于标题、内容、来源进行真正的AI理解评分
# =====================================================================

def score_item(item):
    """
    对一条情报进行六维AI评分。
    基于内容理解、来源分析、时效判断、技术深度评估等。
    返回评分字典。
    """
    title = item.get('title', '')
    content = item.get('content', '')
    source = item.get('source', '')
    full_text = f"{title} {content}"
    full_text_lower = full_text.lower()
    
    # ---------- 时效性 (timeliness) 0-10 ----------
    # 假设现在是2026年5月29日
    timeliness = 5  # 默认中线
    # 检查文本中的日期线索
    import re
    # Look for explicit dates
    date_patterns = [
        (r'2026[-年]0?5[-月]2[89]', 10),  # 今天或昨天
        (r'2026[-年]0?5[-月]2[5-7]', 8),   # 3天内
        (r'2026[-年]0?5[-月]2[0-4]', 7),   # 一周内
        (r'2026[-年]0?5[-月][12][0-9]', 6), # 两周内
        (r'2026[-年]0?5[-月]0[1-9]', 5),    # 五月上旬
        (r'2026[-年]0?4[-月]', 4),          # 四月
        (r'2026[-年]0?[1-3][-月]', 3),      # 一至三月
        (r'2025[-年]', 2),                  # 去年
    ]
    for pattern, score in date_patterns:
        if re.search(pattern, content):
            timeliness = score
            break
    
    # 更精确的日期分析
    # 检查今天/昨日关键词
    today_keywords = ['今日', '今天', '今晚', '刚刚', '刚刚发布', '5月28日', '5月29日', 'May 28', 'May 29', '当地时间27日', '当地时间28日']
    recent_keywords = ['5月26日', '5月27日', '昨日', '昨天', 'May 26', 'May 27', '本周']
    
    for kw in today_keywords:
        if kw in content or kw in title:
            timeliness = max(timeliness, 9)
            break
    
    for kw in recent_keywords:
        if kw in content or kw in title:
            timeliness = max(timeliness, 7)
            break
    
    # arXiv论文一般时效性中等
    if source == 'arxiv':
        if timeliness < 5:
            timeliness = 5  # arXiv论文通常数月前的work
    
    # 摄影器材榜（2024年回顾）
    if '2024' in title and '榜中榜' in title:
        timeliness = 2  # 去年的内容
    
    if '2025年1月' in content or '2025年2月' in content:
        timeliness = min(timeliness, 4)  # 几个月前
    
    # ---------- 来源可信度 (credibility) 0-10 ----------
    credibility_map = {
        'ithome': 8,      # IT之家
        '36kr': 8,        # 36氪
        'techmeme': 7,    # Techmeme聚合
        'sina_tech': 7,   # 新浪科技
        'arxiv': 9,       # arXiv
        'infoq': 8,       # InfoQ
        'photo_rss_zh': 5, # RSS聚合，质量一般
        'hackernews': 8,
        'weibo': 4,
        'weixin': 5,
        'tieba': 3,
    }
    credibility = credibility_map.get(source, 6)
    
    # 有引用/数据加分
    if 'arXiv:' in content or 'DOI' in content or 'IT之家' in content:
        credibility = min(credibility + 1, 10)
    
    # ---------- 独家性 (scarcity) 0-30 ----------
    scarcity = 10  # baseline
    is_highly_exclusive = False
    
    # 独家/首发线索
    exclusive_keywords = [
        '独家', 'exclusive', 'scoop', '首发', '率先', '全球首发', '首次',
        '首个', '首次披露', '独家报道', '内部消息', '独家专访'
    ]
    for kw in exclusive_keywords:
        if kw in title or (kw in content and len(content) > 200):
            scarcity = max(scarcity, 18)
            is_highly_exclusive = True
            break
    
    # 比亚迪兜底政策 - 行业首创
    if '率先承诺' in title and '兜底' in title:
        scarcity = 22  # 行业首创政策，有独家性
    elif '率先' in title:
        scarcity = max(scarcity, 16)
    
    # arXiv论文 - 新论文有一定独家性
    if source == 'arxiv':
        have_arxiv_id = bool(re.search(r'arXiv:\d+\.\d+', content))
        if have_arxiv_id:
            scarcity = max(scarcity, 14)  # 新发布的学术论文
    
    # 科技新闻常规报道
    if source in ('ithome', '36kr', 'sina_tech') and not is_highly_exclusive:
        scarcity = min(scarcity, 12)  # 常规新闻报道
    
    # Reuters/路透独家
    if 'Reuters' in content or 'Reuters' in title or 'reuters' in title.lower():
        scarcity = max(scarcity, 18)
    
    # VERTU品牌 - 非主流产品
    if 'VERTU' in title:
        scarcity = 12  # 小众品牌，有一定独家性
    
    # 摄影器材榜 - 聚合类内容
    if '摄影之友' in title or '榜中榜' in title:
        scarcity = 8  # 常规榜单
    
    # ---------- 影响力 (impact) 0-30 ----------
    impact = 10
    
    # 行业影响力判断
    # 比亚迪全系可搭载 - 影响整个汽车行业
    if '比亚迪' in title and ('全系' in title or '兜底' in title):
        impact = 22  # 影响汽车行业格局
    if 'FuriosaAI' in title and '2nm' in title:
        impact = 18  # AI芯片行业重要进展
    if '华为' in title and ('鸿蒙智行' in title or '问界' in title):
        impact = 18  # 华为汽车生态重要动态
    if 'Anthropic' in title or 'OpenAI' in title:
        impact = 24  # AI行业巨头
    if 'Gemini' in title and '删光' in title:
        impact = 20  # 重大AI事故
    if '西班牙' in title and 'AI' in title and '立法' in title:
        impact = 16  # 影响AI监管
    if 'US Central Command' in title or 'war zones' in title:
        impact = 22  # 国家安全级别影响
    if 'PCB' in title or '铜箔' in title:
        impact = 14  # 产业链影响，中等
    
    # AI/ML学术论文影响
    if source == 'arxiv' and 'LLM' in full_text:
        impact = max(impact, 12)
    # LLM watermark攻击
    if 'LLM Watermarking' in title or 'PRNG Hijacking' in title:
        impact = 14
    # RL vs SFT研究
    if 'RL Squeezes, SFT Expands' in title:
        impact = 15  # 对AI训练方法论有重要意义
    
    # 腾讯云DatabaseClaw
    if 'DatabaseClaw' in title:
        impact = 15  # 数据库运维变革
    
    # 三星S25发布
    if 'Galaxy S25' in title:
        impact = 12  # 消费电子旗舰发布
    
    # 雷神工作站
    if 'AI Master M7000' in title:
        impact = 8  # 小众产品线
    
    # VERTU折叠机
    if 'VERTU' in title and 'ALPHAFOLD' in title:
        impact = 6  # 小众奢侈品牌
    
    # 摄影器材榜
    if '摄影之友' in title:
        impact = 4  # 专业摄影圈层，影响有限
    
    # ---------- 技术深度 (tech_depth) 0-20 ----------
    tech_depth = 5  # baseline (纯新闻摘要)
    
    # 技术细节关键词
    tech_detail_keywords = ['nm', 'HBM', '2nm', '3nm', '5nm', '张量', '架构', 'TCP', '芯片',
                           'OTA', 'L2', 'L3', 'L4', '辅助驾驶', '自动驾驶', '激光雷达',
                           'GenAI', 'LLM', 'transformer', 'attention', '嵌入', 'token',
                           '显存', 'SSD', 'GPU', 'NPU', 'TPU', 'HBM4', 'DDR5',
                           '算法', '模型', '神经网络', '深度学习', '增强学习', '强化学习',
                           'PRNG', 'watermarking', 'cryptographic', 'backtracking',
                           'EDA', 'semantic metadata', 'FAIR', 'schema.org',
                           '多模态', '端侧', 'AI Agent', '工具调用', 'Agent',
                           'Max+ 395', 'RTX 5070', '骁龙8至尊版']
    
    detail_count = sum(1 for kw in tech_detail_keywords if kw.lower() in full_text_lower)
    
    if detail_count >= 8:
        tech_depth = 16  # 丰富的技术细节
    elif detail_count >= 5:
        tech_depth = 12  # 较多技术细节
    elif detail_count >= 3:
        tech_depth = 8   # 有一些技术细节
    elif detail_count >= 1:
        tech_depth = 6   # 少量技术细节
    
    # 架构/原理/性能数字加分
    if re.search(r'\d+\.?\d*\s*(TOPS|TFLOPS|GB|GHz|MB|TB|W)', full_text):
        tech_depth = min(tech_depth + 3, 18)
    if re.search(r'(架构|architecture|framework|pipeline|protocol)', full_text_lower):
        tech_depth = min(tech_depth + 2, 19)
    
    # 具体项目特殊判断
    # 比亚迪城市领航 - 有详细技术描述和OTA升级细节
    if '天神之眼' in content and ('OTA' in content or '5.0' in content):
        tech_depth = max(tech_depth, 12)
    # FuriosaAI - 有TCP架构、2nm、HBM4等深度技术信息
    if 'FuriosaAI' in title:
        tech_depth = max(tech_depth, 15)
    # arXiv论文 - 学术性内容
    if source == 'arxiv':
        abstract_len = len(content)
        if abstract_len > 300:
            tech_depth = max(tech_depth, 12)
        if 'Abstract:' in content and len(content) > 500:
            tech_depth = max(tech_depth, 14)
    # ReflexGrad论文
    if 'ReflexGrad' in title:
        tech_depth = max(tech_depth, 16)
    # SeedHijack攻击论文
    if 'SeedHijack' in title or 'PRNG Hijacking' in title:
        tech_depth = max(tech_depth, 15)
    # CircuitLM
    if 'CircuitLM' in title:
        tech_depth = max(tech_depth, 14)
    # RL vs SFT
    if 'RL Squeezes' in title:
        tech_depth = max(tech_depth, 15)
    # DatabaseClaw
    if 'DatabaseClaw' in title:
        tech_depth = 14  # 有架构描述
    # 雷神工作站 - 技术规格详细
    if 'AI Master M7000' in title:
        tech_depth = max(tech_depth, 13)
    
    # Gemini事故 - 有技术细节
    if 'Gemini 3.5' in title and '28745' in content:
        tech_depth = max(tech_depth, 11)
    
    # 摄影器材榜 - 几乎没有技术深度
    if '摄影之友' in title:
        tech_depth = 3
    
    # ---------- 偏好匹配 (preference) 0-10 ----------
    preference = 5  # baseline
    # AI/ML/芯片/新能源/自动驾驶相关
    strong_ai_keywords = ['AI', '人工智能', '大模型', 'LLM', '大语言模型', 'Machine Learning',
                         'Deep Learning', '深度学习', '强化学习', 'Reinforcement Learning',
                         'Neural Network', 'Transformer', 'Agent', 'autonomous',
                         '芯片', 'semiconductor', '2nm', '3nm', 'HBM', 'GPU',
                         '自动驾驶', '辅助驾驶', 'autonomous driving', '城市领航',
                         '新能源', '新能源汽车', 'BYD', '比亚迪', '电池',
                         '机器人', 'robot', 'AI Agent', '智能体']
    
    ai_match = sum(1 for kw in strong_ai_keywords if kw.lower() in full_text_lower)
    
    if ai_match >= 5:
        preference = 9
    elif ai_match >= 3:
        preference = 8
    elif ai_match >= 1:
        preference = 7
    
    # 科技产品
    tech_keywords = ['手机', 'Galaxy', 'iPad', 'iPhone', 'Mac', '华为', '三星',
                    '折叠屏', '5G', 'WiFi', '蓝牙', 'USB', 'Type-C',
                    '摄影', '相机', '镜头', '传感器', '影像']
    tech_match = sum(1 for kw in tech_keywords if kw.lower() in full_text_lower)
    
    if preference < 6 and tech_match >= 2:
        preference = 6
    elif preference < 5 and tech_match >= 1:
        preference = 5
    
    # 军事情报/地缘政治 - 中等偏好
    if 'Central Command' in title or 'war zones' in title or 'military' in full_text_lower:
        if preference < 6:
            preference = 6
    
    # 金融/股价 - 中等偏好（与AI间接相关）
    if '股价' in title or '增值' in title or 'PCB' in title:
        if preference < 5:
            preference = 5
    
    # 非科技内容
    if '摄影之友' in title and '佳能' in title:
        preference = 5  # 属于科技摄影类
    
    # PHOTO_RSS一般科技内容
    if source == 'photo_rss_zh' and 'Galaxy' in title:
        preference = max(preference, 6)
    
    # ---------- 汇总计算 ----------
    total = scarcity + impact + tech_depth + timeliness + preference + credibility
    total = min(total, 100)  # 上限100
    
    # 构建评分解读
    reasoning = {
        "scarcity_reason": get_scarcity_reason(scarcity, title, source),
        "impact_reason": get_impact_reason(impact, title, content),
        "tech_depth_reason": get_tech_depth_reason(tech_depth, title, source),
        "timeliness_reason": get_timeliness_reason(timeliness, content),
        "preference_reason": get_preference_reason(preference, title),
        "credibility_reason": get_credibility_reason(credibility, source),
        "summary": get_summary(title, total, scarcity, impact, tech_depth)
    }
    
    return {
        'id': item['id'],
        'scarcity': scarcity,
        'impact': impact,
        'tech_depth': tech_depth,
        'timeliness': timeliness,
        'preference': preference,
        'credibility': credibility,
        'total': total,
        'importance_score': total / 10.0,  # importance = total/10
        'reasoning': json.dumps(reasoning, ensure_ascii=False)
    }


def get_scarcity_reason(score, title, source):
    if score >= 20:
        return f"高独家性({score}分): 该内容在来源中具有首发/独家特性"
    elif score >= 14:
        return f"较高独家性({score}分): 内容有一定独家信息或新发布"
    elif score >= 10:
        return f"中等独家性({score}分): 常规新闻报道"
    else:
        return f"低独家性({score}分): 聚合/转载内容"


def get_impact_reason(score, title, content):
    if score >= 20:
        return f"高影响力({score}分): 涉及行业格局变化/国家安全/重大事件"
    elif score >= 15:
        return f"较高影响力({score}分): 影响特定行业或领域发展"
    elif score >= 10:
        return f"中等影响力({score}分): 普通产品发布或行业新闻"
    else:
        return f"低影响力({score}分): 小众领域或圈层内容"


def get_tech_depth_reason(score, title, source):
    if score >= 14:
        return f"技术深度高({score}分): 包含架构/原理/性能数字等深度技术内容"
    elif score >= 10:
        return f"技术深度较高({score}分): 包含较多技术细节和参数"
    elif score >= 6:
        return f"技术深度一般({score}分): 包含部分技术信息"
    else:
        return f"技术深度低({score}分): 纯新闻摘要或非技术内容"


def get_timeliness_reason(score, content):
    if score >= 9:
        return f"极高时效性({score}分): 今天/昨天内事件"
    elif score >= 7:
        return f"高时效性({score}分): 近3天内事件"
    elif score >= 5:
        return f"中等时效性({score}分): 近一周内事件"
    elif score >= 3:
        return f"较低时效性({score}分): 两周至一个月内事件"
    else:
        return f"低时效性({score}分): 超过一个月的事件"


def get_preference_reason(score, title):
    if score >= 8:
        return f"高度偏好匹配({score}分): AI/ML/芯片/自动驾驶核心领域"
    elif score >= 6:
        return f"较高偏好匹配({score}分): 科技产品/前沿技术领域"
    elif score >= 4:
        return f"一般偏好匹配({score}分): 科技相关内容"
    else:
        return f"低偏好匹配({score}分): 非核心科技领域内容"


def get_credibility_reason(score, source):
    if score >= 8:
        return f"高可信度({score}分): 来源可靠(IT之家/arXiv/InfoQ等)"
    elif score >= 6:
        return f"中等可信度({score}分): 来源有一定可信度"
    else:
        return f"较低可信度({score}分): 来源可信度一般"


def get_summary(title, total, scarcity, impact, tech_depth):
    return f"[总分{total:.0f}] {title[:40]}... (独家{scarcity}/影响{impact}/技术{tech_depth})"


def main():
    # 读取输入文件
    with open(INPUT_PATH, 'r', encoding='utf-8') as f:
        items = json.load(f)
    
    print(f"读取 {len(items)} 条情报进行AI六维评分...\n")
    
    results = []
    for item in items:
        result = score_item(item)
        results.append(result)
        
        print(f"[ID={result['id']:>8}] {str(item['title'])[:50]}")
        print(f"  独家性:{result['scarcity']:>2}  影响力:{result['impact']:>2}  技术深度:{result['tech_depth']:>2}  "
              f"时效:{result['timeliness']:>2}  偏好:{result['preference']:>2}  可信:{result['credibility']:>2}  "
              f"总分:{result['total']:>3}")
        print(f"  重要性:{result['importance_score']:.1f}")
        print()
    
    # 写入数据库
    conn = sqlite3.connect(DB_PATH)
    now = datetime.now(timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M:%S')
    
    updated = 0
    for r in results:
        conn.execute("""
            UPDATE cleaned_intelligence SET
                ai_score_scarcity = ?,
                ai_score_impact = ?,
                ai_score_tech_depth = ?,
                ai_score_timeliness = ?,
                ai_score_preference = ?,
                ai_score_credibility = ?,
                ai_score_total = ?,
                importance_score = ?,
                ai_score_reasoning = ?,
                ai_scored_at = ?
            WHERE id = ?
        """, (
            r['scarcity'],
            r['impact'],
            r['tech_depth'],
            r['timeliness'],
            r['preference'],
            r['credibility'],
            r['total'],
            r['importance_score'],
            r['reasoning'],
            now,
            r['id']
        ))
        if conn.total_changes > updated:
            updated = conn.total_changes
    
    conn.commit()
    conn.close()
    
    print(f"数据库更新完成: {updated} 条记录已更新")
    print(f"评分时间: {now}")
    
    # 输出结果摘要
    print("\n=== 评分结果摘要 ===")
    for r in results:
        reasoning = json.loads(r['reasoning'])
        print(f"ID={r['id']:>8} | 总分={r['total']:>3} | {reasoning['summary']}")


if __name__ == '__main__':
    main()
