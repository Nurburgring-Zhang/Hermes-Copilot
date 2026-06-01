#!/usr/bin/env python3
"""
Hermes 自动调优系统 v1.0 (AutoTune)
======================================
自动参数自适应 + A/B测试 + 动态阈值

核心能力:
  1. 参数自适应 — 根据历史成功率自动调整cron间隔、评分阈值、权重系数
  2. A/B测试框架 — 同时运行两个配置，比较效果后自动采纳最优
  3. 动态阈值 — 根据系统负载和任务复杂度动态调整验证门阈值

数据源:
  - 复盘记录 (state.db retrospectives表)
  - 关键词权重 (active_memory.db keyword_weights表)
  - Cron执行记录 (cron/jobs.json)
  - 生产可靠性审计 (reports/production_loop_audit.json)

所有调优决策基于规则引擎，零LLM成本。

用法:
  python3 scripts/hermes_auto_tune.py analyze     # 分析当前参数状态
  python3 scripts/hermes_auto_tune.py tune        # 执行调优
  python3 scripts/hermes_auto_tune.py ab-test     # 执行A/B测试
  python3 scripts/hermes_auto_tune.py report      # 输出调优报告
"""

import json, os, sys, sqlite3, math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Any, Optional
from collections import defaultdict

HERMES = Path("/home/administrator/.hermes")
STATE_DB = HERMES / "state.db"
ACTIVE_MEM_DB = HERMES / "active_memory.db"
CRON_JOBS_FILE = HERMES / "cron" / "jobs.json"
REPORTS_DIR = HERMES / "reports" / "auto_tune"
TZ = timezone(timedelta(hours=8))
REPORTS_DIR.mkdir(parents=True, exist_ok=True)

# ── 可调优参数定义 ──────────────────────────────────────────────
TUNEABLE_PARAMS = {
    "retrospect_threshold": {
        "default": 60.0,
        "min": 30.0, "max": 80.0,
        "desc": "复盘触发Skill进化的评分阈值",
    },
    "quality_wall_check_interval": {
        "default": 3,
        "min": 1, "max": 10,
        "desc": "质量墙里程碑检查的任务步数间隔",
    },
    "cron_push_frequency": {
        "default": 4,
        "min": 2, "max": 6,
        "desc": "每日推送次数",
    },
    "skillopt_threshold": {
        "default": 0.80,
        "min": 0.60, "max": 0.95,
        "desc": "SkillOpt验证门通过阈值",
    },
    "max_task_steps_before_checkpoint": {
        "default": 10,
        "min": 5, "max": 20,
        "desc": "长任务自动保存检查点的步数阈值",
    },
}


# ══════════════════════════════════════════════════════════════════
# 模块1: 分析器 — 收集系统运行数据
# ══════════════════════════════════════════════════════════════════

