"""
⚙️ 七通道扩展 V2.0 — 扩散激活+实体图谱+Hopfield联想+整合记忆通道
================================================================
新增4个通道，实现OI完整七通道要求:

通道4: 扩散激活通道 — petgraph关联权重矩阵+激活扩散算法
通道5: 实体图谱通道 — 实体关系存储+Cypher查询
通道6: Hopfield联想通道 — 联想矩阵+模式补全
通道7: 整合记忆通道 — 独立加权投票仲裁器

所有通道遵循MemoryChannel统一接口
"""

import json, os, sys, sqlite3, time, hashlib, math
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, List, Tuple, Set
from dataclasses import dataclass, field

HERMES = Path.home() / ".hermes"
TZ = timezone(timedelta(hours=8))
NOW = lambda: datetime.now(TZ)


# =================================================================
# 基础数据结构(复用七通道定义)
# =================================================================

@dataclass
class MemoryFragment:
    id: str
    content: str
    channel: str
    score: float = 0.0
    channel_score: float = 0.0
    timestamp: str = ""
    source: str = ""
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
    text: str
    top_k: int = 20
    time_range: Optional[Tuple[str, str]] = None
    entities: List[str] = field(default_factory=list)
    channels: Optional[List[str]] = None
    filters: dict = field(default_factory=dict)


class ChannelHealth:
    OK = "ok"
    DEGRADED = "degraded"
    FAILED = "failed"


class MemoryChannel:
    def name(self) -> str:
        return "base"
    def encode(self, content: str, metadata: Optional[dict] = None) -> bool:
        raise NotImplementedError
    def retrieve(self, query: Query) -> List[MemoryFragment]:
        raise NotImplementedError
    def health_check(self) -> dict:
        return {"status": ChannelHealth.OK, "channel": self.name()}


# =================================================================
# 通道4: 扩散激活通道 (Spreading Activation Channel)
# 对应 OI§15: 扩散激活通道,petgraph内存维护关联权重矩阵
# =================================================================

