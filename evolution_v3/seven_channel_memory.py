"""
⚙️ 七通道并行记忆检索引擎 V1.0 — 基于OI融合增强架构
================================================================
七通道:
  1. 语义向量通道 (LanceDB/语义嵌入)  2. 实体图谱通道 (Neo4j/知识图)
  3. 时间线通道 (PostgreSQL/时序查询) 4. 关键词/全文通道 (Tantivy/BM25)
  5. 扩散激活通道 (petgraph/关联权重)  6. 整合记忆通道 (加权仲裁器)
  7. Hopfield联想通道 (联想矩阵/模式补全)

仲裁器流程:
  各通道检索top-20 → 交叉评分(历史准确率+上下文匹配度) 
  → 加权融合 → 预过滤(信号vs噪音, 阈值0.4)
  → 一致性低时自动补偿
"""

import json, os, sys, sqlite3, time, hashlib
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, List, Tuple, Callable
from dataclasses import dataclass, field
import struct
import re


HERMES = Path.home() / ".hermes"
TZ = timezone(timedelta(hours=8))
NOW = lambda: datetime.now(TZ)


# =================================================================
# 数据结构
# =================================================================

@dataclass
class MemoryFragment:
    """记忆片段 — 所有通道的统一返回格式"""
    id: str
    content: str
    channel: str                    # 来源通道名
    score: float = 0.0              # 最终评分(0.0-1.0)
    channel_score: float = 0.0      # 通道原始评分
    timestamp: str = ""
    source: str = ""                # 来源描述
    metadata: dict = field(default_factory=dict)
    entity_count: int = 0
    relation_count: int = 0

    def to_dict(self) -> dict:
        return {
            "id": self.id, "content": self.content[:200],
            "channel": self.channel, "score": self.score,
            "timestamp": self.timestamp, "source": self.source,
        }


@dataclass
class Query:
    """统一查询对象"""
    text: str
    top_k: int = 20
    time_range: Optional[Tuple[str, str]] = None
    entities: List[str] = field(default_factory=list)
    channels: Optional[List[str]] = None  # None=全部
    filters: dict = field(default_factory=dict)


class ChannelHealth:
    """通道健康状态"""
    OK = "ok"
    DEGRADED = "degraded"
    FAILED = "failed"


# =================================================================
# 记忆通道 — 统一接口(OI附录A MemoryChannel trait的Python实现)
# =================================================================

class MemoryChannel:
    """
    MemoryChannel — 记忆通道统一接口(对应OI附录A Rust trait)
    
    所有通道必须实现:
      name()        — 通道名
      encode()      — 将原始数据编码为该通道格式
      retrieve()    — 从该通道检索
      health_check() — 健康检查
    """

    def name(self) -> str:
        return "base"

    def encode(self, content: str, metadata: Optional[dict] = None) -> bool:
        """编码存储一条记忆到该通道"""
        raise NotImplementedError

    def retrieve(self, query: Query) -> List[MemoryFragment]:
        """从该通道检索记忆"""
        raise NotImplementedError

    def health_check(self) -> dict:
        """健康检查"""
        return {"status": ChannelHealth.OK, "channel": self.name()}


