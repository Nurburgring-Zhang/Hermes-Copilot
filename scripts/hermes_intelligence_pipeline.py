#!/usr/bin/env python3
"""
Hermes 智能情报→专家系统→记忆 数据管道 v2.0 (修复版)
基于实际数据库schema: cleaned_intelligence(id,title,content,url,source,value_level,importance_score,...)
"""

import os, sys, json, sqlite3, time, hashlib, logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Any, Tuple
from collections import defaultdict

# ============================================================================
# 路径
# ============================================================================
HERMES_DIR = Path("/home/administrator/.hermes")
INTELLIGENCE_DB = HERMES_DIR / "intelligence.db"
MEMORY_DIR = HERMES_DIR / "memory"
LOGS_DIR = HERMES_DIR / "logs"
PIPELINE_DIR = HERMES_DIR / "auto_run" / "intelligence_pipeline"
EXPERT_DIR = PIPELINE_DIR / "expert_domains"
TASK_DB = PIPELINE_DIR / "expert_consult_queue.db"
RAG_INDEX_DB = PIPELINE_DIR / "rag_memory_index.db"

for d in [PIPELINE_DIR, EXPERT_DIR, MEMORY_DIR, LOGS_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# ============================================================================
# 日志
# ============================================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOGS_DIR / f"pipeline_{datetime.now().strftime('%Y%m%d')}.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("pipeline")

# ============================================================================
# 数据库
# ============================================================================
def db_conn(path):
    c = sqlite3.connect(str(path), timeout=30)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    return c

# ============================================================================
# 20个Expert领域 + 关键词
# ============================================================================
EXPERT_DOMAINS = {
    "AI与机器学习": {
        "emoji": "🤖", "priority": 5,
        "keywords": ["ai","llm","大模型","深度学习","nlp","cv","强化学习","transformer",
                     "gpt","claude","gemini","openai","anthropic","huggingface","diffusion",
                     "agent","rag","fine-tuning","rlhf","multimodal","vlm","ollama","vllm",
                     "llama","mistral","deepseek","grok","r1","o3"," reasoning","chain-of-thought"]
    },
    "软件工程": {
        "emoji": "💻", "priority": 4,
        "keywords": ["架构","设计模式","微服务","devops","代码审查","重构","clean code",
                     "oop","functional","reactive","event-driven","ddd","cqrs","整洁架构",
                     "solid","rest api","grpc","kubernetes","docker","ci/cd","SOLID"]
    },
    "通信与网络": {
        "emoji": "📡", "priority": 3,
        "keywords": ["网络","协议","tcp","udp","http","websocket","5g","wifi","sdwan",
                     "sdn","nfv","光网络","卫星通信","量子通信","路由","交换","负载均衡",
                     "cdn","dns","bgp","mpls","vpn","tor","mesh"]
    },
    "安全与隐私": {
        "emoji": "🔒", "priority": 5,
        "keywords": ["安全","漏洞","渗透","加密","身份认证","零信任","威胁建模","xss",
                     "sql注入","csrf","oauth","jwt","tls","渗透测试","威胁情报","appsec",
                     "devsecops","waf","ids","ips","零日","cve","ransomware","malware"]
    },
    "产品与商业": {
        "emoji": "💼", "priority": 3,
        "keywords": ["产品战略","商业模式","市场分析","roadmap","prd","需求管理","用户研究",
                     "竞品分析","增长黑客","aarrr","pmf","商业画布","定价策略","saas",
                     "tob","toc","gmv","arpu","留存","转化率"]
    },
    "前端与用户体验": {
        "emoji": "🎨", "priority": 3,
        "keywords": ["前端","ui","ux","css","react","vue","angular","交互设计","可用性",
                     "可访问性","性能优化","响应式","typescript","tailwind","webpack","vite",
                     "svelte","solid","astro","next.js","nuxt"]
    },
    "数据与存储": {
        "emoji": "🗄️", "priority": 4,
        "keywords": ["数据库","sql","nosql","缓存","数据湖","etl","数据仓库","postgresql",
                     "mysql","mongodb","redis","elasticsearch","kafka","hadoop","spark",
                     "arrow","clickhouse","duckdb","sqlite","supabase","fauna"]
    },
    "云计算与基础设施": {
        "emoji": "☁️", "priority": 4,
        "keywords": ["云","aws","azure","gcp","serverless","iac","terraform","kubernetes",
                     "docker","helm","istio","服务网格","弹性伸缩","多云","边缘计算",
                     "cdn","lambda","cloudflare","vercel","netlify","fly.io"]
    },
    "DevOps与SRE": {
        "emoji": "🔧", "priority": 4,
        "keywords": ["devops","cicd","kubernetes","docker","监控","可观测性","sre","prometheus",
                     "grafana","jaeger","opentelemetry","日志聚合","告警","on-call","slo",
                     "alertmanager","argocd","tekton","github actions","gitlab ci"]
    },
    "质量与测试": {
        "emoji": "🧪", "priority": 2,
        "keywords": ["测试","qa","自动化测试","单元测试","性能测试","安全测试","集成测试",
                     "e2e","selenium","playwright","jest","pytest","tdd","bdd","覆盖率",
                     "压测","locust","k6","jmeter","chaos engineering"]
    },
    "管理与沟通": {
        "emoji": "📋", "priority": 2,
        "keywords": ["管理","沟通","团队协作","领导力","冲突调解","敏捷","scrum","看板",
                     "1on1","绩效管理","招聘","技术管理","项目经理","产品经理","okr","kpi"]
    },
    "数学与理论": {
        "emoji": "🔢", "priority": 3,
        "keywords": ["算法","优化","图论","概率论","信息论","博弈论","复杂系统","机器学习理论",
                     "统计学习","凸优化","线性代数","数值分析","密码学理论","分布式理论","cap"]
    },
    "移动与IoT": {
        "emoji": "📱", "priority": 3,
        "keywords": ["移动","ios","android","iot","嵌入式","传感器","物联网","蓝牙","zigbee",
                     "mqtt","arm","单片机","rtos","数字孪生","工业物联网","智能家居","鸿蒙"]
    },
    "内容与创意": {
        "emoji": "🎭", "priority": 2,
        "keywords": ["内容创作","创意","文案","品牌","营销","社交媒体","短视频","视频制作",
                     "数据可视化","交互叙事","游戏叙事","技术写作","文档","changelog"]
    },
    "艺术与设计": {
        "emoji": "🖼️", "priority": 2,
        "keywords": ["设计","视觉","ui","ux","品牌设计","插画","3d","动效设计","字体设计",
                     "配色","设计系统","photoshop","figma","sketch","blender","3d建模"]
    },
    "经济与金融": {
        "emoji": "💰", "priority": 2,
        "keywords": ["金融","投资","量化交易","风控","经济分析","区块链金融","defi","cex",
                     "期权","期货","固收","资产配置","基金","估值","财务报表","税务"]
    },
    "法律与伦理": {
        "emoji": "📜", "priority": 2,
        "keywords": ["法律","合规","伦理","隐私保护","知识产权","监管","gdpr","ccpa",
                     "数据保护","版权","专利","商标","合同法","风险投资法律"]
    },
    "生物与医学": {
        "emoji": "🩺", "priority": 2,
        "keywords": ["生物","医学","基因","药物","医疗器械","健康","生物信息","crispr",
                     "pcr","临床试验","fda","数字医疗","远程医疗","健康大数据"]
    },
    "物理与材料": {
        "emoji": "🔬", "priority": 2,
        "keywords": ["物理","材料","半导体","量子","纳米","能源材料","凝聚态物理","光电子",
                     "芯片制造","euv","光刻机","电池材料","光伏材料","超导材料"]
    },
    "哲学与人文": {
        "emoji": "📚", "priority": 1,
        "keywords": ["哲学","伦理","人文","社会学","心理学","认知科学","ai哲学","技术伦理",
                     "意识研究","语言哲学","形而上学","伦理学","政治哲学","美学"]
    }
}

# ============================================================================
# 获取情报 (基于真实schema)
# ============================================================================
def get_items(min_level: int, hours: int, limit: int) -> List[Dict]:
    items = []
    try:
        conn = db_conn(INTELLIGENCE_DB)
        c = conn.cursor()
        cutoff = (datetime.now() - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")
        c.execute("""
            SELECT id, title, url, source, content, value_level, importance_score, published_at, cleaned_at
            FROM cleaned_intelligence
            WHERE value_level >= ? AND cleaned_at >= ?
            ORDER BY value_level DESC, importance_score DESC, cleaned_at DESC
            LIMIT ?
        """, (min_level, cutoff, limit))
        for row in c.fetchall():
            items.append({
                "id": row[0],
                "title": row[1],
                "url": row[2],
                "source": row[3],
                "content": (row[4] or "")[:500],
                "value_level": row[5],
                "importance_score": row[6],
                "published_at": row[7],
                "cleaned_at": row[8],
                "tags": extract_tags(row[1], row[4] or "")
            })
        conn.close()
    except Exception as e:
        logger.error(f"[获取情报] {e}")
    return items

def extract_tags(title: str, content: str) -> List[str]:
    """从标题和内容中提取关键词标签"""
    text = f"{title} {content}".lower()
    tags = []
    tag_kw = {
        "rust": ["rust"],
        "typescript": ["typescript","ts"],
        "python": ["python","pytorch","pandas"],
        "go": ["golang","go "],
        "javascript": ["javascript","nodejs","node.js"],
        "ai/llm": ["llm","大模型","gpt","claude","gemini","openai","anthropic","deepseek","mistral","llama","ollama","vllm","agent","rag","fine-tuning","rlhf"],
        "架构": ["架构","architecture","微服务","microservice"],
        "开源": ["github","开源","open source"],
        "框架": ["框架","framework","react","vue","angular","django","fastapi"],
        "安全": ["安全","security","漏洞","渗透","加密"],
        "devops": ["docker","kubernetes","k8s","devops","cicd","terraform"],
        "数据库": ["数据库","sql","nosql","redis","postgresql","mysql"],
        "硬件": ["gpu","芯片","cpu","英伟达","amd","intel","苹果m"],
    }
    for tag, kws in tag_kw.items():
        for kw in kws:
            if kw.lower() in text and tag not in tags:
                tags.append(tag)
                break
    return tags[:8]

# ============================================================================
# Expert路由
# ============================================================================
def calc_domain_scores(title: str, content: str, tags: List[str]) -> Dict[str, float]:
    text = f"{title} {content}".lower()
    combined = " ".join([text] + [t.lower() for t in tags])
    scores = {}
    for domain, cfg in EXPERT_DOMAINS.items():
        score = 0.0
        for kw in cfg["keywords"]:
            k = kw.lower()
            if k in title.lower():
                score += 3.0
            if k in combined:
                score += 1.0
        if score > 0:
            scores[domain] = {"score": score, "priority": cfg["priority"]}
    return scores

def route_items(items: List[Dict]) -> Dict:
    logger.info(f"[路由] 开始路由 {len(items)} 条情报...")
    init_queue_db()
    conn = db_conn(TASK_DB)
    c = conn.cursor()
    
    routed = 0
    by_domain = defaultdict(int)
    by_level = defaultdict(int)
    
    for item in items:
        scores = calc_domain_scores(item["title"], item["content"], item["tags"])
        ranked = sorted(scores.items(), key=lambda x: (-x[1]["score"], -x[1]["priority"]))[:3]
        
        for domain, data in ranked:
            c.execute("""
                INSERT OR IGNORE INTO expert_consult_queue
                (intelligence_id, intelligence_title, intelligence_url, source,
                 value_level, matched_domain, match_score, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                item["id"], item["title"][:200], item["url"], item["source"],
                item["value_level"], domain, data["score"],
                datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            ))
            routed += 1
            by_domain[domain] += 1
            by_level[item["value_level"]] += 1
            
            # 写领域日记
            write_diary(item, domain, data)
    
    conn.commit()
    conn.close()
    logger.info(f"[路由] 完成: {routed}条路由到{len(by_domain)}个领域")
    return {"routed": routed, "by_domain": dict(by_domain), "by_level": dict(by_level)}

def write_diary(item: Dict, domain: str, data: Dict):
    domain_safe = domain.replace("与", "_").replace(" ", "_")
    d = EXPERT_DIR / domain_safe
    d.mkdir(exist_ok=True)
    f = d / f"{datetime.now().strftime('%Y%m%d')}.md"
    vl = int(item["value_level"]) if item["value_level"] else 0
    stars = "⭐" * vl
    content = f"""
## {item['cleaned_at'][:16]} | {item['title']}
**星级**: {stars} | **匹配**: {domain} {EXPERT_DOMAINS[domain]['emoji']} (score:{data['score']:.1f})
**来源**: {item['source']}
**标签**: {', '.join(item['tags'][:5])}
**摘要**: {item['content'][:200]}
**链接**: {item['url']}
---
"""
    with open(f, "a", encoding="utf-8") as fh:
        fh.write(content)

def init_queue_db():
    conn = db_conn(TASK_DB)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS expert_consult_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            intelligence_id INTEGER,
            intelligence_title TEXT,
            intelligence_url TEXT,
            source TEXT,
            value_level INTEGER,
            matched_domain TEXT,
            match_score REAL,
            status TEXT DEFAULT 'pending',
            created_at TEXT,
            processed_at TEXT,
            UNIQUE(intelligence_id, matched_domain)
        )
    """)
    conn.commit()
    conn.close()

# ============================================================================
# RAG记忆索引
# ============================================================================
def index_items(items: List[Dict]) -> Dict:
    logger.info(f"[RAG] 开始索引 {len(items)} 条...")
    init_rag_db()
    conn = db_conn(RAG_INDEX_DB)
    c = conn.cursor()
    
    indexed = 0
    by_domain = defaultdict(int)
    
    for item in items:
        scores = calc_domain_scores(item["title"], item["content"], item["tags"])
        ranked = sorted(scores.items(), key=lambda x: -x[1]["score"])
        primary = ranked[0][0] if ranked else "AI与机器学习"
        
        content_hash = hashlib.md5(f"{item['id']}{item['title']}".encode()).hexdigest()
        c.execute("""
            INSERT OR IGNORE INTO rag_index
            (intelligence_id, title, content, domain, value_level, tags, url, indexed_at, content_hash)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            item["id"], item["title"], item["content"],
            primary, item["value_level"], json.dumps(item["tags"]),
            item["url"], datetime.now().strftime("%Y-%m-%d %H:%M:%S"), content_hash
        ))
        
        # 写记忆文件
        write_memory(item, primary)
        
        indexed += 1
        by_domain[primary] += 1
    
    conn.commit()
    conn.close()
    logger.info(f"[RAG] 完成: {indexed}条索引")
    return {"indexed": indexed, "by_domain": dict(by_domain)}

def init_rag_db():
    conn = db_conn(RAG_INDEX_DB)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS rag_index (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            intelligence_id INTEGER UNIQUE,
            title TEXT, content TEXT, domain TEXT,
            value_level INTEGER, tags TEXT, url TEXT,
            indexed_at TEXT, content_hash TEXT
        )
    """)
    c.execute("CREATE INDEX IF NOT EXISTS idx_domain ON rag_index(domain)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_level ON rag_index(value_level)")
    conn.commit()
    conn.close()

def write_memory(item: Dict, domain: str):
    f = MEMORY_DIR / f"intelligence_{datetime.now().strftime('%Y-%m-%d')}.md"
    vl = int(item["value_level"]) if item["value_level"] else 0
    stars = "⭐" * vl
    content = f"""
## {item['cleaned_at'][:16]} | {stars} | {domain}
### {item['title']}
**来源**: {item['source']} | **标签**: {', '.join(item['tags'][:5])}
{item['content'][:300]}
**链接**: {item['url']}
---
"""
    with open(f, "a", encoding="utf-8") as fh:
        fh.write(content)

# ============================================================================
# 任务生成
# ============================================================================
def generate_tasks(items: List[Dict]) -> Dict:
    top_items = [i for i in items if i["value_level"] >= 5]
    if not top_items:
        logger.info("[任务] 无5星情报")
        return {"generated": 0, "tasks": []}
    
    tasks_dir = PIPELINE_DIR / "generated_tasks"
    tasks_dir.mkdir(exist_ok=True)
    
    generated = []
    for item in top_items:
        task_id = f"intel_{item['id']}_{int(time.time())}"
        task = {
            "id": task_id,
            "source": "intelligence",
            "intelligence_id": item["id"],
            "title": item["title"],
            "url": item["url"],
            "source_name": item["source"],
            "value_level": item["value_level"],
            "importance_score": item["importance_score"],
            "tags": item["tags"],
            "priority": "P0",
            "created_at": datetime.now().isoformat(),
            "status": "generated"
        }
        with open(tasks_dir / f"{task_id}.json", "w", encoding="utf-8") as f:
            json.dump(task, f, indent=2, ensure_ascii=False)
        generated.append(task)
        logger.info(f"[任务] {item['title'][:40]} → {task_id}")
    
    logger.info(f"[任务] 完成: {len(generated)}个")
    return {"generated": len(generated), "tasks": generated}

# ============================================================================
# 完整流程
# ============================================================================
def run_all() -> Dict:
    logger.info("=" * 60)
    logger.info("🔗 情报→专家→记忆 管道启动")
    logger.info("=" * 60)
    
    # 48小时内4+星情报
    items_4 = get_items(min_level=4, hours=48, limit=200)
    logger.info(f"[情报] 获取到{len(items_4)}条4+星情报")
    
    # 7天内5星情报
    items_5 = get_items(min_level=5, hours=168, limit=50)
    logger.info(f"[情报] 获取到{len(items_5)}条5星情报")
    
    # 全流程用4+星
    r1 = route_items(items_4)
    r2 = index_items(items_4)
    r3 = generate_tasks(items_5)
    
    logger.info("=" * 60)
    logger.info(f"✅ 完成: 路由{r1['routed']}条 | 索引{r2['indexed']}条 | 任务{r3['generated']}个")
    logger.info("=" * 60)
    
    return {"items_4": len(items_4), "items_5": len(items_5),
            "routing": r1, "indexing": r2, "tasks": r3}

# ============================================================================
# 统计
# ============================================================================
def get_stats() -> Dict:
    stats = {}
    try:
        conn = db_conn(INTELLIGENCE_DB)
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM cleaned_intelligence")
        stats["total_cleaned"] = c.fetchone()[0]
        c.execute("SELECT value_level, COUNT(*) FROM cleaned_intelligence GROUP BY value_level ORDER BY value_level DESC")
        stats["by_level"] = dict(c.fetchall())
        conn.close()
    except: pass
    
    try:
        if TASK_DB.exists():
            conn = db_conn(TASK_DB)
            c = conn.cursor()
            c.execute("SELECT COUNT(*) FROM expert_consult_queue")
            stats["total_routed"] = c.fetchone()[0]
            c.execute("SELECT matched_domain, COUNT(*) FROM expert_consult_queue GROUP BY matched_domain ORDER BY COUNT(*) DESC LIMIT 5")
            stats["top_domains"] = dict(c.fetchall())
            conn.close()
    except: pass
    
    try:
        if RAG_INDEX_DB.exists():
            conn = db_conn(RAG_INDEX_DB)
            c = conn.cursor()
            c.execute("SELECT COUNT(*) FROM rag_index")
            stats["total_indexed"] = c.fetchone()[0]
            conn.close()
    except: pass
    
    return stats

# ============================================================================
# Score Mode: 批量评分cleaned_intelligence未评分条目
# ============================================================================
def score_mode(limit: int = 200) -> Dict:
    """
    基于规则引擎的批量评分模式。
    查找cleaned_intelligence中ai_score_total为NULL或0且未评分的条目，计算六维评分。
    """
    result = {
        "mode": "score",
        "limit": limit,
        "processed": 0,
        "skipped": 0,
        "score_stats": {},
        "top_scores": [],
        "bottom_scores": []
    }
    
    conn = db_conn(INTELLIGENCE_DB)
    c = conn.cursor()
    
    # 查找未评分条目
    rows = c.execute("""
        SELECT id, title, COALESCE(content,'') as content, 
               source, platform, published_at
        FROM cleaned_intelligence
        WHERE (ai_score_total IS NULL OR ai_score_total = 0)
        AND (ai_score_reasoning IS NULL OR ai_score_reasoning = '')
        ORDER BY id ASC
        LIMIT ?
    """, (limit,)).fetchall()
    
    if not rows:
        result["skipped"] = 1
        result["message"] = "无未评分数据，cleaned_intelligence全部已评分"
        conn.close()
        return result
    
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    all_scores = []
    
    for row in rows:
        item_id = row['id']
        title = row['title'] or ''
        content = row['content'] or ''
        source = row['source'] or ''
        platform = row['platform'] or ''
        
        scores = calc_item_scores(title, content, source, platform)
        
        c.execute("""
            UPDATE cleaned_intelligence
            SET ai_score_scarcity=?,
                ai_score_impact=?,
                ai_score_tech_depth=?,
                ai_score_timeliness=?,
                ai_score_preference=?,
                ai_score_credibility=?,
                ai_score_total=?,
                importance_score=?,
                ai_score_reasoning=?,
                ai_scored_at=?
            WHERE id=?
        """, (
            scores['scarcity'], scores['impact'], scores['tech_depth'],
            scores['timeliness'], scores['preference'], scores['credibility'],
            scores['total'], scores['importance_score'],
            scores['reasoning_json'], now, item_id
        ))
        all_scores.append((item_id, scores['total'], title[:60]))
    
    conn.commit()
    conn.close()
    
    result["processed"] = len(all_scores)
    totals = [s[1] for s in all_scores]
    result["score_stats"] = {
        "min": min(totals) if totals else 0,
        "max": max(totals) if totals else 0,
        "avg": round(sum(totals) / len(totals), 1) if totals else 0,
        "lt40": sum(1 for t in totals if t < 40),
        "40_60": sum(1 for t in totals if 40 <= t < 60),
        "60_80": sum(1 for t in totals if 60 <= t < 80),
        "ge80": sum(1 for t in totals if t >= 80),
    }
    
    sorted_desc = sorted(all_scores, key=lambda x: -x[1])
    sorted_asc = sorted(all_scores, key=lambda x: x[1])
    result["top_scores"] = [{"id": sid, "score": sc, "title": t} for sid, sc, t in sorted_desc[:10]]
    result["bottom_scores"] = [{"id": sid, "score": sc, "title": t} for sid, sc, t in sorted_asc[:5]]
    
    return result


def calc_item_scores(title: str, content: str, source: str, platform: str) -> Dict:
    """
    六维评分规则引擎（移植自score_backlog_200.py）
    评分维度：稀缺性(0-30)、影响力(0-30)、技术深度(0-15)、时效性(0-10)、偏好(0-10)、可信度(0-5)
    """
    combined = (f"{title} {content}").lower()
    
    # --- 1. SCARCITY (0-30) ---
    scarcity = 10
    scarcity_reason = ""
    if any(kw in combined for kw in ['全球首', '业界首款', '第一个', '全球首个', '独家', 'world first', 'only one']):
        scarcity = 26
        scarcity_reason = "全球首发/独家报道"
    elif any(kw in combined for kw in ['首款', '首次', '首发', '里程碑', '首个']):
        scarcity = 18
        scarcity_reason = "首款/首次/里程碑"
    elif any(kw in combined for kw in ['泄露', '曝光', '独家', '提前', 'reveals', 'leak']):
        scarcity = 20
        scarcity_reason = "泄露/提前曝光"
    elif any(kw in combined for kw in ['报告', '调研', '白皮书']):
        scarcity = 14
        scarcity_reason = "行业报告/调研"
    else:
        scarcity = 10
        scarcity_reason = "常规信息"
    
    # --- 2. IMPACT (0-30) ---
    impact = 8
    impact_reason = ""
    if any(kw in combined for kw in ['改变格局', '颠覆', '变革', '全球最强', '没有之一', '引领', '跃迁']):
        impact = 24
        impact_reason = "改变格局/引领变革"
    elif any(kw in combined for kw in ['发布', '推出', '新品', '上线', '开源']):
        impact = 14
        impact_reason = "新品发布/产品推出"
    elif any(kw in combined for kw in ['收购', '融资', 'ipo', '上市', '投资']):
        impact = 16
        impact_reason = "资本运作/融资收购"
    elif any(kw in combined for kw in ['裁员', '关闭', '破产']):
        impact = 18
        impact_reason = "重大变动/裁员破产"
    else:
        impact = 8
        impact_reason = "常规信息"
    
    # --- 3. TECH DEPTH (0-15) ---
    tech_depth = 3
    tech_depth_reason = ""
    tech_terms = ['transformer', 'cnn', 'rnn', 'lstm', 'attention', 'diffusion', 'vae', 'gan',
                  'bert', 'gpt', 'llm', 'rag', 'fine-tuning', '强化学习', '深度学习', '神经网络',
                  'kubernetes', 'docker', '微服务', 'serverless', 'gpu', 'tpu', '算子', '量化',
                  '剪枝', '蒸馏', 'embedding', 'token', '参数', '算法', '架构', '协议']
    found_terms = [t for t in tech_terms if t in combined]
    if len(found_terms) >= 10:
        tech_depth = 13
        tech_depth_reason = f"含{len(found_terms)}项技术细节，深度技术内容"
    elif len(found_terms) >= 5:
        tech_depth = 8
        tech_depth_reason = f"含{len(found_terms)}项技术术语"
    elif len(found_terms) >= 1:
        tech_depth = 5
        tech_depth_reason = f"提及{len(found_terms)}项技术概念"
    else:
        tech_depth = 3
        tech_depth_reason = "无技术细节"
    
    # --- 4. TIMELINESS (0-10) ---
    timeliness = 5
    timeliness_reason = ""
    if any(kw in combined for kw in ['刚刚', '今日', '今天', '刚刚发布', '分钟前', '小时前']):
        timeliness = 9
        timeliness_reason = "今天/刚刚发布"
    elif any(kw in combined for kw in ['昨日', '昨天', '本周', '本周末']):
        timeliness = 7
        timeliness_reason = "昨天/本周"
    elif any(kw in combined for kw in ['本周', '本月', '上周']):
        timeliness = 5
        timeliness_reason = "本周/本月"
    else:
        timeliness = 5
        timeliness_reason = "无明确日期"
    
    # --- 5. PREFERENCE (0-10) ---
    preference = 5
    preference_reason = ""
    if any(kw in combined for kw in ['ai', '人工智能', '大模型', 'llm', 'gpt', 'deepseek']):
        preference = 8
        preference_reason = "AI/科技领域，格林主人高度关注"
    elif source and any(s in source.lower() for s in ['csdn', 'github', 'arxiv', 'huggingface']):
        preference = 7
        preference_reason = "技术平台来源"
    else:
        preference = 5
        preference_reason = "相关科技领域"
    
    # --- 6. CREDIBILITY (0-5) ---
    credibility = 3
    credibility_reason = ""
    trusted_sources = ['36kr', '虎嗅', '品玩', '极客公园', '界面', '财新', '第一财经',
                        '澎湃', '腾讯科技', '新浪科技', '网易科技', 'cnbeta', 'ithome',
                        'arxiv', 'github', 'huggingface', 'nature', 'ieee']
    if source and any(s in source.lower() for s in trusted_sources):
        credibility = 4
        credibility_reason = "可靠来源"
    elif platform and any(p in platform.lower() for p in ['news', 'tech', 'media']):
        credibility = 3
        credibility_reason = "一般平台来源"
    else:
        credibility = 2
        credibility_reason = "自媒体/个人来源"
    
    total = scarcity + impact + tech_depth + timeliness + preference + credibility
    importance_score = round(total / 10.0, 1)
    
    reasoning = {
        "scarcity_reason": scarcity_reason,
        "impact_reason": impact_reason,
        "tech_depth_reason": tech_depth_reason,
        "timeliness_reason": timeliness_reason,
        "preference_reason": preference_reason,
        "credibility_reason": credibility_reason,
        "scarcity": scarcity,
        "impact": impact,
        "tech_depth": tech_depth,
        "timeliness": timeliness,
        "preference": preference,
        "credibility": credibility,
        "total": total
    }
    
    return {
        "scarcity": scarcity,
        "impact": impact,
        "tech_depth": tech_depth,
        "timeliness": timeliness,
        "preference": preference,
        "credibility": credibility,
        "total": total,
        "importance_score": importance_score,
        "reasoning_json": json.dumps(reasoning, ensure_ascii=False)
    }


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--mode", choices=["all", "route", "index", "generate", "stats", "score"], default="stats")
    p.add_argument("--limit", type=int, default=200, help="评分模式每次处理的条目上限")
    args = p.parse_args()
    
    t0 = time.time()
    
    if args.mode == "all":
        result = run_all()
        print(json.dumps(result, indent=2, ensure_ascii=False))
    elif args.mode == "route":
        items = get_items(min_level=4, hours=48, limit=200)
        result = route_items(items)
        print(json.dumps(result, indent=2, ensure_ascii=False))
    elif args.mode == "index":
        items = get_items(min_level=4, hours=48, limit=200)
        result = index_items(items)
        print(json.dumps(result, indent=2, ensure_ascii=False))
    elif args.mode == "generate":
        items = get_items(min_level=5, hours=168, limit=50)
        result = generate_tasks(items)
        print(json.dumps(result, indent=2, ensure_ascii=False))
    elif args.mode == "stats":
        result = get_stats()
        print(json.dumps(result, indent=2, ensure_ascii=False))
    elif args.mode == "score":
        result = score_mode(limit=args.limit)
        print(json.dumps(result, indent=2, ensure_ascii=False))
    
    elapsed = time.time() - t0
    logger.info(f"⏱ 耗时: {elapsed:.1f}秒")
