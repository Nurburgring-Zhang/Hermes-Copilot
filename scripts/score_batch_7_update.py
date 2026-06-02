#!/usr/bin/env python3
"""
Score batch 7 — Update existing cleaned_intelligence items with fresh 6-dimension scoring.
Items already exist in cleaned_intelligence — update their AI scores.
"""
import sqlite3
import json
from datetime import datetime

DB_PATH = "/home/administrator/.hermes/intelligence.db"
BATCH_FILE = "/tmp/score_batch_7.json"

# ── Keyword lists ──
HIGH_VALUE_KEYWORDS = [
    "ai", "人工智能", "大模型", "chatgpt", "gpt", "llm", "LLM",
    "芯片", "半导体", "gpu", "GPU", "npu", "NPU",
    "ai agent", "AI agent", "机器人", "自动驾驶",
    "新能源", "华为", "英伟达", "微软",
    "openai", "OpenAI", "Anthropic", "deepseek", "DeepSeek",
    "大语言模型", "深度学习", "transformer", "Transformer",
    "yolo", "YOLO", "训练", "推理", "模型",
]
LOW_VALUE_KEYWORDS = [
    "游戏", "娱乐", "明星", "八卦", "体育",
    "美食", "旅游", "宠物", "电影", "综艺",
    "cosplay", "动漫", "小说", "摄影", "旅行", "游记",
]
HIGH_QUALITY_PATTERNS = [
    "ithome.com", "36kr.com", "huxiu.com", "arxiv.org",
    "github.com", "nature.com", "science.org", "sciencemag.org", "ieee.org",
]
LOW_QUALITY_PATTERNS = ["tieba.baidu.com", "zhidao.baidu.com", "wenda.so.com"]
TECH_BOOST_KEYWORDS = [
    "transformer", "Transformer", "yolo", "YOLO",
    "深度学习", "训练", "推理", "模型", "大语言模型",
    "芯片", "半导体", "GPU", "gpu", "架构",
    "算法", "框架", "神经网络",
]

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

def check_source_quality(source, url):
    if not source and not url:
        return False, False
    source_str = str(source or "").lower()
    url_str = str(url or "").lower()
    for s in ["ithome", "IT之家", "36kr", "36氪", "huxiu", "虎嗅", "arxiv", "github", "GitHub", "nature", "science", "ieee", "IEEE"]:
        if s.lower() in source_str:
            return True, False
    for pat in HIGH_QUALITY_PATTERNS:
        if pat in url_str:
            return True, False
    for s in ["tieba", "zhidao", "wenda"]:
        if s.lower() in source_str:
            return False, True
    for pat in LOW_QUALITY_PATTERNS:
        if pat in url_str:
            return False, True
    return False, False

