#!/usr/bin/env python3
"""
Hermes 反思层引擎 (Reflector Engine)
=====================================
源自: Reflexion (Shinn+2023) + OpenClaw 三轮反思 + 华为IPD TR评审
功能: 在监控层发出 REFLECT/RECOVER 信号时进行深度反思
      三轮递进: 执行复盘 → 策略复盘 → 元认知复盘
接入: monitor.py / hermes_retrospect.py / hermes_self_evolve_cluster.py

用法:
  from agent.reflector import ReflectorEngine
  r = ReflectorEngine()
  report = r.reflect({"task": "xxx", "errors": [...], "turns": 10, ...})
"""

import json, os, time, hashlib
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from enum import Enum

HERMES_HOME = Path(os.path.expanduser("~/.hermes"))

class ReflectionLevel(str, Enum):
    EXECUTION = "execution"      # 第一轮：执行层反思 — 这一步做错了吗？
    STRATEGY = "strategy"        # 第二轮：策略层反思 — 策略对吗？
    META = "meta"               # 第三轮：元认知反思 — 我为什么选这个策略？

class ReflectorEngine:
    """
    反思层核心引擎
    
    三轮递进反思:
    Round 1 (Execution): 检查执行过程是否准确
      - 工具调用是否正确？参数传递是否无误？
      - 错误原因分类：语法错误/逻辑错误/环境问题/资源不足
      
    Round 2 (Strategy): 检查策略是否合理
      - 整体方向正确吗？有没有更优路径？
      - 任务分解合理吗？阶段划分对吗？
      - 是否过早优化？是否遗漏关键步骤？
      
    Round 3 (Meta): 元认知反思
      - 为什么一开始选择了这个策略？
      - 这次犯的错误是否以前也犯过？
      - 我应该学到什么通用经验？
    """
    
    def __init__(self):
        self.reflection_history = []
        self.pattern_db = self._load_pattern_db()
    
    def _load_pattern_db(self) -> Dict[str, Any]:
        """加载已知错误模式库"""
        pattern_path = HERMES_HOME / "reports" / "reflection_patterns.json"
        if pattern_path.exists():
            try:
                with open(pattern_path) as f:
                    return json.load(f)
            except:
                pass
        return {"patterns": [], "lessons": []}
    
    def _save_pattern_db(self):
        """保存错误模式库"""
        pattern_path = HERMES_HOME / "reports" / "reflection_patterns.json"
        pattern_path.parent.mkdir(parents=True, exist_ok=True)
        with open(pattern_path, "w") as f:
            json.dump(self.pattern_db, f, indent=2, ensure_ascii=False)
    
    def reflect(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        执行三轮反思
        
        context 应包含:
          task: str — 任务描述
          errors: List[str] — 错误列表
          turns: int — 已执行步数
          actions_taken: List[str] — 已执行的动作(可选)
          task_type: str — 任务类型(可选)
          session_id: str — 会话ID(可选)
        """
        task = context.get("task", "未知任务")
        errors = context.get("errors", [])
        turns = context.get("turns", 0)
        actions = context.get("actions_taken", [])
        task_type = context.get("task_type", "general")
        session_id = context.get("session_id", f"ref_{int(time.time())}")
        
        report_id = hashlib.md5(f"{session_id}_{time.time()}".encode()).hexdigest()[:12]
        
        # ===== R1: 执行层反思 =====
        r1 = self._reflect_execution(task, errors, actions)
        
        # ===== R2: 策略层反思 =====
        r2 = self._reflect_strategy(task, errors, turns, task_type)
        
        # ===== R3: 元认知反思 =====
        r3 = self._reflect_meta(task, errors, task_type)
        
        # ===== 综合 =====
        summary = self._synthesize(r1, r2, r3)
        
        report = {
            "report_id": report_id,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S+08:00"),
            "task": task,
            "task_type": task_type,
            "session_id": session_id,
            "turns": turns,
            "error_count": len(errors),
            "rounds": {
                "execution_reflection": r1,
                "strategy_reflection": r2,
                "meta_reflection": r3,
            },
            "summary": summary,
            "improvement_suggestions": summary["improvements"],
        }
        
        # 写入历史
        self.reflection_history.append(report)
        if len(self.reflection_history) > 50:
            self.reflection_history = self.reflection_history[-50:]
        
        # 如果发现新模式，写入模式库
        if summary.get("new_pattern"):
            self.pattern_db["patterns"].append({
                "pattern": summary["new_pattern"],
                "task_type": task_type,
                "ts": report["timestamp"],
                "ref_count": 1,
            })
            self._save_pattern_db()
        
        return report
    
    def _reflect_execution(self, task: str, errors: List[str], actions: List[str]) -> Dict[str, Any]:
        """R1: 执行层反思"""
        error_categories = {"syntax": 0, "logic": 0, "environment": 0, "resource": 0, "unknown": 0}
        for err in errors:
            err_lower = err.lower()
            if any(kw in err_lower for kw in ["syntax", "parse", "invalid syntax", "unexpected"]):
                error_categories["syntax"] += 1
            elif any(kw in err_lower for kw in ["not found", "no such", "missing", "does not exist"]):
                error_categories["environment"] += 1
            elif any(kw in err_lower for kw in ["timeout", "memory", "disk", "quota", "rate limit"]):
                error_categories["resource"] += 1
            elif any(kw in err_lower for kw in ["logic", "assert", "expected", "unexpected"]):
                error_categories["logic"] += 1
            else:
                error_categories["unknown"] += 1
        
        top_category = max(error_categories, key=error_categories.get)
        
        return {
            "level": "execution",
            "error_categories": error_categories,
            "top_error_type": top_category,
            "total_errors": len(errors),
            "assessment": f"执行层发现{len(errors)}个错误，主要类型为{top_category}",
        }
    
    def _reflect_strategy(self, task: str, errors: List[str], turns: int, task_type: str) -> Dict[str, Any]:
        """R2: 策略层反思"""
        # 策略评估: 根据错误类型和步数评估策略是否合理
        strategy_issues = []
        
        if len(errors) > 3 and turns < 10:
            strategy_issues.append("策略可能在初期就被误导，建议重新评估任务分解")
        if len(errors) > 5:
            strategy_issues.append("频繁出错，整体策略可能需要调整方向")
        if turns > 20 and len(errors) > 8:
            strategy_issues.append("步数多且错误多，考虑是否可以换一种完全不同的方案")
        
        # 针对任务类型的策略建议
        type_suggestions = {
            "fix": "修复任务建议先精确定位根因再修改，避免盲目试错",
            "develop": "开发任务建议先写测试再实现，确保每步可验证",
            "research": "研究任务建议先确定检索关键词范围再深入",
            "push": "推送任务建议先验证候选数据质量再批量推送",
            "general": "建议在投入更多资源前先做小规模验证",
        }
        
        return {
            "level": "strategy",
            "strategy_issues": strategy_issues,
            "turns_taken": turns,
            "strategy_suggestion": type_suggestions.get(task_type, type_suggestions["general"]),
        }
    
    def _reflect_meta(self, task: str, errors: List[str], task_type: str) -> Dict[str, Any]:
        """R3: 元认知反思"""
        # 检查模式库中是否有类似错误
        matched_patterns = []
        for p in self.pattern_db.get("patterns", []):
            if p["task_type"] == task_type:
                match_score = sum(1 for err in errors if any(kw in err.lower() for kw in p["pattern"].split()))
                if match_score > 0:
                    matched_patterns.append({"pattern": p["pattern"], "match": match_score})
        
        repeated_pattern = bool(matched_patterns)
        
        # 检查记忆库中是否有相关教训
        lesson_file = HERMES_HOME / "reports" / "correction_library.json"
        related_lessons = []
        if lesson_file.exists():
            try:
                with open(lesson_file) as f:
                    lessons = json.load(f)
                if isinstance(lessons, list):
                    for l in lessons:
                        l_text = l.get("lesson", "") if isinstance(l, dict) else str(l)
                        if task_type in l_text.lower():
                            related_lessons.append(l_text[:100])
            except:
                pass
        
        new_pattern = None
        if len(errors) >= 2 and not repeated_pattern:
            # 如果新错误模式重复出现且不在库中，建议入库
            common_words = set()
            for err in errors:
                words = err.lower().split()[:5]
                common_words.update(words)
            if common_words:
                new_pattern = " ".join(list(common_words)[:8])
        
        meta_lesson = ""
        if repeated_pattern:
            meta_lesson = f"⚠️ 检测到重复模式：之前犯过的类似错误再次出现，建议修改底层Skill"
        elif len(errors) > 5:
            meta_lesson = f"执行{len(errors)}次错误后需要修正执行策略，避免继续浪费资源"
        else:
            meta_lesson = "本次为偶发错误，不需要改变底层策略"
        
        return {
            "level": "meta",
            "repeated_patterns": matched_patterns[:3],
            "repeated_error": repeated_pattern,
            "related_lessons": related_lessons[:2],
            "meta_lesson": meta_lesson,
            "new_pattern_candidate": new_pattern,
        }
    
    def _synthesize(self, r1: Dict, r2: Dict, r3: Dict) -> Dict[str, Any]:
        """综合三轮反思结果"""
        improvements = []
        new_pattern = r3.get("new_pattern_candidate")
        
        # R1改进建议
        if r1["total_errors"] > 0:
            improvements.append(f"修复{r1['top_error_type']}类型错误（共{r1['total_errors']}个）")
        
        # R2改进建议
        for issue in r2["strategy_issues"]:
            improvements.append(issue)
        improvements.append(r2["strategy_suggestion"])
        
        # R3改进建议
        improvements.append(r3["meta_lesson"])
        
        return {
            "improvements": improvements[:5],
            "new_pattern": new_pattern,
            "repeated_error": r3["repeated_error"],
        }
    
    def get_stats(self) -> Dict[str, Any]:
        """获取反思引擎统计"""
        return {
            "engine": "ReflectorEngine",
            "total_reflections": len(self.reflection_history),
            "pattern_db_size": len(self.pattern_db.get("patterns", [])),
            "recent_reflection": self.reflection_history[-1]["report_id"] if self.reflection_history else None,
        }

# ===== 独立运行入口 =====
if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "test"
    
    engine = ReflectorEngine()
    
    if cmd == "test":
        test_contexts = [
            {"task": "修复推送系统", "errors": ["FileNotFoundError: no such config", "Connection refused"], 
             "turns": 5, "task_type": "fix", "actions_taken": ["read config", "try connect"]},
            {"task": "开发新采集器", "errors": ["SyntaxError: invalid syntax", "NameError: x not defined", "TypeError: int expected"],
             "turns": 8, "task_type": "develop", "actions_taken": ["write code", "test", "fix"]},
            {"task": "检查数据库状态", "errors": [], "turns": 3, "task_type": "general", "actions_taken": ["connect", "query"]},
        ]
        for i, ctx in enumerate(test_contexts):
            report = engine.reflect(ctx)
            print(f"\n=== 反思案例{i+1}: {ctx['task']} ===")
            print(f"  错误数: {report['error_count']}")
            for rnd_name, rnd in report['rounds'].items():
                print(f"  {rnd_name}: {rnd.get('assessment') or rnd.get('meta_lesson','')[:60]}")
            print(f"  改进建议: {report['summary']['improvements'][:2]}")
        
        print(f"\nStats: {json.dumps(engine.get_stats(), ensure_ascii=False)}")
    
    elif cmd == "stats":
        print(json.dumps(engine.get_stats(), indent=2, ensure_ascii=False))
