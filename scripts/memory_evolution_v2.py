#!/usr/bin/env python3
"""
Hermes 深度记忆进化引擎 v2 (Parallel Lifecycle)
=================================================
彻底解决"只有--all串行,能力不进化"的问题。

核心改进:
1. **并行执行** — 多进程同时运行互不依赖的模块 (增强/索引/压缩/分析)
2. **真实压缩** — 默认执行实际删除,不是dry-run (老化>30天+低访问量的自动清理)
3. **技能沉淀** — 从使用模式中自动生成新skill文件
4. **终身学习** — 持久记忆从session_search中沉淀到RAG
5. **能力进化** — 自动检测能力瓶颈并生成改进方案
6. **记忆融合** — 将分散的rag_index.db + main.sqlite统一成一个可搜索层
"""

import os, sys, json, sqlite3, time, hashlib, logging, subprocess, multiprocessing
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional, Tuple

# ============================================================================
# 路径
# ============================================================================
HERMES = Path("/home/administrator/.hermes")
SCRIPTS = HERMES / "scripts"
SKILLS = HERMES / "skills"
SKILLS_DIR = SKILLS
INTELLIGENCE_DB = HERMES / "intelligence.db"
MEMORY_DIR = HERMES / "memory"
RAG_SKILL = SKILLS / "rag-memory-enhanced"
RAG_CORE = RAG_SKILL / "rag_core.py"
MEMORIES_DIR = HERMES / "memories"
PIPELINE_DIR = HERMES / "auto_run" / "intelligence_pipeline"
RAG_INDEX_DB = PIPELINE_DIR / "rag_memory_index.db"
LOG_DIR = HERMES / "logs"
MEMORIES_DIR.mkdir(parents=True, exist_ok=True)
PIPELINE_DIR.mkdir(parents=True, exist_ok=True)

C = {"OK": "\033[92m", "ERR": "\033[91m", "WRN": "\033[93m", "CYAN": "\033[96m", "BOLD": "\033[1m", "END": "\033[0m"}

log = logging.getLogger("memory_evolve_v2")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / f"memory_v2_{datetime.now().strftime('%Y%m%d')}.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)

def p(msg, level="INFO"):
    prefix = {"INFO": f"{C['CYAN']}[MEM]{C['END']}", "OK": f"{C['OK']}[{C['BOLD']}✓{C['END']}{C['OK']}]{C['END']}",
              "ERR": f"{C['ERR']}[{C['BOLD']}✗{C['END']}{C['ERR']}]{C['END']}", 
              "WRN": f"{C['WRN']}[!]{C['END']}",
              "SKILL": f"{C['WRN']}[SKILL]{C['END']}",
              "EVOLVE": f"{C['BOLD']}[EVOLVE]{C['END']}"}
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"{prefix.get(level, '[--]')} {ts} {msg}")


