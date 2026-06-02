#!/usr/bin/env python3
"""
Hermes AI六维评分管道 v3 — 真正的AI内容理解评分
=================================================
对cleaned_intelligence中未评分的数据进行六维AI内容理解评分。

工作原理:
1. 从cleaned_intelligence中读取有内容但未评分的条目
2. 对每条记录使用AI进行真正的六维内容理解评分
3. 评分维度: 稀缺性(0-30),影响力(0-30),技术深度(0-20),时效性(0-10),偏好匹配(0-10),可信度(0-10)
4. 写入ai_score_total和各细分字段以及推理说明

使用方式:
  python3 hermes_ai_scoring.py                    # 评分新条目(最多20条)
  python3 hermes_ai_scoring.py --backfill 50      # 回填历史重要条目
  python3 hermes_ai_scoring.py --dry-run          # 预览待评分条目
  python3 hermes_ai_scoring.py --full             # 全量评分(所有未评分)
"""

import sqlite3, json, sys, os, re, time
import urllib.request
import urllib.error
import socket
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional

HERMES = Path("/home/administrator/.hermes")

# ========== 提前定义简单日志（在env加载之前可用） ==========
def _early_log(msg):
    """env加载阶段使用的简单日志"""
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}")

# ========== 加载.env环境变量 ==========
# 确保cron子进程也能获取到API key
_env_path = HERMES / ".env"
if _env_path.exists():
    try:
        for _line in _env_path.read_text(encoding="utf-8").splitlines():
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _v = _line.split("=", 1)
                _k = _k.strip()
                _v = _v.strip()
                # 跳过hermes隐藏的***值
                if _v and _v != "***" and (_k not in os.environ or not os.environ[_k]):
                    os.environ[_k] = _v
    except Exception as e:
        _early_log(f"WARNING .env加载失败: {e}")

# 也尝试加载config.yaml中的deepseek api_key
try:
    import yaml
    _cfg_path = HERMES / "config.yaml"
    if _cfg_path.exists():
        with open(_cfg_path, encoding='utf-8') as _f:
            _cfg = yaml.safe_load(_f) or {}
        for _p in _cfg.get("custom_providers", []):
            if _p.get("name") == "deepseek" and _p.get("api_key"):
                if not os.environ.get("DEEPSEEK_API_KEY"):
                    os.environ["DEEPSEEK_API_KEY"] = _p["api_key"]
                if not os.environ.get("OPENROUTER_API_KEY"):
                    os.environ["OPENROUTER_API_KEY"] = _p["api_key"]
except Exception as e:
    _early_log(f"WARNING config.yaml加载失败: {e}")

DB_PATH = HERMES / "intelligence.db"
LOG_DIR = HERMES / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

# 允许最小内容长度为0,使得完全无内容的条目(仅标题)也能被评分
MIN_CONTENT_LEN_RULE = 0

def log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}")
    from datetime import date as _date
    logfile = LOG_DIR / f"ai_scoring_{_date.today().strftime('%Y%m%d')}.log"
    with open(logfile, "a", encoding="utf-8") as f:
        f.write(f"[{ts}] {msg}\n")

def load_keyword_weights() -> Dict[str, float]:
    """从active_memory.db加载格林主人偏好权重"""
    try:
        am_path = HERMES / "active_memory.db"
        if not am_path.exists():
            return {}
        am = sqlite3.connect(str(am_path))
        rows = am.execute("SELECT keyword, weight FROM keyword_weights").fetchall()
        am.close()
        return {kw.lower(): float(w) for kw, w in rows}
    except Exception as e:
        log(f"WARNING 无法加载keyword_weights: {e}")
        return {}

def get_pending_items(limit: int = 20, min_content_len: int = 30, 
                       backfill: bool = False, full: bool = False) -> List[Dict]:
    """获取待评分条目 — 优先选有完整内容、高价值的条目以节省API token"""
    conn = sqlite3.connect(str(DB_PATH))
    
    # 优先选择有足够内容且标题有意义且未被真正AI评分过的条目
    query = """
        SELECT id, title, COALESCE(content, '') as content,
               platform, source, author, tags, category,
               importance_score, value_level, published_at, url
        FROM cleaned_intelligence
        WHERE ai_scored_at IS NULL
          AND LENGTH(COALESCE(content, '')) >= ?
          AND title IS NOT NULL AND title != ''
        ORDER BY LENGTH(COALESCE(content, '')) DESC, importance_score DESC
        LIMIT ?
    """
    cur = conn.execute(query, (min_content_len, limit))
    cols = [d[0] for d in cur.description]
    items = [dict(zip(cols, r)) for r in cur.fetchall()]
    conn.close()
    return items