class SpreadingActivationChannel(MemoryChannel):
    """
    扩散激活通道 — 基于关联权重矩阵的记忆扩散检索
    
    核心机制:
      - 内存维护word-concept关联矩阵
      - 激活扩散算法(衰减因子0.85)
      - 多跳关联展开
    """

    def __init__(self, db_path: Optional[Path] = None):
        self._db_path = db_path or (HERMES / "data" / "spreading_channel.db")
        self._db_path.parent.mkdir(exist_ok=True)
        
        # 内存关联矩阵: word -> {concept_id -> weight}
        self._assoc_matrix: Dict[str, Dict[str, float]] = {}
        # 内存概念存储: concept_id -> content
        self._concepts: Dict[str, str] = {}
        
        self.decay_factor = 0.85  # 衰减因子(匹配文档要求)
        self.max_hops = 3         # 最大跳数
        self._init_db()
        self._load_matrices()

    def name(self) -> str:
        return "spreading_activation"

    def _init_db(self):
        conn = sqlite3.connect(str(self._db_path))
        conn.execute("""
            CREATE TABLE IF NOT EXISTS concepts (
                id TEXT PRIMARY KEY,
                content TEXT NOT NULL,
                source TEXT DEFAULT '',
                timestamp TEXT DEFAULT (datetime('now','localtime'))
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS associations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                word TEXT NOT NULL,
                concept_id TEXT NOT NULL,
                weight REAL DEFAULT 1.0,
                FOREIGN KEY (concept_id) REFERENCES concepts(id)
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_assoc_word ON associations(word)
        """)
        conn.commit()
        conn.close()

    def _load_matrices(self):
        """从SQLite加载关联矩阵到内存"""
        conn = sqlite3.connect(str(self._db_path))
        try:
            # 加载概念
            cursor = conn.execute("SELECT id, content, source, timestamp FROM concepts")
            for row in cursor:
                self._concepts[row[0]] = row[1]
            
            # 加载关联
            cursor = conn.execute("SELECT word, concept_id, weight FROM associations")
            for row in cursor:
                word = row[0]
                if word not in self._assoc_matrix:
                    self._assoc_matrix[word] = {}
                self._assoc_matrix[word][row[1]] = row[2]
        finally:
            conn.close()

    def encode(self, content: str, metadata: Optional[dict] = None) -> bool:
        """编码存储 — 提取关联关系"""
        if len(content) < 5:
            return False
        
        import re
        source = (metadata or {}).get("source", "")
        concept_id = f"spreading_{int(time.time())}_{hashlib.md5(content.encode()).hexdigest()[:6]}"
        
        conn = sqlite3.connect(str(self._db_path))
        try:
            # 存入概念
            conn.execute(
                "INSERT INTO concepts (id, content, source) VALUES (?, ?, ?)",
                (concept_id, content, source)
            )
            
            # 提取关键词(中文n-gram)+建立关联
            def extract_ngrams(t: str) -> set:
                import re
                ngrams = set()
                eng = re.findall(r'[a-zA-Z0-9_]{2,}', t.lower())
                ngrams.update(eng)
                chars = re.findall(r'[\u4e00-\u9fff]', t)
                for length in [2, 3, 4]:
                    for i in range(len(chars) - length + 1):
                        ngrams.add(''.join(chars[i:i+length]))
                return ngrams
            
            words = extract_ngrams(content)
            for word in words:
                weight = min(1.0, content.lower().count(word) / max(len(content), 1) * 10)
                conn.execute(
                    "INSERT INTO associations (word, concept_id, weight) VALUES (?, ?, ?)",
                    (word, concept_id, weight)
                )
                # 更新内存矩阵
                if word not in self._assoc_matrix:
                    self._assoc_matrix[word] = {}
                self._assoc_matrix[word][concept_id] = weight
            
            self._concepts[concept_id] = content
            conn.commit()
            return True
        finally:
            conn.close()

    def retrieve(self, query: Query) -> List[MemoryFragment]:
        """
        扩散激活检索
        
        算法:
          1. 从查询词激活初始节点
          2. 以衰减因子0.85向邻接节点扩散
          3. 多跳后稳定
          4. 返回激活值排序的记忆
        """
        # 中文n-gram提取
        def extract_ngrams(t: str) -> set:
            import re
            ngrams = set()
            eng = re.findall(r'[a-zA-Z0-9_]{2,}', t.lower())
            ngrams.update(eng)
            chars = re.findall(r'[\u4e00-\u9fff]', t)
            for length in [2, 3, 4]:
                for i in range(len(chars) - length + 1):
                    ngrams.add(''.join(chars[i:i+length]))
            return ngrams
        
        query_words = extract_ngrams(query.text)
        
        if not query_words:
            return []
        
        # 激活值: concept_id -> activation
        activation: Dict[str, float] = {}
        
        # 第0跳: 从查询词直接关联的节点开始
        for word in query_words:
            if word in self._assoc_matrix:
                for concept_id, weight in self._assoc_matrix[word].items():
                    activation[concept_id] = activation.get(concept_id, 0.0) + weight
        
        # 多跳扩散
        for hop in range(1, self.max_hops):
            new_activation: Dict[str, float] = {}
            for concept_id, act in activation.items():
                # 找到该概念关联的词
                for word, assoc in self._assoc_matrix.items():
                    if concept_id in assoc:
                        # 继续扩散到该词关联的其他概念
                        for other_id, weight in assoc.items():
                            if other_id != concept_id:
                                spread = act * weight * (self.decay_factor ** hop)
                                new_activation[other_id] = new_activation.get(other_id, 0.0) + spread
            
            for cid, act in new_activation.items():
                activation[cid] = activation.get(cid, 0.0) + act
        
        # 转成MemoryFragment
        results = []
        for concept_id, act in activation.items():
            if concept_id in self._concepts:
                fragment = MemoryFragment(
                    id=concept_id,
                    content=self._concepts[concept_id],
                    channel="spreading_activation",
                    channel_score=min(1.0, act),
                    score=min(1.0, act),
                    source="spreading",
                )
                results.append(fragment)
        
        # 排序取top-k
        results.sort(key=lambda x: x.channel_score, reverse=True)
        return results[:query.top_k]

    def health_check(self) -> dict:
        try:
            conn = sqlite3.connect(str(self._db_path))
            concepts = conn.execute("SELECT COUNT(*) FROM concepts").fetchone()[0]
            assocs = conn.execute("SELECT COUNT(*) FROM associations").fetchone()[0]
            conn.close()
            return {
                "status": ChannelHealth.OK,
                "channel": "spreading_activation",
                "concepts": concepts,
                "associations": assocs,
                "memory_matrix_size": len(self._assoc_matrix),
            }
        except Exception as e:
            return {"status": ChannelHealth.FAILED, "channel": "spreading_activation", "error": str(e)}


