#!/usr/bin/env python3
"""
Hermes 强制武器调度引擎 — 不依赖LLM主动性
================================================
核心思路: 不在prompt里"告诉"Hermes有武器,
而是在任务执行前自动调用武器,把结果直接塞进上下文.

这样Hermes不需要"主动使用武器"——武器已经被用了,
它看到的是"采集器已经跑完了,结果在这里,继续往下处理".

工作流:
  用户说"采集微博数据"
  ↓
  ① 调度引擎截获任务
  ② 自动分析需要什么武器(采集器→清洗→评分→推送)
  ③ 自动并行执行武器(unified_collector_v5)
  ④ 结果写入文件
  ⑤ 把结果摘要+下一步建议注入到回复中
  ↓
  Hermes看到的是:
    "微博数据已采集(137条),已清洗(120条),已评分.
     最高分: xxx. 建议推送到微信. 要推送吗?"
"""

import os, sys, json, subprocess, time, threading
from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import datetime
from collections import defaultdict

HERMES = Path(os.path.expanduser("~/.hermes"))


class Weapon:
    """一件武器的定义"""
    def __init__(self, name: str, path: str, wtype: str,
                 trigger_keywords: list = None,
                 run_type: str = "script",
                 timeout: int = 60):
        self.name = name
        self.path = path
        self.type = wtype  # 采集/清洗/评分/推送/记忆/质检/...
        self.trigger_keywords = trigger_keywords or []
        self.run_type = run_type  # script / skill / agent
        self.timeout = timeout
        self.success_count = 0
        self.fail_count = 0
        self.last_run = None
        self.last_output = ""
    
    def is_relevant(self, task: str) -> float:
        """判断武器是否与任务相关, 返回相关度0-1"""
        task_lower = task.lower()
        score = 0.0
        
        # 类型匹配(权重0.5)
        if self.type in task_lower:
            score += 0.5
        
        # 关键词匹配(权重0.5)
        for kw in self.trigger_keywords:
            if kw in task_lower:
                score += 0.5 / max(len(self.trigger_keywords), 1)
        
        return min(score, 1.0)
    
    def fire(self, params: str = "") -> str:
        """执行武器"""
        full_path = HERMES / self.path
        if not full_path.exists():
            self.fail_count += 1
            return f"[武器:{self.name}] 文件不存在: {full_path}"
        
        try:
            result = subprocess.run(
                [sys.executable, str(full_path)] + (params.split() if params else []),
                capture_output=True, text=True, timeout=self.timeout,
                cwd=str(HERMES)
            )
            self.last_run = datetime.now().isoformat()
            output = result.stdout.strip()[-2000:] if result.stdout else ""
            error = result.stderr.strip()[-500:] if result.stderr else ""
            
            if result.returncode == 0:
                self.success_count += 1
                self.last_output = output[:500]
                return f"[武器:{self.name}] ✅ 成功 | {output[:200]}"
            else:
                self.fail_count += 1
                return f"[武器:{self.name}] ⚠️ 退出码{result.returncode} | {error[:200]}"
        except subprocess.TimeoutExpired:
            self.fail_count += 1
            return f"[武器:{self.name}] ❌ 超时({self.timeout}s)"
        except Exception as e:
            self.fail_count += 1
            return f"[武器:{self.name}] ❌ {e}"