def score_timeliness(published_at: Optional[str]) -> int:
    """时效性规则评分:24h内=10, 48h内=7, 一周内=4, 更早=1"""
    if not published_at:
        return 5
    try:
        pub = datetime.fromisoformat(published_at.replace('Z', '+00:00'))
        now = datetime.now(pub.tzinfo) if pub.tzinfo else datetime.now()
        hours = (now - pub).total_seconds() / 3600
        if hours <= 24: return 10
        if hours <= 48: return 7
        if hours <= 168: return 4
        return 1
    except (ValueError, TypeError):
        return 5

def score_source_credibility(source: Optional[str], platform: Optional[str]) -> int:
    """来源可信度规则评分:官方=10, 一手=8, 媒体=6, 自媒体=3"""
    s = (source or "").lower()
    p = (platform or "").lower()
    official = ["github", "huggingface", "arxiv", "openai", "deepseek", "anthropic",
                "google-gemini", "karpathy", "pytorch", "nvidia", "microsoft",
                "openclaw", "worldmonitor"]
    first_hand = ["twitter", "x.com", "weibo", "zhihu", "bilibili", "hackernews",
                  "solidot", "ithome"]
    media = ["36kr", "huxiu", "techcrunch", "theverge", "ars", "wired",
             "reddit", "theinformation", "bloomberg", "reuters"]
    
    combined = s + "|" + p
    if any(k in combined for k in official):
        return 10
    if any(k in combined for k in first_hand):
        return 8
    if any(k in combined for k in media):
        return 6
    return 3

def score_preference_rule(title: str, content: str, kw_weights: Dict[str, float]) -> int:
    """偏好匹配规则评分:基于keyword_weights"""
    if not kw_weights:
        return 5
    text = (title + " " + (content or "")[:500]).lower()
    score = 0
    for kw, w in kw_weights.items():
        if kw in text:
            score += w
    return min(round(score / 3), 10)

def generate_ai_scoring_prompt(items: List[Dict], kw_weights: Dict[str, float]) -> str:
    """为批量评分生成AI评分prompt"""
    if not items:
        return ""
    
    # 先产生规则初始分作为参考
    pref_keywords = sorted(kw_weights.items(), key=lambda x: -x[1])[:15]
    pref_hints = "\n".join([f"  - {kw} (权重{w:.1f})" for kw, w in pref_keywords])
    
    items_desc = []
    for item in items:
        title = (item.get("title", "") or "")[:150]
        content = (item.get("content", "") or "")[:500]
        platform = item.get("platform", "")
        source = item.get("source", "")
        author = item.get("author", "")
        tags = (item.get("tags", "") or "")[:100]
        category = item.get("category", "") or ""
        pub = item.get("published_at", "") or ""
        
        items_desc.append(f"""
## 条目 #{item['id']}
- **ID (必须原样返回)**: {item['id']}
- **标题**: {title}
- **内容**: {content[:400]}
- **平台**: {platform} | **来源**: {source} | **作者**: {author}
- **分类**: {category} | **标签**: {tags}
- **发布时间**: {pub}
""")
    
    prompt = f"""你是一位严格的情报价值评估专家。请对以下{len(items)}条情报逐条进行**真正的AI内容理解评分**。

用户关注领域(供偏好匹配参考):
{pref_hints}

## 六维评分标准(满分100分)

| 维度 | 范围 | 详细说明 |
|------|------|---------|
| 稀缺性(scarcity) | 0-30 | 独家/首发/一手信息(25-30),深度分析/独特视角(15-24),转载/聚合(5-14),普通内容(0-4) |
| 影响力(impact) | 0-30 | 行业级变革(25-30),公司级战略(15-24),产品级更新(5-14),个人/一般(0-4) |
| 技术深度(tech_depth) | 0-20 | 具体技术细节/代码/数据(15-20),有分析论证(8-14),普通信息(0-7) |
| 时效性(timeliness) | 0-10 | 24h内(9-10),48h内(7-8),一周内(4-6),更早(0-3) |
| 偏好匹配(preference) | 0-10 | 完全匹配核心兴趣(9-10),部分匹配(5-8),不相关(0-4) |
| 可信度(credibility) | 0-10 | 官方/一手(9-10),知名媒体(7-8),普通来源(4-6),不明来源(0-3) |

**核心要求**:请真正理解每条内容的内在价值后进行评分,不要受标题党影响。

## 待评分条目
{''.join(items_desc)}

## 输出格式
请输出严格JSON数组(纯文本,不要markdown代码块):
[
  {{
    "id": ID(必须原样返回),
    "scarcity": 0-30,
    "impact": 0-30, 
    "tech_depth": 0-20,
    "timeliness": 0-10,
    "preference": 0-10,
    "credibility": 0-10,
    "scarcity_reason": "简短原因(中文)",
    "impact_reason": "简短原因(中文)",
    "tech_depth_reason": "简短原因(中文)",
    "timeliness_reason": "简短原因(中文)",
    "preference_reason": "简短原因(中文)",
    "credibility_reason": "简短原因(中文)",
    "summary": "一句话价值总结(中文)"
  }}
]

确保对所有{len(items)}条都评分,不要遗漏。"""
    
    return prompt