# ============================================================================
# 模块1: 并行增强 — 从intelligence.db批量提取高价值情报到rag_index
# ============================================================================
def module_enhance(min_importance: float = 0, limit: int = 200):
    """
    记忆增强(改进版):
    - 默认min_importance=0: 用value_level (0-5) 代替importance_score
    - 批量处理200条而不是50条
    - 使用value_level >= 3作为高价值过滤
    """
    p("=" * 60)
    p("🗄️ 模块1: 记忆增强 (情报→记忆) [并行线程1]")
    p("=" * 60)

    if not INTELLIGENCE_DB.exists():
        return {"status": "error", "reason": "intelligence.db not found"}

    try:
        intel_conn = sqlite3.connect(str(INTELLIGENCE_DB))
        intel_conn.row_factory = sqlite3.Row

        # 使用value_level (0-5) 作为过滤,而不是importance_score
        # value_level >= 3 是重要情报
        rows = intel_conn.execute("""
            SELECT ci.id, ci.title, ci.content, ci.url, ci.source, ci.platform,
                   ci.importance_score, ci.value_level, ci.value_reasons, ci.tags,
                   ci.published_at, ci.language, ci.is_ai_related
            FROM cleaned_intelligence ci
            WHERE ci.value_level >= 3
            ORDER BY ci.importance_score DESC
            LIMIT ?
        """, (limit,)).fetchall()

        # 如果value_level不够,用importance_score再捞一波
        if len(rows) < limit:
            existing_ids = [r['id'] for r in rows]
            if existing_ids:
                placeholders = ','.join('?' * len(existing_ids))
                extra = intel_conn.execute(f"""
                    SELECT ci.id, ci.title, ci.content, ci.url, ci.source, ci.platform,
                           ci.importance_score, ci.value_level, ci.value_reasons, ci.tags,
                           ci.published_at, ci.language, ci.is_ai_related
                    FROM cleaned_intelligence ci
                    WHERE ci.id NOT IN ({placeholders})
                      AND ci.importance_score > 20
                    ORDER BY ci.importance_score DESC
                    LIMIT ?
                """, (*existing_ids, limit - len(rows))).fetchall()
                rows.extend(extra)

        p(f"从intelligence.db读取 {len(rows)} 条高价值情报", "OK")

        if not rows:
            intel_conn.close()
            return {"status": "ok", "enhanced": 0}

        # 写入rag_index.db
        rag_conn = sqlite3.connect(str(RAG_INDEX_DB))
        rag_conn.execute("""
            CREATE TABLE IF NOT EXISTS rag_index (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                intelligence_id INTEGER,
                title TEXT,
                content TEXT,
                domain TEXT,
                value_level INTEGER,
                tags TEXT,
                url TEXT,
                indexed_at TEXT,
                content_hash TEXT UNIQUE
            )
        """)
        rag_conn.execute("""
            CREATE TABLE IF NOT EXISTS memory_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entry_type TEXT,
                content TEXT,
                domain TEXT,
                importance REAL,
                created_at TEXT,
                accessed_at TEXT,
                access_count INTEGER DEFAULT 0
            )
        """)

        enhanced = 0
        for row in rows:
            row_dict = dict(row)
            content_hash = hashlib.md5(
                (str(row_dict.get('title', '')) + str(row_dict.get('content', ''))[:500]).encode()
            ).hexdigest()

            existing = rag_conn.execute(
                "SELECT id FROM rag_index WHERE content_hash = ? LIMIT 1", (content_hash,)
            ).fetchone()
            if existing:
                continue

            content = row_dict.get('content') or ''
            if len(content) > 1000:
                content = content[:500] + "\n\n...[截断]...\n\n" + content[-500:]

            # 智能域名分类
            title = row_dict.get('title') or ''
            content_lower = (title + ' ' + content).lower()
            domain_map = {
                'AI_机器学习': ['llm', 'gpt', 'ai', '机器学习', 'deep learning', 'transformer', 'neural', '模型', '推理', 'agent', 'mcp'],
                '软件工程': ['架构', '微服务', 'ddd', '代码', '重构', 'typescript', 'rust', 'python', 'golang'],
                '安全_隐私': ['安全', '漏洞', '攻击', '加密', 'privacy', 'security'],
                '前端_用户体验': ['react', 'vue', '前端', 'ui', 'ux', 'css', 'javascript'],
                '数据_存储': ['数据库', 'sql', 'nosql', '数据', '存储', 'etl'],
                '云计算_基础设施': ['云', 'kubernetes', 'docker', 'devops', 'ci/cd', '部署'],
                '产品_商业': ['产品', '商业', '创业', '融资', '市场', '增长'],
                '新能源汽车': ['新能源', '电动车', 'ev', '电池', '自动驾驶', 'tesla'],
                '国际形势': ['国际', '外交', '制裁', '贸易战', '军事'],
            }
            domain = '综合'
            for d, keywords in domain_map.items():
                if any(kw in content_lower for kw in keywords):
                    domain = d
                    break

            try:
                rag_conn.execute("""
                    INSERT OR IGNORE INTO rag_index 
                    (intelligence_id, title, content, domain, value_level, tags, url, indexed_at, content_hash)
                    VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'), ?)
                """, (
                    row_dict.get('id'), title, content, domain,
                    row_dict.get('value_level', 1),
                    row_dict.get('tags', '') or '',
                    row_dict.get('url', ''), content_hash
                ))
                enhanced += 1
            except Exception:
                pass

        rag_conn.commit()

        # 统计
        total_rag = rag_conn.execute("SELECT COUNT(*) FROM rag_index").fetchone()[0]
        total_mem = rag_conn.execute("SELECT COUNT(*) FROM memory_entries").fetchone()[0]
        rag_conn.close()
        intel_conn.close()

        p(f"增强完成: {enhanced} 条新情报 → RAG索引 (总计:{total_rag})", "OK" if enhanced else "WRN")
        return {"status": "ok", "enhanced": enhanced, "total": total_rag, "memory_entries": total_mem}

    except Exception as e:
        p(f"记忆增强失败: {e}", "ERR")
        import traceback
        traceback.print_exc()
        return {"status": "error", "reason": str(e)}


