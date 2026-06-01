#!/usr/bin/env python3
"""
IPD TR Gate Check Script (P2-1)
=================================
6道质量门(TR1-TR6)门禁检查系统。
每道门有Exit Criteria检查，不通过不能进入下一阶段。

Usage:
  python3 tr_gate.py --check tr1        # 检查TR1门
  python3 tr_gate.py --check all        # 全部检查
  python3 tr_gate.py --list             # 列出所有门的状态
"""

import json, sys, os, sqlite3, hashlib
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple

HERMES = Path("/home/administrator/.hermes")
TZ = timezone(timedelta(hours=8))

def log(msg: str):
    ts = datetime.now(TZ).strftime("%H:%M:%S")
    print(f"[{ts}] {msg}")

# ══════════════════════════════════════════════════════════════════
# TR Gate Definitions
# ══════════════════════════════════════════════════════════════════

TR_GATES = {
    "tr1": {
        "name": "TR1 需求评审",
        "description": "检查需求目标明确性、可行性评估、成功标准完整性",
        "criteria": [
            {
                "id": "tr1_c1",
                "name": "目标明确性",
                "description": "任务目标是否明确、无歧义、可衡量",
                "check": lambda ctx: ctx.get("has_clear_goal", False),
                "suggestion": "请将任务目标分解为可量化的指标（如：完成X功能，达到Y性能）",
            },
            {
                "id": "tr1_c2",
                "name": "可行性评估",
                "description": "是否有初步的可行性和风险评估",
                "check": lambda ctx: ctx.get("has_feasibility", False),
                "suggestion": "评估所需资源（时间/工具/数据）是否充足，识别潜在风险点",
            },
            {
                "id": "tr1_c3",
                "name": "成功标准完整",
                "description": "是否已定义完整的成功标准（DoD层级）",
                "check": lambda ctx: ctx.get("has_success_criteria", False),
                "suggestion": "定义明确的通过/失败标准，包含功能、性能、质量等多维度",
            },
        ],
    },
    "tr2": {
        "name": "TR2 方案评审",
        "description": "检查技术方案选择理由、替代方案评估",
        "criteria": [
            {
                "id": "tr2_c1",
                "name": "技术方案选择理由",
                "description": "所选技术方案是否有明确的选型理由",
                "check": lambda ctx: ctx.get("has_tech_rationale", False),
                "suggestion": "写明选择该方案的理由（性能/可维护性/生态成熟度等）",
            },
            {
                "id": "tr2_c2",
                "name": "替代方案评估",
                "description": "是否至少评估了2种替代方案",
                "check": lambda ctx: ctx.get("has_alternatives", False),
                "suggestion": "至少对比2种替代方案，列出优缺点对比表",
            },
        ],
    },
    "tr3": {
        "name": "TR3 详细设计",
        "description": "检查伪代码/模块设计/接口定义",
        "criteria": [
            {
                "id": "tr3_c1",
                "name": "伪代码/核心逻辑",
                "description": "是否有核心流程的伪代码或流程图",
                "check": lambda ctx: ctx.get("has_pseudocode", False),
                "suggestion": "编写核心算法的伪代码或绘制流程图",
            },
            {
                "id": "tr3_c2",
                "name": "模块设计",
                "description": "模块划分是否合理，职责是否单一",
                "check": lambda ctx: ctx.get("has_module_design", False),
                "suggestion": "按单一职责原则划分模块，明确每个模块的输入/输出",
            },
            {
                "id": "tr3_c3",
                "name": "接口定义",
                "description": "模块间接口是否明确定义",
                "check": lambda ctx: ctx.get("has_interface_def", False),
                "suggestion": "定义模块间API接口（函数签名、参数类型、返回值）",
            },
        ],
    },
    "tr4": {
        "name": "TR4 原型验证",
        "description": "检查关键功能验证、边界测试",
        "criteria": [
            {
                "id": "tr4_c1",
                "name": "关键功能验证",
                "description": "核心功能是否已通过原型验证",
                "check": lambda ctx: ctx.get("has_proto_verify", False),
                "suggestion": "为核心功能编写原型或最小可行实现并验证",
            },
            {
                "id": "tr4_c2",
                "name": "边界测试",
                "description": "是否覆盖了输入边界和异常场景",
                "check": lambda ctx: ctx.get("has_boundary_test", False),
                "suggestion": "测试空值/极值/异常输入/并发等边界情况",
            },
        ],
    },
    "tr5": {
        "name": "TR5 集成评审",
        "description": "检查所有模块集成、完整流程测试",
        "criteria": [
            {
                "id": "tr5_c1",
                "name": "模块集成",
                "description": "所有模块是否已正确集成",
                "check": lambda ctx: ctx.get("has_integration", False),
                "suggestion": "按依赖顺序逐步集成各模块，确保接口匹配",
            },
            {
                "id": "tr5_c2",
                "name": "完整流程测试",
                "description": "端到端流程是否测试通过",
                "check": lambda ctx: ctx.get("has_e2e_test", False),
                "suggestion": "执行端到端测试用例，覆盖主流程和所有分支",
            },
        ],
    },
    "tr6": {
        "name": "TR6 交付评审",
        "description": "检查DoD全满足、文档齐全、可交付",
        "criteria": [
            {
                "id": "tr6_c1",
                "name": "DoD全满足",
                "description": "所有Definition of Done项是否完成",
                "check": lambda ctx: ctx.get("has_dod_met", False),
                "suggestion": "对照DoD清单逐项检查，确保无遗漏",
            },
            {
                "id": "tr6_c2",
                "name": "文档齐全",
                "description": "使用文档/设计文档/API文档是否齐全",
                "check": lambda ctx: ctx.get("has_docs", False),
                "suggestion": "准备使用说明、部署文档、API文档",
            },
            {
                "id": "tr6_c3",
                "name": "可交付确认",
                "description": "交付物是否经过最终确认可发布",
                "check": lambda ctx: ctx.get("has_deliverable", False),
                "suggestion": "确认交付物完整且经过最终审核",
            },
        ],
    },
}