def parse_ai_response(ai_text: str, items: List[Dict] = None) -> List[Dict]:
    """解析AI返回的评分JSON"""
    # 尝试直接解析
    ai_text = ai_text.strip()
    # 去掉可能的markdown代码块标记
    ai_text = re.sub(r'^```(?:json)?\s*', '', ai_text)
    ai_text = re.sub(r'\s*```$', '', ai_text)
    
    try:
        scores = json.loads(ai_text)
        if isinstance(scores, list):
            # 如果缺少id字段，按顺序匹配items
            if scores and 'id' not in scores[0] and items:
                for i, s in enumerate(scores):
                    if i < len(items):
                        s['id'] = items[i]['id']
            return scores
        if isinstance(scores, dict) and "scores" in scores:
            result = scores["scores"]
            if result and 'id' not in result[0] and items:
                for i, s in enumerate(result):
                    if i < len(items):
                        s['id'] = items[i]['id']
            return result
        return []
    except json.JSONDecodeError:
        # 尝试用正则提取JSON数组
        match = re.search(r'\[\s*\{.*\}\s*\]', ai_text, re.DOTALL)
        if match:
            try:
                scores = json.loads(match.group())
                if isinstance(scores, list) and scores and 'id' not in scores[0] and items:
                    for i, s in enumerate(scores):
                        if i < len(items):
                            s['id'] = items[i]['id']
                return scores if isinstance(scores, list) else []
            except (json.JSONDecodeError, KeyError):
                pass
        return []

def apply_rules_for_fallback(item: Dict, kw_weights: Dict[str, float]) -> Dict:
    """当AI评分不可用时的规则评分后备方案"""
    title = item.get('title', '')[:300]
    content = item.get('content', '')[:1000]
    text = (title + " " + (content or "")[:500]).lower()
    
    timeliness = score_timeliness(item.get('published_at', ''))
    credibility = score_source_credibility(item.get('source', ''), item.get('platform', ''))
    pref = score_preference_rule(title, content, kw_weights)
    
    # 规则评分
    scarcity, impact, tech_depth = 5, 5, 5
    
    if any(k in text for k in ['独家','首次','首发','突破','首款','革命性','开源发布','论文','白皮书']):
        scarcity = 25
    elif any(k in text for k in ['曝光','爆料','泄露','传闻','据传','内部','秘密','最新','发布','推出']):
        scarcity = 20
    elif any(k in text for k in ['研究','论文','报告','分析','白皮书']):
        scarcity = 15
    
    if any(k in text for k in ['行业','全球','颠覆','变革','重大','里程碑','生态','治理']):
        impact = 25
    elif any(k in text for k in ['融资','收购','亿','上市','IPO','估值']):
        impact = 20
    elif any(k in text for k in ['合作','战略','联盟','开放','标准化','市场','增长']):
        impact = 18
    
    if any(k in text for k in ['架构','算法','框架','源码','实现','技术方案','模型','训练','推理']):
        tech_depth = 18
    elif any(k in text for k in ['分布式','并发','高可用','容错','一致性','协议']):
        tech_depth = 14
    
    # 平台加权
    p = (item.get('platform', '') or '').lower()
    if 'github' in p: scarcity, tech_depth = max(scarcity, 20), max(tech_depth, 16)
    if 'arxiv' in p or 'huggingface' in p: scarcity, tech_depth = max(scarcity, 18), max(tech_depth, 18)
    if 'hackernews' in p: tech_depth = max(tech_depth, 12)
    
    total = scarcity + impact + tech_depth + timeliness + pref + credibility
    total = min(round(total, 1), 100)
    
    return {
        'scarcity': scarcity,
        'impact': impact,
        'tech_depth': tech_depth,
        'timeliness': timeliness,
        'preference': pref,
        'credibility': credibility,
        'total': total,
        'scarcity_reason': '规则评分',
        'impact_reason': '规则评分',
        'tech_depth_reason': '规则评分',
        'timeliness_reason': '规则评分',
        'preference_reason': '规则评分',
        'credibility_reason': '规则评分',
        'summary': '规则自动评分(关键词匹配)'
    }