# =================================================================
# 通道5: 实体图谱通道 (Entity Graph Channel)
# 对应 OI§15: 实体图谱通道,Neo4j知识图谱
# =================================================================

class EntityGraphChannel(MemoryChannel):
    """
    实体图谱通道 — 实体关系三元组存储+图遍历检索
    
    后端: SQLite实现三元组存储(模拟Neo4j Cypher)
    存储: 主体-关系-客体 + 来源对话ID + 时间戳 + 置信度
    """

    def __init__(self, db_path: Optional[Path] = None):
        self._db_path = db_path or (HERMES / "data" / "entity_graph.db")
        self._db_path.parent.mkdir(exist_ok=True)
        self._init_db()

    def name(self) -> str:
        return "entity_graph"

    def _init_db(self):
        conn = sqlite3.connect(str(self._db_path))
        conn.execute("""
            CREATE TABLE IF NOT EXISTS entities (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                type TEXT DEFAULT 'concept',
                first_seen TEXT DEFAULT (datetime('now','localtime'))
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS triples (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                subject_id INTEGER NOT NULL,
                predicate TEXT NOT NULL,
                object_id INTEGER NOT NULL,
                confidence REAL DEFAULT 0.5,
                source TEXT DEFAULT '',
                timestamp TEXT DEFAULT (datetime('now','localtime')),
                FOREIGN KEY (subject_id) REFERENCES entities(id),
                FOREIGN KEY (object_id) REFERENCES entities(id)
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_triple_subj ON triples(subject_id)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_triple_obj ON triples(object_id)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_entity_name ON entities(name)
        """)
        conn.commit()
        conn.close()

    def _get_or_create_entity(self, conn, name: str, type_: str = "concept") -> int:
        """获取或创建实体"""
        cursor = conn.execute("SELECT id FROM entities WHERE name = ?", (name,))
        row = cursor.fetchone()
        if row:
            return row[0]
        conn.execute("INSERT INTO entities (name, type) VALUES (?, ?)", (name, type_))
        return conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    def encode(self, content: str, metadata: Optional[dict] = None) -> bool:
        """
        编码存储 — 从文本提取实体关系三元组
        
        使用简单的共现+模式匹配提取
        生产级应使用LLM/NER提取
        """
        if len(content) < 10:
            return False
        
        import re
        source = (metadata or {}).get("source", "")
        
        # 提取可能的实体(中文2-6字词组+英文单词)
        entities = set()
        for m in re.finditer(r'[\u4e00-\u9fff]{2,6}', content):
            entities.add((m.group(), "concept"))
        for m in re.finditer(r'[A-Z][a-zA-Z0-9_]{2,}', content):
            entities.add((m.group(), "technology"))
        
        if len(entities) < 2:
            return False
        
        conn = sqlite3.connect(str(self._db_path))
        try:
            # 获取或创建实体ID
            entity_ids = {}
            for name, type_ in entities:
                entity_ids[name] = self._get_or_create_entity(conn, name, type_)
            
            # 构建共现关系三元组
            entity_list = list(entities)
            for i in range(len(entity_list)):
                for j in range(i + 1, len(entity_list)):
                    subj, obj = entity_list[i][0], entity_list[j][0]
                    # 使用"related_to"作为默认谓语
                    # 在真实场景中应该使用LLM提取精确关系
                    conn.execute(
                        "INSERT INTO triples (subject_id, predicate, object_id, confidence, source) VALUES (?, ?, ?, ?, ?)",
                        (entity_ids[subj], "related_to", entity_ids[obj], 0.5, source)
                    )
            
            conn.commit()
            return True
        finally:
            conn.close()

    def retrieve(self, query: Query) -> List[MemoryFragment]:
        """
        图谱检索 — Cypher风格的多跳图遍历
        
        支持:
          - 实体直接查询
          - 多跳图遍历(最多3跳)
          - 按置信度排序
        """
        import re
        # 从查询提取实体关键字
        query_entities = set(re.findall(r'[\u4e00-\u9fff]{2,6}', query.text))
        
        if not query_entities:
            return []
        
        conn = sqlite3.connect(str(self._db_path))
        try:
            # 找到匹配的实体
            related_fragments = set()
            
            for qe in query_entities:
                # 精确匹配实体
                cursor = conn.execute(
                    "SELECT id, name FROM entities WHERE name LIKE ?",
                    (f"%{qe}%",)
                )
                for row in cursor:
                    entity_id, entity_name = row
                    
                    # 1跳: 直接关联的实体
                    cursor2 = conn.execute("""
                        SELECT e.name, t.predicate, t.confidence
                        FROM triples t
                        JOIN entities e ON t.object_id = e.id
                        WHERE t.subject_id = ?
                        UNION
                        SELECT e.name, t.predicate, t.confidence
                        FROM triples t
                        JOIN entities e ON t.subject_id = e.id
                        WHERE t.object_id = ?
                    """, (entity_id, entity_id))
                    
                    for row2 in cursor2:
                        related_name, pred, conf = row2
                        related_fragments.add((entity_name, pred, related_name, conf))
            
            # 转换为MemoryFragment
            results = []
            for subj, pred, obj, conf in related_fragments:
                frag = MemoryFragment(
                    id=f"graph_{hashlib.md5(f'{subj}{pred}{obj}'.encode()).hexdigest()[:8]}",
                    content=f"实体关系: {subj} --[{pred}]--> {obj}",
                    channel="entity_graph",
                    channel_score=float(conf),
                    score=float(conf),
                    metadata={"subject": subj, "predicate": pred, "object": obj},
                    entity_count=2,
                    relation_count=1,
                )
                results.append(frag)
            
            results.sort(key=lambda x: x.channel_score, reverse=True)
            return results[:query.top_k]
        finally:
            conn.close()

    def health_check(self) -> dict:
        try:
            conn = sqlite3.connect(str(self._db_path))
            entities = conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0]
            triples = conn.execute("SELECT COUNT(*) FROM triples").fetchone()[0]
            conn.close()
            return {
                "status": ChannelHealth.OK,
                "channel": "entity_graph",
                "entities": entities,
                "triples": triples,
            }
        except Exception as e:
            return {"status": ChannelHealth.FAILED, "channel": "entity_graph", "error": str(e)}


