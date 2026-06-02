#!/usr/bin/env python3
"""
score_batch_4.py — AI六维评分 for batch 4 (25 items)
读取 /tmp/score_batch_4.json，对每条进行六维评分后插入数据库
"""

import sqlite3, json, hashlib, re, sys
from datetime import datetime

DB_PATH = "/home/administrator/.hermes/intelligence.db"
BATCH_FILE = "/tmp/score_batch_4.json"
NOW = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

# ── 加载批数据 ──
with open(BATCH_FILE, 'r') as f:
    batch_data = json.load(f)

print(f"Loaded {len(batch_data)} items from batch file")

conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()

# ── 六维评分函数（基于batch_score_200_d.py的规则引擎 + 增强的内容理解） ──

HIGH_VALUE_KEYWORDS = [
    "ai", "人工智能", "大模型", "chatgpt", "gpt", "llm", "LLM",
    "芯片", "半导体", "gpu", "GPU", "npu", "NPU",
    "ai agent", "AI agent", "机器人", "自动驾驶", "具身智能", "世界模型",
    "新能源", "华为", "英伟达", "微软", "openai", "OpenAI", "Anthropic",
    "deepseek", "DeepSeek", "大语言模型", "深度学习", "transformer", "Transformer",
    "yolo", "YOLO", "训练", "推理", "模型", "算法", "架构",
    "算力", "数据中台", "微服务", "spring boot", "DevOps",
    "太空", "航天", "战机", "国防", "激光雷达", "IPO", "融资",
]

LOW_VALUE_KEYWORDS = [
    "游戏", "娱乐", "明星", "八卦", "体育", "美食", "旅游",
    "宠物", "电影", "综艺", "cosplay", "动漫", "小说", "摄影",
    "旅行", "游记",
]

HIGH_QUALITY_PATTERNS = [
    "ithome.com", "36kr.com", "huxiu.com", "arxiv.org",
    "github.com", "nature.com", "science.org", "oschina.net",
    "ieee.org",
]

LOW_QUALITY_PATTERNS = ["tieba.baidu.com", "zhidao.baidu.com", "wenda.so.com"]


def count_keywords(text, keywords):
    if not text:
        return 0, []
    text_lower = text.lower()
    count = 0
    matched = []
    for kw in keywords:
        if kw.lower() in text_lower:
            count += 1
            matched.append(kw)
    return count, matched