def save_scores_to_db(scores: List[Dict]) -> int:
    """保存评分结果到数据库"""
    conn = sqlite3.connect(str(DB_PATH))
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    saved = 0
    
    # 收集所有要更新的item_id用于队列清理
    updated_ids = []
    
    for s in scores:
        item_id = s.get("id")
        if not item_id:
            continue
        
        total = s.get("scarcity", 0) + s.get("impact", 0) + s.get("tech_depth", 0) + \
                s.get("timeliness", 0) + s.get("preference", 0) + s.get("credibility", 0)
        total = min(total, 100)
        
        reasoning = json.dumps({
            "scarcity_reason": s.get("scarcity_reason", ""),
            "impact_reason": s.get("impact_reason", ""),
            "tech_depth_reason": s.get("tech_depth_reason", ""),
            "timeliness_reason": s.get("timeliness_reason", ""),
            "preference_reason": s.get("preference_reason", ""),
            "credibility_reason": s.get("credibility_reason", ""),
            "summary": s.get("summary", ""),
        }, ensure_ascii=False)
        
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
            s.get("scarcity", 0),
            s.get("impact", 0),
            s.get("tech_depth", 0),
            s.get("timeliness", 0),
            s.get("preference", 0),
            s.get("credibility", 0),
            total,
            round(total / 10.0, 2),
            reasoning,
            now,
            item_id,
        ))
        updated_ids.append(item_id)
        saved += 1
    
    # 清理队列
    if updated_ids:
        placeholders = ",".join(["?"] * len(updated_ids))
        conn.execute(f"""
            DELETE FROM ai_score_queue 
            WHERE item_id IN ({placeholders}) AND status = 'pending'
        """, updated_ids)
    
    conn.commit()
    conn.close()
    return saved