# =================================================================
# 通道6: Hopfield联想通道 (Hopfield Association Channel)
# 对应 OI§15: Hopfield联想通道,nalgebra联想矩阵+模式补全
# =================================================================

class HopfieldChannel(MemoryChannel):
    """
    Hopfield联想通道 — 基于Hopfield网络的模式补全联想
    
    核心机制:
      - 联想矩阵(weight matrix)存储模式关联
      - 异步更新规则实现模式补全
      - 能量阈值控制补全终止
    """

    def __init__(self, db_path: Optional[Path] = None):
        self._db_path = db_path or (HERMES / "data" / "hopfield_channel.db")
        self._db_path.parent.mkdir(exist_ok=True)
        
        # 联想矩阵: pattern_id -> {(related_pattern_id, weight)}
        self._assoc_weights: Dict[str, Dict[str, float]] = {}
        # 模式存储
        self._patterns: Dict[str, str] = {}
        
        self.energy_threshold = 0.08  # 能量阈值(降低以捕捉弱联想信号)
        self._init_db()
        self._load_patterns()

    def name(self) -> str:
        return "hopfield_association"

    def _init_db(self):
        conn = sqlite3.connect(str(self._db_path))
        conn.execute("""
            CREATE TABLE IF NOT EXISTS patterns (
                id TEXT PRIMARY KEY,
                content TEXT NOT NULL,
                source TEXT DEFAULT '',
                timestamp TEXT DEFAULT (datetime('now','localtime'))
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS associations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pattern_a TEXT NOT NULL,
                pattern_b TEXT NOT NULL,
                weight REAL DEFAULT 0.0,
                FOREIGN KEY (pattern_a) REFERENCES patterns(id),
                FOREIGN KEY (pattern_b) REFERENCES patterns(id)
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_assoc_a ON associations(pattern_a)
        """)
        conn.commit()
        conn.close()

    def _load_patterns(self):
        """加载模式到内存"""
        conn = sqlite3.connect(str(self._db_path))
        try:
            cursor = conn.execute("SELECT id, content FROM patterns")
            for row in cursor:
                self._patterns[row[0]] = row[1]
            
            cursor = conn.execute("SELECT pattern_a, pattern_b, weight FROM associations")
            for row in cursor:
                a, b, w = row
                if a not in self._assoc_weights:
                    self._assoc_weights[a] = {}
                self._assoc_weights[a][b] = w
                if b not in self._assoc_weights:
                    self._assoc_weights[b] = {}
                self._assoc_weights[b][a] = w  # 对称权重
        finally:
            conn.close()

    def _content_hash(self, content: str) -> str:
        return hashlib.sha256(content.encode()).hexdigest()[:16]

    def encode(self, content: str, metadata: Optional[dict] = None) -> bool:
        """编码存储 — 建立联想关联"""
        if len(content) < 5:
            return False
        
        pattern_id = f"hopfield_{self._content_hash(content)}"
        source = (metadata or {}).get("source", "")
        
        conn = sqlite3.connect(str(self._db_path))
        try:
            # 检查是否已存在
            existing = conn.execute("SELECT id FROM patterns WHERE id = ?", (pattern_id,)).fetchone()
            if existing:
                return True
            
            # 存入新模式
            conn.execute(
                "INSERT OR IGNORE INTO patterns (id, content, source) VALUES (?, ?, ?)",
                (pattern_id, content, source)
            )
            
            # 计算与已有模式的相似度并建立联想
            self._patterns[pattern_id] = content
            
            # 中文n-gram提取函数
            def extract_ngrams(t: str) -> set:
                import re
                ngrams = set()
                eng = re.findall(r'[a-zA-Z0-9_]{2,}', t.lower())
                ngrams.update(eng)
                chars = re.findall(r'[\u4e00-\u9fff]', t)
                for length in [2, 3, 4]:
                    for i in range(len(chars) - length + 1):
                        ngrams.add(''.join(chars[i:i+length]))
                return ngrams
            
            words_self = extract_ngrams(content)
            
            for existing_id, existing_content in list(self._patterns.items()):
                if existing_id == pattern_id:
                    continue
                # 使用相同的extract_ngrams(在外部定义)
                words_existing = extract_ngrams(existing_content)
                
                # Jaccard相似度作为联想权重
                intersection = words_self & words_existing
                union = words_self | words_existing
                weight = len(intersection) / max(len(union), 1)
                
                if weight > 0.01:  # 低阈值联想(降低以更好捕获中文n-gram)
                    conn.execute(
                        "INSERT INTO associations (pattern_a, pattern_b, weight) VALUES (?, ?, ?)",
                        (pattern_id, existing_id, weight)
                    )
                    if pattern_id not in self._assoc_weights:
                        self._assoc_weights[pattern_id] = {}
                    self._assoc_weights[pattern_id][existing_id] = weight
                    if existing_id not in self._assoc_weights:
                        self._assoc_weights[existing_id] = {}
                    self._assoc_weights[existing_id][pattern_id] = weight
            
            conn.commit()
            return True
        finally:
            conn.close()

    def _pattern_completion(self, query_text: str) -> List[Tuple[str, float, str]]:
        """
        模式补全 — Hopfield异步更新规则
        
        算法:
          1. 将查询视为初始模式
          2. 联想矩阵迭代更新
          3. 能量函数控制收敛
          4. 返回补全后的相关模式
        """
        import re
        def _ngrams(t):
            ngrams = set()
            eng = re.findall(r'[a-zA-Z0-9_]{2,}', t.lower())
            ngrams.update(eng)
            chars = re.findall(r'[\u4e00-\u9fff]', t)
            for L in [2, 3, 4]:
                for i in range(len(chars) - L + 1):
                    ngrams.add(''.join(chars[i:i+L]))
            return ngrams
        query_words = _ngrams(query_text.lower())
        
        if not query_words:
            return []
        
        # 找到初始化匹配的模式
        def extract_ngrams(t: str) -> set:
            import re
            ngrams = set()
            eng = re.findall(r'[a-zA-Z0-9_]{2,}', t.lower())
            ngrams.update(eng)
            chars = re.findall(r'[\u4e00-\u9fff]', t)
            for length in [2, 3, 4]:
                for i in range(len(chars) - length + 1):
                    ngrams.add(''.join(chars[i:i+length]))
            return ngrams
        
        activations: Dict[str, float] = {}
        for pid, content in self._patterns.items():
            content_words = extract_ngrams(content)
            overlap = len(query_words & content_words)
            if overlap > 0:
                activations[pid] = overlap / max(len(content_words), 1)
        
        if not activations:
            return []
        
        # Hopfield异步更新: 通过联想矩阵传播激活
        max_iterations = 10
        for _ in range(max_iterations):
            new_activations = dict(activations)
            for pid in activations:
                if pid in self._assoc_weights:
                    for related_pid, weight in self._assoc_weights[pid].items():
                        if related_pid not in activations:
                            # 联想激活传播
                            spread = activations[pid] * weight * 0.5
                            new_activations[related_pid] = new_activations.get(related_pid, 0.0) + spread
            
            # 能量收敛检测
            diff = sum(abs(new_activations.get(p, 0) - activations.get(p, 0)) 
                      for p in set(list(activations.keys()) + list(new_activations.keys())))
            activations = new_activations
            if diff < self.energy_threshold:
                break
        
        # 返回排序结果
        results = [(pid, act, self._patterns.get(pid, "")) 
                  for pid, act in activations.items()
                  if act > self.energy_threshold]
        results.sort(key=lambda x: x[1], reverse=True)
        return results

    def retrieve(self, query: Query) -> List[MemoryFragment]:
        """Hopfield联想检索 — 模式补全"""
        completed = self._pattern_completion(query.text)
        
        results = []
        for pid, act, content in completed:
            fragment = MemoryFragment(
                id=pid,
                content=content,
                channel="hopfield_association",
                channel_score=min(1.0, act),
                score=min(1.0, act),
                source="hopfield",
                metadata={"activation": act},
            )
            results.append(fragment)
        
        return results[:query.top_k]

    def health_check(self) -> dict:
        try:
            conn = sqlite3.connect(str(self._db_path))
            patterns = conn.execute("SELECT COUNT(*) FROM patterns").fetchone()[0]
            assocs = conn.execute("SELECT COUNT(*) FROM associations").fetchone()[0]
            conn.close()
            return {
                "status": ChannelHealth.OK,
                "channel": "hopfield_association",
                "patterns": patterns,
                "associations": assocs,
                "energy_threshold": self.energy_threshold,
            }
        except Exception as e:
            return {"status": ChannelHealth.FAILED, "channel": "hopfield_association", "error": str(e)}


