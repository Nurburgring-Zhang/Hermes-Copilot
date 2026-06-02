#!/usr/bin/env python3
"""
Hermes Multi-Agent Plan 自动切换系统 v1
=========================================
根据任务类型自动选择最合适的 Coding Plan

功能:
- 任务特征分析(复杂度/领域/约束)
- 基于规则的 Plan 匹配
- 模型动态切换
- 执行策略调整
- 决策日志记录

Usage:
  python3 plan_switcher.py "帮我设计一个FastAPI微服务"
  python3 plan_switcher.py --list-plans
  python3 plan_switcher.py --detect "写个Python脚本处理CSV"
"""
import os, sys, json, re, yaml
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import List, Dict, Optional, Tuple
from datetime import datetime

# ============================================================================
# Plan 配置
# ============================================================================
PLANS = {
    "microservice-dev": {
        "name": "微服务开发模式",
        "description": "FastAPI/Spring Boot微服务,包含完整测试和容器化",
        "model": {"primary": "claude-4-opus", "fallback": ["deepseek-coder-33b", "gpt-4o"]},
        "tools": ["shell_exec", "git", "docker", "mypy", "pytest", "uvicorn"],
        "context": ["constraints/microservice.md", "contexts/rest-api-design.md"],
        "policy": {"max_iterations": 15, "require_validation": True, "auto_test": True},
        "match": {
            "keywords": ["微服务", "API", "REST", "Spring", "FastAPI", "数据库", "认证", "JWT", "CRUD", "服务", "架构", "容器化", "Docker", "K8s", "部署"],
            "file_patterns": ["*.java", "pom.xml", "requirements.txt", "Dockerfile", "docker-compose.yml", "*.yaml"],
            "complexity": "high",
        }
    },
    "script-dev": {
        "name": "脚本开发模式",
        "description": "Python/Bash脚本,数据处理,快速原型",
        "model": {"primary": "deepseek-chat", "fallback": ["gpt-3.5-turbo"]},
        "tools": ["shell_exec", "python_repl", "file_edit"],
        "context": ["constraints/script.md"],
        "policy": {"max_iterations": 5, "require_validation": False, "auto_test": False},
        "match": {
            "keywords": ["脚本", "处理数据", "转换", "爬虫", "自动化", "CSV", "JSON", "清洗", "ETL", "定时任务", "批处理"],
            "file_patterns": ["*.py", "*.sh", "*.js", "*.ts"],
            "complexity": "low",
        }
    },
    "frontend-dev": {
        "name": "前端开发模式",
        "description": "React/Vue组件,UI/UX,响应式",
        "model": {"primary": "claude-4-sonnet", "fallback": ["gpt-4o", "deepseek-chat"]},
        "tools": ["shell_exec", "git", "npm", "vite", "eslint", "prettier"],
        "context": ["constraints/frontend.md", "contexts/react-patterns.md"],
        "policy": {"max_iterations": 10, "require_validation": True, "auto_test": False},
        "match": {
            "keywords": ["React", "Vue", "组件", "样式", "UI", "前端", "页面", "CSS", "HTML", "JS", "TypeScript", "Tailwind", "页面", "交互"],
            "file_patterns": ["*.jsx", "*.tsx", "*.vue", "*.css", "*.scss", "package.json", "vite.config.*"],
            "complexity": "medium",
        }
    },
    "ml-ai-dev": {
        "name": "AI/机器学习开发模式",
        "description": "模型训练,ML流水线,数据处理",
        "model": {"primary": "claude-4-opus", "fallback": ["deepseek-coder-33b"]},
        "tools": ["shell_exec", "git", "python_repl", "jupyter", "pytest", "mlflow"],
        "context": ["constraints/ml.md", "contexts/ml-pipeline.md"],
        "policy": {"max_iterations": 20, "require_validation": True, "auto_test": True},
        "match": {
            "keywords": ["机器学习", "深度学习", "训练", "模型", "AI", "LLM", "GPT", "神经网络", "TensorFlow", "PyTorch", "HuggingFace", "微调", "RAG", "向量数据库", "Embedding", "Agent", "LangChain"],
            "file_patterns": ["*.py", "*.ipynb", "requirements.txt", "pyproject.toml", "train.py", "model.py"],
            "complexity": "high",
        }
    },
    "devops-sre": {
        "name": "DevOps/SRE模式",
        "description": "CI/CD,监控,容器编排,基础设施",
        "model": {"primary": "claude-4-opus", "fallback": ["deepseek-coder-33b"]},
        "tools": ["shell_exec", "git", "docker", "kubectl", "helm", "ansible", "terraform"],
        "context": ["constraints/devops.md"],
        "policy": {"max_iterations": 10, "require_validation": True, "auto_test": False},
        "match": {
            "keywords": ["部署", "CI/CD", "Docker", "K8s", "Kubernetes", "监控", "Prometheus", "Grafana", "Helm", "Ansible", "Terraform", "云", "AWS", "GCP", "Azure", "VM", "服务器", "运维", "容器的", "Pod", "Ingress"],
            "file_patterns": ["Dockerfile", "docker-compose*.yml", "*.yaml", "Jenkinsfile", ".gitlab-ci.yml", "Makefile", "helm/**"],
            "complexity": "high",
        }
    },
    "code-review": {
        "name": "代码审查模式",
        "description": "代码审查,优化建议,安全审计",
        "model": {"primary": "claude-4-sonnet", "fallback": ["deepseek-coder-33b", "gpt-4o"]},
        "tools": ["git", "shell_exec", "code_review", "security_scan"],
        "context": ["constraints/review.md"],
        "policy": {"max_iterations": 5, "require_validation": False, "auto_test": False},
        "match": {
            "keywords": ["审查", "review", "优化", "重构", "安全", "漏洞", "bug", "错误", "性能", "审计", "检查"],
            "file_patterns": ["*.py", "*.js", "*.ts", "*.java", "*.go", "*.rs", "*.cpp"],
            "complexity": "medium",
        }
    },
    "general": {
        "name": "通用对话模式",
        "description": "问答,写作,分析等通用任务",
        "model": {"primary": "deepseek-chat", "fallback": ["gpt-3.5-turbo"]},
        "tools": ["shell_exec", "file_edit", "web_search"],
        "context": [],
        "policy": {"max_iterations": 3, "require_validation": False, "auto_test": False},
        "match": {
            "keywords": [],
            "file_patterns": [],
            "complexity": "low",
        }
    },
}

