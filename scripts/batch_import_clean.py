#!/usr/bin/env python3
"""
批量导入原始数据到清洗管道 (cleaned_intelligence.db)
====================================================
从 intelligence.db raw_intelligence 批量导入近7天数据到 cleaned_intelligence.db
做：偏好匹配、AI评分、来源标记
优先导入高价值平台
"""

import sqlite3
import json
import sys
import re
from datetime import datetime, timedelta
from pathlib import Path

HERMES = Path("/home/administrator/.hermes")
INTELLIGENCE_DB = HERMES / "data" / "intelligence.db"
CLEANED_DB = HERMES / "data" / "cleaned_intelligence.db"

# ===== 用户偏好关键词 (P0/P1/P2 分层) =====
PREFERENCE_KEYWORDS = {
    # P0: 核心兴趣 (权重乘数 2.5)
    "AI": ("core-tech", 2.5), "人工智能": ("core-tech", 2.5), "机器学习": ("core-tech", 2.5),
    "LLM": ("core-tech", 2.5), "大模型": ("core-tech", 2.5), "AI Agent": ("core-tech", 2.5),
    "智能体": ("core-tech", 2.5), "deep learning": ("core-tech", 2.5), "transformer": ("core-tech", 2.5),
    "GPT": ("core-tech", 2.5), "Claude": ("core-tech", 2.5), "OpenAI": ("core-tech", 2.5),
    "Rust": ("dev", 2.5), "TypeScript": ("dev", 2.5), "Python": ("dev", 2.5),
    "开源": ("dev", 2.5), "GitHub": ("dev", 2.5), "开发者": ("dev", 2.5),
    "编程": ("dev", 2.5), "架构": ("dev", 2.5), "代码": ("dev", 2.5),
    "芯片": ("tech", 2.5), "半导体": ("tech", 2.5), "GPU": ("tech", 2.5),
    "新能源": ("ev", 2.5), "自动驾驶": ("ev", 2.5), "EV": ("ev", 2.5),
    "电动汽车": ("ev", 2.5), "新能源汽车": ("ev", 2.5),
    "军事": ("mil", 2.5), "国防": ("mil", 2.5), "武器": ("mil", 2.5),
    "网络安全": ("security", 2.5), "安全": ("security", 2.5), "渗透": ("security", 2.5),
    "地缘政治": ("geo", 2.5), "国际形势": ("geo", 2.5), "全球": ("geo", 2.5),
    # P1: 高兴趣 (权重乘数 1.5)
    "UFC": ("sports", 1.5), "格斗": ("sports", 1.5), "拳击": ("sports", 1.5),
    "美女": ("lifestyle", 1.5), "写真": ("lifestyle", 1.5), "摄影": ("lifestyle", 1.5),
    "电影": ("entertainment", 1.5), "数码": ("digital", 1.5),
    # P2: 一般兴趣 (权重乘数 1.0)
    "经济": ("finance", 1.0), "关税": ("finance", 1.0), "贸易": ("finance", 1.0),
    "航天": ("science", 1.0), "量子": ("science", 1.0), "火箭": ("science", 1.0),
    "医疗": ("health", 1.0), "生物": ("health", 1.0),
}

# 高价值优先导入平台
HIGH_VALUE_PLATFORMS = [
    "hackernews", "sina_tech", "ithome", "arxiv", "github", "freebuf",
    "techmeme", "oschina", "tmtpost", "ifanr", "36kr", "infoq", "zhihu", "toutiao"
]

# 垃圾过滤关键词
TRASH_KEYWORDS = [
    "小说", "修仙", "穿越", "赘婿", "兵王", "末世", "玄幻", "修真",
    "吃播", "ASMR", "vlog", "日常", "挑战", "翻唱", "舞蹈", "COS",
    "二次元", "动漫", "番剧", "鬼畜", "追番", "新番",
    "小姐姐", "小哥哥", "老铁", "666",
    "NBA", "英超", "欧冠", "足球", "电竞", "LOL", "王者荣耀", "原神",
    "吃盐", "酒窝", "打赏", "主播", "胖东来", "起诉", "爆雷",
    "晒背", "养生", "美白", "减肥", "彩礼", "相亲", "结婚",
    "探店", "打卡", "航拍",
]

# 低质量来源（娱乐/社会类，权重降低）
LOW_QUALITY_PLATFORMS = {"weibo", "bilibili", "tieba", "baidu", "kuaishou", "douyin"}


def is_trash(title, content=""):
    """检查是否垃圾内容"""
    if not title:
        return True
    text = (title + " " + (content or "")).lower()
    for kw in TRASH_KEYWORDS:
        if kw.lower() in text:
            return True
    clean_title = re.sub(r'[^\u4e00-\u9fff\w]', '', title)
    if len(clean_title) < 4 and not re.search(r'[A-Za-z]{3,}', title):
        return True
    return False