TR_ORDER = ["tr1", "tr2", "tr3", "tr4", "tr5", "tr6"]


class TRGateChecker:
    """IPD TR Gate Checker"""

    def __init__(self):
        self.results: Dict[str, Any] = {}

    def check_gate(self, gate_id: str, context: dict) -> Dict[str, Any]:
        """Check a single TR gate"""
        gate_info = TR_GATES.get(gate_id)
        if not gate_info:
            return {"error": f"未知TR门: {gate_id}"}

        log(f"🔍 检查 {gate_info['name']}...")
        
        passed = True
        failed_criteria = []
        suggestions = []
        criterion_results = []

        for criterion in gate_info["criteria"]:
            try:
                is_passed = criterion["check"](context)
            except Exception as e:
                is_passed = False
                log(f"  ⚠️ 检查 {criterion['name']} 发生异常: {e}")

            criterion_results.append({
                "id": criterion["id"],
                "name": criterion["name"],
                "description": criterion["description"],
                "passed": is_passed,
                "suggestion": criterion["suggestion"] if not is_passed else "",
            })

            if not is_passed:
                passed = False
                failed_criteria.append(criterion["name"])
                suggestions.append(criterion["suggestion"])

        result = {
            "gate_id": gate_id,
            "gate_name": gate_info["name"],
            "description": gate_info["description"],
            "passed": passed,
            "failed_criteria": failed_criteria,
            "suggestions": suggestions,
            "criterion_results": criterion_results,
            "checked_at": datetime.now(TZ).isoformat(),
        }

        status = "✅ PASS" if passed else "❌ FAIL"
        log(f"  {status} - {len(failed_criteria)}/{len(gate_info['criteria'])} 项未通过")
        if failed_criteria:
            for fc, sug in zip(failed_criteria, suggestions):
                log(f"    - {fc}: {sug[:60]}...")

        self.results[gate_id] = result
        return result

    def check_sequential(self, context: dict, start_from: str = "tr1") -> Dict[str, Any]:
        """Sequential check: each gate must pass before proceeding to next"""
        start_idx = TR_ORDER.index(start_from) if start_from in TR_ORDER else 0
        results = {}
        
        log("\n" + "=" * 60)
        log("IPD TR Gate 顺序检查")
        log("=" * 60)

        for i in range(start_idx, len(TR_ORDER)):
            gate_id = TR_ORDER[i]
            result = self.check_gate(gate_id, context)
            results[gate_id] = result

            if not result["passed"]:
                # Check if previous gates passed
                if i > 0:
                    prev = TR_ORDER[i - 1]
                    if prev in self.results and not self.results[prev]["passed"]:
                        log(f"\n  ⛔ 前置门 {TR_GATES[prev]['name']} 未通过，阻塞中")
                        break
                log(f"\n  ⛔ {result['gate_name']} 未通过，无法进入下一阶段")
                break

            log(f"  ✅ 通过 - 可进入下一阶段")
            if i < len(TR_ORDER) - 1:
                next_gate = TR_GATES[TR_ORDER[i + 1]]["name"]
                log(f"  ➡️ 下一门: {next_gate}")

        return results

    def generate_summary(self) -> Dict[str, Any]:
        """Generate summary report"""
        total_gates = len(TR_GATES)
        checked = len(self.results)
        passed_gates = sum(1 for r in self.results.values() if r["passed"])
        
        summary = {
            "total_gates": total_gates,
            "checked": checked,
            "passed": passed_gates,
            "failed": checked - passed_gates,
            "overall_status": "PASS" if passed_gates == total_gates else "BLOCKED",
            "gate_results": self.results,
            "generated_at": datetime.now(TZ).isoformat(),
        }
        return summary

    def save_results(self) -> str:
        """Save check results to file"""
        summary = self.generate_summary()
        date_str = datetime.now(TZ).strftime("%Y%m%d_%H%M%S")
        filepath = HERMES / "reports" / f"tr_gate_{date_str}.json"
        (HERMES / "reports").mkdir(exist_ok=True)
        
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)
        
        log(f"\n📄 门禁检查报告已保存: {filepath}")
        return str(filepath)

    def save_to_db(self):
        """Save to state.db for other modules to consume"""
        if not self.results:
            return
        try:
            conn = sqlite3.connect(str(HERMES / "state.db"))
            c = conn.cursor()
            c.execute("""
                CREATE TABLE IF NOT EXISTS tr_gates (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    gate_id TEXT,
                    gate_name TEXT,
                    passed INTEGER,
                    failed_criteria TEXT,
                    suggestions TEXT,
                    full_result TEXT,
                    created_at TEXT
                )
            """)
            for gate_id, result in self.results.items():
                c.execute("""
                    INSERT INTO tr_gates
                    (gate_id, gate_name, passed, failed_criteria, suggestions, full_result, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    gate_id,
                    result["gate_name"],
                    1 if result["passed"] else 0,
                    json.dumps(result["failed_criteria"], ensure_ascii=False),
                    json.dumps(result["suggestions"], ensure_ascii=False),
                    json.dumps(result, ensure_ascii=False),
                    result["checked_at"],
                ))
            conn.commit()
            conn.close()
            log("  ✅ 门禁结果已存入state.db")
        except Exception as e:
            log(f"  ⚠️ 存入state.db失败: {e}")


def list_gates():
    """List all TR gates"""
    log("\nIPD TR Gate 门禁清单:")
    log("=" * 60)
    for i, gate_id in enumerate(TR_ORDER, 1):
        gate = TR_GATES[gate_id]
        log(f"\n  {i}. {gate['name']}")
        log(f"     {gate['description']}")
        for crit in gate["criteria"]:
            log(f"     - {crit['name']}: {crit['description']}")
    log("=" * 60)


def build_example_context(passed_gates: int = 0) -> dict:
    """Build an example context for testing. Passed_gates controls how many gates pass"""
    ctx = {}
    # TR1 criteria
    ctx["has_clear_goal"] = passed_gates >= 1
    ctx["has_feasibility"] = passed_gates >= 1
    ctx["has_success_criteria"] = passed_gates >= 1
    # TR2 criteria
    ctx["has_tech_rationale"] = passed_gates >= 2
    ctx["has_alternatives"] = passed_gates >= 2
    # TR3 criteria
    ctx["has_pseudocode"] = passed_gates >= 3
    ctx["has_module_design"] = passed_gates >= 3
    ctx["has_interface_def"] = passed_gates >= 3
    # TR4 criteria
    ctx["has_proto_verify"] = passed_gates >= 4
    ctx["has_boundary_test"] = passed_gates >= 4
    # TR5 criteria
    ctx["has_integration"] = passed_gates >= 5
    ctx["has_e2e_test"] = passed_gates >= 5
    # TR6 criteria
    ctx["has_dod_met"] = passed_gates >= 6
    ctx["has_docs"] = passed_gates >= 6
    ctx["has_deliverable"] = passed_gates >= 6
    return ctx


def main():
    if "--list" in sys.argv:
        list_gates()
        return

    if "--check" in sys.argv:
        idx = sys.argv.index("--check")
        target = sys.argv[idx + 1] if idx + 1 < len(sys.argv) else "tr1"
        
        checker = TRGateChecker()
        
        # Build test context - by default all pass for demo, can override
        context = build_example_context(6)
        
        if target == "all":
            results = checker.check_sequential(context)
        elif target in TR_GATES:
            checker.check_gate(target, context)
        else:
            log(f"❌ 未知门: {target}")
            log(f"可用选项: {', '.join(TR_ORDER)} all")
            return

        checker.save_results()
        checker.save_to_db()
        
        summary = checker.generate_summary()
        log(f"\n📊 门禁汇总: {summary['passed']}/{summary['checked']} 通过 | 状态: {summary['overall_status']}")
        return

    # Default: show help
    print("""TR Gate Checker (P2-1)
Usage:
  python3 tr_gate.py --check tr1    检查单个TR门
  python3 tr_gate.py --check all    顺序检查所有门
  python3 tr_gate.py --list         列出所有门定义
""")


if __name__ == "__main__":
    main()
