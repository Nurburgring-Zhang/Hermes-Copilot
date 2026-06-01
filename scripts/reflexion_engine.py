#!/usr/bin/env python3
"""
Reflexion三角循环自动触发引擎 (P3-1)
========================================
功能：复盘<60分时自动执行执行→评估→反思三角循环

三角循环:
  1. Actor: 重新执行任务（用失败后的修正方案）
  2. Evaluator: 评估修正后的结果
  3. Reflector: 生成结构化反思报告+经验写入memory

Usage:
  python3 reflexion_engine.py --retro-file <retro_file.json>
  python3 reflexion_engine.py --trigger <task_info_json>
  python3 reflexion_engine.py --check-candidates
"""

import json, sys, os, sqlite3, hashlib, uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple

HERMES = Path("/home/administrator/.hermes")
STATE_DB = HERMES / "state.db"
ACTIVE_MEM_DB = HERMES / "active_memory.db"
TZ = timezone(timedelta(hours=8))

def log(msg: str):
    ts = datetime.now(TZ).strftime("%H:%M:%S")
    print(f"[{ts}] {msg}")


class ReflexionEngine:
    """
    Reflexion三角循环引擎
    复盘<60分时自动执行 执行→评估→反思 三角循环
    """

    REFLEXION_THRESHOLD = 60  # 低于此分触发三角循环

    def __init__(self):
        self.cycle_data = {
            "cycle_id": str(uuid.uuid4())[:8],
            "triggered_at": datetime.now(TZ).isoformat(),
            "original_retro": {},
            "actor_result": {},
            "evaluator_result": {},
            "reflector_result": {},
            "cycle_complete": False,
        }

    def should_trigger(self, retro_report: dict) -> bool:
        """判断是否触发Reflexion三角循环"""
        score = retro_report.get("overall_summary", retro_report.get("quality_assessment", {})).get("overall_score", 100)
        if isinstance(score, dict):
            score = score.get("total_score", 100)
        if isinstance(score, str):
            try:
                score = float(score)
            except:
                score = 100
        
        should = score < self.REFLEXION_THRESHOLD
        if should:
            log(f"  🔔 复盘评分 {score} < {self.REFLEXION_THRESHOLD}，触发Reflexion三角循环")
        else:
            log(f"  ✅ 复盘评分 {score} >= {self.REFLEXION_THRESHOLD}，无需三角循环")
        
        return should

    def phase1_actor(self, retro_report: dict) -> Dict[str, Any]:
        """
        Phase 1: Actor - 重新执行任务（生成修正方案）
        根据复盘结果生成修正建议和重新执行的方案
        """
        log("\n  [Phase 1/3] Actor — 分析失败，生成修正方案")

        root_causes = retro_report.get("root_causes", [])
        improvements = retro_report.get("experience", {}).get("improvements", [])
        error_rate = retro_report.get("task_summary", {}).get("error_rate", 0)

        if isinstance(root_causes, str):
            try:
                root_causes = json.loads(root_causes)
            except:
                root_causes = [root_causes]

        actor_result = {
            "phase": "actor",
            "analysis": {
                "root_causes": root_causes,
                "improvements_needed": improvements,
                "error_rate": error_rate,
            },
            "correction_plan": [],
            "corrected_execution": [],
        }

        # 生成修正计划
        if root_causes:
            for cause in root_causes:
                actor_result["correction_plan"].append({
                    "issue": cause,
                    "fix": f"修正: {cause} — 建议重新检查参数和调用方式",
                    "priority": "high" if "error" in str(cause).lower() else "medium",
                })

        if improvements:
            for imp in improvements:
                actor_result["correction_plan"].append({
                    "issue": imp,
                    "fix": f"执行: {imp}",
                    "priority": "medium",
                })

        # 生成修正后的执行步骤
        if not actor_result["correction_plan"]:
            actor_result["correction_plan"].append({
                "issue": "无明确根因",
                "fix": "重新执行并增加详细的日志记录",
                "priority": "high",
            })

        actor_result["corrected_execution"] = [
            f"Step {i+1}: {plan['fix']}" for i, plan in enumerate(actor_result["correction_plan"])
        ]

        log(f"    分析完成 - 发现 {len(root_causes)} 个根因, {len(improvements)} 项改进建议")
        log(f"    生成 {len(actor_result['correction_plan'])} 条修正计划")

        return actor_result

    def phase2_evaluator(self, actor_result: dict) -> Dict[str, Any]:
        """
        Phase 2: Evaluator - 评估修正后的结果
        对Actor的修正方案进行评估和打分
        """
        log("\n  [Phase 2/3] Evaluator — 评估修正方案")

        correction_plan = actor_result.get("correction_plan", [])
        
        evaluation = {
            "phase": "evaluator",
            "plan_assessment": {},
            "risk_analysis": [],
            "evaluation_score": 0.0,
            "verdict": "",
        }

        # 评估修正计划的质量
        if not correction_plan:
            evaluation["plan_assessment"] = {
                "completeness": 0,
                "specificity": 0,
                "feasibility": 0,
                "note": "无修正计划",
            }
            evaluation["evaluation_score"] = 0
            evaluation["verdict"] = "REJECT"
            return evaluation

        high_priority = sum(1 for p in correction_plan if p.get("priority") == "high")
        medium_priority = sum(1 for p in correction_plan if p.get("priority") == "medium")

        completeness = min(100, len(correction_plan) * 25)
        specificity = min(100, 50 + high_priority * 15)
        feasibility = min(100, 60 + high_priority * 10)

        evaluation["plan_assessment"] = {
            "completeness": completeness,
            "specificity": specificity,
            "feasibility": feasibility,
            "total_items": len(correction_plan),
            "high_priority_items": high_priority,
            "medium_priority_items": medium_priority,
        }

        # 风险评估
        if high_priority > 3:
            evaluation["risk_analysis"].append("⚠️ 高风险项目过多，建议分阶段执行")
        if completeness < 50:
            evaluation["risk_analysis"].append("⚠️ 修正计划不完整，需补充更多细节")
        if feasibility < 60:
            evaluation["risk_analysis"].append("⚠️ 部分修正方案可行性较低，需重新评估")

        # 综合评分
        avg_score = (completeness + specificity + feasibility) / 3
        if evaluation["risk_analysis"]:
            avg_score -= len(evaluation["risk_analysis"]) * 5
        
        evaluation["evaluation_score"] = round(max(0, min(100, avg_score)), 1)
        evaluation["verdict"] = "APPROVED" if evaluation["evaluation_score"] >= 60 else "REJECT"

        log(f"    完整性: {completeness}% | 具体性: {specificity}% | 可行性: {feasibility}%")
        log(f"    评估得分: {evaluation['evaluation_score']} | 判定: {evaluation['verdict']}")
        if evaluation["risk_analysis"]:
            for risk in evaluation["risk_analysis"]:
                log(f"    {risk}")

        return evaluation

    def phase3_reflector(self, actor_result: dict, evaluator_result: dict) -> Dict[str, Any]:
        """
        Phase 3: Reflector - 生成结构化反思报告+经验写入memory
        """
        log("\n  [Phase 3/3] Reflector — 生成反思报告并写入memory")

        reflection = {
            "phase": "reflector",
            "cycle_id": self.cycle_data["cycle_id"],
            "structured_reflection": {},
            "experience_to_write": [],
            "memory_write_result": [],
            "reflection_complete": False,
        }

        # 结构化反思
        plan_assessment = evaluator_result.get("plan_assessment", {})
        reflection["structured_reflection"] = {
            "what_went_wrong": [p["issue"] for p in actor_result.get("correction_plan", []) if p.get("priority") == "high"],
            "what_was_improved": [p["fix"] for p in actor_result.get("correction_plan", [])],
            "confidence": evaluator_result.get("evaluation_score", 0),
            "risk_factors": evaluator_result.get("risk_analysis", []),
            "recommendation": evaluator_result.get("verdict", "UNKNOWN"),
        }

        # 提取可写经验
        for plan in actor_result.get("correction_plan", []):
            experience = {
                "id": str(uuid.uuid4())[:12],
                "type": "reflexion_correction",
                "issue": plan["issue"],
                "fix": plan["fix"],
                "priority": plan["priority"],
                "evaluation_score": evaluator_result.get("evaluation_score", 0),
                "created_at": datetime.now(TZ).isoformat(),
            }
            reflection["experience_to_write"].append(experience)

        # 写入memory
        memory_write_result = []
        for exp in reflection["experience_to_write"]:
            success = self._write_experience_to_memory(exp)
            memory_write_result.append({
                "experience_id": exp["id"],
                "written": success,
                "target": "active_memory.db",
            })
            if success:
                log(f"    ✅ 经验已写入: {exp['issue'][:50]}...")
                # 同时写入memory_semantic(长期语义记忆)
                self._write_to_memory_semantic(exp)

        reflection["memory_write_result"] = memory_write_result
        reflection["reflection_complete"] = True

        # 如果评估通过，写入经验池
        if evaluator_result.get("verdict") == "APPROVED":
            self._write_to_experience_pool(reflection["experience_to_write"])

        log(f"    反思完成 - 写入 {len(reflection['experience_to_write'])} 条经验")
        
        return reflection

    def _write_experience_to_memory(self, experience: dict) -> bool:
        """写入经验到active_memory.db (memory_reflexion + memory_semantic)"""
        try:
            conn = sqlite3.connect(str(ACTIVE_MEM_DB))
            c = conn.cursor()
            c.execute("""
                CREATE TABLE IF NOT EXISTS memory_reflexion (
                    id TEXT PRIMARY KEY,
                    type TEXT,
                    issue TEXT,
                    fix TEXT,
                    priority TEXT,
                    evaluation_score REAL,
                    created_at TEXT
                )
            """)
            c.execute("""
                INSERT OR REPLACE INTO memory_reflexion
                (id, type, issue, fix, priority, evaluation_score, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                experience["id"],
                experience["type"],
                experience["issue"][:500],
                experience["fix"][:500],
                experience["priority"],
                experience["evaluation_score"],
                experience["created_at"],
            ))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            log(f"    ⚠️ 写入memory失败: {e}")
            return False

    def _write_to_memory_semantic(self, experience: dict):
        """将反思结论写入memory_semantic表(供长期记忆使用)"""
        try:
            conn = sqlite3.connect(str(ACTIVE_MEM_DB))
            c = conn.cursor()
            c.execute("""
                CREATE TABLE IF NOT EXISTS memory_semantic (
                    id TEXT PRIMARY KEY,
                    fact TEXT,
                    cat TEXT,
                    confidence REAL,
                    active INTEGER DEFAULT 1,
                    source TEXT,
                    created_at TEXT
                )
            """)
            fact = f"[Reflexion] 问题: {experience['issue'][:200]} → 方案: {experience['fix'][:200]} | 优先级: {experience['priority']} | 评分: {experience.get('evaluation_score', 0)}"
            c.execute("""
                INSERT OR REPLACE INTO memory_semantic
                (id, fact, cat, confidence, active, source, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                f"reflexion_{experience['id']}",
                fact,
                "reflexion",
                0.8,
                1,
                "reflexion_engine",
                datetime.now(TZ).isoformat(),
            ))
            conn.commit()
            conn.close()
            log(f"    ✅ 反思结论已写入memory_semantic: {fact[:60]}...")
        except Exception as e:
            log(f"    ⚠️ 写入memory_semantic失败: {e}")

    def _write_to_experience_pool(self, experiences: list):
        """写入经验池（供Skill进化使用）"""
        try:
            pool_file = HERMES / "data" / "reflexion_experience_pool.jsonl"
            (HERMES / "data").mkdir(exist_ok=True)
            with open(pool_file, "a") as f:
                for exp in experiences:
                    f.write(json.dumps(exp, ensure_ascii=False) + "\n")
            log(f"    📝 经验已追加到池: {pool_file}")
        except Exception as e:
            log(f"    ⚠️ 写入经验池失败: {e}")

    def run_cycle(self, retro_report: dict) -> Dict[str, Any]:
        """执行完整三角循环"""
        log("\n" + "=" * 50)
        log(f"Reflexion三角循环启动 [Cycle: {self.cycle_data['cycle_id']}]")
        log("=" * 50)

        self.cycle_data["original_retro"] = retro_report

        # Phase 1
        self.cycle_data["actor_result"] = self.phase1_actor(retro_report)
        
        # Phase 2
        self.cycle_data["evaluator_result"] = self.phase2_evaluator(
            self.cycle_data["actor_result"]
        )
        
        # Phase 3
        self.cycle_data["reflector_result"] = self.phase3_reflector(
            self.cycle_data["actor_result"],
            self.cycle_data["evaluator_result"],
        )

        self.cycle_data["cycle_complete"] = True

        # 保存完整报告
        self._save_cycle_report()

        log("\n" + "=" * 50)
        log(f"Reflexion三角循环完成")
        log(f"  Cycle: {self.cycle_data['cycle_id']}")
        log(f"  修正计划: {len(self.cycle_data['actor_result']['correction_plan'])} 条")
        log(f"  评估得分: {self.cycle_data['evaluator_result']['evaluation_score']}")
        log(f"  经验写入: {sum(1 for r in self.cycle_data['reflector_result']['memory_write_result'] if r['written'])} 条")
        log("=" * 50)

        return self.cycle_data

    def _save_cycle_report(self):
        """保存三角循环报告"""
        date_str = datetime.now(TZ).strftime("%Y%m%d_%H%M%S")
        filepath = HERMES / "reports" / f"reflexion_cycle_{date_str}.json"
        (HERMES / "reports").mkdir(exist_ok=True)
        
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(self.cycle_data, f, ensure_ascii=False, indent=2)
        
        log(f"\n📄 三角循环报告已保存: {filepath}")