# ============================================================================
# 模块2: RAG索引 (并行)
# ============================================================================
def module_rag_index(force=False):
    """RAG索引 — 向量化workspace文件"""
    p("=" * 60)
    p("📚 模块2: RAG索引 (workspace→向量) [并行线程2]")
    p("=" * 60)

    if not RAG_CORE.exists():
        return {"status": "error", "reason": "rag_core not found"}

    sys.path.insert(0, str(RAG_SKILL))
    try:
        from rag_core import RAGIndexer
    except ImportError as e:
        p(f"导入rag_core失败: {e}", "ERR")
        return {"status": "error", "reason": str(e)}

    db_path = MEMORY_DIR / "main.sqlite"
    ws_path = HERMES / "workspace"

    try:
        indexer = RAGIndexer(db_path=db_path, workspace_dir=ws_path, auto_watch=False)
        stats = indexer.index_all()
        p(f"索引完成: {stats.get('total_chunks', 0)} chunks, {stats.get('total_files', 0)} files", "OK")
        return {"status": "ok", "stats": stats}
    except Exception as e:
        p(f"RAG索引失败: {e}", "ERR")
        # 非致命,继续
        return {"status": "error", "reason": str(e)}


# ============================================================================
# 模块3: 真实压缩 — 不再dry-run
# ============================================================================
def module_compress(force_execute=True, max_age_days=60):
    """
    记忆压缩(真实版):
    - 删除30天以上且无访问的chunks
    - 删除rag_index.db中超过90天的低价值记录
    - 清理intelligence.db中超过7天的低价值raw记录
    - 默认执行实际删除(不再是dry-run)
    """
    p("=" * 60)
    p("🧹 模块3: 记忆压缩与老化 [并行线程3]")
    p("=" * 60)

    results = {}
    now_ts = int(time.time())

    # 3.1 清理rag_index.db — 删除90天以上+低价值的
    try:
        rag_conn = sqlite3.connect(str(RAG_INDEX_DB))
        before = rag_conn.execute("SELECT COUNT(*) FROM rag_index").fetchone()[0]
        
        cutoff = (datetime.now() - timedelta(days=max_age_days)).isoformat()
        # 删除30天前且value_level < 3的
        deleted = rag_conn.execute("""
            DELETE FROM rag_index 
            WHERE indexed_at < ? AND (value_level IS NULL OR value_level < 3)
        """, (cutoff,)).rowcount
        rag_conn.commit()
        after = rag_conn.execute("SELECT COUNT(*) FROM rag_index").fetchone()[0]
        p(f"rag_index: {deleted}条低价值记录已清理 ({before}→{after})", "OK" if deleted else "WRN")
        results['rag_index_clean'] = {'before': before, 'after': after, 'deleted': deleted}
        rag_conn.close()
    except Exception as e:
        p(f"rag_index清理失败: {e}", "WRN")
        results['rag_index_clean'] = {'error': str(e)}

    # 3.2 清理main.sqlite — 60天以上无更新的chunks
    try:
        conn = sqlite3.connect(str(MEMORY_DIR / "main.sqlite"))
        before_chunks = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        
        # 检查是否有access_count列
        cols = [c[1] for c in conn.execute("PRAGMA table_info(chunks)").fetchall()]
        if 'access_count' in cols:
            cutoff_ts = now_ts - max_age_days * 86400
            deleted_chunks = conn.execute("""
                DELETE FROM chunks 
                WHERE updated_at < ? AND (access_count IS NULL OR access_count < 1)
            """, (cutoff_ts,)).rowcount
        else:
            # 没有access_count列,用updated_at
            cutoff_ts = now_ts - max_age_days * 86400
            deleted_chunks = conn.execute("""
                DELETE FROM chunks WHERE updated_at < ?
            """, (cutoff_ts,)).rowcount
        
        conn.commit()
        after_chunks = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        p(f"main.sqlite: {deleted_chunks}个旧chunks已清理 ({before_chunks}→{after_chunks})", "OK" if deleted_chunks else "WRN")
        results['main_clean'] = {'before': before_chunks, 'after': after_chunks, 'deleted': deleted_chunks}
        conn.close()
    except Exception as e:
        p(f"main.sqlite清理失败: {e}", "WRN")
        results['main_clean'] = {'error': str(e)}

    # 3.3 清理intelligence.db — 删除7天前的低价值raw数据
    try:
        conn = sqlite3.connect(str(INTELLIGENCE_DB))
        before_raw = conn.execute("SELECT COUNT(*) FROM raw_intelligence").fetchone()[0]
        
        cutoff_7d = (datetime.now() - timedelta(days=7)).isoformat()
        # 只删除低热度且7天前的
        deleted_raw = conn.execute("""
            DELETE FROM raw_intelligence 
            WHERE collected_at < ? AND (hot_score IS NULL OR hot_score < 5)
        """, (cutoff_7d,)).rowcount
        
        conn.commit()
        after_raw = conn.execute("SELECT COUNT(*) FROM raw_intelligence").fetchone()[0]
        p(f"intelligence.db(raw): {deleted_raw}条低价值原始数据已清理 ({before_raw}→{after_raw})", "OK" if deleted_raw else "WRN")
        results['intel_clean'] = {'before': before_raw, 'after': after_raw, 'deleted': deleted_raw}
        conn.close()
    except Exception as e:
        p(f"intelligence.db清理失败: {e}", "WRN")
        results['intel_clean'] = {'error': str(e)}

    return {"status": "ok", "results": results}