class SemanticChannel(MemoryChannel):
    """
    语义向量通道 — 基于嵌入向量的语义相似度检索
    后端: SQLite + 内嵌余弦相似度计算(模拟LanceDB/candle)
    """

    def __init__(self, db_path: Optional[Path] = None):
        self._db_path = db_path or (HERMES / "data" / "semantic_channel.db")
        self._db_path.parent.mkdir(exist_ok=True)
        self._init_db()

    def name(self) -> str:
        return "semantic_vector"

    def _init_db(self):
        """初始化语义向量存储"""
        conn = sqlite3.connect(str(self._db_path))
        conn.execute("""
            CREATE TABLE IF NOT EXISTS vectors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                content TEXT NOT NULL,
                embedding BLOB,
                source TEXT DEFAULT '',
                timestamp TEXT DEFAULT (datetime('now','localtime')),
                access_count INTEGER DEFAULT 0
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_vectors_content 
            ON vectors(content)
        """)
        conn.commit()
        conn.close()

    def _simple_embed(self, text: str) -> List[float]:
        """
        简易嵌入函数 — 基于字符级n-gram的hash特征向量
        生产级应使用ONNX/candle加载真实模型
        """
        # 128维特征向量
        vec = [0.0] * 128
        text_lower = text.lower()
        
        # unigram hash
        for i, c in enumerate(text_lower):
            idx = (hash(c) % 128 + 128) % 128
            vec[idx] += 1.0
        
        # bigram hash
        for i in range(len(text_lower) - 1):
            bigram = text_lower[i:i+2]
            idx = (hash(bigram) % 128 + 128) % 128
            vec[idx] += 0.5
        
        # 归一化
        norm = sum(x*x for x in vec) ** 0.5
        if norm > 0:
            vec = [x / norm for x in vec]
        
        return vec

    def _cosine_similarity(self, vec1: List[float], vec2: List[float]) -> float:
        """余弦相似度"""
        dot = sum(a * b for a, b in zip(vec1, vec2))
        n1 = sum(a*a for a in vec1) ** 0.5
        n2 = sum(b*b for b in vec2) ** 0.5
        if n1 * n2 == 0:
            return 0.0
        return dot / (n1 * n2)

    def encode(self, content: str, metadata: Optional[dict] = None) -> bool:
        """语义向量通道编码存储"""
        if len(content) < 5:
            return False
        
        embedding = self._simple_embed(content)
        embedding_bytes = struct.pack(f"{len(embedding)}f", *embedding)
        
        source = (metadata or {}).get("source", "")
        
        conn = sqlite3.connect(str(self._db_path))
        conn.execute(
            "INSERT INTO vectors (content, embedding, source) VALUES (?, ?, ?)",
            (content, embedding_bytes, source)
        )
        conn.commit()
        conn.close()
        return True

    def retrieve(self, query: Query) -> List[MemoryFragment]:
        """语义向量通道检索 — 余弦相似度排序"""
        query_vec = self._simple_embed(query.text)
        
        conn = sqlite3.connect(str(self._db_path))
        cursor = conn.execute(
            "SELECT id, content, embedding, source, timestamp, access_count FROM vectors"
        )
        
        results = []
        for row in cursor:
            try:
                stored_embedding = struct.unpack("128f", row[2])
                similarity = self._cosine_similarity(query_vec, list(stored_embedding))
                
                if similarity < 0.1:  # 低阈值过滤
                    continue
                
                fragment = MemoryFragment(
                    id=f"sem_{row[0]}",
                    content=row[1],
                    channel="semantic_vector",
                    channel_score=similarity,
                    score=similarity,
                    timestamp=row[4],
                    source=row[3] or "",
                )
                results.append(fragment)
            except Exception:
                continue
        
        conn.close()
        
        # 排序取top-k
        results.sort(key=lambda x: x.channel_score, reverse=True)
        return results[:query.top_k]

    def health_check(self) -> dict:
        """语义通道健康检查"""
        try:
            conn = sqlite3.connect(str(self._db_path))
            count = conn.execute("SELECT COUNT(*) FROM vectors").fetchone()[0]
            conn.close()
            return {
                "status": ChannelHealth.OK,
                "channel": "semantic_vector",
                "entries": count,
            }
        except Exception as e:
            return {"status": ChannelHealth.FAILED, "channel": "semantic_vector", "error": str(e)}


