#!/usr/bin/env python3
"""
Hermes v12 推送系统 — HTML模板+可点击链接+平台高亮
=======================================================
核心修复:
1. ✅ PushPlus HTML模板 — 微信中可点击的<a>超链接
2. ✅ 平台图标+颜色编码 — 快速识别内容来源
3. ✅ 平台不足168h扩展 — 确保多平台覆盖
4. ✅ 智能降级 — 不足8条降级推送
"""
import sqlite3, json, sys, os, time, re, urllib.request
from datetime import datetime, timedelta, date
from pathlib import Path
from typing import List, Dict, Tuple, Set

HERMES = Path("/home/administrator/.hermes")
DB_PATH = HERMES / "intelligence.db"
ACTIVE_MEMORY_DB = HERMES / "active_memory.db"
PUSH_LOG = HERMES / "logs" / "v12_push.log"
TARGET_COUNT = 25  # 推送25条(减少HTML体积,避免PushPlus 2万字限制)
MIN_PLATFORMS = 6
MAX_PLATFORM_RATIO = 0.3

# ============ P0/P1/P2 分层权重映射 ============
# ============ 格林主人40+方向标签 → P0/P1/P2层级映射 ============
# 方向标签来自extract_tags()的输出(如 "AI|Military|Tech")
# 映射每个可能的标签到P0/P1/P2
TAG_TO_TIER = {
    # ==== P0 核心兴趣 (权重x2.5) ====
    "AI": "P0", "AI_LLM": "P0", "AI_News": "P0",
    "Dev_OpenSource": "P0", "Dev": "P0", "OpenSource": "P0",
    "Mobile_PC": "P0", "IT": "P0", "Consumer_Electronics": "P0",
    "Tech": "P0",
    "Military_Intl": "P0", "Military": "P0",
    "EV": "P0", "Auto": "P0", "Auto_Moto": "P0",
    "Security": "P0",
    "Politics": "P0",
    "Robot": "P0",
    # ==== P1 高兴趣 (权重x1.5) ====
    "Sports_Fight": "P1", "Martial_Arts": "P1",
    "Beauty_Photo": "P1",
    "Movie_Video": "P1", "Movie": "P1",
    "Music": "P1",
    "Art": "P1", "Photography": "P1",
    "Game": "P1",
    "Science": "P1",
    "Space": "P1",
    "Sports": "P1",
    # ==== P2 一般兴趣 (权重x1.0) ====
    "Travel_Food": "P2", "Travel": "P2",
    "History_Culture": "P2", "History": "P2",
    "Fashion": "P2",
    "Entertainment": "P2",
    "Social_News": "P2",
    "Life": "P2",
    "News": "P2",
    "Platform": "P2",
    "Video": "P2",
    "Startup": "P2",
    "Paper": "P2", "ArXiv": "P2",
    "Hot": "P2",
    "General": "P2",  # 无法分类的默认低权重
}

TIER_MULTIPLIER = {"P0": 2.5, "P1": 1.5, "P2": 1.0}

# 兼容旧CATEGORY_MULTIPLIER
CATEGORY_MULTIPLIER = TIER_MULTIPLIER
DEFAULT_MULTIPLIER = 1.0  # 未分类的关键词默认权重

TIER_MARKERS = {
    "P0": "🔥",
    "P1": "⭐",
    "P2": "",
    "DEFAULT": "",
}

def get_tier_for_tag(tag):
    """根据tags中的方向标签返回P0/P1/P2层级"""
    tier = TAG_TO_TIER.get(tag, "P2")
    return tier

def get_tier_marker(tag):
    """获取层级的显示标记"""
    tier = get_tier_for_tag(tag)
    return TIER_MARKERS.get(tier, "")

# 平台图标映射
PLATFORM_ICONS = {
    "ithome": "🏠", "huxiu": "🐯", "toutiao": "📰", "weibo": "🐦",
    "zhihu": "🤔", "baidu": "🔍", "solidot": "🔧", "hackernews": "👾",
    "github": "🐙", "sogou_wechat": "💬", "bilibili": "📺", "douyin": "🎵",
    "devto": "💻", "oschina": "🇨🇳", "36kr": "📊", "cnblogs": "📝",
}

# 平台主色(HTML颜色)
PLATFORM_COLORS = {
    "ithome": "#E74C3C", "huxiu": "#2ECC71", "toutiao": "#3498DB",
    "weibo": "#E74C3C", "zhihu": "#1ABC9C", "baidu": "#2C3E50",
    "solidot": "#7F8C8D", "hackernews": "#FF6600", "github": "#333333",
    "sogou_wechat": "#27AE60", "bilibili": "#00A1D6", "douyin": "#000000",
    "devto": "#0A0A23", "oschina": "#F27227", "36kr": "#FB7236",
    "cnblogs": "#D24D57",
}

# ============ 日志 ============
_LOG_FILE = None
def log(msg):
    global _LOG_FILE
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    try:
        with open(PUSH_LOG, 'a', encoding='utf-8') as f:
            f.write(line + "\n")
    except:
        pass

_USER_KW_CACHE = None
_USER_KW_CACHE_TIME = 0.0

def load_user_keywords():
    global _USER_KW_CACHE, _USER_KW_CACHE_TIME
    now = time.time()
    if _USER_KW_CACHE is not None and now - _USER_KW_CACHE_TIME < 300:
        return _USER_KW_CACHE
    try:
        conn = sqlite3.connect(str(ACTIVE_MEMORY_DB))
        c = conn.cursor()
        rows = c.execute("SELECT keyword, weight, COALESCE(category, '') FROM keyword_weights ORDER BY weight DESC").fetchall()
        conn.close()
        _USER_KW_CACHE = rows
        _USER_KW_CACHE_TIME = now
        print(f"[kw] 已加载 {len(rows)} 条偏好关键词")
        return rows
    except Exception:
        return []

    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with open(PUSH_LOG, 'a', encoding='utf-8') as f:
        f.write(line + "\n")

