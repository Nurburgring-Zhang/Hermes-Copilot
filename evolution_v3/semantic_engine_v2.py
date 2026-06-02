"""
⚙️ 语义嵌入引擎 V2.0 + 英中文混合漂移检测
================================================================
修复GAP2: 嵌入精度限制 — 自动检测并使用sentence-transformers(回退n-gram)
修复GAP5: 英中文混合漂移检测 — 中英文关键词分开处理

核心改进:
  1. sentence-transformers自动检测(384维真实嵌入)
  2. 如果不可用, 自动回退增强型n-gram(128维+位置权重)
  3. 英中文分开的漂移检测策略
  4. 同义词映射(如JWT≡认证≡Token)
"""

import json, os, sys, re, hashlib
from pathlib import Path
from typing import Optional, List, Tuple, Dict

HERMES = Path.home() / ".hermes"


class SemanticEmbeddingEngine:
    """
    语义嵌入引擎 V2.0
    
    自动检测可用模型:
      1. sentence-transformers (384/768维) — 首选
      2. ONNX Runtime (384维) — 次选
      3. 增强型n-gram hash (128维) — 回退
    """

    def __init__(self):
        self._model = None
        self._model_type = None
        self._dimension = 128
        self._loaded = False
        self._load_model()

    def _load_model(self):
        """尝试加载最优可用模型"""
        # 尝试sentence-transformers
        try:
            from sentence_transformers import SentenceTransformer
            cache = str(HERMES / "models")
            self._model = SentenceTransformer('all-MiniLM-L6-v2', cache_folder=cache)
            self._model_type = "sentence-transformers"
            self._dimension = 384
            self._loaded = True
            return
        except Exception:
            pass
        
        # 尝试ONNX
        try:
            import onnxruntime
            model_path = HERMES / "models" / "embedding.onnx"
            if model_path.exists():
                self._model = onnxruntime.InferenceSession(str(model_path))
                self._model_type = "onnx"
                self._dimension = 384
                self._loaded = True
                return
        except Exception:
            pass
        
        # 回退到增强型n-gram
        self._model_type = "enhanced_ngram"
        self._dimension = 128
        self._loaded = True

    def embed(self, text: str) -> List[float]:
        """获取文本嵌入向量"""
        if not self._loaded:
            self._load_model()
        
        if self._model_type == "sentence-transformers":
            return self._model.encode(text).tolist()
        elif self._model_type == "onnx":
            return self._model.run(None, {"input": [text]})[0][0].tolist()
        else:
            return self._enhanced_ngram_embed(text)

    def _enhanced_ngram_embed(self, text: str) -> List[float]:
        """
        增强型n-gram hash嵌入(128维)
        
        改进:
          - 英文字母单独处理(不split成字符)
          - 位置权重(前部关键词权重更高)
          - 中文2-4字滑动窗口
        """
        vec = [0.0] * 128
        text_lower = text.lower()
        
        # 英文单词(完整word hash)
        eng_words = re.findall(r'[a-zA-Z0-9_]+', text_lower)
        for word in eng_words:
            if len(word) >= 2:
                idx = (hash(word) % 128 + 128) % 128
                vec[idx] += len(word) * 0.3  # 长词权重大
        
        # 中文n-gram(2-4字滑动窗口)
        chars = re.findall(r'[\u4e00-\u9fff]', text_lower)
        for length in [2, 3, 4]:
            for i in range(len(chars) - length + 1):
                ngram = ''.join(chars[i:i+length])
                idx = (hash(ngram) % 128 + 128) % 128
                # 前部词权重高(位置信息)
                pos_weight = 1.0 - (i / max(len(chars), 1)) * 0.3
                vec[idx] += pos_weight
        
        # 归一化
        norm = sum(x * x for x in vec) ** 0.5
        if norm > 0:
            vec = [x / norm for x in vec]
        
        return vec

    def cosine_similarity(self, v1: List[float], v2: List[float]) -> float:
        """余弦相似度"""
        if not v1 or not v2:
            return 0.0
        dot = sum(a * b for a, b in zip(v1, v2))
        n1 = sum(a * a for a in v1) ** 0.5
        n2 = sum(b * b for b in v2) ** 0.5
        if n1 * n2 == 0:
            return 0.0
        return dot / (n1 * n2)

    def model_info(self) -> dict:
        """返回当前模型信息"""
        return {
            "type": self._model_type,
            "dimension": self._dimension,
            "loaded": self._loaded,
        }


