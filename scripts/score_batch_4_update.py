#!/usr/bin/env python3
"""
score_batch_4_update.py — AI六维评分 Update for batch 4 (25 items)
The items already exist in cleaned_intelligence with different raw_ids.
We need to find them by title and UPDATE the scores.
"""

import sqlite3, json, re, sys
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

# ── 六维评分函数 ──

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
    """AI内容理解六维评分 - 基于规则引擎 + 内容理解"""
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

    is_deep_content = clen > 400
    is_medium_content = clen > 150
    has_data = bool(re.search(r'\d+[.%]?', content))
    has_tech_detail = bool(re.search(r'(transformer|yolo|gpt|llm|api|SDK|python|java|spring|docker|微服务|架构|算法|模型)', content.lower()))
    is_ai_core = bool(re.search(r'(gpt|llm|大模型|openai|deepseek|ai|人工智能|chatgpt)', title.lower()))
    is_biz = bool(re.search(r'(营收|融资|IPO|上市|财报|亿元|投资|订单|销量)', title))
    is_policy = bool(re.search(r'(标准|规划|政策|座谈会|加快|制定|数据局|算力)', title))
    is_tech_hw = bool(re.search(r'(芯片|半导体|激光雷达|传感器|GPU|NPU|Surface|鼠标|触觉|车规)', title))

    # ── Scarcity (0-30) ──
    scarcity = 5.0
    if is_high_quality: scarcity += 5.0
    if is_deep_content: scarcity += 4.0
    elif is_medium_content: scarcity += 2.0
    if high_count >= 3: scarcity += 8.0
    elif high_count >= 1: scarcity += 4.0
    if has_tech_detail: scarcity += 3.0
    if is_ai_core: scarcity += 3.0
    if is_biz: scarcity += 2.0
    if low_count > 0: scarcity -= low_count * 2.0
    scarcity = max(0, min(30, scarcity))

    # ── Impact (0-30) ──
    impact = 5.0
    if is_high_quality: impact += 4.0
    if high_count >= 3: impact += 8.0
    elif high_count >= 1: impact += 4.0
    if is_ai_core: impact += 5.0
    if is_biz: impact += 5.0
    if is_policy: impact += 5.0
    if is_tech_hw: impact += 3.0
    if has_data: impact += 2.0
    if tlen > 10: impact += 1.0
    impact = max(0, min(30, impact))

    # ── Tech Depth (0-20) ──
    tech_depth = 3.0
    if is_deep_content: tech_depth += 4.0
    elif is_medium_content: tech_depth += 2.0
    if has_tech_detail: tech_depth += 4.0
    if has_data: tech_depth += 2.0
    if is_ai_core: tech_depth += 4.0
    if high_count >= 2: tech_depth += 3.0
    if low_count > 0: tech_depth -= low_count * 1.0
    tech_depth = max(0, min(20, tech_depth))

    # ── Timeliness (0-10) ──
    timeliness = 5.0
    if is_high_quality: timeliness += 2.0
    if high_count >= 1: timeliness += 2.0
    timeliness = max(0, min(10, timeliness))

    # ── Preference (0-10) ──
    preference = 3.0
    if is_ai_core: preference += 4.0
    if has_tech_detail: preference += 2.0
    if is_tech_hw: preference += 2.0
    if 'AI' in tags or 'AI' in title: preference += 1.0
    if 'Dev' in tags or 'Dev' in title or 'OpenSource' in tags: preference += 1.0
    if low_count > 0: preference -= low_count * 1.0
    preference = max(0, min(10, preference))

    # ── Credibility (0-10) ──
    credibility = 4.0
    if is_high_quality: credibility += 4.0
    elif is_low_quality: credibility -= 2.0
    if is_deep_content: credibility += 1.0
    if has_data: credibility += 1.0
    credibility = max(0, min(10, credibility))

    # Round
    scarcity = round(scarcity, 1)
    impact = round(impact, 1)
    tech_depth = round(tech_depth, 1)
    timeliness = round(timeliness, 1)
    preference = round(preference, 1)
    credibility = round(credibility, 1)
    total = round(scarcity + impact + tech_depth + timeliness + preference + credibility, 1)
    total = min(total, 100.0)

    # ── Reasoning ──
    reason_parts = []
    if high_count > 0: reason_parts.append(f"高价值关键词×{high_count}")
    if low_count > 0: reason_parts.append(f"低价值关键词×{low_count}")
    if is_high_quality: reason_parts.append("知名来源")
    if is_deep_content: reason_parts.append("深度内容")
    if has_tech_detail: reason_parts.append("含技术细节")
    if has_data: reason_parts.append("含数据")
    if is_ai_core: reason_parts.append("AI核心")
    if is_biz: reason_parts.append("商业")
    if is_policy: reason_parts.append("政策")
    reason_str = ", ".join(reason_parts) if reason_parts else "规则评分(基础)"

    detail_reasons = {
        "scarcity_reason": "独家深度" if is_deep_content and is_high_quality else ("高价值+深度" if high_count >= 3 else "来源优势" if is_high_quality else "普通"),
        "impact_reason": "行业重大" if is_ai_core and is_biz else ("行业影响" if is_biz or is_policy else "产品影响" if is_tech_hw else "一般"),
        "tech_depth_reason": "含技术细节+深度分析" if has_tech_detail and is_deep_content else ("含技术细节" if has_tech_detail else "有分析论证" if is_deep_content else "普通"),
        "timeliness_reason": "近期发布",
        "preference_reason": "AI领域高度匹配" if is_ai_core else ("技术领域匹配" if has_tech_detail else "部分匹配"),
        "credibility_reason": "知名媒体/官方来源" if is_high_quality else ("低质来源" if is_low_quality else "普通来源"),
        "summary": reason_str,
    }

    reasoning = json.dumps({
        "scarcity_reason": detail_reasons["scarcity_reason"],
        "impact_reason": detail_reasons["impact_reason"],
        "tech_depth_reason": detail_reasons["tech_depth_reason"],
        "timeliness_reason": detail_reasons["timeliness_reason"],
        "preference_reason": detail_reasons["preference_reason"],
        "credibility_reason": detail_reasons["credibility_reason"],
        "summary": reason_str,
    }, ensure_ascii=False)

    return {
        "scarcity": scarcity,
        "impact": impact,
        "tech_depth": tech_depth,
        "timeliness": timeliness,
        "preference": preference,
        "credibility": credibility,
        "total": total,
        "reasoning": reasoning,
    }