class Arsenal:
    """武器库 — 管理所有武器"""
    
    # 预定义武器清单 (按任务类型分类)
    WEAPONS = [
        # 采集类
        Weapon("unified_collector_v5", "scripts/unified_collector_v5.py",
               "采集", ["采集", "crawl", "scrape", "收集", "collect"],
               timeout=300),
        Weapon("wechat_bing_collector", "scripts/wechat_bing_collector.py",
               "采集", ["微信", "wechat", "公众号"], timeout=120),
        Weapon("toutiao_browser_collector_v4", "scripts/toutiao_browser_collector_v4.py",
               "采集", ["头条", "toutiao", "今日头条"], timeout=120),
        Weapon("xhs_collector_v5", "scripts/xhs_collector_v5.py",
               "采集", ["小红书", "xhs", "red"], timeout=120),
        Weapon("csdn_blog_collector", "scripts/csdn_blog_collector.py",
               "采集", ["csdn", "博客"], timeout=120),
        
        # 清洗类
        Weapon("unified_cleaning_pipeline", "scripts/unified_cleaning_pipeline.py",
               "清洗", ["清洗", "clean", "过滤", "filter"], timeout=120),
        Weapon("spam_filter", "scripts/spam_filter.py",
               "清洗", ["垃圾", "spam", "广告"], timeout=60),
        
        # 评分类
        Weapon("real_ai_scorer", "scripts/real_ai_scorer.py",
               "评分", ["评分", "score", "排序", "rank"], timeout=180),
        Weapon("ai_sixdim_scorer", "scripts/ai_sixdim_scorer.py",
               "评分", ["六维", "sixdim", "深度评分"], timeout=180),
        
        # 推送类
        Weapon("hermes_v12_push", "scripts/hermes_v12_push.py",
               "推送", ["推送", "push", "发送", "send"], timeout=120),
        Weapon("guardian", "scripts/guardian.py",
               "推送", ["守护", "guardian", "调度"], timeout=120),
        
        # 记忆类
        Weapon("hy_memory_orchestrator", "scripts/hy_memory_orchestrator.py",
               "记忆", ["记忆", "memory", "回忆", "recall"], timeout=60),
        Weapon("auto_recall", "scripts/auto_recall.py",
               "记忆", ["召回", "recall", "搜索", "search"], timeout=30),
        
        # 质检类
        Weapon("consistency_guard", "scripts/consistency_guard.py",
               "质检", ["检查", "check", "审计", "audit", "verify"], timeout=30),
        Weapon("auto_healer", "scripts/auto_healer.py",
               "质检", ["修复", "repair", "恢复", "recover"], timeout=30),
        
        # 上下文
        Weapon("context_packer", "scripts/context_packer.py",
               "上下文", ["压缩", "compress", "pack"], timeout=10),
        Weapon("surgical_context_slicer", "scripts/surgical_context_slicer.py",
               "上下文", ["切分", "slice", "精简"], timeout=10),
        
        # 引擎类
        Weapon("gear_enforcer", "scripts/gear_enforcer.py",
               "引擎", ["齿轮", "gear", "自检", "health"], timeout=30),
    ]
    
    def __init__(self):
        self.weapons = {w.name: w for w in self.WEAPONS}
    
    def get_relevant(self, task: str, min_score: float = 0.3) -> list:
        """获取与任务相关的武器, 按相关度排序"""
        scored = [(w, w.is_relevant(task)) for w in self.weapons.values()]
        scored = [(w, s) for w, s in scored if s >= min_score]
        scored.sort(key=lambda x: -x[1])
        return scored
    
    def parallel_fire(self, weapons: list, params: str = "",
                      max_parallel: int = 5) -> Dict[str, str]:
        """并行执行多个武器"""
        results = {}
        threads = []
        lock = threading.Lock()
        
        def _fire(w: Weapon):
            result = w.fire(params)
            with lock:
                results[w.name] = result
        
        # 分批执行(限并发)
        for i in range(0, len(weapons), max_parallel):
            batch = weapons[i:i+max_parallel]
            threads = []
            for w, _ in batch:
                t = threading.Thread(target=_fire, args=(w,))
                t.start()
                threads.append(t)
            for t in threads:
                t.join(timeout=60)
        
        return results
    
    def auto_execute(self, task: str) -> dict:
        """
        自动执行与任务相关的所有武器
        — 这是核心入口, 不依赖LLM主动性
        """
        relevant = self.get_relevant(task)
        
        if not relevant:
            return {"status": "no_weapons", "message": "没有找到相关武器"}
        
        # 按类型分组
        by_type = defaultdict(list)
        for w, score in relevant:
            by_type[w.type].append((w, score))
        
        results = {}
        
        # 按类型执行(同类型可并行, 不同类型可能有依赖)
        execution_order = ["采集", "清洗", "评分", "推送", "质检", "记忆", "上下文", "引擎"]
        
        for etype in execution_order:
            if etype in by_type:
                batch_results = self.parallel_fire(by_type[etype])
                results.update(batch_results)
        
        return {
            "status": "done",
            "task": task,
            "weapons_fired": len(relevant),
            "results": results,
            "summary": self._make_summary(results),
        }
    
    def _make_summary(self, results: Dict[str, str]) -> str:
        """生成人类可读的执行摘要"""
        success = [k for k, v in results.items() if "✅" in v]
        fail = [k for k, v in results.items() if "❌" in v]
        warn = [k for k, v in results.items() if "⚠️" in v]
        
        lines = []
        if success:
            lines.append(f"✅ 成功: {', '.join(success)}")
        if warn:
            lines.append(f"⚠️ 警告: {', '.join(warn)}")
        if fail:
            lines.append(f"❌ 失败: {', '.join(fail)}")
        lines.append(f"📊 共执行{len(results)}件武器, "
                      f"{len(success)}成功/{len(warn)}警告/{len(fail)}失败")
        
        return "\n".join(lines)


