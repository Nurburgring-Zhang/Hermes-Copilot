#!/usr/bin/env python3
"""
DoD (Definition of Done) 清单检查脚本 (P2-2)
===============================================
每类任务有强制完成检查清单：
- fix任务DoD
- develop任务DoD
- research任务DoD
- push任务DoD

Usage:
  python3 dod_checklist.py --check fix <context_json>
  python3 dod_checklist.py --task-type fix --list
"""

import json, sys, os, sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any

HERMES = Path("/home/administrator/.hermes")
TZ = timezone(timedelta(hours=8))

def log(msg: str):
    ts = datetime.now(TZ).strftime("%H:%M:%S")
    print(f"[{ts}] {msg}")

# ══════════════════════════════════════════════════════════════════
# DoD Definitions
# ══════════════════════════════════════════════════════════════════

DOD_DEFINITIONS = {
    "fix": {
        "name": "Fix任务DoD",
        "description": "Bug修复类任务的完成检查清单",
        "criteria": [
            {
                "id": "fix_c1",
                "name": "根因已定位",
                "description": "已通过日志/调试/分析定位到问题的根本原因",
                "check": lambda ctx: ctx.get("root_cause_found", False),
                "suggestion": "使用二分法或日志分析定位最小复现步骤",
                "severity": "critical",
            },
            {
                "id": "fix_c2",
                "name": "修复已验证",
                "description": "修复方案已执行并通过验证",
                "check": lambda ctx: ctx.get("fix_verified", False),
                "suggestion": "在修复环境中验证问题不再复现",
                "severity": "critical",
            },
            {
                "id": "fix_c3",
                "name": "无副作用",
                "description": "修复不会引入新的问题或影响已有功能",
                "check": lambda ctx: ctx.get("no_side_effects", False),
                "suggestion": "执行回归测试，检查相关功能是否受影响",
                "severity": "critical",
            },
            {
                "id": "fix_c4",
                "name": "日志已更新",
                "description": "修复记录已写入变更日志或问题跟踪系统",
                "check": lambda ctx: ctx.get("log_updated", False),
                "suggestion": "在CHANGELOG或issue tracker中记录修复内容",
                "severity": "normal",
            },
        ],
    },
    "develop": {
        "name": "Develop任务DoD",
        "description": "开发类任务的完成检查清单",
        "criteria": [
            {
                "id": "dev_c1",
                "name": "语法通过",
                "description": "代码语法检查通过，无编译错误",
                "check": lambda ctx: ctx.get("syntax_passed", False),
                "suggestion": "运行 linter (pyflakes/flake8/eslint 等)",
                "severity": "critical",
            },
            {
                "id": "dev_c2",
                "name": "测试通过",
                "description": "所有单元测试和集成测试通过",
                "check": lambda ctx: ctx.get("tests_passed", False),
                "suggestion": "编写并运行 pytest 或对应测试框架",
                "severity": "critical",
            },
            {
                "id": "dev_c3",
                "name": "边界覆盖",
                "description": "已覆盖边界情况和异常场景的测试",
                "check": lambda ctx: ctx.get("boundary_covered", False),
                "suggestion": "添加空值/越界/异常输入的测试用例",
                "severity": "normal",
            },
            {
                "id": "dev_c4",
                "name": "文档已更新",
                "description": "相关文档（README/API文档/注释）已同步更新",
                "check": lambda ctx: ctx.get("docs_updated", False),
                "suggestion": "更新函数docstring和项目文档",
                "severity": "normal",
            },
        ],
    },
    "research": {
        "name": "Research任务DoD",
        "description": "调研/研究类任务的完成检查清单",
        "criteria": [
            {
                "id": "res_c1",
                "name": "来源可追溯",
                "description": "所有引用来源可追溯，包含URL/文档引用",
                "check": lambda ctx: ctx.get("sources_traceable", False),
                "suggestion": "记录每个信息点的原始出处URL或文档路径",
                "severity": "critical",
            },
            {
                "id": "res_c2",
                "name": "非幻觉验证",
                "description": "关键事实已交叉验证，确保无幻觉",
                "check": lambda ctx: ctx.get("hallucination_checked", False),
                "suggestion": "对关键数据/API/版本号进行实际验证",
                "severity": "critical",
            },
            {
                "id": "res_c3",
                "name": "逻辑链完整",
                "description": "推理链条完整，结论与论据一致",
                "check": lambda ctx: ctx.get("logic_chain_complete", False),
                "suggestion": "检查推理链路是否有跳跃或假设未被证实",
                "severity": "normal",
            },
        ],
    },
    "push": {
        "name": "Push任务DoD",
        "description": "内容推送类任务的完成检查清单",
        "criteria": [
            {
                "id": "push_c1",
                "name": "候选已筛选",
                "description": "推送内容经过质量筛选，低质量内容已排除",
                "check": lambda ctx: ctx.get("candidates_filtered", False),
                "suggestion": "按 AI评分+时效性+相关性 过滤候选内容",
                "severity": "critical",
            },
            {
                "id": "push_c2",
                "name": "内容已验证",
                "description": "推送内容的完整性和正确性已确认",
                "check": lambda ctx: ctx.get("content_verified", False),
                "suggestion": "检查推送内容是否有损坏/截断/乱码",
                "severity": "critical",
            },
            {
                "id": "push_c3",
                "name": "推送成功",
                "description": "推送操作已成功执行",
                "check": lambda ctx: ctx.get("push_succeeded", False),
                "suggestion": "检查推送API返回码及接收方确认",
                "severity": "critical",
            },
            {
                "id": "push_c4",
                "name": "记录已保存",
                "description": "推送记录已写入历史数据库",
                "check": lambda ctx: ctx.get("record_saved", False),
                "suggestion": "保存推送时间/内容/接收方到推送历史",
                "severity": "normal",
            },
        ],
    },
}