# ============================================================================
# 任务分析器
# ============================================================================
class TaskAnalyzer:
    """分析任务特征"""
    
    COMPLEXITY_KEYWORDS_HIGH = [
        "架构", "重构", "设计", "系统", "分布式", "事务", "并发", "微服务",
        "集群", "高可用", "容灾", "安全", "加密", "认证", "机器学习", "深度学习",
        "大模型", "神经网络", "训练", "AI", "LLM", "DevOps", "K8s", "Docker",
    ]
    
    COMPLEXITY_KEYWORDS_LOW = [
        "修改", "添加", "删除", "查看", "查询", "查看", "显示", "统计",
        "脚本", "处理", "转换", "导出", "导入", "清理", "简单的",
    ]
    
    DOMAIN_PATTERNS = {
        "backend": ["API", "数据库", "服务", "Spring", "Django", "FastAPI", "Flask", "Express", "后端"],
        "frontend": ["React", "Vue", "组件", "样式", "UI", "CSS", "HTML", "JS", "前端", "页面"],
        "devops": ["部署", "CI/CD", "Docker", "K8s", "监控", "云", "AWS", "服务器", "运维", "容器"],
        "ml": ["机器学习", "深度学习", "AI", "LLM", "模型", "训练", "PyTorch", "TensorFlow", "HuggingFace", "RAG", "Embedding"],
        "security": ["安全", "漏洞", "渗透", "XSS", "SQL注入", "CSRF", "加密", "认证", "授权"],
        "data": ["数据", "分析", "统计", "清洗", "ETL", "CSV", "Pandas", "数据库", "查询"],
        "game": ["游戏", "Unity", "Unreal", "3D", "渲染", "物理", "引擎"],
    }
    
    def analyze(self, task: str, files: List[str] = None) -> Dict:
        """分析任务,返回特征向量"""
        task_lower = task.lower()
        files = files or []
        files_str = " ".join(files).lower()
        
        # 复杂度评估
        complexity = self._assess_complexity(task)
        
        # 领域识别
        domain = self._identify_domain(task)
        
        # 关键词匹配
        matched_kw = self._extract_keywords(task)
        
        # 文件类型推断
        inferred_domain = self._infer_domain_from_files(files)
        
        # 估计步骤数
        steps = self._estimate_steps(task, complexity)
        
        return {
            "task": task,
            "files": files,
            "complexity": complexity,
            "domain": domain,
            "secondary_domain": inferred_domain if inferred_domain != domain else None,
            "matched_keywords": matched_kw,
            "estimated_steps": steps,
            "task_length": len(task),
            "has_code_pattern": bool(re.search(r'[a-zA-Z_]+\s*[=\(]', task)),
        }
    
    def _assess_complexity(self, task: str) -> str:
        high = sum(1 for k in self.COMPLEXITY_KEYWORDS_HIGH if k in task)
        low = sum(1 for k in self.COMPLEXITY_KEYWORDS_LOW if k in task)
        if high >= 3 or (high >= 2 and low < high): return "high"
        if low > high or low >= 2: return "low"
        return "medium"
    
    def _identify_domain(self, task: str) -> str:
        scores = {}
        for domain, keywords in self.DOMAIN_PATTERNS.items():
            scores[domain] = sum(1 for k in keywords if k in task)
        if not scores or max(scores.values()) == 0:
            return "general"
        return max(scores, key=scores.get)
    
    def _infer_domain_from_files(self, files: List[str]) -> str:
        if not files:
            return "general"
        ext_map = {
            "backend": [".java", ".go", ".rs", ".kt", ".scala"],
            "frontend": [".jsx", ".tsx", ".vue", ".css", ".scss", ".sass"],
            "ml": [".ipynb"],
            "data": [".py", ".r"],
            "script": [".sh", ".bash"],
        }
        for f in files:
            for domain, exts in ext_map.items():
                if any(f.endswith(e) for e in exts):
                    return domain
        return "general"
    
    def _extract_keywords(self, task: str) -> List[str]:
        return [k for k in set(self.DOMAIN_PATTERNS.get("backend", []) + 
                               self.DOMAIN_PATTERNS.get("frontend", []) + 
                               self.DOMAIN_PATTERNS.get("ml", []) + 
                               self.DOMAIN_PATTERNS.get("devops", []))
                 if k in task]
    
    def _estimate_steps(self, task: str, complexity: str) -> int:
        base = {"low": 2, "medium": 5, "high": 10}
        steps = base.get(complexity, 3)
        # 额外指示词
        if any(k in task for k in ["完整", "全面", "详细"]): steps += 3
        if any(k in task for k in ["简单", "基础", "快速"]): steps = min(steps, 3)
        return min(steps, 20)