def trigger_from_retro_file(retro_file: str):
    """从复盘文件触发三角循环"""
    if not os.path.exists(retro_file):
        log(f"❌ 复盘文件不存在: {retro_file}")
        return
    
    with open(retro_file) as f:
        retro_report = json.load(f)
    
    engine = ReflexionEngine()
    if engine.should_trigger(retro_report):
        engine.run_cycle(retro_report)
    else:
        log("无需触发Reflexion三角循环")


def check_candidates():
    """检查候选队列中的待处理任务"""
    candidates_file = HERMES / "data" / "retro_candidates.jsonl"
    if not candidates_file.exists():
        log("📝 候选队列为空")
        return
    
    with open(candidates_file) as f:
        lines = f.readlines()
    
    log(f"📝 Reflexion候选队列: {len(lines)} 条待处理")
    for line in lines[-10:]:
        d = json.loads(line)
        score = d.get("score", "?")
        source = d.get("source", "?")
        log(f"  [{score}] {source}: {d.get('improvements', ['?'])[:1]}")


def main():
    if "--retro-file" in sys.argv:
        idx = sys.argv.index("--retro-file")
        filepath = sys.argv[idx + 1] if idx + 1 < len(sys.argv) else ""
        if filepath:
            trigger_from_retro_file(filepath)
        else:
            log("用法: --retro-file <path>")
    elif "--check-candidates" in sys.argv:
        check_candidates()
    elif "--trigger" in sys.argv:
        idx = sys.argv.index("--trigger")
        task_json = sys.argv[idx + 1] if idx + 1 < len(sys.argv) else "{}"
        try:
            task_info = json.loads(task_json)
            # 构造复盘报告格式
            retro_report = {
                "overall_summary": {"overall_score": task_info.get("score", 50)},
                "root_causes": task_info.get("root_causes", ["未知错误"]),
                "task_summary": {"error_rate": task_info.get("error_rate", 50)},
                "experience": {"improvements": task_info.get("improvements", ["需改进"])},
            }
            engine = ReflexionEngine()
            if engine.should_trigger(retro_report):
                engine.run_cycle(retro_report)
        except json.JSONDecodeError:
            log("❌ JSON解析失败")
    else:
        print("""Reflexion三角循环引擎 (P3-1)
Usage:
  python3 reflexion_engine.py --retro-file <file>     从复盘文件触发
  python3 reflexion_engine.py --trigger <json>         直接触发
  python3 reflexion_engine.py --check-candidates       检查候选队列
""")


if __name__ == "__main__":
    main()
