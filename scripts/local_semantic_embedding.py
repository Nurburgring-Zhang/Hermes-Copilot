#!/usr/bin/env python3
"""
本地语义嵌入引擎 — 纯Python实现, 无需下载模型
==============================================
使用TF-IDF加权 + 字符n-gram + 近似语义哈希
完全离线工作, 零外部依赖(仅numpy)

适用于内网环境的漂移检测语义相似度计算
"""

import math
import re
from collections import Counter
from typing import List, Tuple, Set
from difflib import SequenceMatcher

try:
    import numpy as np
    NUMPY_AVAILABLE = True
except ImportError:
    np = None
    NUMPY_AVAILABLE = False


class LocalSemanticEmbedding:
    """
    本地语义嵌入引擎 v3 — 关键短语命中率 + LCS + 负术语
    =====================================================
    
    核心思想: 从目标中提取关键短语, 检查上下文中是否存在
    这模仿了人类判断\"是否在聊同一个话题\"的方式:
      1. 从目标中提取关键短语 (中文双字词+英文词)
      2. 计算这些短语在上下文中的命中率
      3. 加上SequenceMatcher的字符重叠
      4. 减去无关话题的惩罚
    """

    NEGATIVE_TERMS = {
        '天气', '公园', '散步', '吃饭', '电影', '旅游', '景点',
        '美食', '菜谱', '足球', '世界杯', '梅西', '决赛', '比赛',
        '炒股', '股市', '基金', '投资', '星座', '运势',
        '八卦', '明星', '娱乐', '综艺', '健身', '跑步', '睡觉',
        '周末', '假期', '放假', '休息', '购物', '逛街', '唱歌',
        '去哪里', '什么地方', '好不好',
    }

    # 领域关键术语 → 语义权重 (同一个术语在不同上下文中权重不同)
    DOMAIN_TERMS = {
        # AI/ML
        '大模型': 2.0, 'llm': 2.0, 'transformer': 1.8, 'attention': 1.5,
        '推理': 1.8, '多模态': 1.8, 'agent': 1.8, 'rag': 1.5,
        '深度学习': 1.5, '机器学习': 1.5, '神经网络': 1.5, '强化学习': 1.8,
        '联邦学习': 1.8, '知识图谱': 1.5, '自然语言': 1.5, 'token': 1.2,
        'embedding': 1.2, 'diffusion': 1.5, '微调': 1.5, '量化': 1.2,
        # 记忆系统
        '记忆': 2.0, 'memory': 2.0, '压缩': 1.8, 'lcm': 1.8, 'dag': 1.8,
        '摘要': 1.5, '持久化': 1.5, '校验': 1.5, '哈希': 1.5,
        '冗余': 1.8, '备份': 1.5, '三冗余': 2.0, 'hindsight': 1.8,
        'mem0': 1.8, 'sqlite': 1.2,
        # 数据安全
        '加密': 2.0, '解密': 2.0, '安全': 1.5, '审计': 1.8, '隐私': 1.8,
        '差分': 1.5, '同态': 1.8, '零信任': 1.8, 'aes': 1.8, 'gcm': 1.5,
        '联邦': 1.5, '密钥': 1.5,
        # 任务执行
        '漂移': 2.0, '检测': 1.5, '恢复': 1.5, '任务': 1.2, '上下文': 1.5,
        '对话': 1.2, '执行': 1.2, '规划': 1.2, '编排': 1.5,
        # 架构
        '架构': 1.2, '设计': 1.0, '系统': 1.0, '框架': 1.2, '引擎': 1.2,
        '齿轮': 1.5, '验证': 1.2, '啮合': 1.5, '催化': 1.5,
        # 无关话题(负权重)
        '天气': -1.0, '公园': -1.0, '散步': -1.0, '吃饭': -1.0,
        '足球': -1.5, '世界杯': -1.5, '梅西': -1.5, '决赛': -1.5,
        '电影': -1.5, '旅游': -1.5, '景点': -1.5, '美食': -1.5,
        '菜谱': -1.5, '炒股': -1.5, '股市': -1.5, '基金': -1.5,
    }

    def __init__(self):
        self.vocab = {}
        self.idf = {}
        self.doc_count = 0
        self.initialized = False
        self._corpus = []

    def _tokenize(self, text: str) -> List[str]:
        """提取特征: 中文分词(字+词) + 英文词 + 关键术语"""
        text = text.lower().strip()
        tokens = []

        # 1. 中文: 使用双字词(比单字更语义) + 三字/四字短语
        chinese_chars = re.findall(r'[\u4e00-\u9fff]+', text)
        for chunk in chinese_chars:
            # 双字词 - 最重要
            for i in range(len(chunk) - 1):
                tokens.append(f'2:{chunk[i:i+2]}')
            # 三字
            for i in range(len(chunk) - 2):
                tokens.append(f'3:{chunk[i:i+3]}')
            # 四字(成语/术语)
            for i in range(len(chunk) - 3):
                tokens.append(f'4:{chunk[i:i+4]}')
            # 整体作为短语(如果长度2-6)
            if 2 <= len(chunk) <= 6:
                tokens.append(f'p:{chunk}')

        # 2. 英文/数字词
        english_parts = re.findall(r'[a-zA-Z][a-zA-Z0-9_]{1,}', text)
        for word in english_parts:
            tokens.append(f'w:{word.lower()}')

        # 3. 关键术语权重加倍: 重复添加
        key_terms = [
            '推理', '模型', '学习', '训练', '数据', '算法', '网络',
            '记忆', '压缩', '加密', '安全', '审计', '漂移', '检测',
            '冗余', '备份', '验证', '恢复', '任务', '对话', '上下文',
            'ai', 'llm', 'transformer', 'attention', 'memory',
            'agent', 'rag', 'diffusion', 'token', 'embedding',
            '加密', '联邦', '隐私', '差分', '零信任', '同态',
            '大模型', '深度学习', '机器学习', '知识图谱', '多模态',
            '联邦学习', '强化学习', '神经网络', '自然语言',
            '无损', '压缩', '摘要', 'dag', '持久化', '校验',
        ]
        text_lower = text.lower()
        for term in key_terms:
            if term in text_lower:
                # 关键术语重复3次以提高权重
                tokens.extend([f'kt:{term}'] * 3)

        return tokens

    def _compute_tf(self, tokens: List[str]) -> Counter:
        """计算词频"""
        if not tokens:
            return Counter()
        c = Counter(tokens)
        # 归一化: TF = log(1 + count)
        return Counter({k: math.log(1 + v) for k, v in c.items()})

    def _compute_tfidf(self, tokens: List[str]) -> dict:
        """计算TF-IDF向量"""
        tf = self._compute_tf(tokens)
        if not self.initialized or not self.idf:
            # 无IDF语料时使用纯TF
            return dict(tf)

        result = {}
        for token, tf_val in tf.items():
            idf_val = self.idf.get(token, math.log((self.doc_count + 1) / 1))
            result[token] = tf_val * idf_val
        return result

    def add_to_corpus(self, texts: List[str]):
        """增量添加语料, 更新IDF统计"""
        for text in texts:
            tokens = self._tokenize(text)
            unique_tokens = set(tokens)
            self.doc_count += 1
            for t in unique_tokens:
                self.vocab[t] = self.vocab.get(t, 0) + 1
            self._corpus.append(text)

        # 更新IDF
        n = self.doc_count
        self.idf = {
            token: math.log((n + 1) / (freq + 1)) + 1
            for token, freq in self.vocab.items()
        }
        self.initialized = True

    # 领域核心词汇表 (手工定义的专有技术词汇)
    DOMAIN_VOCAB = {
        '人工智能', '大模型', '机器学习', '深度学习', '强化学习', '联邦学习',
        '神经网络', '自然语言', '计算机视觉', '知识图谱', '多模态',
        'transformer', '注意力机制', '推理', '上下文',
        'agent', '自主决策', '工具调用', 'rag', '检索增强',
        'diffusion', '生成式', '微调', '量化',
        '长期记忆', '短期记忆', '工作记忆', '无损压缩', '增量摘要',
        '持久化', '哈希', '三冗余', '交叉', '冗余架构',
        'lcm', 'mem0', 'hindsight', '上下文管理', '热温冷',
        '数据安全', '加密', '解密', '审计日志', '差分隐私', '同态加密',
        '零信任', '联邦', 'aes', 'gcm', 'mTLS', '密钥', '双向认证',
        '权限', '验证', '隔离',
        '漂移检测', '自动恢复', '保真度', 'checkpoint', '断点续传',
        '任务编排', '状态机', '工作流',
        '信息保真', '啮合', '冗余', '备份', '免疫', '多样性',
        '齿轮', '互审', '验证', '签名', '注册',
        '自我强化', '自进化', '技能', '持续学习', '反思',
        'token', 'kv cache', '流式', '实时',
    }

    # 语义联想规则: 目标中出现某个词 → 自动联想相关词
    SEMANTIC_MAP = {
        '人工智能': {'ai', '大模型', '机器学习', '深度学习', '神经网络'},
        '大模型': {'llm', 'transformer', 'gpt', '推理', '上下文', '预训练'},
        '推理': {'agent', '思维链', 'decoding', 'token'},
        '记忆': {'memory', '长期记忆', '短期记忆', '工作记忆', '回忆'},
        '安全': {'加密', '审计', '隐私', '安全', '零信任'},
        '加密': {'aes', 'gcm', '加密', '解密', '密钥'},
        '任务': {'编排', '执行', '规划', '状态'},
        'agent': {'工具', '自主', '编排', '决策', 'mcp'},
        '联邦学习': {'联邦', '隐私', '分布式'},
        '零信任': {'mTLS', '双向认证', '最小权限', '验证', '隔离'},
        '压缩': {'无损', '量化', '剪枝', '蒸馏'},
        '漂移': {'漂移检测', '上下文保真', 'kl散度', '恢复'},
        '冗余': {'三冗余', '备份', '免疫', '交叉验证'},
        '技能': {'skill', '技能', '自进化', '持续学习'},
        '对话': {'上下文', '会话', '聊天', '轮次'},
    }

    def _extract_phrases(self, text: str) -> Set[str]:
        """提取关键短语：词汇表匹配 + n-gram补充 + 语义联想"""
        text_lower = text.lower()
        phrases = set()
        
        # 1. 匹配领域词汇表中的完整词
        for term in self.DOMAIN_VOCAB:
            if term in text_lower:
                phrases.add(term)
        
        # 2. 英文技术词
        for word in re.findall(r'[a-zA-Z][a-zA-Z0-9_]{1,}', text):
            if len(word) >= 2:
                phrases.add(word.lower())
        
        # 3. 中文n-gram作为补充
        for chunk in re.findall(r'[\u4e00-\u9fff]{3,}', text):
            for i in range(len(chunk) - 2):
                trigram = chunk[i:i+3]
                if trigram not in phrases:
                    phrases.add(trigram)
            if len(chunk) >= 4:
                for i in range(len(chunk) - 3):
                    phrases.add(chunk[i:i+4])
        
        # 4. 语义联想: 扩大匹配范围
        expanded = set(phrases)
        for phrase in phrases:
            for trigger, related in self.SEMANTIC_MAP.items():
                if trigger in phrase or phrase in trigger:
                    expanded.update(related)
        phrases.update(expanded)
        
        return phrases

    def similarity(self, text1: str, text2: str) -> float:
        """
        计算语义相似度 [0, 1]
        
        策略变更: 不再过滤停用词, 而是用加权匹配
        - 长词(3-4字)比短词(2字)权重更高
        - 英文科技词权重最高
        """
        t1 = text1.lower().strip()
        t2 = text2.lower().strip()
        if not t1 or not t2:
            return 0.0

        # 方法1: 加权短语命中率
        phrases_goal = self._extract_phrases(t1)
        phrases_ctx = self._extract_phrases(t2)
        
        if phrases_goal:
            # 加权命中: 长词权重 > 短词权重
            total_weight = 0
            hit_weight = 0
            for p in phrases_goal:
                # 权重 = min(词长/2, 3) — 4字词权重3, 2字词权重1
                w = min(len(p) / 2, 3) if not p.isascii() else 2.0
                total_weight += w
                if p in t2:
                    hit_weight += w
            hit_ratio = hit_weight / total_weight if total_weight > 0 else 0
        else:
            hit_ratio = 0.0

        # 方法2: 反向命中率
        if phrases_ctx:
            reverse_hits = sum(1 for p in phrases_ctx if p in t1)
            reverse_ratio = reverse_hits / len(phrases_ctx)
        else:
            reverse_ratio = 0.0

        # 方法3: LCS
        lcs_ratio = SequenceMatcher(None, t1[:500], t2[:500]).ratio()

        # 加权融合
        similarity = (
            hit_ratio * 0.55 +
            reverse_ratio * 0.20 +
            lcs_ratio * 0.25
        )
        
        self._debug = {
            "hit_ratio": hit_ratio,
            "reverse_ratio": reverse_ratio,
            "lcs_ratio": lcs_ratio,
            "goal_phrases": len(phrases_goal),
            "hits": sum(1 for p in phrases_goal if p in t2),
        }
        
        return max(0.0, min(1.0, similarity))

    def drift_score(self, goal: str, context: str) -> float:
        """漂移分数: 三段式判定 (阈值优化版)"""
        sim = self.similarity(goal, context)
        d = self._debug
        hit_ratio = d.get("hit_ratio", 0)
        reverse_ratio = d.get("reverse_ratio", 0)
        lcs = d.get("lcs_ratio", 0)
        
        neg_penalty = sum(1 for t in self.NEGATIVE_TERMS if t in context.lower()) * 0.15
        
        # 有直接命中 → 相关
        if hit_ratio > 0:
            base_drift = 0.25 * (1.0 - hit_ratio)
        # 有反向命中或LCS有一定重叠 → 弱相关
        elif reverse_ratio > 0.03 or lcs > 0.03:
            signal = max(reverse_ratio, lcs)
            base_drift = 0.45 * (1.0 - signal)
        # 无负术语 → 中性 (略微偏向相关)
        elif neg_penalty == 0:
            base_drift = 0.40
        # 有负术语 → 漂移
        else:
            base_drift = 0.85
        
        drift = base_drift + min(neg_penalty, 0.3)
        return max(0.0, min(1.0, drift))