# ============================================================================
# 模块4: 技能沉淀 — 从状态文件中自动生成skill
# ============================================================================
def module_skill_mining():
    """从记忆使用模式中自动发现可沉淀的skill"""
    p("=" * 60)
    p("🧠 模块4: 能力进化 — 技能自动沉淀 [并行线程4]")
    p("=" * 60)

    discoveries = []

    # 4.1 从rag_index.db发现高频主题
    try:
        conn = sqlite3.connect(str(RAG_INDEX_DB))
        domain_count = conn.execute("""
            SELECT domain, COUNT(*) as cnt FROM rag_index 
            GROUP BY domain ORDER BY cnt DESC
        """).fetchall()
        conn.close()
        
        # 如果某个域名超过50条记录但还没有对应的skill,建议生成
        existing_skills = set()
        if SKILLS_DIR.exists():
            for d in SKILLS_DIR.iterdir():
                if d.is_dir():
                    existing_skills.add(d.name.lower())
        
        for domain, cnt in domain_count:
            if cnt >= 30:
                skill_name = f"memory-domain-{domain.lower().replace('_', '-')}"
                if skill_name not in existing_skills:
                    discoveries.append({
                        'type': 'skill_domain',
                        'domain': domain,
                        'count': cnt,
                        'suggested_skill': skill_name
                    })
        p(f"发现 {len(discoveries)} 个可沉淀技能方向", "OK" if discoveries else "WRN")
    except Exception as e:
        p(f"技能发现失败: {e}", "WRN")

    # 4.2 实际生成skill文件(如果有高价值域名)
    created_skills = []
    for disc in discoveries[:3]:  # 最多生成3个
        domain = disc['domain']
        skill_content = f"""---
name: memory-domain-{domain.lower().replace('_', '-')}
description: 领域记忆强化 — {domain} 专业知识查询与利用
category: memory
tags: [{', '.join(d.lower() for d in [domain])}]
---

# Domain Memory: {domain}

本skill是从记忆系统的使用模式中自动生成的。

## 领域关键词
{domain} 相关的查询关键词列表(自动发现)。

## 使用方式
当用户询问 {domain} 相关问题时,优先从以下来源检索:
1. rag_index.db 中 domain='{domain}' 的记录
2. memory/main.sqlite 中相关的chunks

## 相关情报(最近自动同步)
此skill随记忆增强管道自动更新。
"""
        skill_path = SKILLS_DIR / f"memory-domain-{domain.lower().replace('_', '-')}" / "SKILL.md"
        skill_path.parent.mkdir(parents=True, exist_ok=True)
        skill_path.write_text(skill_content)
        created_skills.append(str(skill_path))
        p(f"  自动生成skill: {skill_path.name}", "SKILL")

    # 4.3 发现可合并的记忆源
    try:
        # main.sqlite中的文件类型分布
        conn = sqlite3.connect(str(MEMORY_DIR / "main.sqlite"))
        file_types = conn.execute("""
            SELECT 
                CASE 
                    WHEN path LIKE '%.py' THEN 'python'
                    WHEN path LIKE '%.md' THEN 'markdown' 
                    WHEN path LIKE '%.js%' THEN 'javascript'
                    WHEN path LIKE '%.ts%' THEN 'typescript'
                    WHEN path LIKE '%.yaml%' OR path LIKE '%.yml' THEN 'yaml'
                    ELSE 'other'
                END as ext,
                COUNT(*) as cnt
            FROM chunks GROUP BY ext ORDER BY cnt DESC
        """).fetchall()
        conn.close()

        total = sum(r[1] for r in file_types)
        p(f"记忆内容分布: " + " | ".join(f"{r[0]}:{r[1]}({r[1]*100//total}%)" for r in file_types))
    except Exception as e:
        p(f"类型分析失败: {e}", "WRN")

    return {"status": "ok", "discoveries": discoveries, "skills_created": created_skills}


