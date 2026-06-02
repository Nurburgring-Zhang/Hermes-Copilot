#!/usr/bin/env python3
"""
gbrain_bridge.py — GBrain 知识图谱桥接
为 Hermes 提供类似 gbrain 的知识检索能力：
  1. 实体搜索 (搜索 people/companies/concepts)
  2. 关系查询 (实体间的关系链路)
  3. 知识合成 (多源信息合并输出摘要)

不依赖 gbrain 的 bun/Node.js 运行时，纯 Python 实现。
数据源：intelligence.db + active_memory.db + reports/
"""

import json, sqlite3, re, os, sys
from pathlib import Path
from datetime import datetime, timedelta

HERMES = Path.home() / ".hermes"

# ============================================================
# 实体提取
# ============================================================
COMMON_ENTITIES = {
    # AI/科技公司
    "openai": "company", "anthropic": "company", "google": "company",
    "microsoft": "company", "meta": "company", "deepseek": "company",
    "nous research": "company", "mistral": "company", "xai": "company",
    # 产品
    "gpt": "product", "claude": "product", "gemini": "product",
    "hermes": "product", "codex": "product", "dalle": "product",
    "sora": "product", "qwen": "product",
    # 人
    "sam altman": "person", "elon musk": "person", "garry tan": "person",
    # 概念
    "llm": "concept", "rag": "concept", "agent": "concept",
    "transformer": "concept", "diffusion": "concept",
}

def extract_entities(text: str) -> list:
    """从文本中提取实体"""
    found = set()
    text_lower = text.lower()
    for name, etype in COMMON_ENTITIES.items():
        if name in text_lower:
            found.add((name, etype))
    # 匹配大写短语 (可能的人名/公司名)
    for m in re.finditer(r'\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+\b', text):
        phrase = m.group().strip().lower()
        if phrase not in COMMON_ENTITIES and len(phrase.split()) >= 2:
            found.add((phrase, "unknown"))
    return [{"name": n, "type": t} for n, t in found]

# ============================================================
# 知识搜索
# ============================================================
def search_knowledge(query: str, limit: int = 10) -> dict:
    """搜索知识图谱 — 检索情报DB+记忆DB"""
    results = {"query": query, "entities": [], "articles": [], "memories": []}
    
    # 1. 提取实体
    results["entities"] = extract_entities(query)
    
    # 2. 搜索情报DB
    try:
        db = sqlite3.connect(str(HERMES / "intelligence.db"))
        db.row_factory = sqlite3.Row
        rows = db.execute("""
            SELECT title, content, url, source, platform, ai_score_total, collected_at
            FROM cleaned_intelligence
            WHERE (title LIKE ? OR content LIKE ?) AND ai_score_total >= 40
            ORDER BY ai_score_total DESC LIMIT ?
        """, (f'%{query}%', f'%{query}%', limit)).fetchall()
        for r in rows:
            results["articles"].append({
                "title": r["title"], "snippet": (r["content"] or "")[:200],
                "source": r["source"], "platform": r["platform"],
                "score": r["ai_score_total"], "url": r["url"]
            })
        db.close()
    except: pass
    
    # 3. 搜索记忆DB
    try:
        db = sqlite3.connect(str(HERMES / "active_memory.db"))
        db.row_factory = sqlite3.Row
        rows = db.execute("""
            SELECT fact, cat, confidence FROM memory_semantic
            WHERE (fact LIKE ? OR keywords LIKE ?) AND active=1
            ORDER BY confidence DESC LIMIT ?
        """, (f'%{query}%', f'%{query}%', limit)).fetchall()
        for r in rows:
            results["memories"].append({
                "fact": r["fact"], "category": r["cat"],
                "confidence": r["confidence"]
            })
        db.close()
    except: pass
    
    return results

# ============================================================
# 关系查询
# ============================================================
def query_relations(entity: str) -> dict:
    """查询实体间关系"""
    results = {"entity": entity, "relations": [], "related_entities": []}
    # 从语义记忆中提取关联事实
    try:
        db = sqlite3.connect(str(HERMES / "active_memory.db"))
        cur = db.cursor()
        cur.execute("SELECT fact, cat, confidence FROM memory_semantic WHERE fact LIKE ? AND active=1 ORDER BY confidence DESC LIMIT 20",
                    (f'%{entity}%',))
        for r in cur.fetchall():
            results["relations"].append({"fact": r[0], "category": r[1], "confidence": r[2]})
        db.close()
    except: pass
    return results

# ============================================================
# 知识合成
# ============================================================
def synthesize(topic: str) -> dict:
    """多源信息合并输出摘要"""
    knowledge = search_knowledge(topic, limit=15)
    relations = query_relations(topic)
    
    synthesis = {"topic": topic, "entity_count": len(knowledge["entities"]),
                 "articles_found": len(knowledge["articles"]),
                 "memory_facts": len(knowledge["memories"]),
                 "relations_found": len(relations["relations"])}
    
    if knowledge["entities"]:
        synthesis["entities"] = [e["name"] for e in knowledge["entities"]]
    if knowledge["articles"]:
        synthesis["top_article"] = knowledge["articles"][0]["title"]
        synthesis["sources"] = list(set(a["source"] for a in knowledge["articles"] if a.get("source")))
    
    return synthesis


# ============================================================
# CLI
# ============================================================
def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "help"
    
    if cmd == "search":
        query = " ".join(sys.argv[2:])
        result = search_knowledge(query)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    
    elif cmd == "relations":
        entity = " ".join(sys.argv[2:])
        result = query_relations(entity)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    
    elif cmd == "synthesize":
        topic = " ".join(sys.argv[2:])
        result = synthesize(topic)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    
    elif cmd == "extract":
        text = sys.stdin.read()
        entities = extract_entities(text)
        print(json.dumps(entities, ensure_ascii=False, indent=2))
    
    else:
        print("""
GBrain Bridge — 知识图谱桥接
用法:
  gbrain_bridge.py search <query>         搜索知识
  gbrain_bridge.py relations <entity>     查询实体关系
  gbrain_bridge.py synthesize <topic>     知识合成
  gbrain_bridge.py extract                从stdin提取实体
""")


if __name__ == "__main__":
    main()
