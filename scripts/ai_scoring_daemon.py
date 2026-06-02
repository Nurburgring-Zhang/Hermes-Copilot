#!/usr/bin/env python3
"""
Hermes AI评分守护进程 (定时任务版)
===================================
每次运行:
1. 取当天新增的有内容(content长度>50)的未评分条目(最多20条)
2. 用LLM API做真正的AI六维度内容理解评分
3. 评分结果持久化到数据库

使用方式(被cron调用):
  python3 ai_scoring_daemon.py              # 标准模式
  python3 ai_scoring_daemon.py --dry-run     # 预览不做评分
  python3 ai_scoring_daemon.py --backfill N  # 对历史重要条目回填评分(N条)
"""

import sqlite3, json, sys, os, logging, re, urllib.request
from datetime import datetime, date
from pathlib import Path
from typing import List, Dict

HERMES = Path("/home/administrator/.hermes")
DB_PATH = HERMES / "intelligence.db"
LOG_DIR = HERMES / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / f"ai_scoring_daemon_{date.today().strftime('%Y%m%d')}.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler(LOG_FILE, encoding="utf-8"), logging.StreamHandler()]
)
log = logging.getLogger("ai_scoring_daemon")


def get_pending_items(limit: int = 20, min_content_len: int = 50, backfill: bool = False) -> List[Dict]:
    """获取待评分的条目(有内容,未评分)"""
    conn = sqlite3.connect(str(DB_PATH))
    
    if backfill:
        query = """
            SELECT id, title, COALESCE(content, '') as content,
                   platform, source, author, tags, category,
                   importance_score, value_level, published_at
            FROM cleaned_intelligence
            WHERE (ai_score_total IS NULL OR ai_score_total = 0)
              AND LENGTH(COALESCE(content, '')) >= ?
              AND title IS NOT NULL AND title != ''
            ORDER BY importance_score DESC
            LIMIT ?
        """
    else:
        today = date.today().isoformat()
        query = f"""
            SELECT id, title, COALESCE(content, '') as content,
                   platform, source, author, tags, category,
                   importance_score, value_level, published_at
            FROM cleaned_intelligence
            WHERE (ai_score_total IS NULL OR ai_score_total = 0)
              AND LENGTH(COALESCE(content, '')) >= ?
              AND title IS NOT NULL AND title != ''
              AND DATE(cleaned_at) = '{today}'
            ORDER BY importance_score DESC
            LIMIT ?
        """
    
    cur = conn.execute(query, (min_content_len, limit))
    cols = [d[0] for d in cur.description]
    items = [dict(zip(cols, r)) for r in cur.fetchall()]
    conn.close()
    return items