def match_preferences(title, content):
    """匹配偏好关键词，返回 (preference_tags_json, matched_keywords_json, preference_score)"""
    text = (title + " " + (content or "")).lower()
    matched_tags = set()
    matched_kws = []
    total_score = 0.0
    
    for kw, (cat, multiplier) in PREFERENCE_KEYWORDS.items():
        if kw.lower() in text:
            matched_tags.add(cat)
            matched_kws.append(kw)
            total_score += multiplier * 2.0  # 基础分 * 权重乘数
    
    # P0额外加分
    p0_kw = [kw for kw, (cat, mult) in PREFERENCE_KEYWORDS.items() if mult >= 2.5]
    p0_hits = sum(1 for kw in p0_kw if kw.lower() in text)
    if p0_hits >= 2:
        total_score *= 1.3  # 多个P0命中额外加成
    elif p0_hits >= 1:
        total_score *= 1.1
    
    return json.dumps(list(matched_tags), ensure_ascii=False), json.dumps(matched_kws, ensure_ascii=False), total_score


def ai_score_article(item, preference_score):
    """AI综合评分 0-100，基于内容质量、时效、偏好匹配度、来源"""
    title = item.get('title', '') or ''
    content = item.get('content', '') or ''
    source = item.get('source', '') or ''
    hot_score = item.get('hot_score', 0) or 0
    
    score = 0.0
    
    # 1. 来源质量 (0-25分)
    if source in HIGH_VALUE_PLATFORMS:
        score += 20 + (HIGH_VALUE_PLATFORMS.index(source) / len(HIGH_VALUE_PLATFORMS)) * 5
    elif source in LOW_QUALITY_PLATFORMS:
        score += 5 + min(hot_score / 100, 10) if hot_score else 5
    else:
        score += 10
    
    # 2. 时效性 (0-15分)
    pub_str = item.get('published_at', '') or ''
    if pub_str:
        try:
            for fmt in ['%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S', '%a, %d %b %Y %H:%M:%S']:
                try:
                    pub_dt = datetime.strptime(str(pub_str)[:25], fmt)
                    hours_ago = (datetime.now() - pub_dt).total_seconds() / 3600
                    if hours_ago <= 1:
                        score += 15
                    elif hours_ago <= 6:
                        score += 12
                    elif hours_ago <= 24:
                        score += 8
                    elif hours_ago <= 72:
                        score += 4
                    else:
                        score += 2
                    break
                except:
                    continue
        except:
            score += 5  # 无法解析给基础分
    else:
        score += 5
    
    # 3. 偏好匹配度 (0-40分)
    score += min(preference_score, 40)
    
    # 4. 内容质量信号 (0-20分)
    title_len = len(title)
    content_len = len(content or '')
    if title_len >= 10:
        score += 5
    if content_len >= 200:
        score += 8
    elif content_len >= 100:
        score += 5
    elif content_len >= 50:
        score += 2
    # 热度加成
    if hot_score and hot_score > 0:
        score += min(hot_score / 50, 7)
    
    return min(score, 100)


