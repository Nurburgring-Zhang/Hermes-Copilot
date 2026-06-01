#!/usr/bin/env python3
"""
经验引擎 - Experience Extractor (P3-3)
=========================================
功能：每次任务后自动从执行轨迹提取可复用经验，写入候选Skill池
- 提取轨迹→抽象模板→参数化→验证→入库
- 提取负面经验→写入"注意事项"库

Usage:
  python3 experience_extractor.py --from-trajectory <trajectory_file>
  python3 experience_extractor.py --from-retro <retro_file>
  python3 experience_extractor.py --from-session <session_id>
  python3 experience_extractor.py --list-pool
  python3 experience_extractor.py --list-caveats
"""

import json, sys, os, sqlite3, hashlib, uuid, re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple

HERMES = Path("/home/administrator/.hermes")
STATE_DB = HERMES / "state.db"
INTEL_DB = HERMES / "intelligence.db"
ACTIVE_MEM_DB = HERMES / "active_memory.db"
TZ = timezone(timedelta(hours=8))

def log(msg: str):
    ts = datetime.now(TZ).strftime("%H:%M:%S")
    print(f"[{ts}] {msg}")


class ExperienceExtractor:
    """
    经验引擎
    从执行轨迹提取可复用经验，写入Skill候选池
    """

    def __init__(self):
        self.extracted_experiences = []
        self.extracted_caveats = []
        self._pattern_counter = {}  # 用于追踪重复模式

    def _check_skill_proposals(self, validated: List[Dict], context: dict):
        """检查是否有连续3次以上相同模式成功，输出skill创建建议"""
        for exp in validated:
            pattern = exp.get("pattern", "unknown")
            if pattern not in self._pattern_counter:
                self._pattern_counter[pattern] = {"count": 0, "first_seen": None, "last_seen": None, "confidence": 0}
            counter = self._pattern_counter[pattern]
            counter["count"] += 1
            if counter["first_seen"] is None:
                counter["first_seen"] = datetime.now(TZ).isoformat()
            counter["last_seen"] = datetime.now(TZ).isoformat()
            counter["confidence"] = max(counter["confidence"], exp.get("confidence", 0))

            if counter["count"] >= 3:
                # 连续3次以上相同模式成功 → 输出skill创建建议
                self._output_skill_proposal(pattern, exp, counter)

    def _output_skill_proposal(self, pattern: str, exp: dict, counter: dict):
        """输出skill创建建议到reports/skill_proposals.json"""
        proposal = {
            "ts": datetime.now(TZ).isoformat(),
            "pattern": pattern,
            "description": exp.get("description", ""),
            "confidence": counter["confidence"],
            "occurrences": counter["count"],
            "first_seen": counter["first_seen"],
            "last_seen": counter["last_seen"],
            "steps": exp.get("parameterized_steps", []),
            "parameters": exp.get("parameters", []),
            "recommendation": f"建议基于'{pattern}'模式创建Skill。该模式已成功出现{counter['count']}次，置信度{counter['confidence']}。",
            "status": "proposed",
        }
        
        proposals_file = HERMES / "reports" / "skill_proposals.json"
        proposals_file.parent.mkdir(parents=True, exist_ok=True)
        
        existing = []
        if proposals_file.exists():
            try:
                with open(proposals_file) as f:
                    existing = json.load(f)
            except (json.JSONDecodeError, Exception):
                existing = []
        
        # 避免重复
        for e in existing:
            if e.get("pattern") == pattern:
                # 更新已有记录
                e.update(proposal)
                break
        else:
            existing.append(proposal)
        
        with open(proposals_file, "w", encoding="utf-8") as f:
            json.dump(existing, f, ensure_ascii=False, indent=2)
        
        log(f"  📋 Skill创建建议已输出: {pattern} ({counter['count']}次出现)")

    def extract_from_steps(self, steps: List[Dict], context: dict = None) -> Dict[str, Any]:
        """
        从执行步骤中提取经验
        流程: 提取轨迹→抽象模板→参数化→验证→入库
        """
        log("🔍 开始提取执行经验...")
        
        context = context or {}
        
        # 1. 提取轨迹 - 分析步骤序列
        trajectory = self._extract_trajectory(steps)
        log(f"  📋 轨迹分析: {len(trajectory)} 个步骤")
        
        # 2. 抽象模板 - 从具体步骤中抽象出通用模式
        templates = self._abstract_templates(trajectory)
        log(f"  📝 抽象模板: 生成 {len(templates)} 个模板")
        
        # 3. 参数化 - 用占位符替换具体参数
        parameterized = self._parameterize_templates(templates)
        log(f"  🔧 参数化: {len(parameterized)} 个模板已完成参数化")
        
        # 4. 验证 - 检查模板的有效性和完整性
        validated = self._validate_experiences(parameterized)
        log(f"  ✅ 验证: {len(validated)}/{len(parameterized)} 通过验证")
        
        # 5. 入库
        stored = self._store_experiences(validated, context)
        log(f"  💾 入库: {stored} 条经验已写入数据库")
        
        # 自动检查skill创建建议
        self._check_skill_proposals(validated, context)
        
        # 负面经验提取
        caveats = self._extract_caveats(steps, context)
        if caveats:
            self._store_caveats(caveats)
            log(f"  ⚠️ 负面经验: {len(caveats)} 条注意事项已提取")
        
        return {
            "trajectory": trajectory,
            "templates": templates,
            "parameterized": parameterized,
            "validated": validated,
            "stored": stored,
            "caveats": caveats,
        }

    def _extract_trajectory(self, steps: List[Dict]) -> List[Dict]:
        """提取执行轨迹"""
        trajectory = []
        for i, step in enumerate(steps):
            trajectory.append({
                "sequence": i,
                "type": step.get("type", "unknown"),
                "tool": step.get("tool", ""),
                "status": step.get("status", "unknown"),
                "args_preview": str(step.get("args_summary", ""))[:100],
            })
        return trajectory

    def _abstract_templates(self, trajectory: List[Dict]) -> List[Dict]:
        """从轨迹中抽象出通用模板"""
        templates = []
        
        # 分析工具调用序列，提取模式
        tool_sequence = [t.get("tool", "") for t in trajectory if t.get("tool")]
        
        if tool_sequence:
            # 提取连续的工具对作为模式
            for i in range(len(tool_sequence) - 1):
                pair = (tool_sequence[i], tool_sequence[i + 1])
                
                # 抽象模板
                if pair == ("read_file", "write_file"):
                    templates.append({
                        "id": f"tmp_{str(uuid.uuid4())[:8]}",
                        "pattern": "read_before_write",
                        "description": "读取文件后写入的编辑模式",
                        "steps": [
                            {"action": "read_file", "purpose": "获取当前内容"},
                            {"action": "modify_content", "purpose": "编辑修改"},
                            {"action": "write_file", "purpose": "写入变更"},
                        ],
                        "confidence": 0.8,
                    })
                elif pair == ("search_files", "read_file"):
                    templates.append({
                        "id": f"tmp_{uuid.uuid4()[:8]}",
                        "pattern": "search_then_read",
                        "description": "搜索后读取的查询模式",
                        "steps": [
                            {"action": "search_or_grep", "purpose": "定位目标文件"},
                            {"action": "read_file", "purpose": "查看内容"},
                        ],
                        "confidence": 0.7,
                    })
                elif pair == ("terminal", "read_file"):
                    templates.append({
                        "id": f"tmp_{uuid.uuid4()[:8]}",
                        "pattern": "execute_then_verify",
                        "description": "执行命令后验证结果的模式",
                        "steps": [
                            {"action": "execute_command", "purpose": "执行操作"},
                            {"action": "verify_output", "purpose": "验证结果"},
                        ],
                        "confidence": 0.75,
                    })
        
        # 如果什么都没提取到，生成通用模板
        if not templates and tool_sequence:
            templates.append({
                "id": f"tmp_{uuid.uuid4()[:8]}",
                "pattern": "generic_sequence",
                "description": f"通用工具序列: {' → '.join(tool_sequence[:5])}",
                "steps": [{"action": t, "purpose": "通用步骤"} for t in tool_sequence[:5]],
                "confidence": 0.5,
            })
        
        return templates

    def _parameterize_templates(self, templates: List[Dict]) -> List[Dict]:
        """将模板参数化"""
        parameterized = []
        for tmpl in templates:
            param_tmpl = {
                "id": tmpl["id"],
                "pattern": tmpl["pattern"],
                "description": tmpl["description"],
                "parameters": [],
                "parameterized_steps": [],
                "confidence": tmpl["confidence"],
            }
            
            for step in tmpl.get("steps", []):
                action = step.get("action", "")
                purpose = step.get("purpose", "")
                
                # 自动提取参数
                params = []
                if action == "read_file":
                    params.append({"name": "file_path", "type": "string", "description": "目标文件路径"})
                elif action == "write_file":
                    params.append({"name": "file_path", "type": "string", "description": "目标文件路径"})
                    params.append({"name": "content", "type": "string", "description": "写入内容"})
                elif action == "search_files":
                    params.append({"name": "pattern", "type": "string", "description": "搜索模式"})
                elif action == "terminal":
                    params.append({"name": "command", "type": "string", "description": "执行命令"})
                
                param_tmpl["parameters"].extend(params)
                param_tmpl["parameterized_steps"].append({
                    "action_template": f"{action}({{params}})",
                    "purpose": purpose,
                    "required_params": [p["name"] for p in params],
                })
            
            # 去重参数
            seen = set()
            unique_params = []
            for p in param_tmpl["parameters"]:
                if p["name"] not in seen:
                    seen.add(p["name"])
                    unique_params.append(p)
            param_tmpl["parameters"] = unique_params
            
            parameterized.append(param_tmpl)
        
        return parameterized

    def _validate_experiences(self, experiences: List[Dict]) -> List[Dict]:
        """验证经验的有效性"""
        validated = []
        for exp in experiences:
            issues = []
            
            # 检查完整性
            if not exp.get("parameterized_steps"):
                issues.append("缺少参数化步骤")
            if not exp.get("parameters") and exp.get("parameterized_steps"):
                issues.append("有步骤但无参数")
            
            # 检查置信度
            if exp.get("confidence", 0) < 0.3:
                issues.append("置信度过低")
            
            # 标记
            if not issues:
                exp["valid"] = True
                exp["validation_note"] = "通过验证"
                validated.append(exp)
            else:
                exp["valid"] = False
                exp["validation_note"] = "; ".join(issues)
                log(f"  ⚠️ 经验 {exp['id']} 未通过验证: {exp['validation_note']}")
                # 低置信度但也加入
                if exp.get("confidence", 0) >= 0.3:
                    validated.append(exp)
        
        return validated

    def _store_experiences(self, experiences: List[Dict], context: dict) -> int:
        """存储经验到数据库和Skill池"""
        stored_count = 0
        for exp in experiences:
            exp_record = {
                "id": exp["id"],
                "pattern": exp["pattern"],
                "description": exp["description"],
                "parameterized_steps": json.dumps(exp.get("parameterized_steps", []), ensure_ascii=False),
                "parameters": json.dumps(exp.get("parameters", []), ensure_ascii=False),
                "confidence": exp.get("confidence", 0.5),
                "source_session": context.get("session_id", ""),
                "created_at": datetime.now(TZ).isoformat(),
            }
            
            # 写入intelligence.db
            try:
                conn = sqlite3.connect(str(INTEL_DB))
                c = conn.cursor()
                c.execute("""
                    CREATE TABLE IF NOT EXISTS skill_experiences (
                        id TEXT PRIMARY KEY,
                        pattern TEXT,
                        description TEXT,
                        parameterized_steps TEXT,
                        parameters TEXT,
                        confidence REAL,
                        source_session TEXT,
                        created_at TEXT
                    )
                """)
                c.execute("""
                    INSERT OR REPLACE INTO skill_experiences
                    (id, pattern, description, parameterized_steps, parameters, confidence, source_session, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, tuple(exp_record.values()))
                conn.commit()
                conn.close()
                stored_count += 1
            except Exception as e:
                log(f"  ⚠️ 存储经验失败: {e}")
            
            # 写入Skill候选池
            self._write_to_skill_pool(exp_record)
        
        return stored_count

    def _write_to_skill_pool(self, experience: dict):
        """写入Skill候选池"""
        try:
            pool_file = HERMES / "data" / "experience_skill_pool.jsonl"
            (HERMES / "data").mkdir(exist_ok=True)
            
            pool_entry = {
                "source": "experience_extractor",
                "type": "skill_template",
                "pattern": experience["pattern"],
                "description": experience["description"],
                "steps": experience.get("parameterized_steps", "[]"),
                "confidence": experience.get("confidence", 0.5),
                "created_at": datetime.now(TZ).isoformat(),
            }
            
            with open(pool_file, "a") as f:
                f.write(json.dumps(pool_entry, ensure_ascii=False) + "\n")
        except Exception as e:
            log(f"  ⚠️ 写入Skill候选池失败: {e}")

    def _extract_caveats(self, steps: List[Dict], context: dict) -> List[Dict]:
        """从错误步骤中提取负面经验（注意事项）"""
        caveats = []
        
        for i, step in enumerate(steps):
            if step.get("status") == "error":
                tool = step.get("tool", "unknown")
                args = step.get("args_summary", "")
                
                caveat = {
                    "id": f"cav_{str(uuid.uuid4())[:8]}",
                    "type": "negative_experience",
                    "tool": tool,
                    "context": args[:100],
                    "caveat": f"使用 {tool} 时可能出错: {args[:50]}",
                    "sequence": i,
                    "severity": "warning",
                    "created_at": datetime.now(TZ).isoformat(),
                }
                caveats.append(caveat)
        
        return caveats

    def _store_caveats(self, caveats: List[Dict]):
        """存储负面经验到注意事项库"""
        try:
            conn = sqlite3.connect(str(INTEL_DB))
            c = conn.cursor()
            c.execute("""
                CREATE TABLE IF NOT EXISTS experience_caveats (
                    id TEXT PRIMARY KEY,
                    type TEXT,
                    tool TEXT,
                    context TEXT,
                    caveat TEXT,
                    severity TEXT,
                    created_at TEXT
                )
            """)
            for cav in caveats:
                c.execute("""
                    INSERT OR REPLACE INTO experience_caveats
                    (id, type, tool, context, caveat, severity, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (cav["id"], cav["type"], cav["tool"], cav["context"], cav["caveat"], cav["severity"], cav["created_at"]))
            conn.commit()
            conn.close()
            
            # 同时也写入文件
            caveats_file = HERMES / "data" / "experience_caveats.jsonl"
            (HERMES / "data").mkdir(exist_ok=True)
            with open(caveats_file, "a") as f:
                for cav in caveats:
                    f.write(json.dumps(cav, ensure_ascii=False) + "\n")
        except Exception as e:
            log(f"  ⚠️ 存储注意事项失败: {e}")

    def extract_from_retro(self, retro_file: str):
        """从复盘报告中提取经验"""
        if not os.path.exists(retro_file):
            log(f"❌ 复盘文件不存在: {retro_file}")
            return
        
        with open(retro_file) as f:
            retro = json.load(f)
        
        # 从复盘报告中构造步骤
        steps = []
        root_causes = retro.get("root_causes", [])
        if isinstance(root_causes, str):
            try:
                root_causes = json.loads(root_causes)
            except:
                root_causes = [root_causes]
        
        for cause in root_causes:
            steps.append({
                "tool": "analysis",
                "type": "tool_call",
                "status": "error",
                "args_summary": str(cause)[:100],
            })
        
        context = {
            "session_id": retro.get("meta", {}).get("session_id", "unknown"),
            "source": "retrospective",
        }
        
        return self.extract_from_steps(steps, context)

    def list_pool(self):
        """列出经验池"""
        pool_file = HERMES / "data" / "experience_skill_pool.jsonl"
        if not pool_file.exists():
            log("📝 经验池为空")
            return
        
        with open(pool_file) as f:
            lines = f.readlines()
        
        log(f"\n📊 经验池 ({len(lines)} 条)")
        log("=" * 50)
        for line in lines[-20:]:
            entry = json.loads(line)
            log(f"  [{entry.get('pattern', '?')}] {entry.get('description', '')[:60]}")

    def list_caveats(self):
        """列出注意事项库"""
        # 从数据库读取
        try:
            conn = sqlite3.connect(str(INTEL_DB))
            c = conn.cursor()
            rows = c.execute("SELECT tool, caveat, severity, created_at FROM experience_caveats ORDER BY created_at DESC LIMIT 20").fetchall()
            conn.close()
            
            if rows:
                log(f"\n📊 注意事项库 ({len(rows)} 条)")
                log("=" * 50)
                for tool, caveat, severity, created_at in rows:
                    log(f"  [{severity}] {tool}: {caveat[:60]}")
            else:
                log("📝 注意事项库为空")
        except Exception as e:
            log(f"  ⚠️ 读取注意事项库失败: {e}")
        
        # 也从文件读取
        caveats_file = HERMES / "data" / "experience_caveats.jsonl"
        if caveats_file.exists():
            with open(caveats_file) as f:
                lines = f.readlines()
            log(f"  文件备份: {len(lines)} 条")


def main():
    extractor = ExperienceExtractor()
    
    if "--from-trajectory" in sys.argv:
        idx = sys.argv.index("--from-trajectory")
        filepath = sys.argv[idx + 1] if idx + 1 < len(sys.argv) else ""
        if filepath:
            if os.path.exists(filepath):
                with open(filepath) as f:
                    data = json.load(f)
                steps = data.get("steps", data.get("messages", []))
                extractor.extract_from_steps(steps, {"session_id": data.get("id", "unknown")})
            else:
                log(f"❌ 文件不存在: {filepath}")
    
    elif "--from-retro" in sys.argv:
        idx = sys.argv.index("--from-retro")
        filepath = sys.argv[idx + 1] if idx + 1 < len(sys.argv) else ""
        if filepath:
            extractor.extract_from_retro(filepath)
    
    elif "--from-session" in sys.argv:
        idx = sys.argv.index("--from-session")
        session_id = sys.argv[idx + 1] if idx + 1 < len(sys.argv) else ""
        if session_id:
            # Load session and extract
            try:
                conn = sqlite3.connect(str(STATE_DB))
                c = conn.cursor()
                rows = c.execute("SELECT messages FROM sessions WHERE id=?", (session_id,)).fetchall()
                conn.close()
                if rows:
                    messages = json.loads(rows[0][0]) if rows[0][0] else []
                    extractor.extract_from_steps(messages, {"session_id": session_id})
                else:
                    log(f"❌ 未找到会话: {session_id}")
            except Exception as e:
                log(f"⚠️ 加载会话失败: {e}")
    
    elif "--list-pool" in sys.argv:
        extractor.list_pool()
    
    elif "--list-caveats" in sys.argv:
        extractor.list_caveats()
    
    else:
        print("""经验引擎 - Experience Extractor (P3-3)
Usage:
  python3 experience_extractor.py --from-trajectory <file>   从轨迹文件提取
  python3 experience_extractor.py --from-retro <file>       从复盘报告提取
  python3 experience_extractor.py --from-session <id>       从会话提取
  python3 experience_extractor.py --list-pool               列出经验池
  python3 experience_extractor.py --list-caveats            列出注意事项
""")


if __name__ == "__main__":
    main()