class BattleCommander:
    """
    作战指挥 — 分析任务→自动编组武器→同时发动
    不依赖LLM,"强制"并行使用多组武器
    """
    
    def __init__(self):
        self.arsenal = Arsenal()
        self.battle_log = []
    
    def analyze_battlefield(self, task: str) -> dict:
        """战场分析: 识别需要哪些武器编组"""
        task_lower = task.lower()
        
        # 识别所有涉及的武器类型
        needed_types = set()
        
        # 采集相关
        if any(kw in task_lower for kw in ["采集","收集","crawl","scrape","抓取","爬虫"]):
            needed_types.add("采集")
        # 清洗相关
        if any(kw in task_lower for kw in ["清洗","过滤","clean","filter","去重"]):
            needed_types.add("清洗")
        # 评分相关
        if any(kw in task_lower for kw in ["评分","打分","score","rank","排序"]):
            needed_types.add("评分")
        # 推送相关
        if any(kw in task_lower for kw in ["推送","发送","push","send","通知"]):
            needed_types.add("推送")
        # 记忆相关
        if any(kw in task_lower for kw in ["记忆","回忆","memory","recall","搜索"]):
            needed_types.add("记忆")
        # 质检相关
        if any(kw in task_lower for kw in ["检查","审计","audit","verify","质量"]):
            needed_types.add("质检")
        # 上下文相关
        if any(kw in task_lower for kw in ["压缩","上下文","pack","精简"]):
            needed_types.add("上下文")
        
        # 如果什么都没识别到, 根据任务复杂度推断
        if not needed_types:
            # 简单任务不需要武器, 复杂任务自动调用质检+记忆
            if len(task) > 100:
                needed_types.add("质检")
        
        return {
            "task": task,
            "needed_types": list(needed_types),
            "total_types": len(needed_types),
        }
    
    def command(self, task: str) -> dict:
        """
        执行一次作战指挥
        1. 分析战场 → 2. 调用武器 → 3. 汇总结果
        """
        analysis = self.analyze_battlefield(task)
        
        # 按编组执行
        all_results = {}
        weapon_count = 0
        
        for wtype in analysis["needed_types"]:
            # 获取该类型所有武器
            type_weapons = [(w, 1.0) for w in self.arsenal.weapons.values()
                          if w.type == wtype]
            if type_weapons:
                results = self.arsenal.parallel_fire(type_weapons)
                all_results.update(results)
                weapon_count += len(type_weapons)
        
        # 生成作战报告
        success = [k for k, v in all_results.items() if "✅" in v]
        fail = [k for k, v in all_results.items() if "❌" in v]
        warn = [k for k, v in all_results.items() if "⚠️" in v]
        
        report = {
            "time": datetime.now().isoformat(),
            "task": task,
            "analysis": analysis,
            "weapons_used": weapon_count,
            "results": all_results,
            "success": success,
            "fail": fail,
            "warn": warn,
            "summary": (
                f"⚔️ 作战报告: {task}\n"
                f"  出动{weapon_count}件武器({len(success)}成功/{len(warn)}警告/{len(fail)}失败)\n"
                f"  编组: {', '.join(analysis['needed_types'])}\n"
                + (f"  ✅ {', '.join(success[:5])}" if success else "")
                + (f"\n  ❌ {', '.join(fail[:3])}" if fail else "")
            ),
        }
        
        self.battle_log.append(report)
        return report


# ════════════════════════════════════════════════════════════
# 强制注入层 — 在任务执行前自动调用
# ════════════════════════════════════════════════════════════

def preemptive_strike(task: str) -> str:
    """
    先发制人: 在Hermes处理任务之前, 自动调用相关武器.
    返回一个"武器已经帮你跑完了"的上下文摘要.
    """
    commander = BattleCommander()
    report = commander.command(task)
    return report["summary"]


# ════════════════════════════════════════════════════════════
# CLI入口
# ════════════════════════════════════════════════════════════
if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "demo"
    
    if cmd == "demo":
        test_tasks = [
            "采集微博数据并清洗推送",
            "检查系统健康状态",
            "修复推送系统的SQL错误",
            "压缩上下文并检查记忆",
        ]
        for task in test_tasks:
            print(f"\n{'='*60}")
            print(f"任务: {task}")
            print(f"{'='*60}")
            
            # 战场分析
            commander = BattleCommander()
            analysis = commander.analyze_battlefield(task)
            print(f"分析: 需要{analysis['total_types']}个编组 → {analysis['needed_types']}")
            
            # 列出相关武器但不实际执行(避免副作用)
            arsenal = Arsenal()
            relevant = arsenal.get_relevant(task)
            if relevant:
                print(f"可用武器({len(relevant)}件):")
                for w, score in relevant:
                    print(f"  [{w.type}] {w.name} (相关度{score:.1f})")
            
            # 执行结果摘要
            report = commander.command(task)
            print(f"执行: 出动{report['weapons_used']}件武器")
            print(f"结果: {len(report['success'])}成功/{len(report['warn'])}警告/{len(report['fail'])}失败")
    
    elif cmd == "fire":
        task = sys.argv[2] if len(sys.argv) > 2 else "采集微博数据"
        summary = preemptive_strike(task)
        print(summary)
    
    elif cmd == "types":
        """列出所有武器类型分布"""
        arsenal = Arsenal()
        by_type = defaultdict(list)
        for w in arsenal.weapons.values():
            by_type[w.type].append(w.name)
        print("武器类型分布:")
        for t, weapons in sorted(by_type.items()):
            print(f"  {t}: {len(weapons)}件 → {', '.join(weapons)}")