def score_items_via_openrouter(items: List[Dict], kw_weights: Dict[str, float],
                                 model: str = "deepseek-chat",
                                 batch_size: int = 5) -> int:
    """
    通过AI API直接调用进行真正的六维内容理解评分。
    优先使用deepseek-chat（Hermes主模型），回退openrouter/anthropic/openai。
    每次批量发送batch_size条给AI，解析JSON返回并写入数据库。
    """
    if not items:
        return 0

    # 多路API key搜索：deepseek优先(因为Hermes主模型是deepseek)
    api_key = os.environ.get("DEEPSEEK_API_KEY", "")
    api_url = "https://api.deepseek.com/v1/chat/completions"
    model_to_use = model
    
    if not api_key:
        api_key = os.environ.get("OPENROUTER_API_KEY", "")
        api_url = "https://openrouter.ai/api/v1/chat/completions"
        model_to_use = model if model != "deepseek-chat" else "openrouter/auto"
    
    if not api_key:
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        api_url = "https://api.anthropic.com/v1/messages"
        model_to_use = "claude-sonnet-4-20250514"
    
    if not api_key:
        api_key = os.environ.get("OPENAI_API_KEY", "")
        api_url = "https://api.openai.com/v1/chat/completions"
        model_to_use = "gpt-4o-mini"
        
    if not api_key:
        log(f"❌ 未找到任何API密钥 (DEEPSEEK_API_KEY/OPENROUTER_API_KEY/ANTHROPIC_API_KEY/OPENAI_API_KEY)")
        log(f"   当前环境变量key状态: DEEPSEEK={bool(os.environ.get('DEEPSEEK_API_KEY'))}, OPENROUTER={bool(os.environ.get('OPENROUTER_API_KEY'))}, ANTHROPIC={bool(os.environ.get('ANTHROPIC_API_KEY'))}, OPENAI={bool(os.environ.get('OPENAI_API_KEY'))}")
        return 0
    log(f"🤖 使用 {model_to_use} 进行真正的AI六维评分, 共{len(items)}条, 每批{batch_size}条")

    all_scores = []
    total_batches = (len(items) + batch_size - 1) // batch_size

    for batch_idx in range(total_batches):
        start = batch_idx * batch_size
        end = min(start + batch_size, len(items))
        batch = items[start:end]

        prompt = generate_ai_scoring_prompt(batch, kw_weights)
        if not prompt:
            continue

        system_msg = """你是一位严格的情报价值评估专家。请仔细阅读每条内容，进行真正的理解性评分。
输出必须是严格有效的JSON数组，不要任何markdown代码块包裹，不要其他文字。
每个元素必须包含: id, scarcity, impact, tech_depth, timeliness, preference, credibility,
scarcity_reason, impact_reason, tech_depth_reason, timeliness_reason, preference_reason,
credibility_reason, summary 这些字段。"""

        payload = json.dumps({
            "model": model_to_use,
            "messages": [
                {"role": "system", "content": system_msg},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.3,
            "max_tokens": 1600
        }).encode("utf-8")

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        }
        # DeepSeek不需要Referer, OpenRouter需要
        if "openrouter" in api_url:
            headers["HTTP-Referer"] = "https://hermes.weixin.ai"
            headers["X-Title"] = "Hermes AI Scoring"

        # Retry logic
        max_retries = 3
        response_text = None
        for attempt in range(1, max_retries + 1):
            try:
                req = urllib.request.Request(api_url, data=payload, headers=headers, method="POST")
                with urllib.request.urlopen(req, timeout=120) as resp:
                    response_text = resp.read().decode("utf-8")
                break
            except (urllib.error.URLError, socket.timeout, OSError) as e:
                log(f"⚠️ API请求失败(尝试{attempt}/{max_retries}): {e}")
                if attempt < max_retries:
                    wait = 5 * attempt
                    log(f"⏳ 等待{wait}秒后重试...")
                    time.sleep(wait)
                else:
                    log(f"❌ API请求全部失败: {e}")
                    response_text = None

        if not response_text:
            log(f"⚠️ 第{batch_idx+1}批API无响应,跳过")
            continue

        # Parse the response
        try:
            data = json.loads(response_text)
            ai_content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            if not ai_content:
                log(f"⚠️ 第{batch_idx+1}批AI返回内容为空")
                continue
        except (json.JSONDecodeError, KeyError, IndexError) as e:
            log(f"⚠️ 第{batch_idx+1}批JSON解析失败: {e}")
            log(f"   响应前200字符: {response_text[:200]}")
            continue

        scores = parse_ai_response(ai_content, items=batch)
        if not scores:
            log(f"⚠️ 第{batch_idx+1}批AI返回的评分无法解析")
            # Fallback to rule scores for this batch
            for item in batch:
                fb = apply_rules_for_fallback(item, kw_weights)
                scores.append({
                    "id": item["id"],
                    "scarcity": fb["scarcity"],
                    "impact": fb["impact"],
                    "tech_depth": fb["tech_depth"],
                    "timeliness": fb["timeliness"],
                    "preference": fb["preference"],
                    "credibility": fb["credibility"],
                    "scarcity_reason": fb["scarcity_reason"],
                    "impact_reason": fb["impact_reason"],
                    "tech_depth_reason": fb["tech_depth_reason"],
                    "timeliness_reason": fb["timeliness_reason"],
                    "preference_reason": fb["preference_reason"],
                    "credibility_reason": fb["credibility_reason"],
                    "summary": "AI评分失败后备",
                })
            log(f"  使用规则评分后备，{len(scores)}条")

        all_scores.extend(scores)

        # Show progress
        batch_total = sum(
            s.get("scarcity", 0) + s.get("impact", 0) + s.get("tech_depth", 0) +
            s.get("timeliness", 0) + s.get("preference", 0) + s.get("credibility", 0)
            for s in scores
        )
        avg = round(batch_total / len(scores), 1) if scores else 0
        log(f"📊 第{batch_idx+1}/{total_batches}批完成: {len(scores)}条, 平均{avg}分")

        # Rate limiting pause between batches
        if batch_idx < total_batches - 1:
            time.sleep(2)
        
        # 每5批增量保存一次，避免超时丢失
        if (batch_idx + 1) % 5 == 0 or batch_idx == total_batches - 1:
            try:
                conn = sqlite3.connect(str(DB_PATH))
                c = conn.cursor()
                now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                for s in all_scores:
                    total = s.get("scarcity", 0) + s.get("impact", 0) + s.get("tech_depth", 0) + \
                            s.get("timeliness", 0) + s.get("preference", 0) + s.get("credibility", 0)
                    reasoning = json.dumps({
                        "scarcity_reason": s.get("scarcity_reason", ""),
                        "impact_reason": s.get("impact_reason", ""),
                        "tech_depth_reason": s.get("tech_depth_reason", ""),
                        "timeliness_reason": s.get("timeliness_reason", ""),
                        "preference_reason": s.get("preference_reason", ""),
                        "credibility_reason": s.get("credibility_reason", ""),
                        "summary": s.get("summary", "AI评分"),
                    }, ensure_ascii=False)
                    c.execute("""
                        UPDATE cleaned_intelligence SET
                            ai_score_scarcity = ?, ai_score_impact = ?, ai_score_tech_depth = ?,
                            ai_score_timeliness = ?, ai_score_preference = ?, ai_score_credibility = ?,
                            ai_score_total = ?, ai_score_reasoning = ?, ai_scored_at = ?
                        WHERE id = ?
                    """, (s.get("scarcity", 0), s.get("impact", 0), s.get("tech_depth", 0),
                          s.get("timeliness", 0), s.get("preference", 0), s.get("credibility", 0),
                          total, reasoning, now, s["id"]))
                conn.commit()
                conn.close()
                log(f"💾 增量保存: 已保存{len(all_scores)}条至数据库")
            except Exception as e:
                log(f"⚠️ 增量保存失败: {e}")

    if all_scores:
        saved = save_scores_to_db(all_scores)
        log(f"✅ AI评分完成: 共{saved}条已保存")
        return saved
    else:
        log("❌ AI评分全部失败，无结果可保存")
        return 0