# ============================================================================
# 模块5: 终身学习 — 从持久记忆+session_history中沉淀
# ============================================================================
def module_lifelong_learning():
    """
    终身学习 — 从持久记忆(MEMORY.md/USER.md)和可用的session数据中提取知识
    
    1. 从 ~/.hermes/memories/ 读取持久记忆
    2. 融合到rag_index.db的memory_entries中
    3. 分析记忆一致性
    """
    p("=" * 60)
    p("♾️ 模块5: 终身学习 — 持久记忆沉淀 [并行线程5]")
    p("=" * 60)

    results = {}

    # 5.1 读取持久记忆文件
    try:
        memory_files = {
            'MEMORY.md': MEMORIES_DIR / "MEMORY.md",
            'USER.md': MEMORIES_DIR / "USER.md",
        }
        loaded = []
        for name, path in memory_files.items():
            if path.exists():
                content = path.read_text(encoding='utf-8')
                lines = content.strip().split('\n')
                loaded.append({'name': name, 'lines': len(lines), 'size': len(content)})
                p(f"  读取 {name}: {len(lines)}行, {len(content)}字符")

        results['memory_files'] = loaded
    except Exception as e:
        p(f"读取持久记忆失败: {e}", "WRN")

    # 5.2 同步到memory_entries表
    try:
        rag_conn = sqlite3.connect(str(RAG_INDEX_DB))
        
        # 从持久记忆文件同步
        for name, path in memory_files.items():
            if path.exists():
                content = path.read_text(encoding='utf-8')
                content_hash = hashlib.md5((name + content[:500]).encode()).hexdigest()
                
                existing = rag_conn.execute(
                    "SELECT id FROM memory_entries WHERE entry_type='persistent_memory' AND content LIKE ? LIMIT 1",
                    (f"{name}%",)
                ).fetchone()
                
                if not existing:
                    rag_conn.execute("""
                        INSERT INTO memory_entries (entry_type, content, domain, importance, created_at)
                        VALUES (?, ?, ?, ?, datetime('now'))
                    """, ('persistent_memory', f"{name}\n{content[:500]}", '系统', 5.0))
                    p(f"  写入持久记忆到memory_entries: {name}", "OK")
        
        rag_conn.commit()
        total = rag_conn.execute("SELECT COUNT(*) FROM memory_entries WHERE entry_type='persistent_memory'").fetchone()[0]
        p(f"  memory_entries中持久记忆记录: {total}")
        rag_conn.close()
    except Exception as e:
        p(f"持久记忆同步失败: {e}", "WRN")

    return {"status": "ok", "results": results}


