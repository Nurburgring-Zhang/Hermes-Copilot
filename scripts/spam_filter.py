#!/usr/bin/env python3
"""
🔍 垃圾内容过滤器 v1.0
对 cleaned_intelligence 的推送候选内容进行过滤。
由推送脚本（hermes_v12_push.py）在推送前调用。

逻辑：
1. 关键词匹配：命中 severity>=5 的关键词 → 直接拦截
2. 来源过滤：命中来源 → 分数封顶
3. 组合评分过滤：匹配多个低质关键词 → 降分
"""
import sqlite3, json, re
from pathlib import Path

HERMES = Path("/home/administrator/.hermes")
DB_PATH = HERMES / "intelligence.db"

def load_filter_rules():
    """加载过滤规则"""
    db = sqlite3.connect(str(DB_PATH))
    
    keywords = db.execute("""
        SELECT keyword, category, severity, match_mode 
        FROM spam_filter_keywords WHERE is_active = 1
        ORDER BY severity DESC
    """).fetchall()
    
    sources = db.execute("""
        SELECT source_pattern, base_score_cap, is_blocked
        FROM spam_filter_sources WHERE is_active = 1
    """).fetchall()
    
    db.close()
    return keywords, sources

def check_spam(title, content, source, platform, keywords, sources):
    """
    检查是否垃圾内容。
    返回: (is_spam: bool, reason: str, score_penalty: int)
    """
    text = (title + " " + (content or "")[:200]).lower()
    score_penalty = 0
    reasons = []
    
    # 1. 关键词检查
    matched_keywords = []
    for kw, cat, sev, mode in keywords:
        kw_lower = kw.lower()
        if kw_lower in text:
            matched_keywords.append((kw, cat, sev))
    
    if matched_keywords:
        max_sev = max(s[2] for s in matched_keywords)
        if max_sev >= 5:
            # 严重度5+直接拦截
            top_kws = [s[0] for s in matched_keywords if s[2] >= 5]
            return True, f"🔴 命中高风险关键词: {top_kws[0]}(+{len(top_kws)}个)", 100
        
        elif max_sev >= 4:
            # 严重度4：大幅度降分
            score_penalty = 40
            reasons.append(f"🟠 命中关键词: {matched_keywords[0][0]}")
        
        elif max_sev >= 3:
            # 严重度3：中度降分
            score_penalty = 20
            reasons.append(f"🟡 命中关键词: {matched_keywords[0][0]}")
        
        elif max_sev >= 2:
            score_penalty = 10
            reasons.append(f"⚪ 命中低质词: {matched_keywords[0][0]}")
        
        # 多个低质词叠加
        if len(matched_keywords) >= 3:
            score_penalty += 15
            reasons.append(f"📛 命中{len(matched_keywords)}个低质词")
    
    # 2. 来源检查
    source_lower = (source or "").lower()
    platform_lower = (platform or "").lower()
    combined = source_lower + " " + platform_lower
    
    for src_pat, cap, blocked in sources:
        pat_lower = src_pat.lower()
        if pat_lower in combined:
            if blocked:
                return True, f"🔴 来源被封锁: {src_pat}", 100
            # 来源封顶不直接拦截，但限制分数
            reasons.append(f"🔒 来源封顶{cap}分: {src_pat}")
            break
    
    is_spam = score_penalty >= 40
    reason = "; ".join(reasons) if reasons else ""
    
    return is_spam, reason, score_penalty

def filter_push_candidates(items):
    """
    过滤推送候选列表。
    items: [{id, title, content, source, platform, score}, ...]
    返回: (filtered_items, blocked_log)
    """
    keywords, sources = load_filter_rules()
    filtered = []
    blocked = []
    
    for item in items:
        title = item.get("title", "") or ""
        content = item.get("content", "") or ""
        source = item.get("source", "") or ""
        platform = item.get("platform", "") or ""
        score = item.get("ai_score_total", 0) or 0
        
        is_spam, reason, penalty = check_spam(title, content, source, platform, keywords, sources)
        
        if is_spam:
            blocked.append({
                "id": item.get("id"),
                "title": title[:60],
                "reason": reason,
                "original_score": score
            })
            continue
        
        # 应用降分
        if penalty > 0:
            new_score = max(score - penalty, 0)
            item["ai_score_total"] = new_score
            item["spam_penalty"] = penalty
            item["spam_reason"] = reason
        
        filtered.append(item)
    
    return filtered, blocked

def log_blocked(items):
    """记录拦截日志"""
    if not items:
        return
    db = sqlite3.connect(str(DB_PATH))
    for item in items:
        db.execute(
            "INSERT INTO spam_filter_log (item_id, title, matched_keyword, matched_source, action) VALUES (?, ?, ?, ?, 'block')",
            (item.get("id"), item.get("title", "")[:60], item.get("reason", ""), item.get("reason", ""))
        )
    db.commit()
    db.close()

if __name__ == "__main__":
    import sys
    # 测试模式
    keywords, sources = load_filter_rules()
    print(f"已加载 {len(keywords)} 条关键词, {len(sources)} 条来源规则")
    
    test_cases = [
        ("我国日均Token调用量飙涨超100000%", "", "ithome", "ithome"),
        ("奶龙搞笑日常", "", "bilibili", "B站"),
        ("缝裤裆年入百万、摆摊月入5万——低门槛暴富神话", "", "toutiao_finance", "头条"),
        ("细思极恐！画的是繁华盛世，实际却是亡国预言！", "", "B站-科技", "B站"),
        ("海信RGB Mini LED显示器UX首发价9999元", "", "ithome", "ithome"),
        ("紫光发布PNM架构，存储带宽30TB/s", "", "ithome", "ithome"),
        ("女子打赏主播1700万父亲企业濒临破产", "", "今日头条", "头条"),
        ("夫妻吵架后约好去离婚，妻子从早上八点半等到十点半", "", "toutiao", "头条"),
    ]
    
    print(f"\n{'='*60}")
    print(f"垃圾过滤测试")
    print(f"{'='*60}")
    for title, content, source, platform in test_cases:
        is_spam, reason, penalty = check_spam(title, content, source, platform, keywords, sources)
        status = "🔴 BLOCK" if is_spam else ("🟡降分" if penalty else "✅ PASS")
        print(f"  {status} | {title[:40]:40s} | {source:15s} | {reason[:30]}")