def score_via_llm_api(items: List[Dict]) -> List[Dict]:
    """通过LLM API做真正的AI六维评分"""
    if not items:
        return []
    
    cfg = {}
    cfg_path = HERMES / "config.yaml"
    if cfg_path.exists():
        try:
            import yaml
            with open(cfg_path) as f:
                cfg = yaml.safe_load(f) or {}
        except:
            pass
    
    api_key = os.environ.get("DEEPSEEK_API_KEY", "") or os.environ.get("OPENAI_API_KEY", "") or cfg.get("api", {}).get("key", "")
    if not api_key:
        log.warning("无API key, 无法做AI评分")
        return []
    
    api_url = cfg.get("api", {}).get("url", "https://api.deepseek.com/v1/chat/completions")
    model = cfg.get("api", {}).get("model", "deepseek-chat")
    
    candidates = []
    for item in items:
        title = (item.get("title", "") or "")[:150]
        content = (item.get("content", "") or "")[:400]
        platform = item.get("platform", "")
        candidates.append(f"[id:{item['id']}] ({platform}) {title} | {content[:100]}")
    
    candidates_text = "\n".join(candidates)
    
    prompt = f"""你是情报价值评估专家.请对每条情报做真正的AI内容理解评分.

评分维度(0-100总分):
| 维度 | 范围 | 评估标准 |
|------|------|---------|
| 稀缺性 | 0-30 | 独家/首发/一手信息 |
| 影响力 | 0-30 | 行业级变革(25-30)/公司级(15-24)/产品级(5-14)/一般(0-4) |
| 技术深度 | 0-20 | 有具体技术细节/数据对比(15-20)/有分析(8-14)/普通(0-7) |
| 时效性 | 0-10 | 24h内(9-10)/48h(7-8)/一周(4-6)/更旧(0-3) |
| 偏好匹配 | 0-10 | AI/IT/消费电子/新能源/军事/格斗/写真/开发者生态 |
| 来源可信度 | 0-10 | 官方/一手(9-10)/知名媒体(7-8)/普通媒体(4-6)/自媒体(0-3) |

严格输出JSON(不要markdown代码块,纯JSON对象):
{{"scores": [{{"id": 123, "scarcity":15, "impact":22, "tech_depth":12, "timeliness":8, "preference":7, "credibility":6, "summary":"一句话总结"}}]}}

候选(共{len(items)}条):
{candidates_text}"""

    payload = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.1, "max_tokens": 2000
    }).encode("utf-8")
    
    req = urllib.request.Request(api_url, data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
            "User-Agent": "HermesAI/1.0"
        })
    
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            resp_data = json.loads(resp.read().decode("utf-8"))
        
        ai_text = resp_data.get("choices", [{}])[0].get("message", {}).get("content", "")
        json_match = re.search(r'\{.*\}', ai_text, re.DOTALL)
        if not json_match:
            log.error(f"LLM返回无JSON: {ai_text[:200]}")
            return []
        
        result = json.loads(json_match.group())
        scores = result.get("scores", [])
        log.info(f"LLM返回 {len(scores)} 条评分结果")
        return scores
    except Exception as e:
        log.error(f"LLM API调用失败: {e}")
        return []


def save_scores(scores: List[Dict]) -> int:
    """保存AI评分结果到数据库"""
    conn = sqlite3.connect(str(DB_PATH))
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    saved = 0
    
    for s in scores:
        item_id = s.get("id")
        if not item_id:
            continue
        
        total = sum([
            s.get("scarcity", 0),
            s.get("impact", 0),
            s.get("tech_depth", 0),
            s.get("timeliness", 0),
            s.get("preference", 0),
            s.get("credibility", 0),
        ])
        
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
            reasoning,
            now,
            item_id,
        ))
        saved += 1
    
    conn.commit()
    conn.close()
    return saved


def main():
    backfill = False
    limit = 20
    
    if "--dry-run" in sys.argv:
        items = get_pending_items(limit=10, min_content_len=50)
        print(f"Dry-run: {len(items)} 条待评分")
        for i in items:
            print(f"  #{i['id']:>6} [{i['platform']:<15}] {i['title'][:50]} | content_len={len(i.get('content',''))}")
        return
    
    if "--backfill" in sys.argv:
        idx = sys.argv.index("--backfill")
        if idx + 1 < len(sys.argv):
            limit = int(sys.argv[idx + 1])
        backfill = True
        log.info(f"回填模式: 取{limit}条历史重要条目做AI评分")
    
    items = get_pending_items(limit=limit, min_content_len=50, backfill=backfill)
    if not items:
        log.info("无待评分条目")
        print("TASK_OK")
        return
    
    log.info(f"待评分 {len(items)} 条")
    
    scores = score_via_llm_api(items)
    if not scores:
        log.warning("AI评分未成功(无API key或API失败)")
        print("TASK_NO_API")
        return
    
    saved = save_scores(scores)
    log.info(f"已保存 {saved} 条AI评分")
    
    for s in scores:
        total = s.get("scarcity", 0) + s.get("impact", 0) + s.get("tech_depth", 0) + s.get("timeliness", 0) + s.get("preference", 0) + s.get("credibility", 0)
        summary = (s.get("summary", "") or "")[:60]
        log.info(f"  #{s.get('id','?')} -> {total}分 | {summary}")
    
    print(f"TASK_DONE:{saved}")


if __name__ == "__main__":
    main()