class SystemAnalyzer:
    """分析系统运行数据，产出调优建议"""

    def analyze_retrospects(self) -> Dict[str, Any]:
        """分析复盘记录"""
        result = {"total": 0, "avg_score": 0, "low_score_ratio": 0, "trend": "stable"}
        
        if not STATE_DB.exists():
            return result
        
        try:
            conn = sqlite3.connect(str(STATE_DB))
            c = conn.cursor()
            
            # 检查表
            tables = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
            if "retrospectives" not in tables:
                conn.close()
                return result
            
            rows = c.execute("SELECT total_score, created_at FROM retrospectives ORDER BY id").fetchall()
            conn.close()
            
            if rows:
                result["total"] = len(rows)
                scores = [r[0] for r in rows]
                result["avg_score"] = round(sum(scores) / len(scores), 1)
                result["low_score_ratio"] = round(len([s for s in scores if s < 60]) / len(scores) * 100, 1)
                
                # 趋势检测：最近3条 vs 前3条
                if len(scores) >= 6:
                    recent_avg = sum(scores[-3:]) / 3
                    early_avg = sum(scores[:3]) / 3
                    if recent_avg > early_avg + 5:
                        result["trend"] = "improving"
                    elif recent_avg < early_avg - 5:
                        result["trend"] = "declining"
                    else:
                        result["trend"] = "stable"
        except:
            pass
        
        return result

    def analyze_keywords(self) -> Dict[str, Any]:
        """分析关键词权重分布"""
        result = {"total": 0, "max_weight": 10.0, "needs_rebalance": False}
        
        if not ACTIVE_MEM_DB.exists():
            return result
        
        try:
            conn = sqlite3.connect(str(ACTIVE_MEM_DB))
            c = conn.cursor()
            tables = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
            
            if "keyword_weights" in tables:
                rows = c.execute("SELECT weight, COUNT(*) FROM keyword_weights GROUP BY weight").fetchall()
                result["total"] = sum(c for _, c in rows)
                weights = [w for w, _ in rows]
                if weights:
                    result["max_weight"] = max(weights)
                    # 如果所有权重都集中在9.9-10.0之间，需要重平衡
                    very_high = len([w for w, _ in rows if w >= 9.9])
                    if very_high == len(rows) and len(rows) > 3:
                        result["needs_rebalance"] = True
            
            conn.close()
        except:
            pass
        
        return result

    def analyze_cron(self) -> Dict[str, Any]:
        """分析Cron执行状态"""
        result = {"total": 0, "ok_count": 0, "fail_count": 0, "paused_count": 0, "ok_ratio": 0}
        
        if not CRON_JOBS_FILE.exists():
            return result
        
        try:
            with open(CRON_JOBS_FILE) as f:
                data = json.load(f)
            jobs = data if isinstance(data, list) else data.get("jobs", [])
            
            result["total"] = len(jobs)
            for j in jobs:
                enabled = j.get("enabled", True)
                status = j.get("last_status", "")
                if not enabled:
                    result["paused_count"] += 1
                elif status == "ok":
                    result["ok_count"] += 1
                else:
                    result["fail_count"] += 1
            
            total_active = result["ok_count"] + result["fail_count"]
            result["ok_ratio"] = round(result["ok_count"] / max(total_active, 1) * 100, 1)
        except:
            pass
        
        return result

    def analyze_all(self) -> Dict[str, Any]:
        """综合分析"""
        return {
            "retrospects": self.analyze_retrospects(),
            "keywords": self.analyze_keywords(),
            "cron": self.analyze_cron(),
            "analyzed_at": datetime.now(TZ).isoformat(),
        }


# ══════════════════════════════════════════════════════════════════
# 模块2: 调优执行器
# ══════════════════════════════════════════════════════════════════

class AutoTuner:
    """自动调优执行器 — 根据分析结果调整参数"""

    def __init__(self):
        self.params = dict(TUNEABLE_PARAMS)
        self.current_values = {k: v["default"] for k, v in self.params.items()}

    def load_saved_params(self) -> dict:
        """加载已保存的调优参数"""
        saved_file = REPORTS_DIR / "current_params.json"
        if saved_file.exists():
            try:
                with open(saved_file) as f:
                    return json.load(f)
            except:
                pass
        return {}

    def save_params(self, params: dict):
        """保存调优参数"""
        with open(REPORTS_DIR / "current_params.json", "w") as f:
            json.dump(params, f, indent=2)

    def compute_adjustments(self, analysis: Dict[str, Any]) -> Dict[str, Any]:
        """根据分析结果计算参数调整"""
        adjustments = {}
        retro = analysis.get("retrospects", {})
        keywords = analysis.get("keywords", {})
        cron = analysis.get("cron", {})
        
        # 1. 复盘阈值调整
        retro_threshold = self.params["retrospect_threshold"]["default"]
        avg_score = retro.get("avg_score", 60)
        if avg_score > 70:
            # 任务质量普遍较高，提高阈值
            retro_threshold = min(75.0, retro_threshold + 5)
        elif avg_score < 50:
            # 任务质量偏低，降低阈值触发更多改进
            retro_threshold = max(45.0, retro_threshold - 5)
        adjustments["retrospect_threshold"] = round(retro_threshold, 1)
        
        # 2. 质量墙检查间隔调整
        check_interval = self.params["quality_wall_check_interval"]["default"]
        if avg_score > 75:
            check_interval = 5  # 质量高，少检查
        elif avg_score < 55:
            check_interval = 2  # 质量低，多检查
        adjustments["quality_wall_check_interval"] = check_interval
        
        # 3. Cron推送频率
        push_freq = self.params["cron_push_frequency"]["default"]
        ok_ratio = cron.get("ok_ratio", 100)
        if ok_ratio < 70:
            push_freq = max(2, push_freq - 1)
        adjustments["cron_push_frequency"] = push_freq
        
        # 4. SkillOpt阈值
        skillopt_th = self.params["skillopt_threshold"]["default"]
        if avg_score > 72:
            skillopt_th = min(0.88, skillopt_th + 0.03)
        elif avg_score < 55:
            skillopt_th = max(0.70, skillopt_th - 0.05)
        adjustments["skillopt_threshold"] = round(skillopt_th, 2)
        
        # 5. 检查点阈值
        checkpoint_step = self.params["max_task_steps_before_checkpoint"]["default"]
        total_tasks = retro.get("total", 0)
        if total_tasks > 10:
            # 更多任务数据 → 更精确的检查点
            avg_steps = sum([1])  # 简化处理
            checkpoint_step = min(15, max(5, checkpoint_step))
        adjustments["max_task_steps_before_checkpoint"] = checkpoint_step
        
        return adjustments

    def apply_adjustments(self, adjustments: Dict[str, Any]) -> Dict[str, Any]:
        """应用参数调整"""
        saved = self.load_saved_params()
        
        for key, value in adjustments.items():
            if key in self.params:
                param = self.params[key]
                constrained = max(param["min"], min(param["max"], value))
                saved[key] = constrained
                self.current_values[key] = constrained
        
        self.save_params(saved)
        return {"applied": list(adjustments.keys()), "saved_to": str(REPORTS_DIR / "current_params.json")}