def get_platform_icon(platform):
    return PLATFORM_ICONS.get(platform, "🌐")

def get_platform_color(platform):
    return PLATFORM_COLORS.get(platform, "#666666")

# ============ 垃圾过滤 + 数据库过滤词 ============
# 从spam_filter_keywords表加载额外过滤词
_SPAM_KEYWORDS_CACHE = None

def _load_spam_keywords():
    global _SPAM_KEYWORDS_CACHE
    if _SPAM_KEYWORDS_CACHE is not None:
        return _SPAM_KEYWORDS_CACHE
    try:
        db = sqlite3.connect(str(DB_PATH))
        rows = db.execute("""
            SELECT keyword, severity FROM spam_filter_keywords 
            WHERE is_active = 1 AND severity >= 3
        """).fetchall()
        db.close()
        _SPAM_KEYWORDS_CACHE = rows
        return rows
    except Exception:
        return []

TRASH_KEYWORDS_HARD = {
    # 社会娱乐/低俗标题党
    "目瑙纵歌", "播放突破", "爆火", "全网爆火", "火到", "爆红",
    # 网文/小说
    "小说", "修仙", "穿越", "赘婿", "兵王", "末世", "末世.", "热浪全球",
    "诡秘", "玄幻", "修真", "斗罗", "吞噬星空", "凡人修仙",
    # 低俗社会
    "吃盐", "雨伞羞耻", "酒窝", "黄灿灿", "活塞", "魔术",
    "打赏", "主播", "胖东来", "起诉", "爆雷",
    "晒背", "养生", "美白", "减肥", "彩礼", "相亲", "结婚",
    "吃播", "ASMR", "vlog", "日常", "挑战", "翻唱", "舞蹈", "COS",
    "二次元", "动漫", "番剧", "鬼畜", "追番", "新番",
    "小姐姐", "小哥哥", "老铁", "666", "双击", "点赞",
    "监控记录", "监控拍到", "不敢相信", "难以置信",
    # 体育(非格林主人偏好)
    "抢七", "NBA", "英超", "欧冠", "足球", "电竞", "LOL",
    "吃鸡", "王者荣耀", "原神",
    # 恐怖/猎奇
    "食人魔", "十八楼", "恐怖故事",
    # 低质社交内容
    "我真的好爱", "我爱吃面", "安宁大厦", "王处",
    "打工人", "打工牛", "泡面火腿",
    "手机点单", "举报抽烟",
    "搓了个短片",  # 王珞丹用AI搓了个短片 → 不够有价值
}
BILIBILI_TRASH_PATTERNS = [
    r"代号.*首曝", r"[Pp]\d+", r"戴上耳机", r"多巴胺",
    r"定格动画", r"端水.*技巧", r"反向旅行",
    r"99%.*不知道", r"一集上头", r"诡异", r"失踪", r"犯罪",
    r"完美犯罪", r"名场面", r"释放.*多巴胺", r"别唱那歌",
    r"扭胯", r"眼.*色.*游戏", r"天打雷劈", r"思白发", r"好心人",
]

def is_trash(title, content="", item=None):
    if not title:
        return True
    text = (title + " " + (content or "")).lower()
    # === 宽松过滤：对于已被AI评分≥50的数据，只拦截硬垃圾 ===
    item_score = float(item.get('ai_score_total', 0) or 0) if item else 0
    
    # AI评分高(≥50)的内容：只拦截最严重的垃圾
    if item_score >= 50:
        HARD_TRASH = {"目瑙纵歌", "小说", "修仙", "穿越", "赘婿", "兵王", "末世",
                      "诡秘", "玄幻", "斗罗", "食人魔", "打赏"}
        for kw in HARD_TRASH:
            if kw.lower() in text:
                return True
        return False  # 高分内容直接放行
    
    # 原过滤逻辑（仅对低分内容严格执行）
    for kw in TRASH_KEYWORDS_HARD:
        if kw.lower() in text:
            return True
    # 数据库spam_filter_keywords过滤(从spam_filter表加载)
    for kw, sev in _load_spam_keywords():
        if kw.lower() in text:
            # 写入过滤日志
            try:
                sdb = sqlite3.connect(str(DB_PATH))
                item_id = item.get('id', 0) if item else 0
                sdb.execute(
                    "INSERT OR IGNORE INTO spam_filter_log (item_id, title, matched_keyword, action, created_at) VALUES (?, ?, ?, 'block', datetime('now'))",
                    (item_id, title[:60], kw)
                )
                sdb.commit()
                sdb.close()
            except:
                pass
            return True
    for pat in BILIBILI_TRASH_PATTERNS:
        if re.search(pat, title):
            return True
    clean_title = re.sub(r'[^\u4e00-\u9fff]', '', title)
    if len(clean_title) < 4:
        return True
    if title.count('!') + title.count('!') + title.count('?') + title.count('?') >= 4:
        return True
    # v2增强:不完整标题
    stripped = title.strip()
    if stripped.startswith("就在刚刚"):
        return True
    if stripped.endswith("刚刚") or stripped.endswith("刚刚,") or stripped.endswith("刚刚,"):
        return True
    # 政治套话/空洞标题
    political_vacuous = ["总书记对", "殷切期望", "重要指示", "重要讲话", "深入学习贯彻", "凝心聚力",
                         "看中国", "中国答卷"]
    for kw in political_vacuous:
        if kw in title:
            return True
    # 社会家庭狗血
    social_garbage = ["婚前", "查出", "乙肝", "父母让分手", "彩礼", "乞丐", "走红",
                      "陪伴", "暗藏", "色情"]
    for kw in social_garbage:
        if kw in title:
            return True
    # 体育类标题自动过滤(非格林主人偏好)
    sports_patterns = [r"\d+比\d+", r"绝杀", r"蓉城", r"铁人"]
    for pat in sports_patterns:
        if re.search(pat, title):
            return True
    # 低质vlog/景区/探店
    low_quality = ["景区", "探店", "打卡", "航拍", "延时摄影", "主副驾", "高速上", "驾车"]
    for kw in low_quality:
        if kw in text:
            return True
    return False