def calculate_score(title, content, source, url, published_at=None):
    title = title or ""
    content = content or ""
    source = source or ""
    url = url or ""
    title_len = len(title)
    content_len = len(content)
    title_content = f"{title} {content}"
    high_count, high_matched = count_keywords(title_content, HIGH_VALUE_KEYWORDS)
    low_count, low_matched = count_keywords(title_content, LOW_VALUE_KEYWORDS)
    title_short_penalty = -5.0 if title_len < 10 else 0.0
    content_long_bonus = 5.0 if content_len > 500 else 0.0
    is_high_quality, is_low_quality = check_source_quality(source, url)

    is_strong = (high_count >= 3 or (high_count >= 2 and is_high_quality) or 
                 (is_high_quality and content_len > 300 and high_count >= 1) or
                 high_count >= 4 or (high_count >= 1 and content_len > 500 and is_high_quality))

    # Scarcity (0-30)
    scarcity = 8.0
    scarcity += min(high_count * (4.0 if is_strong else 2.0), 18.0 if is_strong else 10.0)
    if content_len > 500: scarcity += 3.0
    elif content_len > 200: scarcity += 1.0
    if is_high_quality: scarcity += 3.0
    scarcity = max(0, min(30, scarcity + low_count * (-1.0)))

    # Impact (0-30)
    impact = 8.0
    if is_high_quality: impact += 6.0
    impact += min(high_count * (3.0 if is_strong else 1.5), 14.0 if is_strong else 6.0)
    if 10 <= title_len <= 60: impact += 2.0
    if low_count > 0: impact -= low_count * 1.5
    impact = max(0, min(30, impact))

    # Tech Depth (0-20)
    tech_depth = 4.0
    tech_count, _ = count_keywords(title_content, TECH_BOOST_KEYWORDS)
    tech_depth += min(tech_count * 1.5, 8.0)
    if content_len > 500: tech_depth += 3.0
    elif content_len > 200: tech_depth += 1.0
    if is_strong: tech_depth += min(high_count * 1.5, 6.0)
    if low_count > 0: tech_depth -= low_count * 0.8
    tech_depth = max(0, min(20, tech_depth))

    # Timeliness (0-10)
    timeliness = 3.0
    if is_high_quality: timeliness += 3.0
    if high_count > 0: timeliness += min(high_count * 1.0, 3.0)
    if low_count > 0: timeliness -= low_count * 0.5
    timeliness = max(0, min(10, timeliness + title_short_penalty * 0.1))

    # Preference (0-10)
    pref = 3.0
    if is_strong: pref += min(high_count * 1.5, 5.0)
    elif high_count > 0: pref += min(high_count * 1.0, 3.0)
    if content_len > 300: pref += 1.0
    if low_count > 0: pref -= low_count * 1.0
    pref = max(0, min(10, pref))

    # Credibility (0-10)
    credibility = 3.0
    if is_high_quality: credibility += 4.0
    elif is_low_quality: credibility -= 3.0
    if content_len > 500: credibility += 1.5
    elif content_len < 80: credibility -= 1.0
    credibility = max(0, min(10, credibility))

    # Apply penalties/bonuses
    if title_short_penalty < 0:
        impact += title_short_penalty * 0.3
        scarcity += title_short_penalty * 0.3
        timeliness += title_short_penalty * 0.2
        tech_depth += title_short_penalty * 0.2
    if content_long_bonus > 0:
        tech_depth += content_long_bonus * 0.3
        scarcity += content_long_bonus * 0.3
        impact += content_long_bonus * 0.2
        credibility += content_long_bonus * 0.2

    # Clamp
    scarcity = round(max(0, min(30, scarcity)), 1)
    impact = round(max(0, min(30, impact)), 1)
    tech_depth = round(max(0, min(20, tech_depth)), 1)
    timeliness = round(max(0, min(10, timeliness)), 1)
    pref = round(max(0, min(10, pref)), 1)
    credibility = round(max(0, min(10, credibility)), 1)
    total = round(min(scarcity + impact + tech_depth + timeliness + pref + credibility, 100.0), 1)

    # Reasoning
    reason_parts = []
    if high_count > 0:
        reason_parts.append(f"高价值关键词×{high_count}(+{high_count*2})")
    if low_count > 0:
        reason_parts.append(f"低价值关键词×{low_count}(-{low_count*2})")
    if is_high_quality:
        reason_parts.append("知名来源(+8)")
    elif is_low_quality:
        reason_parts.append("低质来源(-5)")
    if title_len < 10:
        reason_parts.append(f"标题过短({title_len}字,-5)")
    if content_len > 500:
        reason_parts.append(f"深度内容({content_len}字,+5)")
    if is_strong:
        reason_parts.append("优质内容多维度高分")

    reason_summary = ", ".join(reason_parts) if reason_parts else "规则评分(基础分)"
    if total >= 70: reason_summary = "★★★★★ " + reason_summary
    elif total >= 50: reason_summary = "★★★★ " + reason_summary
    elif total >= 30: reason_summary = "★★★ " + reason_summary
    elif total >= 20: reason_summary = "★★ " + reason_summary

    reasoning = json.dumps({
        "method": "规则引擎评分v4",
        "rule": reason_summary,
        "high_keywords_hit": high_matched[:10],
        "low_keywords_hit": low_matched[:10],
        "high_count": high_count,
        "low_count": low_count,
        "title_len": title_len,
        "content_len": content_len,
        "is_high_quality_source": is_high_quality,
        "is_low_quality_source": is_low_quality,
        "is_strong": is_strong,
    }, ensure_ascii=False)

    return {
        "scarcity": scarcity, "impact": impact, "tech_depth": tech_depth,
        "timeliness": timeliness, "preference": pref, "credibility": credibility,
        "total": total, "reasoning": reasoning,
    }

