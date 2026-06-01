#!/usr/bin/env python3
"""
Hermes 模型智能路由引擎 (Model Router)
==========================================
源自: MetaGPT按角色分配模型 + Google自动调优
功能: 根据任务复杂度自动选择模型梯队
梯队:
  E0 (value):    deepseek-v4-flash  — 简单/检索/低复杂度任务
  E1 (balanced): deepseek-chat      — 普通任务(当前默认)
  E2 (performance): deepseek-v4-pro  — 高难度/长链推理任务

接入: run_agent.py的LLM调用前自动选择

用法:
  from agent.model_router import ModelRouter
  router = ModelRouter()
  model = router.select("写个简单的hello world")
  # => "deepseek-v4-flash"
  model = router.select("设计一个分布式Raft协议的共识算法实现")
  # => "deepseek-v4-pro"
"""

import json, os, re, math
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from collections import defaultdict

HERMES_HOME = Path(os.path.expanduser("~/.hermes"))

class ModelRouter:
    """
    模型智能路由
    
    判定维度:
    1. 任务复杂度 — 关键词密度/逻辑复杂度/技术深度
    2. 任务长度 — prompt字符数/期望输出长度
    3. 引用工具数 — 预期需要调用的工具数量
    4. 风险等级 — 高风险操作需要更高质量模型
    
    梯队定义:
    E0 (value):     deepseek-v4-flash  → 简单检索/单步操作/状态查询
    E1 (balanced):  deepseek-chat      → 常规开发/修复/普通任务
    E2 (perf):      deepseek-v4-pro    → 复杂推理/长链/高精度要求
    """
    
    def __init__(self, config_path: Optional[Path] = None):
        self.config = self._load_config(config_path)
        self.stats = defaultdict(lambda: {"calls": 0, "avg_complexity": 0.0})
        self.total_calls = 0
    
    def _load_config(self, config_path: Optional[Path]) -> dict:
        """加载路由配置"""
        default = {
            "tiers": {
                "value": {
                    "model": "deepseek-v4-flash",
                    "max_complexity": 0.3,      # 复杂度<=0.3用flash
                    "description": "简单任务：检索/查询/单步操作"
                },
                "balanced": {
                    "model": "deepseek-chat",
                    "max_complexity": 0.7,      # 0.3<复杂度<=0.7用chat
                    "description": "常规任务：开发/修复/普通分析"
                },
                "performance": {
                    "model": "deepseek-v4-pro",
                    "max_complexity": 1.0,      # 复杂度>0.7用pro
                    "description": "高难任务：复杂推理/长链/高精"
                }
            },
            "complexity_weights": {
                "keyword_density": 0.35,
                "logic_depth": 0.30,
                "code_ratio": 0.20,
                "length_factor": 0.15,
            },
            "force_model": None,  # 强制使用特定模型（覆盖路由）
        }
        
        if config_path and config_path.exists():
            try:
                with open(config_path) as f:
                    custom = json.load(f)
                for k, v in custom.items():
                    if k in default and isinstance(v, dict):
                        default[k].update(v)
                    else:
                        default[k] = v
            except:
                pass
        
        return default
    
    def _calc_complexity(self, prompt: str) -> float:
        """
        计算任务复杂度 (0.0 - 1.0)
        
        使用多维度加权:
        - 关键词密度: 高复杂度关键词占比
        - 逻辑深度: 条件/循环/递归等结构密度
        - 代码比例: 代码块占比
        - 长度因子: prompt长度标准化
        """
        if not prompt or len(prompt.strip()) == 0:
            return 0.0
        
        # 高复杂度关键词
        high_complexity_kw = [
            "分布式", "共识", "raft", "paxos", "并发", "同步", "锁",
            "transaction", "consistency", "replication", "sharding",
            "加密", "解密", "签名", "认证", "协议", "算法",
            "机器学习", "深度学习", "神经网络", "transformer",
            "优化", "调度", "编排", "orchestrator", "pipeline",
            "编译", "虚拟机", "解释器", "parser", "ast",
            "fault tolerance", "高可用", "灾备", "recovery",
            "scalable", "百万并发", "千万级", "大规模",
            "kubernetes", "k8s", "docker", "容器编排",
            "微服务", "service mesh", "istio",
            "design pattern", "架构设计", "系统设计",
            "security", "漏洞", "渗透", "安全审计",
        ]
        
        prompt_lower = prompt.lower()
        prompt_words = len(prompt_lower.split())
        
        # 1. 关键词密度
        kw_matches = sum(1 for kw in high_complexity_kw if kw.lower() in prompt_lower)
        kw_density = min(kw_matches / max(prompt_words, 10), 1.0)
        
        # 2. 逻辑深度
        logic_markers = len(re.findall(r'\b(if|else|for|while|递归|循环|依赖|条件|分支|并行)\b', prompt_lower))
        logic_depth = min(logic_markers / 10.0, 1.0)
        
        # 3. 代码占比
        code_blocks = len(re.findall(r'```', prompt))
        code_ratio = min(code_blocks / 6.0, 1.0)
        
        # 4. 长度因子
        length_factor = min(prompt_words / 500.0, 1.0)
        
        # 加权综合
        weights = self.config["complexity_weights"]
        complexity = (
            kw_density * weights["keyword_density"] +
            logic_depth * weights["logic_depth"] +
            code_ratio * weights["code_ratio"] +
            length_factor * weights["length_factor"]
        )
        
        return round(min(complexity, 1.0), 3)
    
    def select(self, prompt: str, force_model: Optional[str] = None, 
               task_type: Optional[str] = None) -> Tuple[str, str, Dict[str, Any]]:
        """
        选择最适合的模型
        
        参数:
          prompt: 用户输入/任务描述
          force_model: 强制使用指定模型(覆盖自动路由)
          task_type: 任务类型(可辅助判断)
          
        返回:
          (model_name, tier_name, detail)
        """
        self.total_calls += 1
        
        # 强制模式
        model_override = force_model or self.config.get("force_model")
        if model_override:
            self.stats["forced"]["calls"] += 1
            return model_override, "forced", {"reason": "manual override", "complexity": 0}
        
        # 任务类型辅助
        if task_type:
            type_tier_map = {
                "query": "value",
                "status": "value",
                "stats": "value",
                "search": "value",
                "fix": "balanced",
                "develop": "performance",
                "review": "performance",
                "research": "balanced",
                "push": "balanced",
                "evolve": "performance",
            }
            if task_type in type_tier_map:
                tier_name = type_tier_map[task_type]
                tier = self.config["tiers"][tier_name]
                model = tier["model"]
                detail = {"reason": f"task_type={task_type}", "complexity": 0, "tier": tier_name}
                self._record_stats(tier_name, 0)
                return model, tier_name, detail
        
        # 复杂度计算
        complexity = self._calc_complexity(prompt)
        
        # 选择梯队
        for tier_name in ["value", "balanced", "performance"]:
            tier = self.config["tiers"][tier_name]
            if complexity <= tier["max_complexity"]:
                self._record_stats(tier_name, complexity)
                return tier["model"], tier_name, {
                    "reason": f"complexity={complexity} <= {tier['max_complexity']}",
                    "complexity": complexity,
                    "tier": tier_name,
                }
        
        # Fallback
        fallback = self.config["tiers"]["performance"]["model"]
        self._record_stats("performance", complexity)
        return fallback, "performance", {"reason": "fallback", "complexity": complexity}
    
    def _record_stats(self, tier: str, complexity: float):
        """记录路由统计"""
        s = self.stats[tier]
        s["calls"] += 1
        total = s["calls"]
        s["avg_complexity"] = (s["avg_complexity"] * (total - 1) + complexity) / total
    
    def get_stats(self) -> Dict[str, Any]:
        """获取路由统计"""
        return {
            "router": "ModelRouter",
            "total_calls": self.total_calls,
            "tiers": {k: dict(v) for k, v in self.stats.items()},
            "config": {k: self.config[k] for k in self.config if k != "tiers"},
        }

# ===== 独立运行入口 =====
if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "test"
    
    router = ModelRouter()
    
    if cmd == "test":
        test_prompts = [
            ("hello, what time is it?", "query"),
            ("检查系统状态，显示推送记录", "status"),
            ("写一个冒泡排序算法", "develop"),
            ("修复推送系统的候选池SQL查询错误", "fix"),
            ("设计一个支持百万并发的分布式消息队列架构", "develop"),
            ("分析这段代码的安全性漏洞并给出修复方案", "review"),
        ]
        print("\n=== 模型路由测试 ===")
        for prompt, tt in test_prompts:
            model, tier, detail = router.select(prompt, task_type=tt)
            complexity = detail.get("complexity", 0)
            print(f"  complexity={complexity:.2f} | {tier:12s} | {model:20s} | {prompt[:40]}")
        
        print(f"\nStats: {json.dumps(router.get_stats(), indent=2, ensure_ascii=False)}")
    
    elif cmd == "stats":
        print(json.dumps(router.get_stats(), indent=2, ensure_ascii=False))