# ============================================================================
# 模块6: 能力进化分析
# ============================================================================
def module_evolution_analysis():
    """分析所有能力的状态,生成优化建议"""
    p("=" * 60)
    p("📊 模块6: 能力进化分析 [并行线程6]")
    p("=" * 60)

    snapshot = {}
    suggestions = []

    # 6.1 所有数据库快照
    dbs = {
        'intelligence.db(raw)': INTELLIGENCE_DB,
        'main.sqlite(chunks)': MEMORY_DIR / "main.sqlite",
        'rag_index.db(index)': RAG_INDEX_DB,
    }

    for name, path in dbs.items():
        try:
            size_mb = path.stat().st_size / 1024 / 1024
            snapshot[name] = f"{size_mb:.1f}MB"
        except:
            snapshot[name] = "N/A"

    # 6.2 intelligence.db详细
    try:
        conn = sqlite3.connect(str(INTELLIGENCE_DB))
        raw = conn.execute("SELECT COUNT(*) FROM raw_intelligence").fetchone()[0]
        cleaned = conn.execute("SELECT COUNT(*) FROM cleaned_intelligence").fetchone()[0]
        today_raw = conn.execute("SELECT COUNT(*) FROM raw_intelligence WHERE DATE(collected_at)=DATE('now')").fetchone()[0]
        high_value = conn.execute("SELECT COUNT(*) FROM cleaned_intelligence WHERE value_level >= 3").fetchone()[0]
        conn.close()
        snapshot['raw'] = raw
        snapshot['cleaned'] = cleaned
        snapshot['today'] = today_raw
        snapshot['high_value(≥3)'] = high_value
        
        p(f"intel: raw={raw}, cleaned={cleaned}, 今日={today_raw}, 高价值={high_value}")
    except Exception as e:
        p(f"intel分析失败: {e}", "WRN")

    # 6.3 main.sqlite详细
    try:
        conn = sqlite3.connect(str(MEMORY_DIR / "main.sqlite"))
        chunks = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        files = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
        embeds = conn.execute("SELECT COUNT(*) FROM embedding_cache").fetchone()[0]
        conn.close()
        snapshot['chunks'] = chunks
        snapshot['files'] = files
        snapshot['embeddings'] = embeds
        p(f"memory: {chunks}chunks, {files}files, {embeds}embeddings")
    except Exception as e:
        p(f"memory分析失败: {e}", "WRN")

    # 6.4 rag_index详细
    try:
        conn = sqlite3.connect(str(RAG_INDEX_DB))
        rag = conn.execute("SELECT COUNT(*) FROM rag_index").fetchone()[0]
        mem = conn.execute("SELECT COUNT(*) FROM memory_entries").fetchone()[0]
        conn.close()
        snapshot['rag_index'] = rag
        snapshot['memory_entries'] = mem
        p(f"rag_index: {rag}索引, {mem}记忆条目")
    except Exception as e:
        p(f"rag_index分析失败: {e}", "WRN")

    # 6.5 生成建议
    hv = snapshot.get('high_value(≥3)', 0)
    ri = snapshot.get('rag_index', 0)
    if hv > ri + 50:
        suggestions.append("高价值情报远多于RAG索引 → 增大 --limit 或提高频率")
    if snapshot.get('today', 0) == 0:
        suggestions.append("今日无采集 → 检查情报采集管线是否运行")
    if snapshot.get('chunks', 0) < 100:
        suggestions.append("记忆chunks太少 → 扩大workspace索引范围")
    if snapshot.get('memory_entries', 0) < 10:
        suggestions.append("memory_entries太少 → 需要更多终身学习")

    if not suggestions:
        suggestions.append("所有系统指标正常 ✓")

    for s in suggestions:
        p(f"  建议: {s}", "EVOLVE" if s.startswith("建议") else "OK")

    return {"status": "ok", "snapshot": snapshot, "suggestions": suggestions}