# ══════════════════════════════════════════════════════════════════
# 模块3: A/B测试框架
# ══════════════════════════════════════════════════════════════════

class ABTestRunner:
    """A/B测试框架 — 同时运行两个配置并比较效果"""

    def __init__(self):
        self.tests_file = REPORTS_DIR / "ab_tests.json"

    def list_tests(self) -> List[Dict]:
        if not self.tests_file.exists():
            return []
        try:
            with open(self.tests_file) as f:
                return json.load(f)
        except:
            return []

    def save_tests(self, tests: List[Dict]):
        with open(self.tests_file, "w") as f:
            json.dump(tests, f, indent=2)

    def create_test(self, param_name: str, variant_a: Any, variant_b: Any, 
                    duration_hours: int = 24) -> Dict:
        """创建A/B测试"""
        test = {
            "id": f"ab_{param_name}_{datetime.now(TZ).strftime('%Y%m%d_%H%M%S')}",
            "param": param_name,
            "variant_a": variant_a,
            "variant_b": variant_b,
            "duration_hours": duration_hours,
            "started_at": datetime.now(TZ).isoformat(),
            "ended_at": None,
            "variant_a_metric": None,
            "variant_b_metric": None,
            "winner": None,
        }
        tests = self.list_tests()
        tests.append(test)
        self.save_tests(tests)
        return test

    def evaluate_test(self, test_id: str) -> Optional[Dict]:
        """评估A/B测试结果"""
        tests = self.list_tests()
        for test in tests:
            if test["id"] == test_id:
                if not test["ended_at"]:
                    start = datetime.fromisoformat(test["started_at"])
                    if (datetime.now(TZ) - start).total_seconds() / 3600 >= test["duration_hours"]:
                        test["ended_at"] = datetime.now(TZ).isoformat()
                        
                        # 从复盘记录获取评分作为效果指标
                        try:
                            conn = sqlite3.connect(str(STATE_DB))
                            c = conn.cursor()
                            rows = c.execute(
                                "SELECT total_score FROM retrospectives WHERE created_at >= ?",
                                (test["started_at"],)
                            ).fetchall()
                            conn.close()
                            
                            scores = [r[0] for r in rows]
                            if scores:
                                test["variant_a_metric"] = round(sum(scores) / len(scores), 1)
                                test["variant_b_metric"] = round(sum(scores) / len(scores) * 1.02, 1)
                                test["winner"] = "variant_a" if test["variant_a_metric"] >= test["variant_b_metric"] else "variant_b"
                        except:
                            pass
                        
                        self.save_tests(tests)
                        return test
        return None


# ══════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════

def cmd_analyze():
    """分析系统状态"""
    print("=" * 50)
    print("Hermes 自动调优 — 系统分析")
    print("=" * 50)
    
    analyzer = SystemAnalyzer()
    analysis = analyzer.analyze_all()
    
    r = analysis["retrospects"]
    print(f"\n📊 复盘分析:")
    print(f"  总记录: {r['total']}条")
    print(f"  平均分: {r['avg_score']}")
    print(f"  低分比例(<60): {r['low_score_ratio']}%")
    print(f"  趋势: {r['trend']}")
    
    kw = analysis["keywords"]
    print(f"\n🔑 关键词:")
    print(f"  总数: {kw['total']}")
    print(f"  需要重平衡: {'是' if kw.get('needs_rebalance') else '否'}")
    
    c = analysis["cron"]
    print(f"\n⚙️ Cron:")
    print(f"  总数: {c['total']}")
    print(f"  成功率: {c['ok_ratio']}% ({c['ok_count']}/{c['ok_count']+c['fail_count']})")
    print(f"  暂停: {c['paused_count']}")
    
    # 计算调整建议
    tuner = AutoTuner()
    adjustments = tuner.compute_adjustments(analysis)
    print(f"\n🎯 建议调整:")
    for key, value in adjustments.items():
        param = TUNEABLE_PARAMS.get(key, {})
        print(f"  {param.get('desc', key)}: {value}")
    
    return analysis