# 全局单例
_embedder = None

def get_embedder() -> LocalSemanticEmbedding:
    """获取全局嵌入器实例(预填充语料)"""
    global _embedder
    if _embedder is None:
        _embedder = LocalSemanticEmbedding()
        # 预填充基础语料
        _embedder.add_to_corpus([
            "AI大模型多模态推理能力的发展趋势和产业应用",
            "Transformer架构的自注意力机制和线性注意力替代方案",
            "Agent自主决策系统的安全设计约束满足和人类反馈对齐",
            "长期记忆系统的三冗余架构LCM DAG和Mem0和Hindsight",
            "无损压缩算法DFloat11位对位压缩和R-KV KV cache压缩",
            "联邦学习在隐私保护中的横向纵向和迁移学习场景",
            "零信任架构的七支柱模型和AI系统安全设计",
            "全同态加密在推理加速领域的最新进展和性能优化",
            "上下文漂移检测的KL散度量化方法和主动干预机制",
            "生物免疫式多样性冗余在系统架构中的抗体多样性设计",
            "信息保真核心IFC架构将记忆任务安全统一设计",
            "知识图谱的实体消歧和关系提取和跨任务实体链接",
            "思维链提示和树状推理和自我一致性推理增强",
            "模型压缩的量化剪枝蒸馏和神经架构搜索",
            "检索增强生成的文档检索和上下文注入和生成验证",
            "端午龙舟竞渡百舸争流粽子艾草",
            "五一假期旅游景点推荐和交通出行攻略",
            "足球世界杯决赛精彩比赛梅西最后时刻绝杀",
            "今日股市行情分析和投资策略推荐",
            "美食烹饪红烧肉做法和清蒸鱼技巧分享",
        ])
    return _embedder


# ============ 测试入口 ============
if __name__ == "__main__":
    emb = get_embedder()

    # 测试: 相关话题
    test_pairs = [
        ("AI大模型的推理能力提升路径", "Transformer自注意力机制和Mamba线性注意力替代方案"),
        ("医疗器械市场准入流程", "今天天气真好去公园散步"),
        ("联邦学习的隐私保护机制", "多家银行在不共享数据的情况下联合训练风控模型"),
        ("足球世界杯决赛", "梅西最后时刻绝杀阿根廷夺冠"),
        ("长期记忆系统的无损压缩设计", "DAG增量摘要树和SQLite持久化和SHA-256位级校验"),
    ]

    print("语义相似度测试 (LocalSemanticEmbedding):")
    for g, c in test_pairs:
        sim = emb.similarity(g, c)
        drift = emb.drift_score(g, c)
        tag = "相关" if sim >= 0.3 else "漂移"
        print(f"  {tag} sim={sim:.4f} drift={drift:.4f}")
        print(f"    目标: {g[:40]}...")
        print(f"    上下文: {c[:40]}...")
        print()
