#!/usr/bin/env python3
"""
Hermes 深度清洗 v2 — 增量清洗引擎
每次只处理新进raw数据,不做全量扫描
BUG#6修复: 基于raw_id增量,不做全表扫描
"""
import sqlite3, re, time, sys
from datetime import datetime
from pathlib import Path

HERMES = Path("/home/administrator/.hermes")
DB_PATH = HERMES / "intelligence.db"
AM_DB = HERMES / "active_memory.db"
NOISE = {"广告","推广","抽奖","中奖","红包","优惠券","秒杀","震惊","惊人","必看","转疯了","删前必看","直播带货","低价","特价"}

# 缓存keyword_weights避免每次查询
_keyword_weights_cache = None
def load_keyword_weights():
    global _keyword_weights_cache
    if _keyword_weights_cache is not None:
        return _keyword_weights_cache
    try:
        am = sqlite3.connect(str(AM_DB))
        rows = am.execute("SELECT keyword, weight, category FROM keyword_weights ORDER BY weight DESC").fetchall()
        am.close()
        # 按权重降序排列,高权重关键词优先匹配
        _keyword_weights_cache = rows
        return rows
    except Exception as e:
        print(f"⚠️ 无法加载keyword_weights: {e}")
        _keyword_weights_cache = []
        return []

def compute_personal_match(title, content):
    """基于active_memory.db的keyword_weights计算真实个人偏好匹配分"""
    weights = load_keyword_weights()
    if not weights:
        return 0
    
    tl = (title + " " + (content or "")[:300]).lower()
    score = 0
    matched = []
    
    for kw, weight, cat in weights:
        if kw.lower() in tl:
            score += weight
            matched.append(kw)
            # 同一类别内多个关键词匹配只累加,不重复限定
    
    # 归一化处理:0~100范围
    score = min(round(score, 1), 100)
    return score, matched