# ============ 核心排序 ============
def score_quality(item):
    """偏好评分 — 整合AI评分 + tags方向标签 + 关键词匹配 + 时间衰减"""
    ai_score = float(item.get('ai_score_total', 0) or 0)
    personal_match = float(item.get('personal_match_score', 0) or 0)
    text = ((item.get('title', '') or '') + ' ' + (item.get('content', '') or '')).lower()
    
    # 时间衰减因子：published_at超过7天扣分
    time_decay = 1.0
    pub_str = item.get('published_at', '') or ''
    if pub_str:
        try:
            from datetime import datetime
            # 尝试解析时间
            pub_time = None
            for fmt in ['%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S', '%a, %d %b %Y %H:%M:%S']:
                try:
                    pub_time = datetime.strptime(str(pub_str)[:25], fmt)
                    break
                except:
                    continue
            if pub_time:
                days_old = (datetime.now() - pub_time).days
                if days_old > 14:
                    time_decay = max(0.1, 1.0 - (days_old - 7) * 0.05)
        except:
            pass
    elif not pub_str:
        # published_at为空的数据降低权重
        time_decay = 0.7
    
    # 第一部分：Tags方向标签匹配（新！）
    tags_str = item.get('tags', '') or ''
    tags = [t.strip() for t in tags_str.split('|') if t.strip()]
    tag_bonus = 0.0
    matched_tags = []
    tag_tiers = set()
    
    # AI评分可用的内容方向分权重更高，未评分的内容方向分打折
    ai_available = ai_score > 0
    tag_weight = 1.0 if ai_available else 0.3  # 未评分内容方向分只给30%
    
    for tag in tags:
        tier = get_tier_for_tag(tag)
        mult = TIER_MULTIPLIER.get(tier, 1.0)
        if tier == "P0":
            # P0核心方向：+20分
            tag_bonus += 20.0 * mult * tag_weight
            matched_tags.append(tag)
            tag_tiers.add(tier)
        elif tier == "P1":
            # P1方向：+12分
            tag_bonus += 12.0 * mult * tag_weight
            matched_tags.append(tag)
            tag_tiers.add(tier)
        elif tag != "General" and tag != "News":
            # 有具体方向(非General/News)：+5分
            tag_bonus += 5.0 * mult * tag_weight
            matched_tags.append(tag)
            tag_tiers.add(tier)
    
    # 第二部分：关键词匹配（原有逻辑增强）
    kw_rows = load_user_keywords()
    kw_bonus = 0.0
    matched_kws = []
    for kw, weight, cat in kw_rows:
        if kw.lower() in text:
            # 用tags的tier来决定关键词权重而不是category
            kw_bonus += weight * 2.0
    
    # 综合评分 = (AI评分 + tags方向分 + 关键词分 + 偏好分) × 时间衰减
    total = (ai_score * 0.4 + tag_bonus * 0.25 + kw_bonus * 0.25 + personal_match * 0.1) * time_decay
    
    # P0内容加分（有AI评分才给大加成）
    if "P0" in tag_tiers and ai_available:
        total += 20.0
    elif "P1" in tag_tiers and ai_available:
        total += 10.0
    
    # AI高评分加成
    if ai_score >= 60:
        total += 10.0
    
    # 低分过滤
    MIN_PREF_SCORE = 10.0
    if total < MIN_PREF_SCORE and not matched_tags and not matched_kws:
        return 0.0, 0
    
    # 调试输出
    tag_str = '|'.join(matched_tags[:3]) if matched_tags else '无标签'
    kw_str = f'{len(matched_kws)}个关键词' if matched_kws else '无关键词'
    tier_str = ''.join(TIER_MARKERS.get(t, '') for t in sorted(tag_tiers, reverse=True))
    print(f"  🎯 [{total:7.1f}] 标签:{tag_str} | {kw_str} {tier_str}| ai={ai_score:.0f}")
    
    item['_matched_tiers'] = tag_tiers
    return total, len(matched_tags) + len(matched_kws)

# ============ 候选获取(按平台均匀取) ============
def is_recent_published(pub_str, max_days=7):
    """判断published_at是否在max_days天内"""
    if not pub_str:
        return None  # 未知，不拦截但标记
    import re
    # timeConvert(unix_timestamp)
    m = re.search(r"timeConvert\('(\d+)'\)", str(pub_str))
    if m:
        dt = datetime.fromtimestamp(int(m.group(1)))
        return (datetime.now() - dt).days <= max_days
    # ISO格式 2026-05-13 12:00:00
    for fmt in ['%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S', '%a, %d %b %Y %H:%M:%S']:
        try:
            dt = datetime.strptime(str(pub_str)[:25], fmt)
            return (datetime.now() - dt).days <= max_days
        except Exception:
            continue
    return None  # 无法解析