def run_ai_scoring_via_delegate_task(limit: int = 20) -> str:
    """
    使用Hermes delegate_task进行真正的AI理解评分。
    这是独立版本，不依赖人肉捕获stdout。
    """
    kw_weights = load_keyword_weights()
    log(f"⭐ 真正的AI评分模式: keyword_weights={len(kw_weights)}条, limit={limit}")
    
    # 获取待评分条目(有内容的)
    items = get_pending_items(limit=limit, min_content_len=30, full=True)
    if not items:
        log("无待评分条目，尝试空内容条目")
        # 尝试只靠标题评分的
        conn = sqlite3.connect(str(DB_PATH))
        rows = conn.execute("""
            SELECT id, title, COALESCE(content, '') as content,
                   platform, source, author, tags, category,
                   importance_score, value_level, published_at, url
            FROM cleaned_intelligence
            WHERE (ai_score_total IS NULL OR ai_score_total = 0)
              AND title IS NOT NULL AND title != ''
            ORDER BY importance_score DESC, cleaned_at DESC
            LIMIT ?
        """, (limit,)).fetchall()
        cols = ['id','title','content','platform','source','author','tags','category',
                'importance_score','value_level','published_at','url']
        items = [dict(zip(cols, r)) for r in rows]  # 12列匹配SELECT
        conn.close()
        
    if not items:
        log("真的无待评分条目了")
        return "TASK_OK:0"
    
    log(f"⭐ 真正AI评分: {len(items)}条待评分")
    for item in items:
        clen = len(item.get("content", "") or "")
        log(f"   #{item['id']:>7} [{item.get('source','?'):<12}] {str(item.get('title',''))[:60]} | content={clen}chars")
    
    # 选择模型：优先使用deepseek-chat（性价比高），备用qwen-plus
    model_to_use = os.environ.get("HERMES_AI_MODEL", "deepseek-chat")
    
    # 使用真正的AI评分进行评分
    try:
        # 检查是否有可用的AI API — 与score_items_via_openrouter一致的多路搜索
        api_key = (os.environ.get("DEEPSEEK_API_KEY", "") or
                   os.environ.get("OPENROUTER_API_KEY", "") or
                   os.environ.get("ANTHROPIC_API_KEY", "") or
                   os.environ.get("OPENAI_API_KEY", ""))
        
        if api_key:
            log(f"⭐ 尝试通过 {model_to_use} 进行真正的AI评分...")
            # 直接调用OpenRouter API进行评分
            saved = score_items_via_openrouter(items, kw_weights, model=model_to_use, batch_size=5)
            if saved > 0:
                return f"TASK_AI_SCORED:{saved}"
            else:
                log("⚠️ AI评分未成功，使用增强版规则评分替代")
                return apply_enhanced_rule_scores(items, kw_weights)
        else:
            log("⚠️ 未配置API密钥，使用增强版规则评分替代")
            return apply_enhanced_rule_scores(items, kw_weights)
            
    except Exception as e:
        log(f"❌ AI评分调用失败: {e}")
        log("⚠️ 回退到增强规则评分")
        return apply_enhanced_rule_scores(items, kw_weights)