def clean_all():
    db = sqlite3.connect(str(DB_PATH))
    db.execute("PRAGMA journal_mode=WAL")
    c = db.cursor()

    # 已清洗最大raw_id
    c.execute("SELECT COALESCE(MAX(raw_id), 0) FROM cleaned_intelligence")
    max_cleaned = c.fetchone()[0]
    
    # 先尝试批量处理积压数据(id <= max_cleaned 但未清洗的)
    # BUG#6修复: 积压数据使用NOT IN范式,不做增量限制
    # BUG#8修复: 从5000提高到50000,加速积压清理(34K条积压中97%是重复标题,快速扫描跳过)
    backlog_limit = 50000  # 每次最多处理50000条积压
    c.execute("""
        SELECT r.id, r.title, r.content, r.url, r.source, r.platform,
               r.author, r.author_id, r.category, r.tags,
               r.hot_score, r.published_at, r.collected_at
        FROM raw_intelligence r
        WHERE r.id NOT IN (
            SELECT COALESCE(c.raw_id, 0) FROM cleaned_intelligence c WHERE c.raw_id IS NOT NULL
        )
        ORDER BY r.id ASC
        LIMIT ?
    """, (backlog_limit,))
    backlog_rows = c.fetchall()
    cols = ['id','title','content','url','source','platform','author',
            'author_id','category','tags','hot_score','published_at','collected_at']
    
    # 然后再取增量数据(id > max_cleaned)
    c.execute("""
        SELECT r.id, r.title, r.content, r.url, r.source, r.platform,
               r.author, r.author_id, r.category, r.tags,
               r.hot_score, r.published_at, r.collected_at
        FROM raw_intelligence r
        WHERE r.id > ?
        AND r.id NOT IN (
            SELECT COALESCE(c.raw_id, 0) FROM cleaned_intelligence c WHERE c.raw_id IS NOT NULL
        )
        ORDER BY r.id ASC
    """, (max_cleaned,))
    new_rows = c.fetchall()
    
    # 合并:先处理积压(旧数据),再处理增量(新数据)
    rows = backlog_rows + new_rows
    
    if not rows:
        print("待清洗新数据: 0 条")
        db.close()
        return 0

    backlog_count = len(backlog_rows)
    new_count = len(new_rows)
    print(f"待清洗新数据: {len(rows)} 条 (积压={backlog_count}, 增量={new_count})")
    print(f"已清洗最大raw_id: {max_cleaned}")

    # 加载已有标题用于去重
    # 如果是积压模式(batch),加载全部已有标题;否则只加载最近5000条
    if backlog_count > 0:
        c.execute("SELECT title FROM cleaned_intelligence")
    else:
        c.execute("SELECT title FROM cleaned_intelligence WHERE raw_id > ?", (max_cleaned - 5000,))
    existing = set()
    for r in c.fetchall():
        t = (r[0] or "").strip()
        if t: existing.add(t)

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cleaned = dup = noise = errors = 0
    start = time.time()

    # 预去重:跳过标题已经在cleaned_intelligence中的项(加速积压清理)
    pre_skip = 0
    pre_checked = 0
    pre_filtered_rows = []
    for row in rows:
        pre_checked += 1
        title = ((row[1] or "") if len(row) > 1 else "").strip()
        if len(title) >= 6 and title not in existing:
            pre_filtered_rows.append(row)
        else:
            pre_skip += 1
    rows = pre_filtered_rows
    if pre_skip > 0:
        print(f"预去重跳过: {pre_skip} 条 (标题已在cleaned中), 剩余 {len(rows)} 条待处理")

    for row in rows:
        try:
            item = dict(zip(cols, row))
            title = (item.get("title","") or "").strip()
            content = (item.get("content","") or "")[:2000]
            source = item.get("source","") or ""
            platform = item.get("platform","") or ""

            if len(title) < 6:
                noise += 1
                continue
            # 【修复】使用完整标题精确匹配去重
            if title in existing:
                dup += 1
                continue
            noise_text = (title + " " + content[:200]).lower()
            if any(n in noise_text for n in NOISE):
                noise += 1
                continue

            existing.add(title)
            hot = float(item.get("hot_score",0) or 0)
            importance = round(hot / 100, 2)
            cn = len(re.findall(r'[\u4e00-\u9fff]', title))
            lang = "zh" if cn > 0 else "en"

            tl = (title + " " + content[:200]).lower()
            tags = []
            if any(k in tl for k in ["llm","gpt","chatgpt","ai","大模型","agent","rag","openai","claude","deepseek"]): tags.append("AI")
            if any(k in tl for k in ["rust","python","typescript","github","开源","代码","编程","开发者"]): tags.append("Dev")
            if any(k in tl for k in ["新能源","电动汽车","自动驾驶","特斯拉","比亚迪"]): tags.append("EV")
            if any(k in tl for k in ["手机","iphone","小米","华为","芯片","半导体"]): tags.append("Tech")
            if any(k in tl for k in ["军事","战争","国防","导弹","战机","航母","国际","中美"]): tags.append("Military")
            if any(k in tl for k in ["ufc","mma","拳击","格斗"]): tags.append("Fight")
            if any(k in tl for k in ["写真","摄影","美女","模特","时尚","cos"]): tags.append("Art")
            tag_str = "|".join(tags) if tags else "General"

            # 基于active_memory.db的keyword_weights计算真实个人偏好匹配
            pref_result = compute_personal_match(title, content)
            if isinstance(pref_result, tuple):
                pref, matched_kws = pref_result
            else:
                pref, matched_kws = pref_result, []

            # 回写匹配反馈到active_memory.db的preference_feedback
            if matched_kws:
                try:
                    am = sqlite3.connect(str(AM_DB))
                    now_ts = datetime.now().isoformat()
                    for mk in matched_kws:
                        am.execute("""
                            INSERT INTO preference_feedback (keyword, hit_count, miss_count, last_hit, last_miss)
                            VALUES (?, 1, 0, ?, NULL)
                            ON CONFLICT(keyword) DO UPDATE SET
                                hit_count = hit_count + 1,
                                last_hit = excluded.last_hit
                        """, (mk, now_ts))
                    am.commit()
                    am.close()
                except Exception as e:
                    print(f"⚠️ preference_feedback回写失败: {e}")

            c.execute("""INSERT INTO cleaned_intelligence 
                (raw_id,title,content,url,source,platform,author,author_id,
                 category,tags,importance_score,value_level,value_reasons,
                 is_ai_related,language,chinese_ratio,is_processed,
                 published_at,collected_at,cleaned_at,agent,
                 personal_match_score,source_type)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (item["id"], title[:500], content[:2000], item.get("url","") or "", source, platform,
                 (item.get("author","") or "")[:100], (item.get("author_id","") or "")[:100],
                 (item.get("category","") or "")[:100], tag_str[:500],
                 importance, 1 if importance>0 else 0, "hermes_deep_clean_v2",
                 0, lang, 1.0, 1,
                 (item.get("published_at","") or ""), (item.get("collected_at","") or ""), now,
                 "hermes_deep_clean_v2", pref, platform[:50]))
            cleaned += 1
        except Exception as e:
            errors += 1

    db.commit()
    elapsed = time.time() - start

    print(f"\n=== 清洗结果 ===")
    print(f"处理: {len(rows)} 条")
    print(f"新增: {cleaned} 条")
    print(f"重复: {dup} 条")
    print(f"噪声: {noise} 条")
    print(f"错误: {errors} 条")
    print(f"耗时: {elapsed:.1f}s")

    c.execute("""SELECT COUNT(*) FROM cleaned_intelligence WHERE DATE(cleaned_at) = DATE('now','localtime')""")
    today = c.fetchone()[0]
    print(f"今日cleaned: {today} 条")
    c.execute("SELECT COUNT(*) FROM cleaned_intelligence")
    total = c.fetchone()[0]
    print(f"总计: {total} 条")
    db.close()
    return cleaned

if __name__ == "__main__":
    start = time.time()
    count = clean_all()
    print(f"✅ 清洗完成: {count} 条, 总耗时{time.time()-start:.0f}s")
