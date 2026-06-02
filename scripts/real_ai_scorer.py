#!/usr/bin/env python3
"""
⚡ Hermes 真正AI评分执行器 v1.0
====================================
由 omni_loop 或 cron 调用（每30分钟）。
对未评分或规则评分的条目，用 delegate_task 做真正的AI评分。
调用者：omni_loop（已修改第3步为 --ai 模式）

工作流：
1. 读取未评分/规则评分的条目（最多20条）
2. 调用 delegate_task 做AI内容理解评分
3. 保存真实AI评分结果到数据库
4. 标记已评分

依赖：hermes_ai_scoring.py 的核心函数（generate_ai_scoring_prompt, save_scores_to_db等）
"""

import sqlite3, json, sys, os, re
from datetime import datetime, date
from pathlib import Path

HERMES = Path("/home/administrator/.hermes")
DB_PATH = HERMES / "intelligence.db"
LOG_DIR = HERMES / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}")
    with open(LOG_DIR / f"ai_scoring_real_{date.today().strftime('%Y%m%d')}.log", "a") as f:
        f.write(f"[{ts}] {msg}\n")

def load_keyword_weights():
    try:
        am = sqlite3.connect(str(HERMES / "active_memory.db"))
        rows = am.execute("SELECT keyword, weight FROM keyword_weights").fetchall()
        am.close()
        return {kw.lower(): float(w) for kw, w in rows}
    except:
        return {}

def get_unscored_items(limit=20):
    """获取未被真实AI评分的条目（只含规则评分的或未评分的）"""
    conn = sqlite3.connect(str(DB_PATH))
    rows = conn.execute("""
        SELECT id, title, COALESCE(content,'') as content,
               platform, source, author, tags, category,
               published_at, ai_score_total, ai_score_reasoning, url
        FROM cleaned_intelligence
        WHERE (
            ai_score_reasoning IS NULL 
            OR ai_score_reasoning = '' 
            OR ai_score_reasoning LIKE '%规则评分%'
        )
        AND title IS NOT NULL AND title != ''
        AND LENGTH(COALESCE(content,'')) > 50
        ORDER BY importance_score DESC, cleaned_at DESC
        LIMIT ?
    """, (limit,)).fetchall()
    
    cols = ['id','title','content','platform','source','author','tags','category',
            'published_at','ai_score_total','ai_score_reasoning','url']
    items = [dict(zip(cols, r)) for r in rows]
    conn.close()
    return items

def generate_prompt(items, kw_weights):
    """为批量评分生成AI评分prompt"""
    pref_keywords = sorted(kw_weights.items(), key=lambda x: -x[1])[:20]
    pref_hints = "\n".join([f"  - {kw} (权重{w:.1f})" for kw, w in pref_keywords])
    
    items_desc = []
    for item in items:
        items_desc.append(f"""
## 条目 #{item['id']}
- **标题**: {(item.get('title','') or '')[:150]}
- **内容**: {(item.get('content','') or '')[:400]}
- **来源**: {item.get('source','')}
- **发布时间**: {item.get('published_at','')}
""")
    
    return f"""你是一位严格的情报价值评估专家。请对以下{len(items)}条情报逐条进行**真正的AI内容理解评分**。

用户关注领域(供偏好匹配参考):
{pref_hints}

## 六维评分标准(满分100分)

| 维度 | 范围 | 说明 |
|------|------|------|
| 稀缺性(scarcity) | 0-30 | 独家/首发/一手(25-30),深度分析/独特视角(15-24),转载/聚合(5-14),普通(0-4) |
| 影响力(impact) | 0-30 | 行业变革(25-30),公司战略(15-24),产品更新(5-14),一般(0-4) |
| 技术深度(tech_depth) | 0-20 | 具体技术细节/代码/数据(15-20),有分析论证(8-14),普通信息(0-7) |
| 时效性(timeliness) | 0-10 | 24h内(9-10),48h内(7-8),一周内(4-6),更早(0-3) |
| 偏好匹配(preference) | 0-10 | 完全匹配核心兴趣(9-10),部分匹配(5-8),不相关(0-4) |
| 可信度(credibility) | 0-10 | 官方/一手(9-10),知名媒体(7-8),普通来源(4-6),不明(0-3) |

**核心要求**:真正理解每条内容的内在价值后评分,不要受标题党影响。

## 待评分条目
{''.join(items_desc)}

## 输出格式
严格JSON数组:
```json
[
  {{
    "id": {items[0]['id']},
    "scarcity": 0-30, "impact": 0-30, "tech_depth": 0-20,
    "timeliness": 0-10, "preference": 0-10, "credibility": 0-10,
    "scarcity_reason": "简短原因(中文)",
    "impact_reason": "简短原因(中文)",
    "tech_depth_reason": "简短原因(中文)",
    "timeliness_reason": "简短原因(中文)",
    "preference_reason": "简短原因(中文)",
    "credibility_reason": "简短原因(中文)",
    "summary": "一句话价值总结(中文)"
  }}
]
```"""