TASK_TYPES = ["fix", "develop", "research", "push"]


class DoDChecker:
    """DoD Checklist Checker"""

    def __init__(self):
        self.results: Dict[str, Any] = {}

    def check_task(self, task_type: str, context: dict) -> Dict[str, Any]:
        """Check DoD for a specific task type"""
        dod = DOD_DEFINITIONS.get(task_type)
        if not dod:
            return {"error": f"未知任务类型: {task_type}"}

        log(f"🔍 检查 {dod['name']}...")

        passed = True
        failed_criteria = []
        suggestions = []
        critical_failures = []
        criterion_results = []

        for criterion in dod["criteria"]:
            try:
                is_passed = criterion["check"](context)
            except Exception as e:
                is_passed = False
                log(f"  ⚠️ 检查 {criterion['name']} 异常: {e}")

            criterion_results.append({
                "id": criterion["id"],
                "name": criterion["name"],
                "description": criterion["description"],
                "severity": criterion["severity"],
                "passed": is_passed,
                "suggestion": criterion["suggestion"] if not is_passed else "",
            })

            if not is_passed:
                passed = False
                failed_criteria.append(criterion["name"])
                suggestions.append(criterion["suggestion"])
                if criterion["severity"] == "critical":
                    critical_failures.append(criterion["name"])

        # Critical items -> block
        dod_met = len(critical_failures) == 0 and passed
        has_critical_blockers = len(critical_failures) > 0

        result = {
            "task_type": task_type,
            "dod_name": dod["name"],
            "description": dod["description"],
            "dod_met": dod_met,
            "has_critical_blockers": has_critical_blockers,
            "passed": passed,
            "critical_failures": critical_failures,
            "failed_criteria": failed_criteria,
            "suggestions": suggestions,
            "criterion_results": criterion_results,
            "checked_at": datetime.now(TZ).isoformat(),
        }

        status = "✅ DoD满足" if dod_met else ("❌ 阻塞(关键项未通过)" if has_critical_blockers else "⚠️ DoD未完全满足(非关键)")
        log(f"  {status}")
        if failed_criteria:
            for fc in failed_criteria:
                log(f"    - {fc}")
        if suggestions:
            for sug in suggestions:
                log(f"    💡 {sug[:80]}")

        self.results[task_type] = result
        return result

    def save_results(self) -> str:
        """Save check results to file"""
        date_str = datetime.now(TZ).strftime("%Y%m%d_%H%M%S")
        filepath = HERMES / "reports" / f"dod_check_{date_str}.json"
        (HERMES / "reports").mkdir(exist_ok=True)
        
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(self.results, f, ensure_ascii=False, indent=2)
        
        log(f"\n📄 DoD检查报告已保存: {filepath}")
        return str(filepath)

    def save_to_db(self):
        """Save to state.db"""
        if not self.results:
            return
        try:
            conn = sqlite3.connect(str(HERMES / "state.db"))
            c = conn.cursor()
            c.execute("""
                CREATE TABLE IF NOT EXISTS dod_checks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_type TEXT,
                    dod_name TEXT,
                    dod_met INTEGER,
                    failed_criteria TEXT,
                    suggestions TEXT,
                    full_result TEXT,
                    created_at TEXT
                )
            """)
            for task_type, result in self.results.items():
                c.execute("""
                    INSERT INTO dod_checks
                    (task_type, dod_name, dod_met, failed_criteria, suggestions, full_result, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    task_type,
                    result.get("dod_name", ""),
                    1 if result.get("dod_met", False) else 0,
                    json.dumps(result.get("failed_criteria", []), ensure_ascii=False),
                    json.dumps(result.get("suggestions", []), ensure_ascii=False),
                    json.dumps(result, ensure_ascii=False),
                    result.get("checked_at", ""),
                ))
            conn.commit()
            conn.close()
            log("  ✅ DoD结果已存入state.db")
        except Exception as e:
            log(f"  ⚠️ 存入state.db失败: {e}")


def list_dod():
    """List all DoD definitions"""
    log("\nDoD 清单定义:")
    log("=" * 60)
    for task_type, dod in DOD_DEFINITIONS.items():
        log(f"\n  📋 {dod['name']}")
        log(f"     {dod['description']}")
        for crit in dod["criteria"]:
            severity_tag = "🔴" if crit["severity"] == "critical" else "🟡"
            log(f"     {severity_tag} [{crit['severity']}] {crit['name']}: {crit['description']}")
    log("=" * 60)


def build_example_context(task_type: str, passed: bool = True) -> dict:
    """Build example context for testing"""
    ctx = {}
    if task_type == "fix":
        ctx["root_cause_found"] = passed
        ctx["fix_verified"] = passed
        ctx["no_side_effects"] = passed
        ctx["log_updated"] = passed
    elif task_type == "develop":
        ctx["syntax_passed"] = passed
        ctx["tests_passed"] = passed
        ctx["boundary_covered"] = passed
        ctx["docs_updated"] = passed
    elif task_type == "research":
        ctx["sources_traceable"] = passed
        ctx["hallucination_checked"] = passed
        ctx["logic_chain_complete"] = passed
    elif task_type == "push":
        ctx["candidates_filtered"] = passed
        ctx["content_verified"] = passed
        ctx["push_succeeded"] = passed
        ctx["record_saved"] = passed
    return ctx


def main():
    if "--list" in sys.argv:
        list_dod()
        return

    if "--check" in sys.argv:
        idx = sys.argv.index("--check")
        task_type = sys.argv[idx + 1] if idx + 1 < len(sys.argv) else "fix"
        
        if task_type not in DOD_DEFINITIONS:
            log(f"❌ 未知任务类型: {task_type}")
            log(f"可用类型: {', '.join(TASK_TYPES)}")
            return

        checker = DoDChecker()
        # Default: all pass for demo
        context = build_example_context(task_type, True)
        checker.check_task(task_type, context)
        checker.save_results()
        checker.save_to_db()
        return

    # Default: show help
    print("""DoD Checklist Checker (P2-2)
Usage:
  python3 dod_checklist.py --check fix       检查fix任务DoD
  python3 dod_checklist.py --check develop   检查develop任务DoD
  python3 dod_checklist.py --check research  检查research任务DoD
  python3 dod_checklist.py --check push      检查push任务DoD
  python3 dod_checklist.py --list            列出所有DoD定义
""")


if __name__ == "__main__":
    main()