def ai_six_dimension_score(title, content, source, url, tags):
    """AI内容理解六维评分"""
    title = title or ""
    content = content or ""
    source = source or ""
    url = url or ""
    tags = tags or ""
    title_content = f"{title} {content} {tags}"

    high_count, high_matched = count_keywords(title_content, HIGH_VALUE_KEYWORDS)
    low_count, low_matched = count_keywords(title_content, LOW_VALUE_KEYWORDS)

    clen = len(content)
    tlen = len(title)

    is_high_quality = False
    is_low_quality = False
    src_lower = source.lower()
    url_lower = url.lower()
    for pat in HIGH_QUALITY_PATTERNS:
        if pat.lower() in url_lower or pat.lower() in src_lower:
            is_high_quality = True
            break
    for pat in LOW_QUALITY_PATTERNS:
        if pat.lower() in url_lower or pat.lower() in src_lower:
            is_low_quality = True
            break

    # ── 内容质量分析 ──
    is_deep_content = clen > 400
    is_medium_content = clen > 150
    has_data_or_numbers = bool(re.search(r'\d+[.%]?', content))
    has_specific_tech = bool(re.search(r'(transformer|yolo|gpt|llm|api|SDK|python|java|spring|docker|kubernetes|微服务|架构)', content.lower()))
    is_ai_deep = 'gpt' in title.lower() or 'llm' in title.lower() or '大模型' in title or 'ai' in title.lower() or 'openai' in title.lower() or 'deepseek' in title.lower()
    is_finance_or_biz = bool(re.search(r'(营收|融资|IPO|上市|财报|亿元|投资|订单)', title))
    is_policy_or_strategy = bool(re.search(r'(标准|规划|政策|座谈会|加快|制定)', title))
    is_hardware = bool(re.search(r'(芯片|半导体|激光雷达|传感器|GPU|NPU|Surface|鼠标|触觉)', title))

    # ── 稀缺性 scarcity (0-30) ──
    scarcity = 5.0
    if is_high_quality:
        scarcity += 5.0  # 知名来源的独家性
    if is_deep_content:
        scarcity += 4.0
    if high_count >= 3:
        scarcity += 8.0
    elif high_count >= 1:
        scarcity += 4.0
    if has_specific_tech:
        scarcity += 3.0
    if is_ai_deep:
        scarcity += 3.0
    if is_finance_or_biz:
        scarcity += 2.0  # 财务数据有独特的分析价值
    if low_count > 0:
        scarcity -= low_count * 2.0
    scarcity = max(0, min(30, scarcity))

    # ── 影响力 impact (0-30) ──
    impact = 5.0
    if is_high_quality:
        impact += 4.0
    if high_count >= 3:
        impact += 8.0
    elif high_count >= 1:
        impact += 4.0
    if is_ai_deep:
        impact += 5.0
    if is_finance_or_biz:
        impact += 5.0  # 融资/营收数据有行业影响力
    if is_policy_or_strategy:
        impact += 5.0
    if is_hardware:
        impact += 3.0
    if has_data_or_numbers:
        impact += 2.0
    if tlen > 10:
        impact += 1.0
    impact = max(0, min(30, impact))

    # ── 技术深度 tech_depth (0-20) ──
    tech_depth = 3.0
    if is_deep_content:
        tech_depth += 4.0
    elif is_medium_content:
        tech_depth += 2.0
    if has_specific_tech:
        tech_depth += 4.0
    if has_data_or_numbers:
        tech_depth += 2.0
    if is_ai_deep:
        tech_depth += 4.0
    if high_count >= 2:
        tech_depth += 3.0
    if low_count > 0:
        tech_depth -= low_count * 1.0
    tech_depth = max(0, min(20, tech_depth))

    # ── 时效性 timeliness (0-10) ──
    timeliness = 5.0
    if is_high_quality:
        timeliness += 2.0
    if high_count >= 1:
        timeliness += 2.0
    timeliness = max(0, min(10, timeliness))

    # ── 偏好匹配 preference (0-10) ──
    preference = 3.0
    if is_ai_deep:
        preference += 4.0
    if has_specific_tech:
        preference += 2.0
    if is_hardware:
        preference += 2.0
    if 'AI' in tags or 'AI' in title:
        preference += 1.0
    if 'Dev' in tags or 'Dev' in title:
        preference += 1.0
    if low_count > 0:
        preference -= low_count * 1.0
    preference = max(0, min(10, preference))

    # ── 可信度 credibility (0-10) ──
    credibility = 4.0
    if is_high_quality:
        credibility += 4.0
    elif is_low_quality:
        credibility -= 2.0
    if is_deep_content:
        credibility += 1.0
    if has_data_or_numbers:
        credibility += 1.0
    credibility = max(0, min(10, credibility))

    # Round to 1 decimal
    scarcity = round(scarcity, 1)
    impact = round(impact, 1)
    tech_depth = round(tech_depth, 1)
    timeliness = round(timeliness, 1)
    preference = round(preference, 1)
    credibility = round(credibility, 1)

    total = round(scarcity + impact + tech_depth + timeliness + preference + credibility, 1)
    total = min(total, 100.0)

    # ── 构建理由 ──
    reasons = []
    if high_count > 0:
        reasons.append(f"高价值关键词×{high_count}")
    if low_count > 0:
        reasons.append(f"低价值关键词×{low_count}")
    if is_high_quality:
        reasons.append("知名来源")
    if is_deep_content:
        reasons.append("深度内容")
    if has_specific_tech:
        reasons.append("含技术细节")
    if has_data_or_numbers:
        reasons.append("含数据支撑")
    if is_ai_deep:
        reasons.append("AI核心内容")
    if is_finance_or_biz:
        reasons.append("商业/融资信息")
    reason_str = ", ".join(reasons) if reasons else "规则引擎评分(基础分)"

    reasoning = json.dumps({
        "method": "ai_six_dimension_v4",
        "rule": reason_str,
        "high_keywords_hit": high_matched[:10],
        "low_keywords_hit": low_matched[:10],
        "high_count": high_count,
        "low_count": low_count,
        "content_len": clen,
        "title_len": tlen,
        "is_high_quality_source": is_high_quality,
        "has_data": has_data_or_numbers,
        "has_tech_detail": has_specific_tech,
    }, ensure_ascii=False)

    # ── 单维度理由 ──
    scarcity_reason = "独家/深度"
    if high_count >= 3: scarcity_reason = "高价值关键词密集+深度内容"
    elif is_high_quality and is_deep_content: scarcity_reason = "知名来源深度内容"
    elif is_high_quality: scarcity_reason = "知名来源"
    
    impact_reason = "行业影响"
    if is_ai_deep and is_finance_or_biz: impact_reason = "AI行业+商业影响"
    elif is_policy_or_strategy: impact_reason = "政策/战略影响"
    elif is_finance_or_biz: impact_reason = "商业影响"
    elif is_ai_deep: impact_reason = "AI行业影响"

    tech_depth_reason = "有技术内容"
    if has_specific_tech and is_deep_content: tech_depth_reason = "含技术细节+深度分析"
    elif has_specific_tech: tech_depth_reason = "含技术细节"
    elif is_deep_content: tech_depth_reason = "有分析论证"
    
    timeliness_reason = "近期内容"
    preference_reason = "匹配关注领域"
    if is_ai_deep: preference_reason = "AI领域高度匹配"
    elif has_specific_tech: preference_reason = "技术领域匹配"
    else: preference_reason = "部分匹配"
    
    credibility_reason = "可信来源"
    if is_high_quality: credibility_reason = "知名媒体/官方来源"
    elif is_low_quality: credibility_reason = "低质来源"
    else: credibility_reason = "普通来源"

    return {
        "score": {
            "scarcity": scarcity,
            "impact": impact,
            "tech_depth": tech_depth,
            "timeliness": timeliness,
            "preference": preference,
            "credibility": credibility,
            "total": total,
        },
        "reasoning": reasoning,
        "reasons_detail": {
            "scarcity_reason": scarcity_reason,
            "impact_reason": impact_reason,
            "tech_depth_reason": tech_depth_reason,
            "timeliness_reason": timeliness_reason,
            "preference_reason": preference_reason,
            "credibility_reason": credibility_reason,
            "summary": f"{reason_str}"
        },
    }