class EnhancedDriftDetector:
    """
    增强型漂移检测器 V2.0
    
    修复GAP5: 英中文混合漂移检测
    策略:
      1. 中文trigram重叠(原有)
      2. 英文关键词重叠(新增)
      3. 同义词映射(新增, JWT↔Token↔认证)
      4. 语义嵌入相似度(新增, 使用SemanticEmbeddingEngine)
    """

    def __init__(self):
        self.embedding_engine = SemanticEmbeddingEngine()
        # 同义词映射
        self.synonym_map = {
            "jwt": ["jwt", "token", "认证", "验证", "auth", "authentication", "签名", "signature", "凭证"],
            "数据库": ["数据库", "db", "sql", "data", "数据", "连接池", "查询", "事务"],
            "用户": ["用户", "user", "账户", "账号", "登录", "login", "身份", "身份验证"],
            "修复": ["修复", "fix", "bug", "修补", "补丁", "修理", "修復"],
            "重构": ["重构", "重建", "refactor", "重写", "重设计", "重新设计", "优化"],
            "部署": ["部署", "deploy", "发布", "上线", "生产", "交付", "发布上线"],
            "测试": ["测试", "test", "验证", "单元测试", "集成测试", "调试", "用例"],
            "性能": ["性能", "performance", "优化", "加速", "吞吐量", "延迟", "响应"],
            "安全": ["安全", "security", "加密", "防护", "防火墙", "漏洞", "攻击"],
            "代码": ["代码", "code", "编码", "编程", "实现", "编写", "编程语言"],
            "系统": ["系统", "system", "平台", "架构", "框架", "框架设计", "体系"],
            "接口": ["接口", "api", "rest", "rpc", "api接口", "端点", "endpoint"],
            "设计": ["设计", "设计", "design", "架构设计", "方案", "技术方案"],
            "配置": ["配置", "config", "设置", "参数", "configuration", "setup"],
            "文档": ["文档", "doc", "documentation", "文档编写", "readme", "文档化"],
        }

    def _expand_synonyms(self, text: str) -> set:
        """扩展同义词"""
        expanded = set()
        text_lower = text.lower()
        
        # 添加原始n-gram
        chars = re.findall(r'[\u4e00-\u9fff]', text_lower)
        for length in [2, 3]:
            for i in range(len(chars) - length + 1):
                expanded.add(''.join(chars[i:i+length]))
        
        # 添加英文关键词
        eng = re.findall(r'[a-zA-Z0-9_]{2,}', text_lower)
        expanded.update(eng)
        
        # 添加同义词: 检查word是否与任何同义词匹配
        for word in list(expanded):
            for key, synonyms in self.synonym_map.items():
                # 检查word是否匹配任何同义词(包含或被包含)
                if any(s in word or word in s for s in synonyms):
                    expanded.update(synonyms)
        
        return expanded

    def detect_drift(self, goal: str, context: str, 
                     current_step: int, total_steps: int) -> dict:
        """
        增强型漂移检测
        
        使用三重检测:
          1. 同义词增强的关键词重叠
          2. 语义嵌入余弦相似度
          3. 进度偏离度
        """
        # 检测1: 同义词增强重叠
        goal_kw = self._expand_synonyms(goal)
        context_kw = self._expand_synonyms(context)
        
        if not context_kw:
            return {"drift_level": "ok", "score": 0.0, "action": "上下文不足"}
        
        overlap = len(goal_kw & context_kw)
        # 使用min归一化而不是除以goal_kw总数(避免同义词扩展导致分母过大)
        min_size = min(len(goal_kw), len(context_kw))
        kw_similarity = overlap / max(min_size, 1)
        kw_similarity = min(1.0, kw_similarity * 2.0)  # 放大以补偿min分母
        kw_distance = 1.0 - kw_similarity
        
        # 检测2: 语义嵌入相似度
        try:
            emb_goal = self.embedding_engine.embed(goal)
            emb_ctx = self.embedding_engine.embed(context)
            emb_similarity = self.embedding_engine.cosine_similarity(emb_goal, emb_ctx)
            emb_distance = 1.0 - emb_similarity
        except Exception:
            emb_distance = kw_distance  # 嵌入不可用时回退
        
        # 综合漂移分(0.5语义 + 0.3关键词 + 0.2进度)
        progress_deviation = abs(0.5 - current_step / max(total_steps, 1)) * 0.5 if total_steps > 0 else 0
        drift_score = emb_distance * 0.5 + kw_distance * 0.3 + progress_deviation * 0.2
        
        # 如果接近完成, 降低漂移警告
        if total_steps > 0 and current_step / total_steps > 0.8:
            drift_score *= 0.6
        
        drift_score = min(1.0, max(0.0, drift_score))
        
        # 判定等级(降低阈值)
        if drift_score < 0.25:
            level = "ok"
            action = "正常执行"
        elif drift_score < 0.5:
            level = "mild"
            action = "轻度偏移"
        elif drift_score < 0.7:
            level = "moderate"
            action = "中度偏移, 需干预"
        else:
            level = "severe"
            action = "严重偏离目标"
        
        return {
            "drift_level": level,
            "score": round(drift_score, 4),
            "kw_overlap": round(kw_similarity, 4),
            "emb_similarity": round(1 - emb_distance, 4) if emb_distance != kw_distance else None,
            "action": action,
        }


if __name__ == "__main__":
    print("=== 语义嵌入引擎测试 ===")
    eng = SemanticEmbeddingEngine()
    info = eng.model_info()
    print(f"模型: {info}")
    
    v1 = eng.embed("实现用户认证系统的JWT重构")
    v2 = eng.embed("完成JWT token的RS256签名验证模块")
    sim = eng.cosine_similarity(v1, v2)
    print(f"相似(JWT重构 vs RS256验证): {sim:.4f}")
    
    v3 = eng.embed("今天天气很好适合去公园散步")
    sim2 = eng.cosine_similarity(v1, v3)
    print(f"相似(JWT重构 vs 天气散步): {sim2:.4f}")
    
    print()
    print("=== 增强型漂移检测测试 ===")
    det = EnhancedDriftDetector()
    
    # 同主题
    r1 = det.detect_drift("实现用户认证系统的JWT重构", "完成JWT token的RS256签名验证模块", 3, 5)
    print(f"同主题(JWT): level={r1['drift_level']} score={r1['score']:.3f} overlap={r1['kw_overlap']:.3f}")
    
    # 不同主题
    r2 = det.detect_drift("实现用户认证系统的JWT重构", "今天天气很好适合去公园散步", 1, 10)
    print(f"不同主题: level={r2['drift_level']} score={r2['score']:.3f}")
    
    # 部分相关
    r3 = det.detect_drift("数据库连接池泄漏修复", "完成了数据库连接的配置", 2, 5)
    print(f"部分相关(数据库): level={r3['drift_level']} score={r3['score']:.3f}")
