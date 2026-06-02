#!/usr/bin/env python3
"""
Hermes 向量嵌入引擎 v1.0 (Production)
===================================
为memory_semantic生成向量嵌入,实现语义向量搜索。
使用Python stdlib的hash + SQLite FTS5实现轻量级向量索引。

运行方式:
  python3 hermes_vector_engine.py --index      # 为所有语义记忆生成向量
  python3 hermes_vector_engine.py --search "关键词"  # 向量搜索
  python3 hermes_vector_engine.py --status     # 查看状态
"""

import sqlite3, json, sys, os, hashlib, struct
from datetime import datetime
from pathlib import Path

HERMES = Path("/home/administrator/.hermes")
DB = HERMES / "active_memory.db"
LOG = HERMES / "logs" / "vector_engine.log"

# 嵌入维度:使用64位hash特征(轻量级,不依赖外部模型)
EMBEDDING_DIM = 64

def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")

def get_conn():
    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row
    return conn

def text_to_vector(text: str) -> list:
    """将文本转换为64维hash特征向量"""
    vector = [0.0] * EMBEDDING_DIM
    words = text.lower().split()
    if not words:
        return vector
    for word in words:
        h = hashlib.md5(word.encode("utf-8")).digest()
        for i in range(min(8, len(h))):
            idx = (h[i] ^ (h[i] << 1)) % EMBEDDING_DIM
            vector[idx] += 1.0
    # 归一化
    norm = sum(v*v for v in vector) ** 0.5
    if norm > 0:
        vector = [v/norm for v in vector]
    return vector

def compute_similarity(v1: list, v2: list) -> float:
    """余弦相似度"""
    dot = sum(a*b for a,b in zip(v1,v2))
    n1 = sum(a*a for a in v1) ** 0.5
    n2 = sum(b*b for b in v2) ** 0.5
    if n1 * n2 == 0:
        return 0.0
    return dot / (n1 * n2)

def index_all():
    """为所有memory_semantic生成向量嵌入"""
    conn = get_conn()
    c = conn.cursor()
    
    count = 0
    facts = c.execute("SELECT rowid, id, fact, cat, confidence FROM memory_semantic WHERE active=1").fetchall()
    
    # 先清空旧向量(增量重建)
    c.execute("DELETE FROM memory_vectors")
    
    for fact in facts:
        text = f"{fact['fact']} {fact['cat']}"
        vector = text_to_vector(text)
        vector_blob = struct.pack(f"{EMBEDDING_DIM}f", *vector)
        
        # 用rowid作为整数entry_id
        entry_id = fact['rowid']
        c.execute("""
            INSERT INTO memory_vectors (entry_id, vector, model, created_at)
            VALUES (?, ?, 'hash64_v1', datetime('now'))
        """, (entry_id, vector_blob))
        count += 1
    
    conn.commit()
    log(f"✅ 向量索引完成: {count}条")
    conn.close()
    return count

def search(query: str, top_k: int = 5):
    """向量搜索:按语义相似度排序"""
    conn = get_conn()
    c = conn.cursor()
    
    query_vec = text_to_vector(query)
    
    # 加载所有向量
    rows = c.execute("""
        SELECT mv.id, mv.entry_id, mv.vector, ms.fact, ms.cat, ms.confidence
        FROM memory_vectors mv
        JOIN memory_semantic ms ON mv.entry_id = ms.id
        WHERE ms.active = 1
    """).fetchall()
    
    scored = []
    for row in rows:
        vec = struct.unpack(f"{EMBEDDING_DIM}f", row['vector'])
        sim = compute_similarity(query_vec, vec)
        scored.append((sim, row['fact'], row['cat'], row['confidence']))
    
    scored.sort(key=lambda x: -x[0])
    
    print(f"\n🔍 向量搜索: '{query}'")
    print(f"  找到 {len([s for s in scored if s[0] > 0.1])} 条相关记忆\n")
    for sim, fact, cat, conf in scored[:top_k]:
        if sim > 0.1:
            print(f"  [{cat:15s}] sim={sim:.3f} conf={conf:.2f}")
            print(f"    {fact[:70]}")
    
    return scored[:top_k]

def status():
    conn = get_conn()
    c = conn.cursor()
    
    vec_count = c.execute("SELECT COUNT(*) FROM memory_vectors").fetchone()[0]
    sem_count = c.execute("SELECT COUNT(*) FROM memory_semantic WHERE active=1").fetchone()[0]
    sem_total = c.execute("SELECT COUNT(*) FROM memory_semantic").fetchone()[0]
    
    print(f"语义记忆: {sem_count}条活跃 / {sem_total}条总计")
    print(f"向量索引: {vec_count}条")
    
    coverage = f"{vec_count/sem_count*100:.0f}%" if sem_count > 0 else "N/A"
    print(f"覆盖率: {coverage}")
    
    if vec_count > 0:
        # 搜索示例
        search("AI 人工智能 机器学习", top_k=3)
    
    conn.close()

def main():
    action = sys.argv[1] if len(sys.argv) > 1 else "status"
    
    if action == "--index":
        log("开始向量索引...")
        n = index_all()
        print(f"✅ 为 {n} 条语义记忆生成向量嵌入")
    
    elif action == "--search":
        query = " ".join(sys.argv[2:]) if len(sys.argv) > 2 else "AI"
        search(query)
    
    elif action == "--status":
        status()
    
    else:
        print(f"用法: {sys.argv[0]} [--index|--search <query>|--status]")

if __name__ == "__main__":
    main()