def get_candidates_balanced():
    """从cleaned_intelligence获取推送候选 — 优先取带方向标签的数据"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    c.execute("PRAGMA table_info(cleaned_intelligence)")
    cols = {r[1] for r in c.fetchall()}
    has_platform = 'platform' in cols
    has_cleaned_at = 'cleaned_at' in cols
    has_tags = 'tags' in cols
    
    candidates = []
    
    # 优先策略：取最近3天、有方向标签(非General)、高价值的数据
    cutoff = (datetime.now() - timedelta(hours=72)).isoformat()
    push_cutoff = (datetime.now() - timedelta(hours=72)).isoformat()
    
    # 获取72h内已推送的cleaned_id集合（源头排除，不在代码层面二次过滤）
    pushed_ids = set()
    try:
        pr = conn.execute("SELECT DISTINCT cleaned_id FROM push_records WHERE push_time >= ?", (push_cutoff,)).fetchall()
        pushed_ids = {r[0] for r in pr if r[0]}
        log(f"已排除 {len(pushed_ids)} 条72h内已推送记录")
    except:
        pass
    
    if has_tags:
        # Step 1: 优先取P0/P1方向标签 + 高价值（AI评分≥15或重要性≥15）+ 未推送
        log("📡 方向标签优先模式: 取P0/P1方向数据")
        if has_platform and has_cleaned_at:
            c.execute("""
                SELECT id,title,content,url,platform,source,importance_score,ai_score_total,
                       cleaned_at,category,personal_match_score,published_at,tags
                FROM cleaned_intelligence 
                WHERE collected_at >= ? 
                  AND id NOT IN (SELECT DISTINCT cleaned_id FROM push_records WHERE push_time >= ?)
                  AND (
                    (COALESCE(ai_score_total,0) >= 15 OR COALESCE(importance_score,0) >= 15)
                    AND tags IS NOT NULL AND tags != '' AND tags != 'General'
                    AND (tags LIKE '%AI%' OR tags LIKE '%Military%' OR tags LIKE '%Tech%' 
                         OR tags LIKE '%Dev%' OR tags LIKE '%EV%' OR tags LIKE '%Auto%'
                         OR tags LIKE '%Security%' OR tags LIKE '%Sports_Fight%'
                         OR tags LIKE '%Beauty_Photo%' OR tags LIKE '%Space%'
                         OR tags LIKE '%Science%' OR tags LIKE '%History%'
                         OR tags LIKE '%Movie%' OR tags LIKE '%Music%'
                         OR tags LIKE '%Travel%' OR tags LIKE '%Game%'
                         OR tags LIKE '%Photo%' OR tags LIKE '%Camera%'
                         OR tags LIKE '%Fight%' OR tags LIKE '%MMA%'
                         OR tags LIKE '%Fengniao%' OR tags LIKE '%Travel%'
                         OR tags LIKE '%Semi%' OR tags LIKE '%Chip%')
                    OR
                    (COALESCE(importance_score,0) >= 50 OR COALESCE(personal_match_score,0) >= 10)
                  )
                ORDER BY ai_score_total DESC, importance_score DESC LIMIT 300
            """, (cutoff, push_cutoff))
        else:
            c.execute("""
                SELECT id,title,content,summary,url,source,category,score,preference_tags,
                       matched_keywords,ai_score,published_at,collected_at,tags
                FROM cleaned_intelligence 
                WHERE is_pushed=0 AND score>=35 AND collected_at>=?
                  AND tags IS NOT NULL AND tags != '' AND tags != 'General'
                  AND (tags LIKE '%AI%' OR tags LIKE '%Military%' OR tags LIKE '%Tech%')
                ORDER BY score DESC LIMIT 200
            """, (cutoff,))
        
        for row in c.fetchall():
            d = dict(row)
            if not has_platform or not has_cleaned_at:
                d['platform'] = d.get('source', 'unknown')
                d['ai_score_total'] = d.get('score', 0)
                d['importance_score'] = d.get('score', 0)
                d['personal_match_score'] = d.get('score', 0) * 0.5
                d['cleaned_at'] = d.get('collected_at', '')
            # SQL层面已排除，但作为二次保险
            if d.get('id') in pushed_ids:
                continue
            candidates.append(d)
        
        log(f"P0/P1方向候选: {len(candidates)}条")
    
    # Step 2: 如果不够80条，放宽到所有有标签的数据
    if len(candidates) < 80:
        log(f"候选不足80条({len(candidates)}), 放宽取有标签+高分的")
        if has_platform and has_cleaned_at:
            c.execute("""
                SELECT id,title,content,url,platform,source,importance_score,ai_score_total,
                       cleaned_at,category,personal_match_score,published_at,tags
                FROM cleaned_intelligence 
                WHERE collected_at >= ? AND (COALESCE(ai_score_total,0) >= 10 OR COALESCE(importance_score,0) >= 10)
                  AND tags IS NOT NULL AND tags != '' AND tags != 'General'
                  AND id NOT IN (SELECT DISTINCT cleaned_id FROM push_records WHERE push_time >= ?)
                ORDER BY ai_score_total DESC LIMIT 500
            """, (cutoff, push_cutoff))
        else:
            c.execute("""
                SELECT id,title,content,summary,url,source,category,score,preference_tags,
                       matched_keywords,ai_score,published_at,collected_at,tags
                FROM cleaned_intelligence 
                WHERE is_pushed=0 AND score>=20 AND collected_at>=?
                  AND tags IS NOT NULL AND tags != '' AND tags != 'General'
                ORDER BY score DESC LIMIT 300
            """, (cutoff,))
        
        existing_urls = {c2.get('url') for c2 in candidates}
        for row in c.fetchall():
            d = dict(row)
            if d.get('url') not in existing_urls:
                if not has_platform or not has_cleaned_at:
                    d['platform'] = d.get('source', 'unknown')
                    d['ai_score_total'] = d.get('score', 0)
                    d['importance_score'] = d.get('score', 0)
                    d['personal_match_score'] = d.get('score', 0) * 0.5
                    d['cleaned_at'] = d.get('collected_at', '')
                candidates.append(d)
                existing_urls.add(d.get('url'))
        
        log(f"放宽后候选: {len(candidates)}条")
    
    # Step 3: 如果还不够120条，补充General数据
    if len(candidates) < 120:
        log(f"候选不足120条({len(candidates)}), 补充带标签的低分+General数据")
        if has_platform and has_cleaned_at:
            # 补充低分但有标签的数据
            c.execute("""
                SELECT id,title,content,url,platform,source,importance_score,ai_score_total,
                       cleaned_at,category,personal_match_score,published_at,tags
                FROM cleaned_intelligence 
                WHERE collected_at >= ? AND ai_score_total < 15
                  AND tags IS NOT NULL AND tags != '' AND tags != 'General'
                  AND id NOT IN (SELECT DISTINCT cleaned_id FROM push_records WHERE push_time >= ?)
                ORDER BY collected_at DESC LIMIT 150
            """, (cutoff, push_cutoff))
            existing_urls = {c2.get('url') for c2 in candidates}
            for row in c.fetchall():
                d = dict(row)
                if d.get('url') not in existing_urls:
                    existing_urls.add(d.get('url'))
                    candidates.append(d)
            
            # 补充General高质数据
            c.execute("""
                SELECT id,title,content,url,platform,source,importance_score,ai_score_total,
                       cleaned_at,category,personal_match_score,published_at,tags
                FROM cleaned_intelligence 
                WHERE collected_at >= ? AND (COALESCE(ai_score_total,0) >= 15 OR COALESCE(importance_score,0) >= 15)
                  AND (tags IS NULL OR tags = '' OR tags = 'General')
                  AND id NOT IN (SELECT DISTINCT cleaned_id FROM push_records WHERE push_time >= ?)
                ORDER BY ai_score_total DESC LIMIT 100
            """, (cutoff, push_cutoff))
        else:
            c.execute("""
                SELECT id,title,content,summary,url,source,category,score,preference_tags,
                       matched_keywords,ai_score,published_at,collected_at,tags
                FROM cleaned_intelligence 
                WHERE is_pushed=0 AND score>=30 AND collected_at>=?
                  AND (tags IS NULL OR tags = '' OR tags = 'General')
                ORDER BY score DESC LIMIT 100
            """, (cutoff,))
        
        existing_urls = {c2.get('url') for c2 in candidates}
        for row in c.fetchall():
            d = dict(row)
            if d.get('url') not in existing_urls:
                if not has_platform or not has_cleaned_at:
                    d['platform'] = d.get('source', 'unknown')
                    d['ai_score_total'] = d.get('score', 0)
                    d['importance_score'] = d.get('score', 0)
                    d['personal_match_score'] = d.get('score', 0) * 0.5
                    d['cleaned_at'] = d.get('collected_at', '')
                candidates.append(d)
                existing_urls.add(d.get('url'))
        
        log(f"补充后候选: {len(candidates)}条")
    
    conn.close()
    log(f"总候选: {len(candidates)}条, {len(set(r.get('platform','?') for r in candidates))}个平台")
    return candidates

# ============ 多样性强制 ============
def enforce_diversity(items, target_count):
    platform_groups = {}
    for item in items:
        p = item.get('platform', 'unknown')
        if p not in platform_groups:
            platform_groups[p] = []
        platform_groups[p].append(item)
    for p in platform_groups:
        platform_groups[p].sort(key=lambda x: x.get('_score', 0), reverse=True)
    max_per = max(1, int(target_count * MAX_PLATFORM_RATIO))
    log(f"平台{len(platform_groups)}个, 每平台上限{max_per}条")
    
    selected = []
    platform_idx = {p: 0 for p in platform_groups}
    platform_sel = {p: 0 for p in platform_groups}
    for p in sorted(platform_groups.keys()):
        if platform_groups[p]:
            selected.append(platform_groups[p][0])
            platform_sel[p] += 1
            platform_idx[p] = 1
    remaining = target_count - len(selected)
    while remaining > 0:
        added = False
        for p in sorted(platform_groups.keys(), key=lambda x: -len(platform_groups[x])):
            idx = platform_idx[p]
            if idx < len(platform_groups[p]) and platform_sel[p] < max_per:
                selected.append(platform_groups[p][idx])
                platform_sel[p] += 1
                platform_idx[p] = idx + 1
                remaining -= 1
                added = True
                if remaining <= 0: break
        if not added:
            break
    final_platforms = set(item.get('platform', '?') for item in selected)
    log(f"多样性后: {len(final_platforms)}个平台, {len(selected)}条")
    selected.sort(key=lambda x: x.get('_score', 0), reverse=True)
    return selected

# ============ 消息构建 — HTML模板(链接可点击) ============
def build_html_message(items, push_time):
    """构建HTML推送消息,每条带<a>超链接,平台用颜色高亮"""
    platforms = {}
    for item in items:
        p = item.get('platform', 'unknown')
        platforms[p] = platforms.get(p, 0) + 1
    
    plat_items = []
    for p, c in sorted(platforms.items(), key=lambda x: -x[1]):
        icon = get_platform_icon(p)
        color = get_platform_color(p)
        plat_items.append(f'<span style="color:{color};font-weight:bold">{icon}{p}:{c}</span>')
    plat_html = ' | '.join(plat_items)
    
    kw_rows = load_user_keywords()
    
    # 构建HTML
    html_parts = [
        '<div style="font-size:14px;line-height:1.6;color:#333;font-family:-apple-system,BlinkMacSystemFont,sans-serif">',
        f'<div style="background:linear-gradient(135deg,#667eea,#764ba2);color:white;padding:12px 16px;border-radius:10px;margin-bottom:12px">',
        f'<h2 style="margin:0;font-size:16px">📊 Hermes 情报 {push_time}</h2>',
        f'<div style="font-size:12px;margin-top:4px;opacity:0.9">{len(items)}条 | {len(platforms)}平台</div>',
        '</div>',
        f'<div style="font-size:12px;color:#666;margin-bottom:10px">{plat_html}</div>',
    ]
    
    for i, item in enumerate(items, 1):
        title = (item.get('title', '') or '').strip()
        if len(title) > 65:
            title = title[:62] + "..."
        platform = item.get('platform', '?')
        score = item.get('ai_score_total', 0) or 0
        url = item.get('url', '') or ''
        
        # 偏好命中标记 — 使用分级权重逻辑
        text_lower = title.lower()
        matched_tiers = set()
        # 用tags字段推导层级，不再用关键词-category映射
        item_tags = item.get('tags', '') or ''
        for t in item_tags.split('|'):
            if t.strip():
                tier = get_tier_for_tag(t.strip())
                matched_tiers.add(tier)
        # 从item中获取已计算的tiers（如果有）
        item_tiers = item.get('_matched_tiers', None)
        if item_tiers:
            matched_tiers = item_tiers
        tier_markers = ''.join(TIER_MARKERS.get(t, '') for t in sorted(matched_tiers, reverse=True))
        marker = f' {tier_markers}' if tier_markers else (' 🎯' if sum(1 for kw, w, _ in kw_rows if kw.lower() in text_lower[:150]) >= 2 else '')
        
        icon = get_platform_icon(platform)
        color = get_platform_color(platform)
        
        # 有URL就用超链接,没有就用纯文本
        if url and url.startswith('http'):
            # 转义URL中的&为&amp;避免HTML验证错误
            safe_url = url.replace('&', '&amp;')
            title_html = f'<a href="{safe_url}" style="color:#2c3e50;text-decoration:none;font-weight:500" target="_blank">{title}</a>{marker}'
        else:
            title_html = f'<span style="color:#2c3e50;font-weight:500">{title}</span>{marker}'
        
        html_parts.append(
            f'<div style="padding:8px 12px;margin:4px 0;background:#f8f9fa;border-radius:8px;border-left:3px solid {color}">'
            f'<div style="font-size:13px">{i}. {title_html}</div>'
            f'<div style="font-size:11px;color:#888;margin-top:3px">'
            f'<span style="color:{color}">{icon}{platform}</span>'
            f' | ⭐{score:.0f}'
            f'</div>'
            f'</div>'
        )
    
    html_parts.extend([
        '<div style="font-size:11px;color:#999;text-align:center;margin-top:12px;padding-top:8px;border-top:1px solid #eee">',
        f'🤖 v12 | {len(items)}条/{len(platforms)}平台 | {push_time}',
        '</div>',
        '</div>'
    ])
    
    return '\n'.join(html_parts)

# ============ 推送执行(HTML模板) ============
def get_pushplus_token():
    # 优先从config.yaml读取完整token(唯一可靠源)
    try:
        import yaml
        with open(HERMES / "config.yaml") as f:
            config = yaml.safe_load(f)
        token = config.get("pushplus", {}).get("token", "")
        if token and len(token) >= 30:
            return token
    except:
        pass
    # 后备:从.env读取(注意.env中token可能被截断)
    env_path = HERMES / ".env"
    if env_path.exists():
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line.startswith("PUSHPLUS_TOKEN="):
                    token = line.split("=", 1)[1]
                    if token and "..." not in token and len(token) >= 30:
                        return token
    return ""

def push_wechat(title, html_content):
    token = get_pushplus_token()
    if not token:
        return {"code": -1, "msg": "无PushPlus token"}
    
    # 检查HTML长度，超过2万字降级为纯文本
    if len(html_content) > 18000:
        log("  ⚠️ HTML超长({}字)，截断至50条标题降级推送".format(len(html_content)))
        # 只保留标题列表
        lines = html_content.split('\n')
        truncated = []
        for line in lines:
            if '<a href=' in line:
                truncated.append(line)
            if len(truncated) >= 30:
                break
        html_content = '<div style="font-size:14px;line-height:1.6">' + ''.join(truncated) + '</div>'
    
    data = json.dumps({
        "token": token,
        "title": title,
        "content": html_content,
        "template": "html",
    }).encode()
    
    max_retries = 2
    last_error = None
    for attempt in range(1, max_retries + 1):
        try:
            req = urllib.request.Request(
                "https://www.pushplus.plus/send",
                data=data,
                headers={"Content-Type": "application/json"}
            )
            resp = urllib.request.urlopen(req, timeout=15)
            result = json.loads(resp.read().decode())
            if result.get("code") == 200:
                return result
            last_error = result.get("msg", "未知错误")
            if attempt < max_retries:
                log(f"  ⚠️ 推送失败({last_error})，第{attempt+1}次重试...")
                time.sleep(2)
        except Exception as e:
            last_error = str(e)
            if attempt < max_retries:
                log(f"  ⚠️ 推送异常({e})，第{attempt+1}次重试...")
                time.sleep(2)
    
    return {"code": -1, "msg": str(last_error)}

def record_pushed(items, push_levels=None):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    now = datetime.now().isoformat()
    saved = 0
    for i, item in enumerate(items):
        try:
            title = (item.get('title', '') or '')[:255]
            # 检查是否已记录过（去重：72h窗口，防止跨天重复推送）
            existing = c.execute(
                "SELECT id FROM push_records WHERE cleaned_id=? AND push_time >= ?",
                (item.get('id', 0), (datetime.now() - timedelta(hours=72)).isoformat())
            ).fetchone()
            if existing:
                continue
            level = (push_levels[i] if push_levels and i < len(push_levels) else 
                     max(3, min(9, int(float(item.get('_score', 0)) / 10))) )
            c.execute("""
                INSERT INTO push_records (cleaned_id, title, content, url, source, platform, 
                                          push_level, push_channel, push_status, push_time, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                item.get('id', 0),
                (item.get('title', '') or '')[:255],
                (item.get('content', '') or '')[:500],
                item.get('url', '') or '',
                item.get('source', '') or '',
                item.get('platform', '') or '',
                level, 'wechat', 'success', now, now
            ))
        except Exception as e:
            log(f"记录失败: {e}")
    conn.commit()
    conn.close()
    log(f"已记录 {len(items)} 条推送历史")