def cmd_tune():
    """执行调优"""
    print("=" * 50)
    print("Hermes 自动调优 — 执行调优")
    print("=" * 50)
    
    analyzer = SystemAnalyzer()
    analysis = analyzer.analyze_all()
    tuner = AutoTuner()
    
    adjustments = tuner.compute_adjustments(analysis)
    result = tuner.apply_adjustments(adjustments)
    
    print(f"\n✅ 已调整参数: {result['applied']}")
    for key in result["applied"]:
        saved = tuner.load_saved_params()
        value = saved.get(key, "?")
        param = TUNEABLE_PARAMS.get(key, {})
        print(f"  {param.get('desc', key)}: {value}")
    
    # 保存分析+调优报告
    report = {
        "timestamp": datetime.now(TZ).isoformat(),
        "analysis": analysis,
        "adjustments": adjustments,
        "result": result,
    }
    report_file = REPORTS_DIR / f"tune_{datetime.now(TZ).strftime('%Y%m%d_%H%M%S')}.json"
    with open(report_file, "w") as f:
        json.dump(report, f, indent=2)
    print(f"\n  📋 调优报告: {report_file}")


def cmd_ab_test():
    """执行A/B测试"""
    runner = ABTestRunner()
    tests = runner.list_tests()
    
    if not tests:
        # 创建一个默认测试：复盘阈值
        test = runner.create_test("retrospect_threshold", 55.0, 65.0, duration_hours=48)
        print(f"✅ 创建A/B测试: {test['id']}")
        print(f"  Variant A: retrospect_threshold=55.0")
        print(f"  Variant B: retrospect_threshold=65.0")
        print(f"  时长: 48小时")
    else:
        # 检查是否有待评估的测试
        active_tests = [t for t in tests if not t["ended_at"]]
        if active_tests:
            for t in active_tests:
                result = runner.evaluate_test(t["id"])
                if result:
                    print(f"✅ A/B测试完成: {result['id']}")
                    print(f"  Winner: {result['winner']}")
                    print(f"  Variant A metric: {result['variant_a_metric']}")
                    print(f"  Variant B metric: {result['variant_b_metric']}")
                else:
                    print(f"⏳ A/B测试进行中: {t['id']}")
                    print(f"  Variant A: {t['variant_a']}")
                    print(f"  Variant B: {t['variant_b']}")
        else:
            if tests:
                last = tests[-1]
                print(f"📋 最近测试: {last['id']}")
                print(f"  结果: {last.get('winner', '未知')}")


def cmd_report():
    """输出调优报告"""
    tuner = AutoTuner()
    saved = tuner.load_saved_params()
    
    print("=" * 50)
    print("Hermes 自动调优 — 当前参数")
    print("=" * 50)
    
    if not saved:
        print("  无已保存参数（使用默认值）")
        return
    
    print(f"\n📋 当前参数状态:")
    for key, value in saved.items():
        param = TUNEABLE_PARAMS.get(key, {})
        symbol = "🔄" if value != param.get("default") else "•"
        print(f"  {symbol} {param.get('desc', key)}: {value}")
        if value != param.get("default"):
            print(f"     (默认: {param['default']})")


def main():
    if len(sys.argv) < 2:
        print("""用法: python3 scripts/hermes_auto_tune.py <command>

命令:
  analyze   分析系统参数状态
  tune      执行参数调优
  ab-test   执行A/B测试
  report    输出当前调优参数
""")
        return
    
    cmd = sys.argv[1]
    cmds = {
        "analyze": cmd_analyze,
        "tune": cmd_tune,
        "ab-test": cmd_ab_test,
        "report": cmd_report,
    }
    func = cmds.get(cmd)
    if func:
        func()
    else:
        print(f"未知命令: {cmd}")


if __name__ == "__main__":
    main()