def main():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    with open(BATCH_FILE, 'r') as f:
        items = json.load(f)

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"Batch 7: Updating {len(items)} items with fresh scores at {now}")

    processed = 0
    errors = 0

    for item in items:
        cleaned_id = item["id"]
        title = item.get("title", "")
        content = item.get("content", "")
        url = item.get("url", "")
        source = item.get("source", "")
        
        try:
            result = calculate_score(title, content, source, url)
            importance_score = round(result["total"] / 100.0, 2)

            # Update cleaned_intelligence
            c.execute("""
                UPDATE cleaned_intelligence
                SET ai_score_scarcity = ?,
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
                result["scarcity"], result["impact"], result["tech_depth"],
                result["timeliness"], result["preference"], result["credibility"],
                result["total"], importance_score, result["reasoning"],
                now, cleaned_id
            ))

            # Update or insert ai_score_queue
            c.execute("SELECT id FROM ai_score_queue WHERE item_id = ?", (cleaned_id,))
            if c.fetchone():
                c.execute("""
                    UPDATE ai_score_queue
                    SET status = 'scored', score_batch = 'batch_7', scored_at = ?
                    WHERE item_id = ?
                """, (now, cleaned_id))
            else:
                c.execute("""
                    INSERT INTO ai_score_queue (item_id, status, score_batch, scored_at)
                    VALUES (?, 'scored', 'batch_7', ?)
                """, (cleaned_id, now))

            processed += 1
            if processed % 10 == 0:
                conn.commit()
                print(f"  Updated {processed}/{len(items)}...")

        except Exception as e:
            errors += 1
            print(f"  ERROR on id={cleaned_id}: {e}")
            conn.rollback()

    conn.commit()

    # Summary
    print(f"\n{'='*60}")
    print(f"📊 Batch 7 Scoring Complete")
    print(f"{'='*60}")
    print(f"  Items in batch:  {len(items)}")
    print(f"  Updated:         {processed}")
    print(f"  Errors:          {errors}")

    # Verify
    c.execute("""
        SELECT id, ai_score_scarcity, ai_score_impact, ai_score_tech_depth,
               ai_score_timeliness, ai_score_preference, ai_score_credibility, ai_score_total
        FROM cleaned_intelligence
        WHERE id IN ({})
    """.format(','.join('?' * len(items))), [i["id"] for i in items])
    rows = c.fetchall()
    scores = [r[7] for r in rows if r[7] is not None]

    print(f"\n  Verified: {len(rows)} items in cleaned_intelligence")
    if scores:
        avg = sum(scores) / len(scores)
        print(f"  Avg score: {avg:.1f}")
        buckets = {"0-19": 0, "20-39": 0, "40-59": 0, "60-79": 0, "80-100": 0}
        for s in scores:
            if s < 20: buckets["0-19"] += 1
            elif s < 40: buckets["20-39"] += 1
            elif s < 60: buckets["40-59"] += 1
            elif s < 80: buckets["60-79"] += 1
            else: buckets["80-100"] += 1
        max_b = max(buckets.values()) or 1
        for k, v in buckets.items():
            bar = "█" * (v * 50 // max_b) if v > 0 else ""
            print(f"    {k}: {v:4d}  {bar}")

    conn.close()
    print(f"\n✅ Done")

    output = {"batch": 7, "scored": processed}
    print(f"\nOUTPUT: {json.dumps(output, ensure_ascii=False)}")

if __name__ == "__main__":
    main()