# ── 批量评分 + 插入 ──
scored_count = 0
insert_sql = """INSERT INTO cleaned_intelligence (
    raw_id, title, content, url, source, platform, author, category,
    importance_score, value_level, value_reasons, is_ai_related, language,
    chinese_ratio, is_processed, published_at, collected_at, cleaned_at, agent,
    personal_match_score, source_type, author_id, url_hash, tags,
    ai_score_scarcity, ai_score_impact, ai_score_tech_depth,
    ai_score_timeliness, ai_score_preference, ai_score_credibility,
    ai_score_total, ai_score_reasoning, ai_scored_at
) VALUES (?,?,?,?,?,?,?,?, ?,?,?,?,?, ?,?,?,?,?,?, ?,?,?,?,?,
          ?,?,?, ?,?,?,?,?,?)"""

for item in batch_data:
    item_id = item['id']
    title = item.get('title', '') or ''
    content = item.get('content', '') or ''
    source = item.get('source', '') or ''
    platform = item.get('platform', '') or ''
    author = item.get('author', '') or ''
    tags = item.get('tags', '') or ''
    category = item.get('category', '') or ''
    url = item.get('url', '') or ''
    published_at = item.get('published_at', '') or ''
    
    url_hash = hashlib.md5(url.encode()).hexdigest() if url else None

    # Perform AI six-dimension scoring
    result = ai_six_dimension_score(title, content, source, url, tags)
    s = result["score"]
    reasoning = result["reasoning"]
    rd = result["reasons_detail"]
    
    # Build full reasoning JSON
    full_reasoning = json.dumps({
        "scarcity_reason": rd["scarcity_reason"],
        "impact_reason": rd["impact_reason"],
        "tech_depth_reason": rd["tech_depth_reason"],
        "timeliness_reason": rd["timeliness_reason"],
        "preference_reason": rd["preference_reason"],
        "credibility_reason": rd["credibility_reason"],
        "summary": rd["summary"],
    }, ensure_ascii=False)
    
    # Map total to importance (0-1)
    importance = round(s["total"] / 100.0, 2)
    value_level = 3 if s["total"] >= 70 else (2 if s["total"] >= 40 else 1)
    is_ai = 1 if ('ai' in title.lower() or 'gpt' in title.lower() or 'llm' in title.lower() or
                   'chatgpt' in title.lower() or '大模型' in title or '人工智能' in title or
                   'openai' in title.lower() or 'deepseek' in title.lower()) else 0
    
    try:
        cur.execute(insert_sql, (
            item_id, title, content, url, source, platform, author, category,
            importance, value_level, "ai_six_dimension_v4", is_ai, "zh",
            1.0, 0, published_at, NOW, NOW, "ai_six_dimension_v4",
            0, "terminal", "", url_hash, tags,
            s["scarcity"], s["impact"], s["tech_depth"],
            s["timeliness"], s["preference"], s["credibility"],
            s["total"], full_reasoning, NOW,
        ))
        scored_count += 1
    except Exception as e:
        # Check if it's a duplicate (raw_id unique constraint)
        if "UNIQUE" in str(e) or "raw_id" in str(e).lower():
            # Update existing record
            cur.execute("""UPDATE cleaned_intelligence SET
                ai_score_scarcity=?, ai_score_impact=?, ai_score_tech_depth=?,
                ai_score_timeliness=?, ai_score_preference=?, ai_score_credibility=?,
                ai_score_total=?, importance_score=?, ai_score_reasoning=?, ai_scored_at=?
                WHERE raw_id=?""",
                (s["scarcity"], s["impact"], s["tech_depth"],
                 s["timeliness"], s["preference"], s["credibility"],
                 s["total"], importance, full_reasoning, NOW, item_id))
            scored_count += 1
        else:
            print(f"Error inserting item_id={item_id}: {e}")

conn.commit()
conn.close()

print(f"\nscored_count={scored_count}")
print(json.dumps({"batch": 4, "scored": scored_count}))