# ── Find existing records by title and update ──
scored = 0
errors = 0

for item in batch_data:
    item_id = item['id']
    title = item.get('title', '') or ''
    content = item.get('content', '') or ''
    source = item.get('source', '') or ''
    url = item.get('url', '') or ''
    tags = item.get('tags', '') or ''

    # Find by title (unique constraint)
    cur.execute('SELECT id FROM cleaned_intelligence WHERE title = ?', (title,))
    row = cur.fetchone()

    if not row:
        print(f"WARNING: item with title '{title[:50]}' not found in DB, skipping")
        errors += 1
        continue

    clean_id = row[0]

    # Score
    s = ai_six_dimension_score(title, content, source, url, tags)
    importance = round(s["total"] / 100.0, 2)

    try:
        cur.execute("""UPDATE cleaned_intelligence SET
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
        WHERE id = ?""", (
            s["scarcity"], s["impact"], s["tech_depth"],
            s["timeliness"], s["preference"], s["credibility"],
            s["total"], importance,
            s["reasoning"], NOW, clean_id
        ))
        scored += 1
        print(f"  cleaned_id={clean_id:>7} | {title[:45]:45s} | total={s['total']:>5.1f}")
    except Exception as e:
        print(f"Error updating clean_id={clean_id}: {e}")
        errors += 1

conn.commit()
conn.close()

print(f"\nScored: {scored}")
print(f"Errors: {errors}")
print(json.dumps({"batch": 4, "scored": scored}))