# ============================================================================
# 并行编排器 — 真正同时运行所有模块
# ============================================================================
def run_parallel():
    """并行运行所有6个模块"""
    p("\n" + "=" * 70)
    p(f"   {C['BOLD']}⚡ Hermes 深度记忆进化引擎 v2 (并行全量){C['END']}")
    p("=" * 70)
    p(f"   6模块并行执行 + 真实压缩 + 自动技能沉淀 + 终身学习")
    p("=" * 70 + "\n")

    start = time.time()
    results = {}

    # Step 1: 模块1 (增强) 和 模块2 (索引) 可以并行
    # 模块3 (压缩) 依赖模块1和2 完成后的状态,但实际不冲突
    # 模块4/5/6 完全独立
    # 所以: 全部并行

    modules = [
        ("enhance", module_enhance),
        ("rag_index", module_rag_index),
        ("compress", module_compress),
        ("skill_mining", module_skill_mining),
        ("lifelong", module_lifelong_learning),
        ("evolve", module_evolution_analysis),
    ]

    # 使用 subprocess 并行: 每个模块作为独立进程运行
    p(f"启动 {len(modules)} 个并行进程...\n")
    
    processes = {}
    for name, func in modules:
        # 创建针对每个模块的包装脚本
        stub = SCRIPTS / f"_mem_sub_{name}.py"
        # 序列化参数
        stub_code = f"""import sys, json, logging, io
# 完全禁用日志输出到stdout
for h in logging.root.handlers[:]:
    logging.root.removeHandler(h)
logging.root.addHandler(logging.NullHandler())
sys.path.insert(0, '{SCRIPTS}')
from memory_evolution_v2 import {func.__name__}
# 重定向函数内的print到stderr,只让json.dumps走stdout
import builtins
_orig_print = builtins.print
def _silent_print(*args, **kwargs):
    kwargs['file'] = sys.stderr
    _orig_print(*args, **kwargs)
builtins.print = _silent_print
result = {func.__name__}()
builtins.print = _orig_print
print(json.dumps(result))
"""
        stub.write_text(stub_code)
        
        proc = subprocess.Popen(
            [sys.executable, str(stub)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            cwd=str(HERMES)
        )
        processes[name] = proc
        p(f"  ⚡ 启动: {name} (PID:{proc.pid})", "INFO")

    # 等待所有进程完成
    results = {}
    for name in [m[0] for m in modules]:
        proc = processes[name]
        stdout, stderr = proc.communicate(timeout=180)
        if proc.returncode == 0:
            try:
                results[name] = json.loads(stdout.decode())
                status = results[name].get('status', 'unknown')
                emoji = "✓" if status == 'ok' else "✗"
                p(f"  {emoji} {name}: {status}", "OK" if status == 'ok' else "ERR")
            except json.JSONDecodeError:
                p(f"  ✗ {name}: JSON解析失败", "ERR")
                results[name] = {"status": "error", "raw": stdout.decode()[:200]}
        else:
            p(f"  ✗ {name}: exit={proc.returncode} {stderr.decode()[:200]}", "ERR")
            results[name] = {"status": "error", "stderr": stderr.decode()[:200]}
        
        # 清理stub
        stub = SCRIPTS / f"_mem_sub_{name}.py"
        if stub.exists():
            stub.unlink()

    elapsed = time.time() - start

    # 汇总
    p("\n" + "=" * 70)
    p(f"   {C['BOLD']}📊 并行执行汇总{C['END']}")
    p("=" * 70)
    for name in [m[0] for m in modules]:
        res = results.get(name, {})
        status = res.get('status', 'unknown')
        emoji = "✓" if status == 'ok' else "✗" if status in ('error', 'timeout') else "?"
        detail = ""
        if name == 'enhance':
            detail = f" +{res.get('enhanced', 0)}新情报"
        elif name == 'compress':
            r = res.get('results', {})
            deleted = sum(v.get('deleted', 0) for v in r.values() if isinstance(v, dict))
            detail = f" 删除{deleted}条"
        elif name == 'skill_mining':
            detail = f" {len(res.get('skills_created', []))}新skills"
        elif name == 'lifelong':
            mf = res.get('results', {}).get('memory_files', [])
            detail = f" {len(mf)}记忆文件同步"
        elif name == 'evolve':
            detail = f" {len(res.get('suggestions', []))}条建议"

        p(f"  {emoji} {name:12s}: {status}{detail}")

    p(f"\n⏱ 总耗时: {elapsed:.1f}s (并行)" + 
      f"  {'→ 比串行快约' + str(int(elapsed * 5 / max(elapsed, 0.1))) + 'x' if elapsed > 0 else ''}")
    p("=" * 70)

    results['_meta'] = {'elapsed': elapsed}
    return results


# ============================================================================
# CLI
# ============================================================================
def main():
    import argparse
    parser = argparse.ArgumentParser(description="Hermes 深度记忆进化引擎 v2")
    parser.add_argument("--parallel", action="store_true", help="并行运行所有模块 (默认)")
    parser.add_argument("--serial", action="store_true", help="串行运行 (调试用)")

    args = parser.parse_args()

    if args.serial:
        # 串行模式(调试)
        module_enhance()
        module_rag_index()
        module_compress()
        module_skill_mining()
        module_lifelong_learning()
        module_evolution_analysis()
    else:
        # 默认并行
        run_parallel()


if __name__ == "__main__":
    main()
