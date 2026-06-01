#!/usr/bin/env python3
"""
Hermes 任务复盘反思引擎 v1.0
==============================
来源: Reflexion + Self-Refine + CRITIC + 软件工程回顾会议方法论
用途: 每次任务完成后自动进行结构化复盘，积累经验，驱动Skill进化

核心流程:
  1. 目标回顾 — 原始任务目标 vs 实际完成
  2. 过程回溯 — 每一步的执行情况、遇到问题的根因
  3. 质量评估 — 功能/正确性/完整性/可维护性多维度审查
  4. 经验提取 — 可复用的模式、教训、改进建议
  5. 知识固化 — 输出复盘报告 + 触发Skill改进 + 写入memory

强制规则: 
  - 每个任务完成后必须触发复盘
  - 复盘报告永久保存到 reports/retrospectives/
  - 输出到状态数据库，供齿轮系统和其他模块消费

用法:
  python3 scripts/hermes_retrospect.py --session <session_id>
  python3 scripts/hermes_retrospect.py --from-wake     # 中断恢复后复盘
  python3 scripts/hermes_retrospect.py --daily-summary  # 每日汇总
"""

import json, os, sys, sqlite3, re, hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple

HERMES = Path("/home/administrator/.hermes")
STATE_DB = HERMES / "state.db"
INTEL_DB = HERMES / "intelligence.db"
ACTIVE_MEM_DB = HERMES / "active_memory.db"
REPORTS_DIR = HERMES / "reports" / "retrospectives"
SCRIPTS_DIR = HERMES / "scripts"
TZ = timezone(timedelta(hours=8))

REPORTS_DIR.mkdir(parents=True, exist_ok=True)

# ── 日志 ──
def log(msg: str):
    ts = datetime.now(TZ).strftime("%H:%M:%S")
    print(f"[{ts}] {msg}")

# ══════════════════════════════════════════════════════════════════
# 核心复盘引擎
# ══════════════════════════════════════════════════════════════════