def apply_enhanced_rule_scores(items: List[Dict], kw_weights: Dict[str, float]) -> str:
    """
    增强版规则评分（当AI评分不可用时的全自动后备方案）
    比原始apply_rule_scores_directly更智能：混合使用关键词+平台+发布时间
    """
    if not items:
        return "TASK_OK:0"
    
    log(f"📊 增强规则评分: {len(items)}条")
    saved = 0
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = sqlite3.connect(str(DB_PATH))
    
    for item in items:
        try:
            result = apply_rules_for_fallback(item, kw_weights)
            total = result['total']
            reasoning = json.dumps({
                "scarcity_reason": result['scarcity_reason'],
                "impact_reason": result['impact_reason'],
                "tech_depth_reason": result['tech_depth_reason'],
                "timeliness_reason": result['timeliness_reason'],
                "preference_reason": result['preference_reason'],
                "credibility_reason": result['credibility_reason'],
                "summary": "增强规则评分(AI不可用后备)",
            }, ensure_ascii=False)
            
            conn.execute("""
                UPDATE cleaned_intelligence SET
                    ai_score_scarcity = ?, ai_score_impact = ?, ai_score_tech_depth = ?,
                    ai_score_timeliness = ?, ai_score_preference = ?, ai_score_credibility = ?,
                    ai_score_total = ?, importance_score = ?,
                    ai_score_reasoning = ?, ai_scored_at = ?
                WHERE id = ?
            """, (
                result['scarcity'], result['impact'], result['tech_depth'],
                result['timeliness'], result['preference'], result['credibility'],
                total, round(total / 10.0, 2),
                reasoning, now, item['id']
            ))
            saved += 1
        except Exception as e:
            log(f"ERROR id={item['id']}: {e}")
    
    conn.commit()
    conn.close()
    
    log(f"增强规则评分完成: {saved}条")
    return f"TASK_ENHANCED_RULES:{saved}"

def save_scored_items_from_stdin():
    """从stdin读取AI评分结果并保存到数据库"""
    try:
        data = json.loads(sys.stdin.read())
        scores = data if isinstance(data, list) else data.get("scores", [])
        
        if not scores:
            log("无评分结果可保存")
            return "TASK_NO_RESULTS"
        
        saved = save_scores_to_db(scores)
        log(f"已保存 {saved} 条AI评分结果")
        
        # 输出评分摘要
        for s in scores:
            item_id = s.get("id", "?")
            total = s.get("scarcity", 0) + s.get("impact", 0) + s.get("tech_depth", 0) + \
                    s.get("timeliness", 0) + s.get("preference", 0) + s.get("credibility", 0)
            summary = (s.get("summary", "") or "")[:60]
            log(f"  #{item_id} -> {total}分 | {summary}")
        
        return f"TASK_DONE:{saved}"
    except Exception as e:
        log(f"保存评分结果失败: {e}")
        return f"TASK_ERROR:{e}"