def batch_import(days=7, max_per_platform=50):
    """批量导入原始数据到清洗管道"""
    print(f"🔍 批量导入: 近{days}天, 每平台上限{max_per_platform}条")
    
    # 连接源库
    src = sqlite3.connect(str(INTELLIGENCE_DB))
    src.row_factory = sqlite3.Row
    
    # 连接目标库
    dst = sqlite3.connect(str(CLEANED_DB))
    dst_c = dst.cursor()
    
    # 获取已有URL避免重复
    existing_urls = set()
    try:
        for r in dst_c.execute("SELECT url FROM cleaned_intelligence WHERE url IS NOT NULL AND url != ''").fetchall():
            existing_urls.add(r[0])
    except:
        pass
    print(f"📋 目标库已有 {len(existing_urls)} 条记录")
    
    cutoff = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d %H:%M:%S')
    
    total_imported = 0
    total_skipped = 0
    
    # 优先导入高价值平台
    for source in HIGH_VALUE_PLATFORMS:
        rows = src.execute("""
            SELECT id, title, content, url, source, category, 
                   hot_score, published_at, collected_at
            FROM raw_intelligence 
            WHERE source = ? AND collected_at >= ?
            ORDER BY collected_at DESC
            LIMIT ?
        """, (source, cutoff, max_per_platform)).fetchall()
        
        if not rows:
            print(f"  {source}: 0条")
            continue
        
        imported = 0
        for row in rows:
            d = dict(row)
            
            # 去重检查
            url = d.get('url', '') or ''
            title = d.get('title', '') or ''
            if url and url in existing_urls:
                total_skipped += 1
                continue
            
            # 垃圾过滤
            if is_trash(title, d.get('content', '')):
                total_skipped += 1
                continue
            
            # 偏好匹配
            pref_tags, matched_kws, pref_score = match_preferences(title, d.get('content', ''))
            
            # AI评分
            ai_score = ai_score_article(d, pref_score)
            
            # 只有有偏好匹配或高评分的才导入
            if pref_score <= 0 and ai_score < 40:
                total_skipped += 1
                continue
            
            # 写入
            try:
                dst_c.execute("""
                    INSERT OR IGNORE INTO cleaned_intelligence 
                    (title, content, summary, url, source, category, score, 
                     preference_tags, matched_keywords, ai_score, 
                     published_at, collected_at, is_pushed)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
                """, (
                    title[:500], (d.get('content', '') or '')[:3000],
                    ((d.get('content', '') or '')[:200]),
                    url, source, d.get('category', '') or '',
                    ai_score, pref_tags, matched_kws, ai_score,
                    d.get('published_at', '') or '',
                    d.get('collected_at', '') or ''
                ))
                if dst_c.rowcount:
                    existing_urls.add(url)
                    imported += 1
                    total_imported += 1
            except Exception as e:
                pass
        
        dst.commit()
        print(f"  {source}: {len(rows)}条原始 → {imported}条导入")
    
    # 其他平台补充导入
    other_sources = src.execute("""
        SELECT DISTINCT source FROM raw_intelligence 
        WHERE collected_at >= ? AND source NOT IN ({})
    """.format(','.join('?' * len(HIGH_VALUE_PLATFORMS))),
        [cutoff] + HIGH_VALUE_PLATFORMS
    ).fetchall()
    
    for (source,) in other_sources:
        if source in LOW_QUALITY_PLATFORMS:
            limit = 10  # 低质量平台少导入
        else:
            limit = 20
        
        rows = src.execute("""
            SELECT id, title, content, url, source, category, 
                   hot_score, published_at, collected_at
            FROM raw_intelligence 
            WHERE source = ? AND collected_at >= ?
            ORDER BY collected_at DESC
            LIMIT ?
        """, (source, cutoff, limit)).fetchall()
        
        if not rows:
            continue
        
        imported = 0
        for row in rows:
            d = dict(row)
            url = d.get('url', '') or ''
            title = d.get('title', '') or ''
            
            if url and url in existing_urls:
                continue
            if is_trash(title, d.get('content', '')):
                continue
            
            pref_tags, matched_kws, pref_score = match_preferences(title, d.get('content', ''))
            ai_score = ai_score_article(d, pref_score)
            
            if pref_score <= 0 and ai_score < 40:
                continue
            
            try:
                dst_c.execute("""
                    INSERT OR IGNORE INTO cleaned_intelligence 
                    (title, content, summary, url, source, category, score, 
                     preference_tags, matched_keywords, ai_score, 
                     published_at, collected_at, is_pushed)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
                """, (
                    title[:500], (d.get('content', '') or '')[:3000],
                    ((d.get('content', '') or '')[:200]),
                    url, source, d.get('category', '') or '',
                    ai_score, pref_tags, matched_kws, ai_score,
                    d.get('published_at', '') or '',
                    d.get('collected_at', '') or ''
                ))
                if dst_c.rowcount:
                    existing_urls.add(url)
                    imported += 1
                    total_imported += 1
            except:
                pass
        
        dst.commit()
        if imported > 0:
            print(f"  {source}: {len(rows)}条原始 → {imported}条导入")
    
    dst.commit()
    dst.close()
    src.close()
    
    print(f"\n{'='*50}")
    print(f"✅ 批量导入完成!")
    print(f"   导入: {total_imported} 条")
    print(f"   跳过(重复/垃圾/低分): {total_skipped} 条")
    print(f"   目标库总计: {total_imported + len(existing_urls)} 条")
    return total_imported


def show_stats():
    """显示导入状态"""
    dst = sqlite3.connect(str(CLEANED_DB))
    c = dst.cursor()
    
    total = c.execute("SELECT COUNT(*) FROM cleaned_intelligence").fetchone()[0]
    with_pref = c.execute("SELECT COUNT(*) FROM cleaned_intelligence WHERE preference_tags != '[]' AND preference_tags != ''").fetchone()[0]
    scored = c.execute("SELECT COUNT(*) FROM cleaned_intelligence WHERE ai_score > 0").fetchone()[0]
    
    print(f"\n📊 cleaned_intelligence.db 统计:")
    print(f"   总计: {total} 条")
    print(f"   有偏好标记: {with_pref} 条")
    print(f"   已评分: {scored} 条")
    
    sources = c.execute("SELECT source, COUNT(*) as cnt FROM cleaned_intelligence GROUP BY source ORDER BY cnt DESC LIMIT 15").fetchall()
    print(f"\n   来源分布:")
    for s, cnt in sources:
        print(f"     {s}: {cnt}条")
    
    dst.close()


if __name__ == "__main__":
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 7
    max_per = int(sys.argv[2]) if len(sys.argv) > 2 else 50
    
    imported = batch_import(days=days, max_per_platform=max_per)
    show_stats()