# ============================================================================
# Plan 路由器
# ============================================================================
class PlanRouter:
    """根据任务特征路由到最佳Plan"""
    
    def __init__(self):
        self.plans = PLANS
        self.analyzer = TaskAnalyzer()
        self.decision_log = []
    
    def route(self, task: str, files: List[str] = None) -> Dict:
        """执行路由决策,返回选中的Plan和原因"""
        features = self.analyzer.analyze(task, files)
        
        # 规则匹配
        best_plan_id, score, match_reason = self._rule_match(features)
        
        # 如果规则匹配分数不高,尝试领域优先匹配
        if score < 0.5 and features.get("domain") != "general":
            plan_id, alt_score, alt_reason = self._domain_priority_match(features)
            if alt_score > score:
                best_plan_id, score, match_reason = plan_id, alt_score, alt_reason
        
        plan = self.plans.get(best_plan_id, self.plans["general"])
        
        decision = {
            "plan_id": best_plan_id,
            "plan_name": plan["name"],
            "model": plan["model"]["primary"],
            "fallback_models": plan["model"]["fallback"],
            "tools": plan["tools"],
            "policy": plan["policy"],
            "confidence": round(score, 2),
            "reason": match_reason,
            "features": {
                "complexity": features["complexity"],
                "domain": features["domain"],
                "estimated_steps": features["estimated_steps"],
                "matched_keywords": features["matched_keywords"],
            },
            "timestamp": datetime.now().isoformat(),
        }
        
        self.decision_log.append(decision)
        return decision
    
    def _rule_match(self, features: Dict) -> Tuple[str, float, str]:
        """基于规则的匹配"""
        best_id, best_score, best_reason = "general", 0.0, ""
        task = features["task"]
        files = features.get("files", [])
        
        for plan_id, plan in self.plans.items():
            if plan_id == "general":
                continue
            
            rules = plan.get("match", {})
            score = 0.0
            matched_reasons = []
            
            # 关键词匹配 (权重 0.4)
            kw_weight = 0.4
            if rules.get("keywords"):
                matched_kw = [k for k in rules["keywords"] if k in task]
                kw_score = len(matched_kw) / len(rules["keywords"]) * kw_weight
                score += kw_score
                if matched_kw:
                    matched_reasons.append(f"关键词:{','.join(matched_kw[:3])}")
            
            # 文件模式匹配 (权重 0.3)
            if rules.get("file_patterns") and files:
                for f in files:
                    for pattern in rules["file_patterns"]:
                        pattern = pattern.replace(".", r"\.").replace("*", ".*")
                        if re.search(pattern, f):
                            score += 0.3
                            matched_reasons.append(f"文件:{f}")
                            break
            
            # 复杂度匹配 (权重 0.3)
            if rules.get("complexity"):
                if features["complexity"] == rules["complexity"]:
                    score += 0.3
                    matched_reasons.append(f"复杂度:{features['complexity']}")
            
            if score > best_score:
                best_score = score
                best_id = plan_id
                best_reason = "; ".join(matched_reasons) if matched_reasons else f"综合评分{score:.2f}"
        
        return best_id, min(best_score / 0.7, 1.0), best_reason
    
    def _domain_priority_match(self, features: Dict) -> Tuple[str, float, str]:
        """领域优先匹配"""
        domain_plan_map = {
            "backend": "microservice-dev",
            "frontend": "frontend-dev",
            "ml": "ml-ai-dev",
            "devops": "devops-sre",
            "data": "script-dev",
        }
        domain = features.get("domain", "general")
        plan_id = domain_plan_map.get(domain, "general")
        plan = self.plans.get(plan_id, self.plans["general"])
        
        return plan_id, 0.6, f"领域优先匹配:{domain}"
    
    def list_plans(self) -> List[Dict]:
        """列出所有可用的Plan"""
        return [
            {
                "id": pid,
                "name": p["name"],
                "description": p["description"],
                "model": p["model"]["primary"],
                "tools": p["tools"],
                "match_keywords": p["match"].get("keywords", [])[:5],
            }
            for pid, p in self.plans.items()
        ]
    
    def get_decision_log(self) -> List[Dict]:
        return self.decision_log