def apply_rule_scores_directly():
    """直接应用规则评分(作为AI评分的后备方案)"""
    kw_weights = load_keyword_weights()
    log(f"应用规则评分(AI后备模式),keyword_weights: {len(kw_weights)}条")
    
    conn = sqlite3.connect(str(DB_PATH))
    
    # 允许标题为空内容(clen=0)的条目通过规则评分,很多InfoQ/FreeBuf等平台
    # 只保存了"点击查看原文>"占位符或无内容,但标题本身足够关键字规则评分
    items = get_pending_items(limit=500, min_content_len=0, full=True)
    if not items:
        log("无待评分条目")
        conn.close()
        return 0
    
    log(f"规则评分 {len(items)} 条...")
    saved = 0
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    for item in items:
        try:
            result = apply_rules_for_fallback(item, kw_weights)
            total = result['total']
            reasoning = json.dumps({
                "scarcity_reason": result['scarcity_reason'],
                "impact_reason": result['impact_reason'],
                "tech_depth_reason": result['tech_depth_reason'],
                "timeliness_reason": result['timeliness_reason'],
                "preference_reason": result['preference_reason'],
                "credibility_reason": result['credibility_reason'],
                "summary": result['summary'],
            }, ensure_ascii=False)
            
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
                result['scarcity'], result['impact'], result['tech_depth'],
                result['timeliness'], result['preference'], result['credibility'],
                total, round(total / 10.0, 2),
                reasoning, now, item['id']
            ))
            saved += 1
        except Exception as e:
            log(f"ERROR 评分异常 id={item['id']}: {e}")
    
    conn.commit()
    conn.close()
    
    log(f"规则评分完成: {saved} 条")
    
    # 输出统计
    conn = sqlite3.connect(str(DB_PATH))
    stats = conn.execute("""
        SELECT COUNT(*), 
               SUM(CASE WHEN ai_score_total >= 80 THEN 1 ELSE 0 END),
               SUM(CASE WHEN ai_score_total >= 60 AND ai_score_total < 80 THEN 1 ELSE 0 END),
               SUM(CASE WHEN ai_score_total >= 30 AND ai_score_total < 60 THEN 1 ELSE 0 END),
               SUM(CASE WHEN ai_score_total > 0 AND ai_score_total < 30 THEN 1 ELSE 0 END),
               ROUND(AVG(CASE WHEN ai_score_total > 0 THEN ai_score_total END), 1)
        FROM cleaned_intelligence
    """).fetchone()
    conn.close()
    
    log(f"全库统计: 总数={stats[0]}, 优秀>={80}={stats[1]}, 良好={stats[2]}, 中等={stats[3]}, 较低={stats[4]}, 平均={stats[5]}")
    
    return saved

if __name__ == "__main__":
    # 模式选择：
    # --ai: 真正的AI评分(直接调API)
    # --batch N: 批量评分N条(分批次调API，每批5条)
    # --save: 从stdin读取AI评分结果并保存
    # --dry-run: 预览待评分条目
    # --apply-rules: 明确的规则评分
    # 默认: 增强规则评分(快速后备)
    if "--save" in sys.argv:
        result = save_scored_items_from_stdin()
        print(result)
    elif "--dry-run" in sys.argv:
        items = get_pending_items(limit=10, min_content_len=0, full=True)
        log(f"待评分: {len(items)} 条")
        for item in items:
            clen = len(item.get("content", "") or "")
            log(f"  #{item['id']:>7} [{item.get('source','?'):<12}] {str(item.get('title',''))[:60]} | {clen}chars")
    elif "--batch" in sys.argv:
        # 批量评分模式：清除积压
        kw_weights = load_keyword_weights()
        batch_limit = 200
        # 检查是否指定了数字参数
        for arg in sys.argv[1:]:
            if arg.isdigit():
                batch_limit = int(arg)
                break
        log(f"📦 批量评分模式: 最多{batch_limit}条, 每批2条")
        items = get_pending_items(limit=batch_limit, min_content_len=0, full=True)
        log(f"📦 获取到 {len(items)} 条待评分条目")
        if not items:
            log("✅ 没有待评分的条目")
            print("TASK_DONE:0")
        else:
            model = os.environ.get("HERMES_AI_MODEL", "deepseek-chat")
            saved = score_items_via_openrouter(items, kw_weights, model=model, batch_size=5)
            if saved > 0:
                print(f"TASK_BATCH_SCORED:{saved}")
            else:
                log("⚠️ 批量AI评分未成功，回退到规则评分")
                saved = apply_rule_scores_directly()
                print(f"TASK_DONE:{saved}")
    elif "--ai" in sys.argv:
        # 真正的AI评分模式
        limit = 50
        if "--full" in sys.argv:
            limit = 100
        if len(sys.argv) > 2 and sys.argv[2].isdigit():
            limit = int(sys.argv[2])
        result = run_ai_scoring_via_delegate_task(limit=limit)
        print(result)
    elif "--apply-rules" in sys.argv:
        # 明确的规则评分
        saved = apply_rule_scores_directly()
        print(f"TASK_DONE:{saved}")
    else:
        # 默认: 先尝试AI评分，如果失败回退规则评分
        result = run_ai_scoring_via_delegate_task(limit=20)
        if result.startswith("TASK_AI_SCORED"):
            log(f"✅ AI评分完成: {result}")
        else:
            log(f"评分完成: {result}")