class HermesRetrospect:
    """Hermes 任务复盘反思引擎"""

    RETRO_DIMENSIONS = {
        "functionality": {"weight": 0.25, "label": "功能性", "desc": "功能是否完整实现"},
        "correctness":  {"weight": 0.25, "label": "正确性", "desc": "结果是否经验证"},
        "completeness": {"weight": 0.20, "label": "完整性", "desc": "是否覆盖边界情况"},
        "quality":      {"weight": 0.15, "label": "质量",   "desc": "是否符合最佳实践"},
        "maintainability": {"weight": 0.15, "label": "可维护性", "desc": "是否清晰可读"},
    }

    def __init__(self):
        self.session_data = {}
        self.retro_report = {}

    def load_session(self, session_id: str) -> bool:
        """从state.db加载会话数据（支持sessions+messages多表）"""
        if not STATE_DB.exists():
            log("  ⚠️ state.db 不存在")
            return False
        try:
            conn = sqlite3.connect(str(STATE_DB))
            c = conn.cursor()
            tables = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
            
            if "sessions" in tables:
                # 先查session基本信息
                c.execute("PRAGMA table_info(sessions)")
                sess_cols = [r[1] for r in c.fetchall()]
                
                if "title" in sess_cols and "started_at" in sess_cols:
                    row = c.execute(
                        "SELECT id, title, model, started_at, input_tokens, output_tokens, message_count, tool_call_count "
                        "FROM sessions WHERE id=?", (session_id,)
                    ).fetchone()
                else:
                    row = None
                
                if row:
                    self.session_data = {
                        "id": row[0], "title": row[1] or "",
                        "model": row[2] or "",
                        "created_at": row[3] or "",
                        "input_tokens": row[4] or 0,
                        "output_tokens": row[5] or 0,
                        "message_count": row[6] or 0,
                        "tool_call_count": row[7] or 0,
                    }
                    
                    # 从messages表加载具体消息
                    if "messages" in tables:
                        msg_rows = c.execute(
                            "SELECT role, content, tool_calls, tool_name FROM messages WHERE session_id=? ORDER BY id ASC LIMIT 200",
                            (session_id,)
                        ).fetchall()
                        
                        msgs = []
                        for mr in msg_rows:
                            msgs.append({
                                "role": mr[0] or "",
                                "content": mr[1] or "",
                                "tool_calls": mr[2],
                                "tool_name": mr[3],
                            })
                        self.session_data["messages"] = json.dumps(msgs)
                        self.session_data["loaded_message_count"] = len(msgs)
                    
                    conn.close()
                    return True
            
            # 尝试conversation_history表
            if "conversation_history" in tables:
                row = c.execute("SELECT id, title, content, created_at FROM conversation_history WHERE id=? ORDER BY created_at DESC LIMIT 1", (session_id,)).fetchone()
                if row:
                    self.session_data = {
                        "id": row[0], "title": row[1],
                        "messages": row[2] if row[2] else "[]",
                        "created_at": row[3],
                    }
                    conn.close()
                    return True
            
            conn.close()
            log(f"  ⚠️ 会话 {session_id} 未找到")
            return False
        except Exception as e:
            log(f"  ⚠️ 加载会话失败: {e}")
            return False

    def load_from_existing_data(self, data: dict):
        """直接从已有的会话数据加载（供管道内联调用）"""
        self.session_data = data
        return True

    def extract_tools_and_steps(self, messages_str: str) -> List[Dict]:
        """从会话消息中提取工具调用步骤"""
        steps = []
        try:
            messages = json.loads(messages_str) if isinstance(messages_str, str) else messages_str
        except:
            messages = []
        
        if not messages:
            return steps

        step_num = 0
        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")
            tool_calls = msg.get("tool_calls", [])
            
            if role == "user" and content:
                step_num += 1
                steps.append({
                    "step": step_num, "type": "user_input",
                    "content": str(content)[:200] if content else "",
                    "status": "input",
                })
            elif role == "assistant" and tool_calls:
                parsed_tcs = tool_calls
                if isinstance(tool_calls, str):
                    try:
                        parsed_tcs = json.loads(tool_calls)
                    except:
                        parsed_tcs = []
                
                for tc in parsed_tcs:
                    step_num += 1
                    fn = tc.get("function", {}) if isinstance(tc, dict) else {}
                    step_name = fn.get("name", str(tc.get("tool_name", tc.get("name", "?")))) if fn else (tc.get("tool_name", tc.get("name", "?")) if isinstance(tc, dict) else "?")
                    fn_args = fn.get("arguments", "") if fn else ""
                    steps.append({
                        "step": step_num, "type": "tool_call",
                        "tool": step_name,
                        "args_summary": str(fn_args)[:100],
                        "status": "executed",
                    })
            elif role == "tool":
                # tool result - 评估是否出错
                is_error = False
                error_patterns = ["error", "fail", "exception", "traceback", "not found",
                                  "timeout", "denied", "refused", "❌", "失败"]
                content_lower = str(content).lower()
                for pat in error_patterns:
                    if pat in content_lower:
                        is_error = True
                        break
                if steps:
                    steps[-1]["status"] = "error" if is_error else "success"
                    steps[-1]["result_len"] = len(str(content)) if content else 0

        return steps

    def assess_quality(self, steps: List[Dict]) -> Dict[str, Any]:
        """多维度质量评估"""
        assessment = {}
        
        # 基本统计
        total_steps = len([s for s in steps if s["type"] in ("tool_call", "user_input")])
        error_steps = len([s for s in steps if s.get("status") == "error"])
        success_steps = len([s for s in steps if s.get("status") == "success"])
        
        assessment["total_steps"] = total_steps
        assessment["error_count"] = error_steps
        assessment["success_count"] = success_steps
        assessment["error_rate"] = round(error_steps / max(total_steps, 1) * 100, 1)
        
        # 五维度评分
        for dim_key, dim_info in self.RETRO_DIMENSIONS.items():
            dim_score = 0.0
            
            if dim_key == "functionality":
                # 功能性: 错误步骤少 + 有成功结果
                base = 50.0
                if success_steps > 0:
                    base += min(30.0, success_steps * 5)
                if error_steps == 0:
                    base += 20.0
                elif error_steps <= total_steps * 0.2:
                    base += 10.0
                dim_score = min(100.0, base)
            
            elif dim_key == "correctness":
                # 正确性: 基于错误率
                err_rate = assessment["error_rate"]
                if err_rate == 0:
                    dim_score = 95.0
                elif err_rate < 10:
                    dim_score = 80.0
                elif err_rate < 30:
                    dim_score = 60.0
                else:
                    dim_score = 40.0
            
            elif dim_key == "completeness":
                # 完整性: 步骤数合理 + 有工具调用多样性
                tools_used = set(s.get("tool") for s in steps if s["type"] == "tool_call" and s.get("tool"))
                diversity = len(tools_used)
                dim_score = min(100.0, 40.0 + diversity * 10 + min(30.0, total_steps * 3))
            
            elif dim_key == "quality":
                # 质量: 看是否有自我修正
                retry_count = 0
                for i in range(1, len(steps)):
                    if (steps[i]["type"] == "tool_call" and steps[i].get("status") == "error" and
                        i + 1 < len(steps) and steps[i+1]["type"] == "tool_call"):
                        retry_count += 1
                has_self_correct = "是" if retry_count > 0 else "否"
                dim_score = min(100.0, 50.0 + (15.0 if has_self_correct == "是" else 0) + min(35.0, max(0, 100 - assessment["error_rate"]) * 0.35))
                assessment["has_self_correct"] = has_self_correct
            
            elif dim_key == "maintainability":
                # 可维护性: 步骤清晰程度
                dim_score = min(100.0, 60.0 + min(40.0, max(0, 30 - assessment["error_rate"]) * 1.5))
            
            assessment[f"score_{dim_key}"] = round(dim_score, 1)
        
        # 总分（加权）
        total_score = 0.0
        for dim_key, dim_info in self.RETRO_DIMENSIONS.items():
            total_score += assessment.get(f"score_{dim_key}", 0) * dim_info["weight"]
        assessment["total_score"] = round(total_score, 1)
        assessment["quality_level"] = self._get_quality_level(assessment["total_score"])
        
        return assessment

    def _get_quality_level(self, score: float) -> str:
        if score >= 90: return "A+ 卓越"
        elif score >= 80: return "A  优秀"
        elif score >= 70: return "B  良好"
        elif score >= 60: return "C  一般"
        elif score >= 40: return "D  需改进"
        else: return "F  失败"

    def generate_retrospect(self) -> Dict[str, Any]:
        """生成完整复盘报告"""
        steps = self.extract_tools_and_steps(self.session_data.get("messages", "[]"))
        
        # 三维评估
        quality = self.assess_quality(steps)
        
        # 提取独特的工具列表
        tools_used = []
        seen_tools = set()
        for s in steps:
            t = s.get("tool", "")
            if t and t not in seen_tools:
                tools_used.append(t)
                seen_tools.add(t)
        
        # 找出关键错误
        error_patterns = {}
        for s in steps:
            if s.get("status") == "error" and s.get("tool"):
                tool_name = s["tool"]
                error_patterns[tool_name] = error_patterns.get(tool_name, 0) + 1
        
        # 错误根因分析
        root_causes = []
        top_errors = sorted(error_patterns.items(), key=lambda x: -x[1])[:3]
        for tool_name, count in top_errors:
            root_causes.append(f"{tool_name} 错误 {count}次 — 建议检查该工具的调用方式或参数格式")

        report = {
            "meta": {
                "session_id": self.session_data.get("id", ""),
                "session_title": self.session_data.get("title", ""),
                "model": self.session_data.get("model", ""),
                "created_at": self.session_data.get("created_at", ""),
                "retrospect_at": datetime.now(TZ).isoformat(),
                "tokens_used": self.session_data.get("tokens_used", 0),
            },
            "task_summary": {
                "total_steps": quality["total_steps"],
                "success_steps": quality["success_count"],
                "error_steps": quality["error_count"],
                "error_rate": quality["error_rate"],
                "tools_used": tools_used,
            },
            "quality_assessment": {
                "total_score": quality["total_score"],
                "level": quality["quality_level"],
                "dimensions": {
                    dim_key: {
                        "score": quality.get(f"score_{dim_key}", 0),
                        "label": dim_info["label"],
                        "description": dim_info["desc"]
                    }
                    for dim_key, dim_info in self.RETRO_DIMENSIONS.items()
                },
                "has_self_correct": quality.get("has_self_correct", "未知"),
            },
            "root_causes": root_causes if root_causes else ["未发现明显错误"],
            "experience": {
                "patterns": [],
                "lessons": [],
                "improvements": [],
            },
        }

        # 经验模式提取
        if quality["total_score"] >= 80:
            report["experience"]["patterns"].append("高成功率执行 — 当前方法可复用到类似任务")
        if quality["error_rate"] == 0:
            report["experience"]["patterns"].append("零错误执行 — 工作流稳定可靠")
        if quality.get("has_self_correct") == "是":
            report["experience"]["patterns"].append(f"具备自我修正能力 — 错误后能自动纠偏")
        if error_patterns:
            report["experience"]["lessons"].extend([f"根因: {rc}" for rc in root_causes])
        
        if quality["total_score"] < 60:
            report["experience"]["improvements"].append("【强烈建议】考虑重新规划任务分解方式")
        if quality["error_rate"] > 20:
            report["experience"]["improvements"].append("建议在执行关键步骤前增加预检查")
        if not quality.get("has_self_correct") != "是" and quality["error_rate"] > 10:
            report["experience"]["improvements"].append("建议增加自动错误恢复机制（如工具调用重试+参数修正）")

        self.retro_report = report
        return report

    def save_report(self) -> str:
        """保存复盘报告到文件"""
        session_id = ""
        if "meta" in self.retro_report:
            session_id = self.retro_report.get("meta", {}).get("session_id", "unknown")
        elif "session_id" in self.retro_report.get("round1_execution", {}).get("quality_assessment", {}):
            session_id = "session_unknown"
        
        safe_id = re.sub(r'[^a-zA-Z0-9_-]', '_', str(session_id)[:30])
        date_str = datetime.now(TZ).strftime("%Y%m%d")
        filename = f"retro_{date_str}_{safe_id}.json"
        filepath = REPORTS_DIR / filename
        
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(self.retro_report, f, ensure_ascii=False, indent=2)
        
        log(f"  ✅ 复盘报告已保存: {filepath}")
        return str(filepath)

    def save_to_db(self):
        """将复盘结果存入state.db，供齿轮系统消费"""
        if not self.retro_report:
            return
        try:
            conn = sqlite3.connect(str(STATE_DB))
            c = conn.cursor()
            # 确保表存在
            c.execute("""
                CREATE TABLE IF NOT EXISTS retrospectives (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT,
                    session_title TEXT,
                    total_score REAL,
                    quality_level TEXT,
                    error_rate REAL,
                    tools_used TEXT,
                    root_causes TEXT,
                    improvements TEXT,
                    retro_json TEXT,
                    created_at TEXT
                )
            """)
            r = self.retro_report
            
            # Handle both old and new report structures
            if "overall_summary" in r:
                # 三轮复盘结构
                meta = r.get("meta", {})
                task_summary = r.get("task_summary", {})
                round1 = r.get("round1_execution", {})
                quality = round1.get("quality_assessment", {})
                
                session_id = meta.get("session_id", "unknown")
                session_title = meta.get("session_title", "")
                total_score = r["overall_summary"].get("overall_score", 0)
                quality_level = r["overall_summary"].get("quality_level", "未知")
                error_rate = task_summary.get("error_rate", 0)
                tools_used = json.dumps(task_summary.get("tools_used", []), ensure_ascii=False)
                root_causes = json.dumps(r.get("round1_execution", {}).get("root_causes", []), ensure_ascii=False)
                improvements = json.dumps(r.get("round1_execution", {}).get("experience", {}).get("improvements", []), ensure_ascii=False)
            else:
                # 旧结构兼容
                meta = r.get("meta", {})
                quality = r.get("quality_assessment", {})
                session_id = meta.get("session_id", "unknown")
                session_title = meta.get("session_title", "")
                total_score = quality.get("total_score", 0)
                quality_level = quality.get("level", "未知")
                error_rate = r.get("task_summary", {}).get("error_rate", 0)
                tools_used = json.dumps(r.get("task_summary", {}).get("tools_used", []), ensure_ascii=False)
                root_causes = json.dumps(r.get("root_causes", []), ensure_ascii=False)
                improvements = json.dumps(r.get("experience", {}).get("improvements", []), ensure_ascii=False)
            
            c.execute("""
                INSERT INTO retrospectives 
                (session_id, session_title, total_score, quality_level, error_rate, tools_used, root_causes, improvements, retro_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                str(session_id)[:100],
                str(session_title)[:200] if session_title else "",
                total_score,
                str(quality_level),
                float(error_rate),
                tools_used,
                root_causes,
                improvements,
                json.dumps(r, ensure_ascii=False),
                meta.get("retrospect_at", datetime.now(TZ).isoformat()),
            ))
            conn.commit()
            conn.close()
            log(f"  ✅ 复盘结果已存入state.db")
        except Exception as e:
            log(f"  ⚠️ 存入state.db失败: {e}")

    def should_trigger_skill_evolution(self) -> bool:
        """判断是否需要触发Skill进化"""
        if not self.retro_report:
            return False
        
        # Handle both old and new report structures
        if "overall_summary" in self.retro_report:
            score = self.retro_report["overall_summary"].get("overall_score", 100)
            round1 = self.retro_report.get("round1_execution", {})
            improvements = round1.get("experience", {}).get("improvements", [])
            root_causes = round1.get("root_causes", [])
        else:
            score = self.retro_report["quality_assessment"]["total_score"]
            improvements = self.retro_report["experience"]["improvements"]
            root_causes = self.retro_report.get("root_causes", [])
        
        # 低分 + 有明确改进建议或根因时触发
        if score < 60 and (len(improvements) > 0 or len(root_causes) > 0):
            return True
        return False

    def try_invoke_skillopt(self):
        """如果复盘发现可改进点，触发SkillOpt验证"""
        if not self.should_trigger_skill_evolution():
            return
        log("  🔔 复盘触发Skill进化建议 — 检测到可改进模式")
        improvements = self.retro_report["experience"]["improvements"]
        patterns = self.retro_report["experience"]["patterns"]
        output = {
            "source": "retrospect",
            "session_id": self.retro_report["meta"]["session_id"],
            "score": self.retro_report["quality_assessment"]["total_score"],
            "patterns": patterns,
            "improvements": improvements,
            "triggered_at": datetime.now(TZ).isoformat(),
        }
        # 写入skill进化候选队列
        try:
            (HERMES / "data").mkdir(exist_ok=True)
            candidate_file = HERMES / "data" / "retro_candidates.jsonl"
            with open(candidate_file, "a") as f:
                f.write(json.dumps(output, ensure_ascii=False) + "\n")
            log(f"  📝 已写入进化候选队列: {candidate_file}")
        except Exception as e:
            log(f"  ⚠️ 写入候选队列失败: {e}")

    # ══════════════════════════════════════════════════════════════════
    # P2-3: 三轮复盘增强
    # ══════════════════════════════════════════════════════════════════

    def round2_strategy_retro(self) -> Dict[str, Any]:
        """
        第二轮：策略复盘
        评估策略是否最优——检查任务执行过程中的策略选择、工具使用效率、资源消耗合理性
        """
        log("  🔄 [第二轮] 策略复盘 — 评估策略是否最优")
        steps = self.extract_tools_and_steps(self.session_data.get("messages", "[]"))
        
        strategy_assessment = {
            "tool_efficiency": self._assess_tool_efficiency(steps),
            "execution_order": self._assess_execution_order(steps),
            "resource_usage": self._assess_resource_usage(),
            "alternative_strategies": [],
            "strategy_score": 0.0,
        }
        
        # 工具效率评分
        tools_used = [s.get("tool", "") for s in steps if s["type"] == "tool_call" and s.get("tool")]
        tool_counts = {}
        for t in tools_used:
            tool_counts[t] = tool_counts.get(t, 0) + 1
        
        efficiency_score = 100.0
        warnings = []
        
        # 检查是否有频繁失败的相同工具
        for tool_name, count in tool_counts.items():
            error_count = sum(1 for s in steps if s.get("tool") == tool_name and s.get("status") == "error")
            if count > 5:
                error_rate_val = error_count / count
                if error_rate_val > 0.3:
                    warnings.append(f"{tool_name} 调用{count}次，错误率{error_rate_val:.0%}，考虑替换方案")
                    efficiency_score -= 15
        
        # 检查步骤冗余
        if len(tools_used) > 0:
            unique_tools = set(tools_used)
            if len(tools_used) > len(unique_tools) * 3:
                warnings.append(f"存在冗余调用：总调用{len(tools_used)}次，仅{len(unique_tools)}种工具")
                efficiency_score -= 10
        
        strategy_assessment["tool_efficiency"] = {
            "score": max(0, efficiency_score),
            "tools_used": list(tool_counts.items()),
            "warnings": warnings,
            "assessment": "高效" if efficiency_score >= 80 else ("一般" if efficiency_score >= 60 else "低效"),
        }
        
        # 执行顺序评估
        order_score = 80.0
        order_warnings = []
        
        # 检查是否先探索后执行（良好策略的特征）
        user_inputs = [s for s in steps if s["type"] == "user_input"]
        tool_calls = [s for s in steps if s["type"] == "tool_call"]
        
        if user_inputs and tool_calls:
            # 检查最开始的步骤是否是探索性操作
            first_tool = tool_calls[0].get("tool", "") if tool_calls else ""
            if first_tool in ("read_file", "search_files", "search"):
                order_score += 10  # 先探索后执行是好的
            elif first_tool in ("write_file", "patch", "terminal"):
                order_score -= 5  # 没先探索就直接执行可能有问题
                order_warnings.append("未先进行信息探索就执行操作，建议先读后写")
        
        # 检查是否有错误后重试的良好模式
        retry_patterns = 0
        for i in range(1, len(steps)):
            if steps[i]["type"] == "tool_call" and steps[i].get("status") == "success":
                if i > 0 and steps[i-1].get("status") == "error":
                    retry_patterns += 1
        if retry_patterns > 0:
            order_score += 5
            strategy_assessment["has_retry_pattern"] = True
        
        strategy_assessment["execution_order"] = {
            "score": min(100, order_score),
            "warnings": order_warnings,
            "retry_patterns": retry_patterns,
            "assessment": "合理" if order_score >= 70 else ("需优化" if order_score >= 50 else "不合理"),
        }
        
        # 资源使用评估
        tokens_used = self.session_data.get("tokens_used", 0)
        msg_count = self.session_data.get("message_count", 0) or self.session_data.get("loaded_message_count", 0)
        resource_score = 80.0
        resource_warnings = []
        
        if tokens_used and tokens_used > 100000:
            resource_warnings.append(f"Token消耗较高 ({tokens_used})，考虑精简提示")
            resource_score -= 15
        if msg_count and msg_count > 100:
            resource_warnings.append(f"消息轮次较多 ({msg_count})，考虑合并步骤")
            resource_score -= 10
        
        strategy_assessment["resource_usage"] = {
            "score": min(100, resource_score),
            "tokens_used": tokens_used,
            "message_count": msg_count,
            "warnings": resource_warnings,
            "assessment": "合理" if resource_score >= 70 else "偏高",
        }
        
        # 综合策略评分
        scores = [
            strategy_assessment["tool_efficiency"]["score"],
            strategy_assessment["execution_order"]["score"],
            strategy_assessment["resource_usage"]["score"],
        ]
        strategy_assessment["strategy_score"] = round(sum(scores) / len(scores), 1)
        
        # 生成替代策略建议
        all_warnings = (warnings + order_warnings + resource_warnings)
        if all_warnings:
            strategy_assessment["alternative_strategies"] = [
                f"替代方案: {w}" for w in all_warnings[:3]
            ]
        
        log(f"  📊 策略评分: {strategy_assessment['strategy_score']}")
        if all_warnings:
            for w in all_warnings[:3]:
                log(f"     ⚠️ {w}")
        
        return strategy_assessment

    def _assess_tool_efficiency(self, steps: List[Dict]) -> Dict[str, Any]:
        """Helper to assess tool efficiency"""
        # Already handled in round2_strategy_retro
        return {}

    def _assess_execution_order(self, steps: List[Dict]) -> Dict[str, Any]:
        """Helper to assess execution order"""
        return {}

    def _assess_resource_usage(self) -> Dict[str, Any]:
        """Helper to assess resource usage"""
        return {}

    def round3_metacognition_retro(self) -> Dict[str, Any]:
        """
        第三轮：元认知复盘
        找出重复错误模式，从历史复盘中学习，识别系统性问题
        """
        log("  🔄 [第三轮] 元认知复盘 — 找出重复错误模式")
        
        # 从state.db加载近期复盘记录（过去7天）
        recent_retros = self._load_recent_retros(days=7)
        
        meta_assessment = {
            "repeated_error_patterns": [],
            "historical_comparison": {},
            "systemic_issues": [],
            "improvement_trend": "",
            "meta_score": 0.0,
        }
        
        # 分析重复错误模式
        if recent_retros:
            # 聚合所有错误模式
            all_root_causes = []
            all_scores = []
            for retro in recent_retros:
                causes = retro.get("root_causes", [])
                if isinstance(causes, str):
                    try:
                        causes = json.loads(causes)
                    except:
                        causes = [causes]
                all_root_causes.extend(causes)
                
                score = retro.get("total_score", 0)
                if isinstance(score, (int, float)):
                    all_scores.append(score)
            
            # 统计重复出现的错误
            error_freq = {}
            for cause in all_root_causes:
                if isinstance(cause, str):
                    # 提取关键工具名
                    for tool_name in ["terminal", "write_file", "patch", "read_file", "search_files"]:
                        if tool_name in cause:
                            error_freq[tool_name] = error_freq.get(tool_name, 0) + 1
            
            repeated = [(tool, count) for tool, count in error_freq.items() if count >= 2]
            if repeated:
                meta_assessment["repeated_error_patterns"] = [
                    f"{tool} 重复错误 {count}次" for tool, count in sorted(repeated, key=lambda x: -x[1])
                ]
                meta_assessment["systemic_issues"].append(
                    "存在系统性重复错误，建议检查相关工具的调用规范和参数传递方式"
                )
            
            # 趋势分析
            if len(all_scores) >= 2:
                trend = "上升" if all_scores[-1] > all_scores[0] else ("下降" if all_scores[-1] < all_scores[0] else "平稳")
                meta_assessment["improvement_trend"] = trend
                
                avg_score = round(sum(all_scores) / len(all_scores), 1)
                meta_assessment["historical_comparison"] = {
                    "total_retros_analyzed": len(recent_retros),
                    "current_score": self.retro_report["quality_assessment"]["total_score"],
                    "historical_avg": avg_score,
                    "trend": trend,
                    "note": f"历史平均分 {avg_score}，当前分 {self.retro_report['quality_assessment']['total_score']}，趋势{trend}",
                }
                
                if trend == "下降":
                    meta_assessment["systemic_issues"].append("质量评分呈下降趋势，建议重新审视整体工作流程")
        
        # 检查当前会话自身的模式
        steps = self.extract_tools_and_steps(self.session_data.get("messages", "[]"))
        tool_names = [s.get("tool", "") for s in steps if s["type"] == "tool_call" and s.get("tool")]
        if len(tool_names) >= 3:
            # 检查是否反复使用同一工具
            from collections import Counter
            tool_counter = Counter(tool_names)
            most_common = tool_counter.most_common(1)
            if most_common and most_common[0][1] > len(tool_names) * 0.5:
                meta_assessment["systemic_issues"].append(
                    f"过度依赖单一工具 ({most_common[0][0]} 使用 {most_common[0][1]}次/{len(tool_names)}次)，建议多元化工具使用"
                )
        
        # 综合元认知评分
        base_score = 70.0
        if meta_assessment["repeated_error_patterns"]:
            base_score -= len(meta_assessment["repeated_error_patterns"]) * 10
        if meta_assessment["systemic_issues"]:
            base_score -= len(meta_assessment["systemic_issues"]) * 5
        if meta_assessment.get("improvement_trend") == "上升":
            base_score += 10
        elif meta_assessment.get("improvement_trend") == "下降":
            base_score -= 10
        
        meta_assessment["meta_score"] = round(max(0, min(100, base_score)), 1)
        
        log(f"  📊 元认知评分: {meta_assessment['meta_score']}")
        if meta_assessment["repeated_error_patterns"]:
            for p in meta_assessment["repeated_error_patterns"]:
                log(f"     🔄 {p}")
        if meta_assessment.get("improvement_trend"):
            log(f"     📈 趋势: {meta_assessment['improvement_trend']}")
        
        return meta_assessment

    def _load_recent_retros(self, days: int = 7) -> List[Dict]:
        """Load recent retrospectives from state.db"""
        retros = []
        try:
            conn = sqlite3.connect(str(STATE_DB))
            c = conn.cursor()
            cutoff = (datetime.now(TZ) - timedelta(days=days)).isoformat()
            rows = c.execute("""
                SELECT session_id, total_score, quality_level, error_rate, root_causes, improvements, created_at
                FROM retrospectives
                WHERE created_at >= ?
                ORDER BY created_at DESC
                LIMIT 50
            """, (cutoff,)).fetchall()
            conn.close()
            
            for r in rows:
                retros.append({
                    "session_id": r[0],
                    "total_score": r[1],
                    "quality_level": r[2],
                    "error_rate": r[3],
                    "root_causes": r[4],
                    "improvements": r[5],
                    "created_at": r[6],
                })
        except Exception as e:
            log(f"  ⚠️ 加载历史复盘记录失败: {e}")
        
        return retros

    def generate_three_round_report(self) -> Dict[str, Any]:
        """生成三轮复盘完整报告"""
        # Round 1: 执行复盘 (已有)
        execution_report = self.retro_report
        
        log("\n" + "-" * 50)
        log("三轮复盘开始")
        log("-" * 50)
        log(f"  [第一轮] 执行复盘 — 已完成 (评分: {execution_report['quality_assessment']['total_score']})")
        
        # Round 2: 策略复盘
        strategy_report = self.round2_strategy_retro()
        
        # Round 3: 元认知复盘
        meta_report = self.round3_metacognition_retro()
        
        # 合并报告
        full_report = {
            "meta": execution_report["meta"],
            "task_summary": execution_report["task_summary"],
            "round1_execution": {
                "quality_assessment": execution_report["quality_assessment"],
                "root_causes": execution_report["root_causes"],
                "experience": execution_report["experience"],
            },
            "round2_strategy": strategy_report,
            "round3_metacognition": meta_report,
            "overall_summary": {
                "execution_score": execution_report["quality_assessment"]["total_score"],
                "strategy_score": strategy_report["strategy_score"],
                "meta_score": meta_report["meta_score"],
                "overall_score": round(
                    execution_report["quality_assessment"]["total_score"] * 0.4
                    + strategy_report["strategy_score"] * 0.35
                    + meta_report["meta_score"] * 0.25, 1
                ),
                "num_rounds": 3,
                "quality_level": execution_report["quality_assessment"]["level"],
            },
            "three_round_report_at": datetime.now(TZ).isoformat(),
        }
        
        self.retro_report = full_report
        
        # 输出三轮汇总
        log("\n" + "=" * 50)
        log("三轮复盘报告")
        log("=" * 50)
        o = full_report["overall_summary"]
        log(f"  🎯 执行评分: {o['execution_score']}")
        log(f"  🧠 策略评分: {o['strategy_score']}")
        log(f"  🔮 元认知评分: {o['meta_score']}")
        log(f"  📊 综合评分: {o['overall_score']}")
        log("=" * 50)
        
        return full_report

    def run(self, session_id: str = None, session_data: dict = None) -> Dict[str, Any]:
        """一站式执行复盘全流程（含三轮复盘增强）"""
        log("=" * 50)
        log("Hermes 复盘反思引擎启动")
        log("=" * 50)

        if session_data:
            self.load_from_existing_data(session_data)
        elif session_id:
            if not self.load_session(session_id):
                log("❌ 无法加载会话，跳过复盘")
                return {"error": "session_not_found"}
        else:
            log("❌ 未提供会话ID或数据")
            return {"error": "no_input"}

        # 生成基础报告（Round 1）
        self.generate_retrospect()
        
        # 执行三轮复盘增强
        self.generate_three_round_report()
        
        # 保存
        filepath = self.save_report()
        self.save_to_db()
        self.try_invoke_skillopt()

        score = self.retro_report["overall_summary"]["overall_score"]
        level = self.retro_report["overall_summary"]["quality_level"]
        log(f"📊 复盘完成 - 综合评分: {score} ({level})")
        log(f"   报告: {filepath}")

        return self.retro_report

# ══════════════════════════════════════════════════════════════════
# 每日汇总模式
# ══════════════════════════════════════════════════════════════════

def daily_summary() -> Dict[str, Any]:
    """汇总当天所有复盘记录，生成趋势分析"""
    log("📊 每日复盘汇总 — 分析当天所有复盘记录")
    
    today = datetime.now(TZ).strftime("%Y%m%d")
    
    # 从state.db读取当天复盘
    all_retros = []
    try:
        conn = sqlite3.connect(str(STATE_DB))
        c = conn.cursor()
        rows = c.execute("""
            SELECT session_title, total_score, quality_level, error_rate, tools_used, created_at
            FROM retrospectives 
            WHERE created_at >= ?
            ORDER BY created_at DESC
        """, (datetime.now(TZ).strftime("%Y-%m-%d"),)).fetchall()
        conn.close()
        
        for r in rows:
            all_retros.append({
                "title": r[0], "score": r[1], "level": r[2],
                "error_rate": r[3], "tools": r[4], "time": r[5],
            })
    except Exception as e:
        log(f"  ⚠️ 读取复盘记录失败: {e}")
    
    if not all_retros:
        log("  当天无复盘记录")
        return {"date": today, "total": 0, "summary": "无记录"}
    
    # 统计
    scores = [r["score"] for r in all_retros]
    avg_score = round(sum(scores) / len(scores), 1) if scores else 0
    min_score = min(scores) if scores else 0
    max_score = max(scores) if scores else 0
    
    # 错误模式聚合
    all_improvements = []
    
    # 写入每日汇总文件
    summary = {
        "date": today,
        "total_retros": len(all_retros),
        "avg_score": avg_score,
        "min_score": min_score,
        "max_score": max_score,
        "high_quality": len([r for r in all_retros if r["score"] >= 80]),
        "needs_improvement": len([r for r in all_retros if r["score"] < 60]),
        "best_session": max(all_retros, key=lambda x: x["score"]) if all_retros else None,
        "worst_session": min(all_retros, key=lambda x: x["score"]) if all_retros else None,
    }
    
    # ── 趋势分析 ──
    trend = {"daily_scores": [], "seven_day_avg": None, "direction": "stable", "insights": []}
    if all_retros:
        trend["daily_scores"] = [{"session": r["title"], "score": r["score"], "time": r["time"]} for r in all_retros]
        trend["avg_score"] = avg_score
        trend["high_count"] = summary["high_quality"]
        trend["low_count"] = summary["needs_improvement"]
        if avg_score >= 80:
            trend["direction"] = "good"
            trend["insights"].append("整体质量较高，继续保持")
        elif avg_score >= 60:
            trend["direction"] = "fair"
            trend["insights"].append("质量中等，部分任务需改进")
        else:
            trend["direction"] = "poor"
            trend["insights"].append("质量偏低，建议检查工作流程")
        if summary["needs_improvement"] > summary["high_quality"]:
            trend["insights"].append("低分任务多于高质量任务，急需改进")
    
    summary["trend"] = trend
    
    summary_path = REPORTS_DIR / f"daily_summary_{today}.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    
    log(f"✅ 每日汇总完成 - {len(all_retros)}个复盘, 平均分{avg_score}")
    log(f"   最高: {max_score} | 最低: {min_score} | 高质量: {summary['high_quality']}个")
    log(f"   汇总文件: {summary_path}")
    
    return summary

# ══════════════════════════════════════════════════════════════════
# 中断恢复复盘
# ══════════════════════════════════════════════════════════════════

def resume_retrospect():
    """从中断状态恢复后自动复盘"""
    log("🔄 中断恢复复盘 — 检查上次中断的任务")
    
    # 读取wake_guide
    wake_guide = HERMES / "reports" / "wake_guide.json"
    if not wake_guide.exists():
        log("  无wake_guide，跳过")
        return {"status": "skipped"}
    
    try:
        with open(wake_guide) as f:
            guide = json.load(f)
        
        interrupted_task = guide.get("interrupted_task")
        if not interrupted_task:
            log("  无中断任务，跳过")
            return {"status": "no_interrupted"}
        
        log(f"  发现中断任务: {interrupted_task}")
        
        # 创建恢复复盘报告
        retro = {
            "meta": {
                "session_id": f"resume_{datetime.now(TZ).strftime('%Y%m%d_%H%M%S')}",
                "session_title": f"中断恢复: {str(interrupted_task)[:100]}",
                "retrospect_at": datetime.now(TZ).isoformat(),
                "type": "interruption_recovery",
            },
            "task_summary": {
                "interrupted_task": str(interrupted_task)[:200],
                "next_action": guide.get("next_action", "未知"),
                "reason": "任务中断后自动恢复",
            },
            "quality_assessment": {
                "total_score": 50.0,
                "level": "C 一般",
                "note": "中断恢复复盘 — 任务已续跑",
            },
            "experience": {
                "lessons": ["任务执行过程中被中断，已通过齿轮系统自动恢复"],
                "improvements": ["建议在关键节点保存状态，减少中断恢复的信息丢失"],
            },
        }
        
        filepath = REPORTS_DIR / f"retro_resume_{datetime.now(TZ).strftime('%Y%m%d_%H%M%S')}.json"
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(retro, f, ensure_ascii=False, indent=2)
        
        log(f"  ✅ 中断复盘已保存: {filepath}")
        return retro
        
    except Exception as e:
        log(f"  ⚠️ 中断复盘失败: {e}")
        return {"error": str(e)}


# ══════════════════════════════════════════════════════════════════
# 内联接口（供其他模块直接调用）
# ══════════════════════════════════════════════════════════════════

def inline_retrospect(session_data: dict) -> Dict[str, Any]:
    """内联复盘 — 供production_loop或其他模块直接调用"""
    engine = HermesRetrospect()
    return engine.run(session_data=session_data)


def inline_after_task(task_info: dict):
    """任务完成后自动复盘（供齿轮系统集成）"""
    engine = HermesRetrospect()
    # 构造会话数据
    session_data = {
        "id": task_info.get("task_id", "task_auto"),
        "title": task_info.get("title", ""),
        "messages": json.dumps(task_info.get("steps", [])),
        "model": task_info.get("model", ""),
        "created_at": task_info.get("started_at", ""),
        "tokens_used": task_info.get("tokens_used", 0),
    }
    engine.run(session_data=session_data)


# ══════════════════════════════════════════════════════════════════
# 命令行入口
# ══════════════════════════════════════════════════════════════════

def main():
    if "--daily-summary" in sys.argv:
        daily_summary()
    elif "--from-wake" in sys.argv:
        resume_retrospect()
    elif "--session" in sys.argv:
        idx = sys.argv.index("--session")
        if idx + 1 < len(sys.argv):
            session_id = sys.argv[idx + 1]
            engine = HermesRetrospect()
            engine.run(session_id=session_id)
        else:
            print("用法: --session <session_id>")
    elif "--check-evolution" in sys.argv:
        # 检查候选队列并触发SkillOpt
        candidate_file = HERMES / "data" / "retro_candidates.jsonl"
        if candidate_file.exists():
            with open(candidate_file) as f:
                lines = f.readlines()
            print(f"📝 进化候选队列: {len(lines)} 条")
            for line in lines[-5:]:
                d = json.loads(line)
                print(f"  [{d.get('score', '?')}] {d.get('source', '?')}: {d.get('improvements', [])[:1]}")
        else:
            print("📝 进化候选队列为空")
    else:
        print("""用法: python3 scripts/hermes_retrospect.py [选项]

选项:
  --session <id>       对指定会话进行复盘
  --from-wake          中断恢复复盘
  --daily-summary      每日汇总
  --check-evolution    检查进化候选队列
  (无参数)              显示帮助
""")

if __name__ == "__main__":
    main()