def is_chinese(text):
    if not text:
        return False
    chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', text))
    return chinese_chars > len(text) * 0.1

# ============ 主流程 ============
def push_v12():
    start = time.time()
    log("=" * 50)
    log("Hermes v12 推送启动 — HTML模板+可点击链接")
    log("=" * 50)
    
    # 1. 已推送去重(72小时窗口 — 防止跨天重复推送)
    already_pushed = set()      # 标题
    already_pushed_ids = set()  # cleaned_id
    try:
        conn = sqlite3.connect(DB_PATH)
        cutoff = (datetime.now() - timedelta(hours=72)).isoformat()
        rows = conn.execute("SELECT DISTINCT title, cleaned_id FROM push_records WHERE push_time >= ?", (cutoff,)).fetchall()
        for r in rows:
            if r[0]:
                already_pushed.add(r[0])
            if r[1]:
                already_pushed_ids.add(r[1])
        conn.close()
        log(f"已加载 {len(already_pushed)} 条最近72小时推送记录(标题), {len(already_pushed_ids)} 个cleaned_id")
    except Exception as e:
        log(f"加载推送记录失败: {e}")
    
    # 2. 候选
    candidates = get_candidates_balanced()
    if not candidates:
        log("❌ 无候选数据")
        return
    log(f"候选池: {len(candidates)}条, {len(set(r['platform'] for r in candidates))}个平台")
    
    # 3. 偏好评分
    log("🔍 偏好评分排序...")
    scored = []
    for item in candidates:
        score_val, kw_count = score_quality(item)
        item['_score'] = score_val
        if score_val > 0:
            scored.append(item)
    log(f"偏好过滤(0分): {len(candidates)} → {len(scored)}条")
    if not scored:
        log("❌ 无偏好匹配内容")
        return
    scored.sort(key=lambda x: x['_score'], reverse=True)
    
    # 4. 垃圾过滤
    before = len(scored)
    scored = [item for item in scored if not is_trash(item.get('title', ''), item.get('content', ''), item)]
    log(f"垃圾过滤: {before} → {len(scored)}条")
    
    # 4.5 时效性过滤：丢弃发布时间超过14天和无时间的老数据
    before = len(scored)
    time_filtered = []
    for item in scored:
        pub_str = item.get('published_at', '') or ''
        title = item.get('title', '') or ''
        ai_score = float(item.get('ai_score_total', 0) or 0)
        
        # 高AI评分(>=80)的内容放宽时效性限制（但不超过30天）
        if ai_score >= 80:
            # 检查是否还是太老（30天以上的即使高分也过滤）
            if pub_str:
                try:
                    pub_time = None
                    for fmt in ['%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S', '%a, %d %b %Y %H:%M:%S']:
                        try:
                            pub_time = datetime.strptime(str(pub_str)[:25], fmt)
                            break
                        except:
                            continue
                    if pub_time:
                        days_old = (datetime.now() - pub_time).days
                        if days_old > 30:
                            continue  # 30天以上即使高分也不推
                except:
                    pass
            time_filtered.append(item)
            continue
        
        if not pub_str:
            # published_at为空 → 只保留AI评分>=50或collected_at在24小时内的
            collected = item.get('collected_at', '') or ''
            if ai_score >= 50:
                time_filtered.append(item)
            elif collected and collected >= (datetime.now() - timedelta(hours=24)).isoformat():
                time_filtered.append(item)
            # 否则丢弃
            continue
        
        # 解析时间判断是否超过14天
        try:
            pub_time = None
            for fmt in ['%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S', '%a, %d %b %Y %H:%M:%S']:
                try:
                    pub_time = datetime.strptime(str(pub_str)[:25], fmt)
                    break
                except:
                    continue
            if pub_time:
                days_old = (datetime.now() - pub_time).days
                if days_old > 14 and ai_score < 80:
                    # 超过14天且AI评分<80 → 丢弃
                    continue
        except:
            pass
        
        time_filtered.append(item)
    
    scored = time_filtered
    log(f"时效性过滤: {before} → {len(scored)}条")
    
    # 5. 已推送排除（标题 + cleaned_id 双重去重）
    before = len(scored)
    scored = [item for item in scored if 
              (item.get('title', '') or '').strip() not in already_pushed 
              and item.get('id', 0) not in already_pushed_ids]
    log(f"已推送排除: {before} → {len(scored)}条")
    
    # 6. 标题去重
    seen_titles = set()
    deduped = []
    for item in scored:
        title = (item.get('title', '') or '').strip()
        if not title or title in seen_titles:
            continue
        seen_titles.add(title)
        deduped.append(item)
    log(f"去重: {len(scored)} → {len(deduped)}条")
    if not deduped:
        log("❌ 去重无结果")
        return
    
    # 中文优先 - 加强P1偏好内容优势
    zh = [x for x in deduped if is_chinese(x.get('title', ''))]
    en = [x for x in deduped if not is_chinese(x.get('title', ''))]
    target_zh = max(14, min(TARGET_COUNT - 2, int(TARGET_COUNT * 0.8)))
    sorted_items = zh[:target_zh] + en[:max(2, TARGET_COUNT - target_zh)]
    if not sorted_items:
        log("❌ 无有效推送内容")
        return
    log(f"中文优先: {len(zh)}中 + {len(en)}英 → {len(sorted_items)}条")
    
    # 8. 平台多样性
    final = enforce_diversity(sorted_items, TARGET_COUNT)
    
    if len(final) < 16:
        log(f"⚠️ 最终不足16条({len(final)}条), 降级为{len(final)}条推送")
        if len(final) < 5:
            log(f"❌ 最终不足5条({len(final)}条)")
            return
    
    log(f"✅ 最终: {len(final)}条, {len(set(i.get('platform','?') for i in final))}个平台")
    
    
    # ===== 二次垃圾过滤 + 等级评分(在构建HTML之前) =====
    graded_items = []
    push_levels = []
    for item in final:
        score = float(item.get('_score', 0))
        ai_score = float(item.get('ai_score_total', 0) or 0)
        # 用ai_score_total作为主要等级依据,_score作为偏好增强
        effective_score = max(score, ai_score)
        if ai_score >= 80:
            level = 9  # 🔴 极重要 (AI评分极高)
        elif ai_score >= 65 or (effective_score >= 75 and score >= 30):
            level = 8  # 🟠 非常重要
        elif ai_score >= 50 or (effective_score >= 50 and score >= 20):
            level = 7  # 🟠 重要
        elif effective_score >= 30:
            level = 6  # 🟡 较重要
        elif effective_score >= 15:
            level = 5  # 🟡 普通
        else:
            level = 3  # 🟢 参考
        
        # 第二遍垃圾验证(推送前最后检查)
        title = item.get('title', '') or ''
        if is_trash(title, item.get('content', ''), item):
            log(f"  ⚠️ 二次过滤拦截: {title[:40]}")
            continue
            
        graded_items.append(item)
        push_levels.append(level)
    
    final = graded_items
    log(f"二次垃圾过滤+等级评分: {len(graded_items)}条保留, 等级{min(push_levels) if push_levels else 0}-{max(push_levels) if push_levels else 0}")
    
    if len(final) < 16:
        log(f"⚠️ 最终不足16条({len(final)}条), 降级推送")
        if len(final) < 5:
            log(f"    → 严重不足({len(final)}条), 跳过推送")
            return []

    push_time = datetime.now().strftime("%H:%M")
    html_message = build_html_message(final, push_time)
    
    # 预览
    print("\n" + "=" * 50)
    print("📋 推送预览(HTML):")
    print(f"标题: 📊 Hermes 情报 {push_time} | {len(final)}条 | {len(set(i.get('platform','?') for i in final))}平台")
    for i, item in enumerate(final, 1):
        title = (item.get('title', '') or '').strip()[:50]
        platform = item.get('platform', '?')
        score = item.get('ai_score_total', 0) or 0
        url = item.get('url', '') or ''
        has_url = '✅' if url.startswith('http') else '❌'
        # 层级标记 — 用tags方向标签
        item_tags = item.get('tags', '') or ''
        preview_tiers = set()
        for t in item_tags.split('|'):
            if t.strip():
                preview_tiers.add(get_tier_for_tag(t.strip()))
        tier_str = ''.join(TIER_MARKERS.get(t, '') for t in sorted(preview_tiers, reverse=True))
        tier_prefix = f'{tier_str} ' if tier_str else ''
        print(f"  {i}. [{has_url}] {tier_prefix}[{platform}] ⭐{score:.0f} | {title}")
    print("=" * 50)
    
    # 10. 推送
    if "--push" in sys.argv:
        log("📤 推送微信(HTML模板)...")
        result = push_wechat(
            f"📊 Hermes 情报 {push_time} | {len(final)}条 | {len(set(i.get('platform','?') for i in final))}平台",
            html_message
        )
        if result.get("code") == 200:
            log("✅ 推送成功! (HTML模板)")
            record_pushed(final, push_levels)
        else:
            log(f"❌ 推送失败: {result.get('msg', '未知')}")
    else:
        log("🔍 DRY RUN模式 — 不推送")
    
    elapsed = time.time() - start
    log(f"⏱️ 耗时: {elapsed:.1f}s")


def main():
    push_v12()

if __name__ == "__main__":
    main()