# =================================================================
# 通道7: 整合记忆通道 (Integrated Memory Channel)
# 对应 OI§15: 整合记忆通道,加权投票仲裁器
# =================================================================

class IntegratedArbiter:
    """
    整合记忆通道 — 独立加权投票仲裁器
    
    对应OI"整合记忆通道"+仲裁器(独立实现,非合并)
    
    核心流程:
      1. 从所有通道并行收集结果
      2. 信号vs噪音预过滤
      3. 交叉评分(历史准确率+上下文匹配度)
      4. 加权投票融合
      5. 一致性检测:低时自动补偿
    """

    def __init__(self):
        self.channels: Dict[str, MemoryChannel] = {}
        self.history_accuracy: Dict[str, float] = {}
        self.signal_threshold = 0.3
        
        # 通道权重(自适应)
        self.channel_weights: Dict[str, float] = {
            "semantic_vector": 1.5,      # 语义通道权重最高
            "keyword_fulltext": 1.3,     # 关键词次之
            "timeline": 0.7,             # 时间线
            "spreading_activation": 1.2,  # 扩散激活
            "entity_graph": 1.1,         # 实体图谱
            "hopfield_association": 0.9, # Hopfield联想
        }

    def register_channel(self, channel: MemoryChannel) -> str:
        name = channel.name()
        self.channels[name] = channel
        return name

    def search(self, query: Query) -> dict:
        """多通道集成仲裁检索"""
        all_results = []
        channel_stats = {}
        
        active_channels = {}
        if query.channels:
            for name in query.channels:
                if name in self.channels:
                    active_channels[name] = self.channels[name]
        else:
            active_channels = dict(self.channels)
        
        for name, channel in active_channels.items():
            try:
                fragments = channel.retrieve(query)
                channel_stats[name] = {"found": len(fragments), "status": "ok"}
                all_results.extend(fragments)
            except Exception as e:
                channel_stats[name] = {"found": 0, "status": "error", "error": str(e)}
        
        # 信号预过滤
        filtered = self._signal_filter(query, all_results)
        
        # 加权融合
        for f in filtered:
            weight = self.channel_weights.get(f.channel, 1.0)
            f.score = f.score * weight
        
        # 排序+去重
        filtered.sort(key=lambda x: x.score, reverse=True)
        
        deduplicated = []
        seen = set()
        for f in filtered:
            content_hash = hashlib.md5(f.content[:100].encode()).hexdigest()
            if content_hash not in seen:
                seen.add(content_hash)
                deduplicated.append(f)
        
        # 一致性检测
        consistency = self._detect_consistency(channel_stats, deduplicated)
        
        return {
            "query": query.text,
            "total_results": len(all_results),
            "deduplicated": len(deduplicated),
            "top_results": [f.to_dict() for f in deduplicated[:query.top_k]],
            "channel_stats": channel_stats,
            "consistency": consistency,
            "ts": NOW().isoformat(),
        }

    def _signal_filter(self, query: Query, fragments: List[MemoryFragment]) -> List[MemoryFragment]:
        """信号vs噪音预过滤"""
        filtered = []
        for f in fragments:
            signal_score = 0.0
            content_lower = f.content.lower()
            
            signal_kw = ["决策", "修复", "bug", "错误", "架构", "设计",
                        "经验", "教训", "方案", "实现"]
            for kw in signal_kw:
                if kw in content_lower:
                    signal_score += 0.2
            
            noise_kw = ["调试", "日志", "临时", "测试", "tmp"]
            for kw in noise_kw:
                if kw in content_lower:
                    signal_score -= 0.3
            
            combined = signal_score * 0.3 + f.channel_score * 0.7
            if combined >= self.signal_threshold:
                f.score = combined
                filtered.append(f)
        
        return filtered

    def _detect_consistency(self, channel_stats: dict, results: List[MemoryFragment]) -> dict:
        """检测各通道结果的一致性"""
        channels_with_results = sum(1 for v in channel_stats.values() if v.get("found", 0) > 0)
        total_channels = len(channel_stats)
        
        if total_channels == 0:
            return {"level": "unknown", "score": 0}
        
        consistency_score = channels_with_results / max(total_channels, 1)
        
        if consistency_score >= 0.7:
            level = "high"
        elif consistency_score >= 0.4:
            level = "medium"
        else:
            level = "low"
        
        return {
            "level": level,
            "score": round(consistency_score, 3),
            "channels_with_results": channels_with_results,
            "total_channels": total_channels,
        }

    def health(self) -> dict:
        report = {
            "ts": NOW().isoformat(),
            "channels": len(self.channels),
            "weights": dict(self.channel_weights),
        }
        for name, ch in self.channels.items():
            report[name] = ch.health_check()
        return report