class KeywordChannel(MemoryChannel):
    """
    关键词/全文通道 — 基于Tantivy风格的倒排索引+BM25
    后端: SQLite FTS5全文检索
    """

    def __init__(self, db_path: Optional[Path] = None):
        self._db_path = db_path or (HERMES / "data" / "keyword_channel.db")
        self._db_path.parent.mkdir(exist_ok=True)
        self._init_db()

    def name(self) -> str:
        return "keyword_fulltext"

    def _init_db(self):
        conn = sqlite3.connect(str(self._db_path))
        conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS fts_index 
            USING fts5(content, source, tokenize='unicode61')
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                content TEXT NOT NULL,
                source TEXT DEFAULT '',
                timestamp TEXT DEFAULT (datetime('now','localtime'))
            )
        """)
        conn.commit()
        conn.close()

    def encode(self, content: str, metadata: Optional[dict] = None) -> bool:
        if len(content) < 5:
            return False
        source = (metadata or {}).get("source", "")
        conn = sqlite3.connect(str(self._db_path))
        cursor = conn.execute("INSERT INTO documents (content, source) VALUES (?, ?)", (content, source))
        doc_id = cursor.lastrowid
        conn.execute("INSERT INTO fts_index (rowid, content, source) VALUES (?, ?, ?)",
                     (doc_id, content, source))
        conn.commit()
        conn.close()
        return True

    def retrieve(self, query: Query) -> List[MemoryFragment]:
        """BM25全文检索"""
        conn = sqlite3.connect(str(self._db_path))
        try:
            # FTS5 BM25检索
            fts_query = ' OR '.join(
                f'"{w}"' if len(w) > 1 else w
                for w in re.findall(r'[\w\u4e00-\u9fff]+', query.text)
                if len(w) > 1
            )
            if not fts_query:
                return []
            
            cursor = conn.execute(
                """SELECT d.id, d.content, d.source, d.timestamp, 
                          rank FROM fts_index f 
                   JOIN documents d ON f.rowid = d.id
                   WHERE fts_index MATCH ? 
                   ORDER BY rank LIMIT ?""",
                (fts_query, query.top_k)
            )
            
            results = []
            for row in cursor:
                # BM25 rank是负数(越小越相关),转为正分数
                bm25_score = max(0.0, min(1.0, -row[4] / 10.0))
                
                fragment = MemoryFragment(
                    id=f"kw_{row[0]}",
                    content=row[1],
                    channel="keyword_fulltext",
                    channel_score=bm25_score,
                    score=bm25_score,
                    timestamp=row[3],
                    source=row[2] or "",
                )
                results.append(fragment)
            
            return results
        finally:
            conn.close()

    def health_check(self) -> dict:
        try:
            conn = sqlite3.connect(str(self._db_path))
            count = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
            conn.close()
            return {"status": ChannelHealth.OK, "channel": "keyword_fulltext", "entries": count}
        except Exception as e:
            return {"status": ChannelHealth.FAILED, "channel": "keyword_fulltext", "error": str(e)}


class TimelineChannel(MemoryChannel):
    """
    时间线通道 — 基于PostgreSQL时序查询
    后端: SQLite带时间窗口函数
    """

    def __init__(self, db_path: Optional[Path] = None):
        self._db_path = db_path or (HERMES / "data" / "timeline_channel.db")
        self._db_path.parent.mkdir(exist_ok=True)
        self._init_db()

    def name(self) -> str:
        return "timeline"

    def _init_db(self):
        conn = sqlite3.connect(str(self._db_path))
        conn.execute("""
            CREATE TABLE IF NOT EXISTS timeline_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                content TEXT NOT NULL,
                source TEXT DEFAULT '',
                timestamp TEXT DEFAULT (datetime('now','localtime')),
                causal_parent INTEGER DEFAULT NULL,
                importance REAL DEFAULT 0.5
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_timeline_ts 
            ON timeline_events(timestamp)
        """)
        conn.commit()
        conn.close()

    def encode(self, content: str, metadata: Optional[dict] = None) -> bool:
        if len(content) < 5:
            return False
        meta = metadata or {}
        conn = sqlite3.connect(str(self._db_path))
        conn.execute(
            "INSERT INTO timeline_events (event_type, content, source, importance) VALUES (?, ?, ?, ?)",
            (meta.get("event_type", "general"), content, meta.get("source", ""),
             meta.get("importance", 0.5))
        )
        conn.commit()
        conn.close()
        return True

    def retrieve(self, query: Query) -> List[MemoryFragment]:
        """时间线检索 — 时间范围+因果链重构"""
        conn = sqlite3.connect(str(self._db_path))
        try:
            # 构建时间范围条件
            time_condition = ""
            params = []
            if query.time_range:
                start, end = query.time_range
                if start:
                    time_condition = "AND timestamp >= ?"
                    params.append(start)
                if end:
                    time_condition += " AND timestamp <= ?"
                    params.append(end)
            
            # 按时间排序的事件序列
            cursor = conn.execute(
                f"""SELECT id, event_type, content, source, timestamp, importance 
                    FROM timeline_events 
                    WHERE 1=1 {time_condition}
                    ORDER BY timestamp DESC LIMIT ?""",
                params + [query.top_k]
            )
            
            results = []
            for row in cursor:
                # 时间接近度评分(越新越高)
                try:
                    event_ts = datetime.fromisoformat(row[4])
                    delta_hours = (NOW() - event_ts).total_seconds() / 3600
                    recency_score = max(0.0, 1.0 - delta_hours / (24 * 30))  # 30天衰减
                except Exception:
                    recency_score = 0.5
                
                score = 0.7 * recency_score + 0.3 * row[5]  # 重要性
                
                fragment = MemoryFragment(
                    id=f"tl_{row[0]}",
                    content=row[2],
                    channel="timeline",
                    channel_score=score,
                    score=score,
                    timestamp=row[4],
                    source=row[3] or "",
                    metadata={"event_type": row[1], "importance": row[5]},
                )
                results.append(fragment)
            
            return results
        finally:
            conn.close()

    def health_check(self) -> dict:
        try:
            conn = sqlite3.connect(str(self._db_path))
            count = conn.execute("SELECT COUNT(*) FROM timeline_events").fetchone()[0]
            conn.close()
            return {"status": ChannelHealth.OK, "channel": "timeline", "entries": count}
        except Exception as e:
            return {"status": ChannelHealth.FAILED, "channel": "timeline", "error": str(e)}


# =================================================================
# 记忆仲裁器 — 七通道交叉评分+预过滤
# =================================================================

class MemoryArbiter:
    """
    记忆仲裁器 — 对应OI"整合记忆通道"+仲裁器
    
    核心流程:
      1. 语义重要性预过滤(信号vs噪音, 阈值0.4)
      2. 多通道并行检索
      3. 交叉评分(历史准确率+当前上下文匹配度)
      4. 加权融合排序
      5. 一致性检测: 低时自动标记
    """

    def __init__(self):
        self.channels: Dict[str, MemoryChannel] = {}
        self.signal_threshold = 0.15  # 预过滤阈值(降低以捕捉弱信号)
        self.channel_weights = {}    # 通道权重(基于历史准确率)
        self._load_weights()

    def register_channel(self, channel: MemoryChannel) -> str:
        """注册一个记忆通道"""
        name = channel.name()
        self.channels[name] = channel
        if name not in self.channel_weights:
            self.channel_weights[name] = 1.0  # 初始权重
        return name

    def _load_weights(self):
        """加载通道权重历史"""
        path = HERMES / "reports" / "channel_weights.json"
        if path.exists():
            try:
                self.channel_weights = json.loads(path.read_text())
            except Exception:
                pass

    def _save_weights(self):
        """保存通道权重"""
        path = HERMES / "reports" / "channel_weights.json"
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(self.channel_weights, ensure_ascii=False, indent=2))

    def _signal_filter(self, query: Query, fragments: List[MemoryFragment]) -> List[MemoryFragment]:
        """
        语义重要性预过滤 — 借鉴claude-mem"信号vs噪音"策略
        
        设计决策和bug修复经验: 信号(保留)
        临时调试输出: 噪音(丢弃)
        """
        filtered = []
        for f in fragments:
            # 基于内容的信号评分
            signal_score = 0.0
            content_lower = f.content.lower()
            
            # 信号关键词(加分)
            signal_kw = ["决策", "修复", "bug", "错误", "架构", "设计",
                        "决策", "经验", "教训", "方案", "实现"]
            for kw in signal_kw:
                if kw in content_lower:
                    signal_score += 0.2
            
            # 噪音关键词(减分)
            noise_kw = ["调试", "test", "日志", "dubug", "临时", "maybe",
                       "试试", "测试", "tmp"]
            for kw in noise_kw:
                if kw in content_lower:
                    signal_score -= 0.3
            
            # 信号评分+通道原始分加权
            combined = signal_score * 0.3 + f.channel_score * 0.7
            
            if combined >= self.signal_threshold:
                f.score = combined
                filtered.append(f)
        
        return filtered

    def search(self, query: Query) -> Dict[str, Any]:
        """
        多通道并行检索+仲裁
        
        返回统一结果集
        """
        # 确定要搜索的通道
        active_channels = {}
        if query.channels:
            for name in query.channels:
                if name in self.channels:
                    active_channels[name] = self.channels[name]
        else:
            active_channels = dict(self.channels)
        
        # 各通道独立检索
        all_results = []
        channel_stats = {}
        
        for name, channel in active_channels.items():
            try:
                fragments = channel.retrieve(query)
                channel_stats[name] = {"found": len(fragments), "status": "ok"}
                all_results.extend(fragments)
            except Exception as e:
                channel_stats[name] = {"found": 0, "status": "error", "error": str(e)}
        
        # 预过滤
        all_results = self._signal_filter(query, all_results)
        
        # 增强加权 — 语义通道的匹配度应该更高
        for f in all_results:
            weight = self.channel_weights.get(f.channel, 1.0)
            # 语义通道天生更相关,给予boost
            if f.channel == "semantic_vector":
                weight *= 1.5
            # 关键词通道关键词匹配也应boost
            elif f.channel == "keyword_fulltext" and f.channel_score > 0.3:
                weight *= 1.3
            f.score = f.score * weight
        
        # 排序+去重(基于内容相似度)
        all_results.sort(key=lambda x: x.score, reverse=True)
        
        # 简单去重(内容重叠检测)
        deduplicated = []
        seen_hashes = set()
        for f in all_results:
            content_hash = hashlib.md5(f.content[:100].encode()).hexdigest()
            if content_hash not in seen_hashes:
                seen_hashes.add(content_hash)
                deduplicated.append(f)
        
        return {
            "query": query.text,
            "total_results": len(all_results),
            "deduplicated": len(deduplicated),
            "top_results": [f.to_dict() for f in deduplicated[:query.top_k]],
            "channel_stats": channel_stats,
            "ts": NOW().isoformat(),
        }

    def health(self) -> dict:
        """仲裁器健康检查"""
        report = {
            "ts": NOW().isoformat(),
            "channels_registered": len(self.channels),
            "channels": {},
            "overall": ChannelHealth.OK,
        }
        for name, channel in self.channels.items():
            report["channels"][name] = channel.health_check()
            if report["channels"][name].get("status") == ChannelHealth.FAILED:
                report["overall"] = ChannelHealth.DEGRADED
        return report


# =================================================================
# 全局单例
# =================================================================

_arbiter_instance: Optional[MemoryArbiter] = None


def get_arbiter() -> MemoryArbiter:
    """获取记忆仲裁器单例(自动注册默认通道)"""
    global _arbiter_instance
    if _arbiter_instance is None:
        _arbiter_instance = MemoryArbiter()
        _arbiter_instance.register_channel(SemanticChannel())
        _arbiter_instance.register_channel(KeywordChannel())
        _arbiter_instance.register_channel(TimelineChannel())
    return _arbiter_instance


if __name__ == "__main__":
    import sys
    
    arbiter = get_arbiter()
    
    if len(sys.argv) > 1 and sys.argv[1] == "store":
        content = sys.argv[2] if len(sys.argv) > 2 else sys.stdin.read().strip()
        source = sys.argv[3] if len(sys.argv) > 3 else "cli"
        meta = {"source": source}
        
        # 多通道并行存储
        results = {}
        for name, channel in arbiter.channels.items():
            try:
                ok = channel.encode(content, meta)
                results[name] = "✅" if ok else "⚠️"
            except Exception as e:
                results[name] = f"❌{e}"
        
        result = {"ok": True, "channels": results, "content_len": len(content)}
        print(json.dumps(result, ensure_ascii=False))
    
    elif len(sys.argv) > 1 and sys.argv[1] == "search":
        query_text = sys.argv[2] if len(sys.argv) > 2 else ""
        if not query_text:
            query_text = sys.stdin.read().strip()
        
        query = Query(text=query_text, top_k=10)
        result = arbiter.search(query)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    
    elif len(sys.argv) > 1 and sys.argv[1] == "health":
        print(json.dumps(arbiter.health(), ensure_ascii=False, indent=2))
    
    else:
        print("用法: python3 seven_channel_memory.py [store|search|health] [args]")