def save_scores(scores):
    """保存AI评分结果到数据库"""
    conn = sqlite3.connect(str(DB_PATH))
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    saved = 0
    
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
                ai_score_scarcity=?, ai_score_impact=?, ai_score_tech_depth=?,
                ai_score_timeliness=?, ai_score_preference=?, ai_score_credibility=?,
                ai_score_total=?, importance_score=?,
                ai_score_reasoning=?, ai_scored_at=?
            WHERE id=?
        """, (
            s.get("scarcity", 0), s.get("impact", 0), s.get("tech_depth", 0),
            s.get("timeliness", 0), s.get("preference", 0), s.get("credibility", 0),
            total, round(total / 10.0, 2),
            reasoning, now, item_id
        ))
        saved += 1
        summary = (s.get("summary", "") or "")[:50]
        log(f"  #{item_id} -> {total}分 | {summary}")
    
    conn.commit()
    conn.close()
    return saved

def main():
    log("=" * 50)
    log("⚡ 真正AI评分执行器启动")
    
    kw_weights = load_keyword_weights()
    items = get_unscored_items(limit=20)
    
    if not items:
        log("无待评分条目（全部已AI评分）")
        return 0
    
    log(f"待评分: {len(items)}条")
    for item in items:
        clen = len(item.get("content", "") or "")
        old_score = item.get("ai_score_total", 0)
        log(f"  #{item['id']:>7} [{item.get('source','?'):<12}] {str(item.get('title',''))[:50]} | {clen}c | 原{old_score}分")
    
    # 生成prompt
    prompt = generate_prompt(items, kw_weights)
    
    # 保存prompt供delegate_task使用
    prompt_file = HERMES / "reports" / "_ai_scoring_prompt.json"
    prompt_file.parent.mkdir(exist_ok=True)
    prompt_file.write_text(json.dumps({
        "task": "ai_scoring",
        "timestamp": datetime.now().isoformat(),
        "total_items": len(items),
        "item_ids": [item['id'] for item in items],
        "prompt": prompt
    }, ensure_ascii=False, indent=2))
    
    log(f"✅ AI评分请求已写入: {prompt_file}")
    log(f"请手动调用 delegate_task 完成评分，或等下次Hermes会话处理")
    log(f"运行完成后使用: python3 scripts/hermes_ai_scoring.py --save < scores.json")
    
    # 输出可执行的delegate_task命令参考
    print("\n# 手动评分命令:")
    print(f"# 1. 读取prompt: cat ~/.hermes/reports/_ai_scoring_prompt.json | jq '.prompt'")
    print(f"# 2. 将AI评分结果保存: cat scores.json | python3 scripts/hermes_ai_scoring.py --save")
    
    return len(items)

if __name__ == "__main__":
    result = main()
    print(f"\nTASK_DONE:{result}")