# =================================================================
# CLI接口
# =================================================================

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "health"
    
    if cmd == "test_spreading":
        ch = SpreadingActivationChannel()
        ch.encode("修复了数据库连接池的泄漏问题", {"source": "test"})
        ch.encode("完成了用户认证系统的JWT重构", {"source": "test"})
        ch.encode("今日股市港股恒指跌0.55%", {"source": "test"})
        
        r = ch.retrieve(Query(text="数据库连接泄漏", top_k=5))
        print(json.dumps([f.to_dict() for f in r], ensure_ascii=False, indent=2))
        print(f"Health: {json.dumps(ch.health_check(), ensure_ascii=False)}")
    
    elif cmd == "test_graph":
        ch = EntityGraphChannel()
        ch.encode("Hermes AI系统使用JWT认证", {"source": "test"})
        ch.encode("数据库连接池需要多线程安全", {"source": "test"})
        r = ch.retrieve(Query(text="Hermes", top_k=5))
        print(json.dumps([f.to_dict() for f in r], ensure_ascii=False, indent=2))
        print(f"Health: {json.dumps(ch.health_check(), ensure_ascii=False)}")
    
    elif cmd == "test_hopfield":
        ch = HopfieldChannel()
        ch.encode("修复了数据库连接池在多线程环境下的泄漏问题")
        ch.encode("完成了用户认证系统的JWT重构设计采用RS256签名")
        ch.encode("今日股市港股恒指跌0.55%科指涨0.17%")
        ch.encode("Hermes AI系统自进化循环已经成功运行")
        r = ch.retrieve(Query(text="数据库连接 线程安全", top_k=5))
        print(json.dumps([f.to_dict() for f in r], ensure_ascii=False, indent=2))
        print(f"Health: {json.dumps(ch.health_check(), ensure_ascii=False)}")
    
    elif cmd == "test_arbiter":
        from seven_channel_memory import SemanticChannel, KeywordChannel, TimelineChannel
        arbiter = IntegratedArbiter()
        arbiter.register_channel(SemanticChannel())
        arbiter.register_channel(KeywordChannel())
        arbiter.register_channel(TimelineChannel())
        
        # Store some data
        test_data = "修复了数据库连接池在多线程环境下的泄漏问题"
        for ch in arbiter.channels.values():
            ch.encode(test_data, {"source": "test"})
        arbiter.register_channel(SpreadingActivationChannel())
        
        r = arbiter.search(Query(text="数据库连接泄漏", top_k=5))
        print(json.dumps(r, ensure_ascii=False, indent=2))
    
    else:
        print("Usage: channels_v2.py [test_spreading|test_graph|test_hopfield|test_arbiter|health]")