# ============================================================================
# CLI 界面
# ============================================================================
def print_plan(decision: Dict):
    """格式化输出路由决策"""
    print(f"""
╔══════════════════════════════════════════════════════════════╗
║  Plan 路由决策                                                ║
╠══════════════════════════════════════════════════════════════╣
║  Plan:     {decision['plan_name']:<47} ║
║  模型:     {decision['model']:<47} ║
║  置信度:   {decision['confidence']:.0%} ({decision['reason'][:40]}){" "*max(0,47-len(decision['reason'])-6)}║
╠══════════════════════════════════════════════════════════════╣
║  复杂度:   {decision['features']['complexity']:<47} ║
║  领域:     {decision['features']['domain']:<47} ║
║  预估步骤: {decision['features']['estimated_steps']:<47} ║
╠══════════════════════════════════════════════════════════════╣
║  工具:     {', '.join(decision['tools'][:4]):<47} ║
║  Fallback: {', '.join(decision['fallback_models'][:2]):<47} ║
╚══════════════════════════════════════════════════════════════╝
""")

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Hermes Plan 自动切换系统")
    parser.add_argument("task", nargs="?", help="要分析的任务描述")
    parser.add_argument("--list-plans", action="store_true", help="列出所有Plan")
    parser.add_argument("--files", nargs="*", help="相关文件列表")
    parser.add_argument("--history", action="store_true", help="显示决策历史")
    args = parser.parse_args()
    
    router = PlanRouter()
    
    if args.list_plans:
        print("\n可用 Plans:")
        for plan in router.list_plans():
            print(f"\n  [{plan['id']}] {plan['name']}")
            print(f"    模型: {plan['model']}")
            print(f"    描述: {plan['description']}")
            print(f"    关键词: {', '.join(plan['match_keywords'])}")
        return
    
    if args.history:
        log = router.get_decision_log()
        if not log:
            print("暂无决策记录")
        else:
            for d in log[-5:]:
                print(f"  [{d['timestamp'][:16]}] {d['plan_name']} | {d['reason'][:40]}")
        return
    
    if not args.task:
        parser.print_help()
        return
    
    decision = router.route(args.task, args.files)
    print_plan(decision)

if __name__ == "__main__":
    main()
