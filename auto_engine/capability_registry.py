#!/usr/bin/env python3
"""
Hermes Capability Integration Hub v2.0
全能力互调系统：所有Skills/Agents/Tools/Workflows可互相调用
"""
import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

HERMES = Path.home() / ".hermes"
SKILLS_DIR = HERMES / "skills"
AUTO_ENGINE = HERMES / "auto_engine"
CAPABILITY_DB = AUTO_ENGINE / "capabilities.db"


class CapabilityRegistry:
    """
    能力注册表 - 统一管理所有可用能力
    能力类型：skill | agent | tool | workflow | service
    """

    def __init__(self):
        self._init_db()
        self._scan_capabilities()

    def _init_db(self):
        """初始化能力数据库"""
        conn = sqlite3.connect(str(CAPABILITY_DB))
        conn.execute("""
            CREATE TABLE IF NOT EXISTS capabilities (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                type TEXT NOT NULL,  -- skill|agent|tool|workflow|service|model
                category TEXT,
                description TEXT,
                entry_point TEXT,   -- file path or command
                dependencies TEXT,  -- JSON array of dep capability names
                tags TEXT,          -- JSON array
                usage_count INTEGER DEFAULT 0,
                success_rate REAL DEFAULT 1.0,
                avg_duration_ms REAL DEFAULT 0,
                last_used TEXT,
                metadata TEXT       -- JSON for type-specific data
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS capability_calls (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                caller TEXT,
                callee TEXT,
                timestamp TEXT,
                success INTEGER,
                duration_ms REAL,
                context TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS skill_chain_registry (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chain_name TEXT UNIQUE,
                steps TEXT,          -- JSON array of (capability_name, params) tuples
                description TEXT,
                created_at TEXT,
                usage_count INTEGER DEFAULT 0
            )
        """)
        conn.commit()
        conn.close()

    def _scan_capabilities(self):
        """扫描所有能力并注册"""
        conn = sqlite3.connect(str(CAPABILITY_DB))
        cur = conn.cursor()

        # 获取已注册数量
        existing = cur.execute("SELECT COUNT(*) FROM capabilities").fetchone()[0]
        if existing > 100:
            conn.close()
            return  # Already scanned

        logger.info("[CapabilityRegistry] Scanning all capabilities...")

        # 1. Scan Skills (SKILL.md files)
        for skill_file in SKILLS_DIR.rglob("SKILL.md"):
            skill_dir = skill_file.parent
            category = skill_dir.name
            # Try to extract name from skill
            content = skill_file.read_text()
            name = content.split("\n")[0].lstrip("# ").strip() if "# " in content else category
            if len(name) > 50:
                name = category

            # Parse YAML frontmatter
            description = ""
            tags = []
            if content.startswith("---"):
                parts = content.split("---", 2)
                if len(parts) >= 3:
                    try:
                        import yaml
                        frontmatter = yaml.safe_load(parts[1])
                        description = frontmatter.get("description", "")
                        tags = frontmatter.get("tags", [])
                    except:
                        pass

            cur.execute("""
                INSERT OR IGNORE INTO capabilities
                (name, type, category, description, entry_point, tags, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                category,
                "skill",
                category,
                description,
                str(skill_dir),
                json.dumps(tags, ensure_ascii=False),
                json.dumps({"skill_file": str(skill_file)}, ensure_ascii=False)
            ))

        # 2. Register Hermes tools as capabilities
        tools = [
            ("web_search", "tool", "search", "Web search for information"),
            ("web_fetch", "tool", "search", "Fetch web page content"),
            ("terminal", "tool", "system", "Execute shell commands"),
            ("execute_code", "tool", "system", "Execute Python code"),
            ("delegate_task", "tool", "agent", "Spawn sub-agent for parallel tasks"),
            ("cronjob", "tool", "system", "Schedule/manage cron jobs"),
            ("skill_view", "tool", "system", "View skill content"),
            ("skill_manage", "tool", "system", "Create/update/delete skills"),
            ("skills_list", "tool", "system", "List available skills"),
            ("memory", "tool", "system", "Persistent memory storage"),
            ("session_search", "tool", "system", "Search past sessions"),
            ("browser_navigate", "tool", "browser", "Navigate browser to URL"),
            ("browser_snapshot", "tool", "browser", "Get page snapshot"),
            ("browser_click", "tool", "browser", "Click page element"),
            ("browser_type", "tool", "browser", "Type into form field"),
            ("text_to_speech", "tool", "media", "Convert text to speech"),
            ("vision_analyze", "tool", "media", "Analyze image with AI"),
        ]
        for name, typ, cat, desc in tools:
            cur.execute("""
                INSERT OR IGNORE INTO capabilities
                (name, type, category, description, metadata)
                VALUES (?, ?, ?, ?, ?)
            """, (name, typ, cat, desc, json.dumps({"native": True}, ensure_ascii=False)))

        # 3. Register Workflow Engine
        wf_dir = SKILLS_DIR / "workflow-engine"
        if wf_dir.exists():
            for wf_file in wf_dir.glob("*.py"):
                name = wf_file.stem
                cur.execute("""
                    INSERT OR IGNORE INTO capabilities
                    (name, type, category, description, entry_point)
                    VALUES (?, ?, ?, ?, ?)
                """, (name, "workflow", "orchestration", f"Workflow engine: {name}", str(wf_file)))

        # 4. Register Expert System
        expert_cfg = Path("/mnt/d/openclaw/experts/expert_system_config.json")
        if expert_cfg.exists():
            data = json.loads(expert_cfg.read_text())
            for expert in data.get("experts", []):
                cur.execute("""
                    INSERT OR IGNORE INTO capabilities
                    (name, type, category, description, metadata)
                    VALUES (?, ?, ?, ?, ?)
                """, (
                    expert.get("id", ""),
                    "agent",
                    expert.get("domain", "unknown"),
                    f"Expert: {expert.get('name', '')}",
                    json.dumps(expert, ensure_ascii=False)
                ))

        # 5. Register Agents Company employees as agents
        emp_db = HERMES / "agents_company" / "data" / "employees.sqlite"
        if emp_db.exists():
            conn2 = sqlite3.connect(str(emp_db))
            emps = conn2.execute("SELECT id, name, department_id, position FROM employees LIMIT 130").fetchall()
            conn2.close()
            for emp_id, name, dept, pos in emps:
                cur.execute("""
                    INSERT OR IGNORE INTO capabilities
                    (name, type, category, description, metadata)
                    VALUES (?, ?, ?, ?, ?)
                """, (
                    f"agent_{emp_id}",
                    "agent",
                    f"dept_{dept}",
                    f"Employee: {name} - {pos}",
                    json.dumps({"employee_id": emp_id, "name": name, "position": pos}, ensure_ascii=False)
                ))

        conn.commit()
        total = cur.execute("SELECT COUNT(*) FROM capabilities").fetchone()[0]
        conn.close()
        logger.info(f"[CapabilityRegistry] Registered {total} capabilities")

    def call_capability(
        self,
        name: str,
        params: Optional[Dict[str, Any]] = None,
        caller: str = "manual"
    ) -> Dict[str, Any]:
        """
        统一调用接口：任何能力都可以通过名字调用
        返回：{success, result, duration_ms, error}
        """
        start = datetime.now()
        params = params or {}

        conn = sqlite3.connect(str(CAPABILITY_DB))
        cur = conn.cursor()

        cap = cur.execute(
            "SELECT name, type, entry_point, metadata FROM capabilities WHERE name = ?",
            (name,)
        ).fetchone()

        if not cap:
            conn.close()
            return {"success": False, "error": f"Capability '{name}' not found"}

        cap_name, cap_type, entry_point, metadata_json = cap
        metadata = json.loads(metadata_json or "{}")

        result = None
        error = None
        success = True

        try:
            if cap_type == "tool":
                result = self._call_tool(name, params)
            elif cap_type == "skill":
                result = self._call_skill(name, params, entry_point)
            elif cap_type == "agent":
                result = self._call_agent(name, params, metadata)
            elif cap_type == "workflow":
                result = self._call_workflow(name, params, entry_point)
            else:
                result = {"info": f"capability_type={cap_type}, entry={entry_point}"}

        except Exception as e:
            success = False
            error = str(e)
            logger.error(f"[CapabilityRegistry] call '{name}' failed: {e}")

        duration_ms = (datetime.now() - start).total_seconds() * 1000

        # Log call
        cur.execute("""
            INSERT INTO capability_calls (caller, callee, timestamp, success, duration_ms)
            VALUES (?, ?, ?, ?, ?)
        """, (caller, name, datetime.now().isoformat(), 1 if success else 0, duration_ms))

        # Update usage stats
        cur.execute("""
            UPDATE capabilities SET
                usage_count = usage_count + 1,
                last_used = ?,
                avg_duration_ms = (avg_duration_ms * (usage_count - 1) + ?) / usage_count
            WHERE name = ?
        """, (datetime.now().isoformat(), duration_ms, name))

        conn.commit()
        conn.close()

        return {
            "success": success,
            "result": result,
            "duration_ms": round(duration_ms, 2),
            "error": error,
            "capability": name,
            "type": cap_type
        }

    def _call_tool(self, name: str, params: Dict) -> Any:
        """通过hermes_tools调用原生工具"""
        from hermes_tools import terminal, search_files, read_file, write_file, patch
        # Map of tools that are actual Python functions in hermes_tools
        tool_map = {
            "terminal": lambda p: terminal(**{k: v for k, v in p.items() if k in ["command", "timeout", "workdir", "background", "pty", "notify_on_complete"]}),
            "search_files": lambda p: search_files(**p),
            "read_file": lambda p: read_file(**p),
            "write_file": lambda p: write_file(**p),
            "patch": lambda p: patch(**p),
        }
        if name in tool_map:
            return tool_map[name](params)
        # For LLM tools (execute_code, delegate_task, etc.), return a directive
        return {
            "directive": f"LLM_TOOL:{name}",
            "params": params,
            "info": f"Tool '{name}' is an LLM native tool - invoke via LLM call",
            "available_builtin_tools": list(tool_map.keys())
        }

    def _call_skill(self, name: str, params: Dict, entry_point: str) -> Any:
        """加载并执行Skill"""
        # Load skill content
        skill_file = Path(entry_point) / "SKILL.md"
        if skill_file.exists():
            return {
                "skill_name": name,
                "skill_file": str(skill_file),
                "params": params,
                "status": "skill_loaded"
            }
        return {"error": f"Skill file not found: {skill_file}"}

    def _call_agent(self, name: str, params: Dict, metadata: Dict) -> Any:
        """调用Agent (专家或员工)"""
        return {
            "agent_id": name,
            "metadata": metadata,
            "params": params,
            "status": "agent_dispatched"
        }

    def _call_workflow(self, name: str, params: Dict, entry_point: str) -> Any:
        """执行工作流"""
        return {
            "workflow": name,
            "entry_point": entry_point,
            "params": params,
            "status": "workflow_initiated"
        }

    def chain_capabilities(
        self,
        steps: List[Dict[str, Any]],
        caller: str = "chain"
    ) -> List[Dict[str, Any]]:
        """
        链式调用：按顺序执行一系列能力
        steps: [{"capability": "name", "params": {...}}, ...]
        """
        results = []
        for step in steps:
            cap_name = step.get("capability")
            params = step.get("params", {})
            result = self.call_capability(cap_name, params, caller=caller)
            results.append(result)
            if not result["success"]:
                logger.warning(f"[Chain] {cap_name} failed, continuing...")
        return results

    def register_skill_chain(
        self,
        chain_name: str,
        steps: List[Dict[str, Any]],
        description: str = ""
    ) -> bool:
        """注册能力链（多个能力组合成链）"""
        conn = sqlite3.connect(str(CAPABILITY_DB))
        try:
            conn.execute("""
                INSERT OR REPLACE INTO skill_chain_registry
                (chain_name, steps, description, created_at, usage_count)
                VALUES (?, ?, ?, ?, 0)
            """, (
                chain_name,
                json.dumps(steps, ensure_ascii=False),
                description,
                datetime.now().isoformat()
            ))
            conn.commit()
            return True
        except Exception as e:
            logger.error(f"[Chain] Failed to register '{chain_name}': {e}")
            return False
        finally:
            conn.close()

    def execute_skill_chain(
        self,
        chain_name: str,
        initial_params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """执行已注册的能力链"""
        conn = sqlite3.connect(str(CAPABILITY_DB))
        cur = conn.cursor()
        row = cur.execute(
            "SELECT steps, description FROM skill_chain_registry WHERE chain_name = ?",
            (chain_name,)
        ).fetchone()
        conn.close()

        if not row:
            return {"success": False, "error": f"Chain '{chain_name}' not found"}

        steps = json.loads(row[0])
        params = initial_params or {}

        # 链式执行
        all_results = []
        for step in steps:
            cap_name = step.get("capability")
            step_params = {**params, **step.get("params", {})}
            result = self.call_capability(cap_name, step_params, caller=f"chain:{chain_name}")
            all_results.append(result)
            # 将结果注入下一步参数
            if result["success"] and "result" in result:
                params[f"prev_result_{cap_name}"] = result["result"]

        # Update usage
        conn = sqlite3.connect(str(CAPABILITY_DB))
        conn.execute(
            "UPDATE skill_chain_registry SET usage_count = usage_count + 1 WHERE chain_name = ?",
            (chain_name,)
        )
        conn.commit()
        conn.close()

        return {
            "success": True,
            "chain_name": chain_name,
            "steps_executed": len(all_results),
            "results": all_results
        }

    def get_capability_info(self, name: str) -> Optional[Dict[str, Any]]:
        """获取能力详情"""
        conn = sqlite3.connect(str(CAPABILITY_DB))
        row = conn.execute(
            "SELECT name, type, category, description, usage_count, success_rate, "
            "avg_duration_ms, last_used FROM capabilities WHERE name = ?",
            (name,)
        ).fetchone()
        conn.close()
        if row:
            return {
                "name": row[0], "type": row[1], "category": row[2],
                "description": row[3], "usage_count": row[4],
                "success_rate": row[5], "avg_duration_ms": row[6], "last_used": row[7]
            }
        return None

    def list_by_category(self, category: str) -> List[Dict[str, Any]]:
        """列出某类别的所有能力"""
        conn = sqlite3.connect(str(CAPABILITY_DB))
        rows = conn.execute(
            "SELECT name, type, description, usage_count FROM capabilities "
            "WHERE category = ? ORDER BY usage_count DESC",
            (category,)
        ).fetchall()
        conn.close()
        return [{"name": r[0], "type": r[1], "description": r[2], "usage_count": r[3]} for r in rows]

    def get_stats(self) -> Dict[str, Any]:
        """获取能力统计"""
        conn = sqlite3.connect(str(CAPABILITY_DB))
        cur = conn.cursor()

        total = cur.execute("SELECT COUNT(*) FROM capabilities").fetchone()[0]
        by_type = dict(cur.execute(
            "SELECT type, COUNT(*) FROM capabilities GROUP BY type"
        ).fetchall())
        by_category = dict(cur.execute(
            "SELECT category, COUNT(*) FROM capabilities GROUP BY category ORDER BY COUNT(*) DESC LIMIT 10"
        ).fetchall())
        top_used = cur.execute(
            "SELECT name, usage_count FROM capabilities ORDER BY usage_count DESC LIMIT 5"
        ).fetchall()
        recent_calls = cur.execute(
            "SELECT callee, timestamp, success FROM capability_calls "
            "ORDER BY timestamp DESC LIMIT 10"
        ).fetchall()

        conn.close()
        return {
            "total_capabilities": total,
            "by_type": by_type,
            "top_categories": dict(by_category),
            "top_used": [{"name": r[0], "count": r[1]} for r in top_used],
            "recent_calls": [{"capability": r[0], "time": r[1], "success": bool(r[2])} for r in recent_calls]
        }


# 全局单例
_registry = None


def get_registry() -> CapabilityRegistry:
    global _registry
    if _registry is None:
        _registry = CapabilityRegistry()
    return _registry


# Pre-registered skill chains
def register_default_chains():
    """注册默认的能力链"""
    reg = get_registry()

    # 情报采集→清洗→评估→推送 管道
    reg.register_skill_chain(
        "intelligence_pipeline",
        [
            {"capability": "web_search", "params": {"query": "latest AI news"}},
            {"capability": "execute_code", "params": {"code": "import sqlite3; ..."}},
            {"capability": "intelligence_analysis", "params": {}},
            {"capability": "push_plus_notify", "params": {}},
        ],
        "情报采集到推送的完整管道"
    )

    # 需求→设计→开发→测试→部署 管道
    reg.register_skill_chain(
        "full_development_pipeline",
        [
            {"capability": "requirements_mining", "params": {}},
            {"capability": "feature_design", "params": {}},
            {"capability": "technical_architecture", "params": {}},
            {"capability": "backend_development", "params": {}},
            {"capability": "quality_assurance", "params": {}},
            {"capability": "deployment", "params": {}},
        ],
        "完整软件开发管道"
    )

    # 自我进化管道
    reg.register_skill_chain(
        "self_evolution_pipeline",
        [
            {"capability": "self_observation", "params": {}},
            {"capability": "evolve_skills", "params": {}},
            {"capability": "optimize_memory", "params": {}},
            {"capability": "optimize_workflow", "params": {}},
            {"capability": "auto_tune", "params": {}},
        ],
        "自我进化完整周期"
    )

    logger.info("[CapabilityRegistry] Default chains registered")


if __name__ == "__main__":
    reg = get_registry()
    stats = reg.get_stats()
    print(f"\n=== CAPABILITY REGISTRY ===")
    print(f"Total Capabilities: {stats['total_capabilities']}")
    print(f"By Type: {stats['by_type']}")
    print(f"\nTop Categories:")
    for cat, count in list(stats['top_categories'].items())[:5]:
        print(f"  {cat}: {count}")
    print(f"\nTop Used:")
    for item in stats['top_used']:
        print(f"  {item['name']}: {item['count']} calls")

    print("\n=== REGISTRY TEST ===")
    # Test chain call
    result = reg.call_capability("terminal", {"command": "echo 'capability registry test'"})
    print(f"tool call: {result['success']}, {result['duration_ms']}ms")
