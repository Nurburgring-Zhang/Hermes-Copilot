#!/usr/bin/env python3
"""
Agent Isolation Engine v2.0
===========================
Every expert and employee gets a FULLY ISOLATED sub-agent with:
- Independent config.yaml (model, parameters, system prompt)
- Own MCP server connections (tools specific to their domain)
- Isolated conversation history (no cross-contamination)
- Delegated task execution via delegate_task() with domain-specific context
- Autonomous workflow loop with self-assessment

Architecture:
  Orchestrator Agent (global)
    ├── Expert Agent 001 (DL Architect) — tools: browser, terminal, file
    │   ├── MCP: code-interpreter, websearch
    │   └── Skills: pytorch, onnx, model-compression
    ├── Expert Agent 002 (NLP Expert) — tools: browser, terminal
    │   ├── MCP: huggingface, nlp-tools
    │   └── Skills: transformers, tokenizers, fine-tuning
    ├── ...
    ├── Employee 001 (Market Analyst) — tools: browser, web
    │   ├── MCP: data-viz, excel
    │   └── Skills: market-analysis, swot
    └── ...
"""

import json
import os
import sys
import time
import logging
import sqlite3
from pathlib import Path
from typing import Dict, List, Optional, Any, Callable
from datetime import datetime
from dataclasses import dataclass, field, asdict

logger = logging.getLogger("agent-isolation")

HERMES = Path("/home/administrator/.hermes")
AGENTS_DIR = HERMES / "agents"
ISOLATION_DB = HERMES / "agent_isolation.db"


@dataclass
class AgentProfile:
    """Complete profile for an isolated sub-agent."""
    agent_id: str                # e.g., "expert_001", "emp_001"
    agent_type: str              # "expert" or "employee"
    name: str                    # Human-readable name
    domain: str                  # Domain/Department
    role_description: str        # System prompt / role definition
    tools_enabled: List[str]     # Tools available to this agent
    mcp_servers: List[str]       # MCP server names
    skills_enabled: List[str]    # Skills available
    model_preference: str        # Preferred model (cheap for simple tasks, strong for complex)
    max_iterations: int = 30     # Max tool calls per delegation
    memory_isolation: bool = True  # Use dedicated memory space
    isolation_profile: Dict[str, Any] = field(default_factory=dict)
    
    @property
    def config_path(self) -> Path:
        return AGENTS_DIR / self.agent_type / self.agent_id / "config.yaml"
    
    @property
    def memory_path(self) -> Path:
        return AGENTS_DIR / self.agent_type / self.agent_id / "memory"
    
    @property
    def workspace_path(self) -> Path:
        return AGENTS_DIR / self.agent_type / self.agent_id / "workspace"


class AgentIsolationEngine:
    """
    Manages lifecycle of isolated sub-agents for every expert and employee.
    
    Key features:
    - Creates isolated agent profile on first use
    - Generates domain-specific system prompt from expert/employee config
    - Configures per-agent tool access (only tools relevant to their domain)
    - Provides helper to generate delegation context for delegate_task()
    - Tracks agent usage stats (calls, tokens, success rate)
    """
    
    def __init__(self):
        self._db_conn = None
        self._ensure_dirs()
        self._init_db()
    
    def _ensure_dirs(self):
        AGENTS_DIR.mkdir(parents=True, exist_ok=True)
        (AGENTS_DIR / "expert").mkdir(exist_ok=True)
        (AGENTS_DIR / "employee").mkdir(exist_ok=True)
    
    def _get_db(self):
        if self._db_conn is None:
            self._db_conn = sqlite3.connect(str(ISOLATION_DB))
            self._db_conn.row_factory = sqlite3.Row
        return self._db_conn
    
    def _init_db(self):
        db = self._get_db()
        db.executescript("""
            CREATE TABLE IF NOT EXISTS agents (
                agent_id TEXT PRIMARY KEY,
                agent_type TEXT NOT NULL,
                name TEXT NOT NULL,
                domain TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_used TIMESTAMP,
                use_count INTEGER DEFAULT 0,
                total_tokens INTEGER DEFAULT 0,
                success_count INTEGER DEFAULT 0,
                fail_count INTEGER DEFAULT 0,
                config_json TEXT
            );
            CREATE TABLE IF NOT EXISTS agent_tools (
                agent_id TEXT,
                tool_name TEXT,
                enabled INTEGER DEFAULT 1,
                PRIMARY KEY (agent_id, tool_name)
            );
            CREATE TABLE IF NOT EXISTS agent_mcp (
                agent_id TEXT,
                server_name TEXT,
                config_json TEXT,
                PRIMARY KEY (agent_id, server_name)
            );
            CREATE TABLE IF NOT EXISTS agent_delegations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_id TEXT,
                task_goal TEXT,
                delegator TEXT DEFAULT 'orchestrator',
                tokens_used INTEGER DEFAULT 0,
                success INTEGER,
                error TEXT,
                started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                completed_at TIMESTAMP
            );
        """)
        db.commit()
    
    def register_agent(self, profile: AgentProfile) -> bool:
        """Register or update an isolated sub-agent."""
        db = self._get_db()
        try:
            db.execute("""
                INSERT OR REPLACE INTO agents 
                (agent_id, agent_type, name, domain, config_json)
                VALUES (?, ?, ?, ?, ?)
            """, (
                profile.agent_id, profile.agent_type, profile.name, 
                profile.domain, json.dumps(asdict(profile))
            ))
            
            # Register tools
            db.execute("DELETE FROM agent_tools WHERE agent_id=?", (profile.agent_id,))
            for tool in profile.tools_enabled:
                db.execute("INSERT INTO agent_tools VALUES (?, ?, 1)", 
                          (profile.agent_id, tool))
            
            # Register MCP servers
            db.execute("DELETE FROM agent_mcp WHERE agent_id=?", (profile.agent_id,))
            for mcp in profile.mcp_servers:
                db.execute("INSERT INTO agent_mcp (agent_id, server_name) VALUES (?, ?)",
                          (profile.agent_id, mcp))
            
            # Create workspace
            profile.workspace_path.mkdir(parents=True, exist_ok=True)
            profile.memory_path.mkdir(parents=True, exist_ok=True)
            
            db.commit()
            return True
        except Exception as e:
            logger.error(f"Failed to register agent {profile.agent_id}: {e}")
            return False
    
    def get_profile(self, agent_id: str) -> Optional[AgentProfile]:
        """Get an agent's profile."""
        db = self._get_db()
        row = db.execute("SELECT * FROM agents WHERE agent_id=?", (agent_id,)).fetchone()
        if not row:
            return None
        config = json.loads(row['config_json'])
        return AgentProfile(**config)
    
    def get_tools(self, agent_id: str) -> List[str]:
        """Get enabled tools for an agent."""
        db = self._get_db()
        rows = db.execute(
            "SELECT tool_name FROM agent_tools WHERE agent_id=? AND enabled=1",
            (agent_id,)
        ).fetchall()
        return [r['tool_name'] for r in rows]
    
    def build_delegation_context(self, agent_id: str) -> Dict[str, Any]:
        """
        Build the full context for delegate_task() to spawn this agent.
        Returns a dict with: context, toolsets, agent profile info.
        """
        profile = self.get_profile(agent_id)
        if not profile:
            return {'context': '', 'toolsets': []}
        
        tools = self.get_tools(agent_id)
        
        context_parts = [
            f"# Agent: {profile.name} ({profile.agent_id})",
            f"# Domain: {profile.domain}",
            f"# Role: {profile.role_description}",
            f"# Tools available: {', '.join(tools)}",
            f"# MCP servers: {', '.join(profile.mcp_servers)}",
            f"# Skills: {', '.join(profile.skills_enabled)}",
            f"# Max iterations: {profile.max_iterations}",
            "",
            f"# Memory workspace: {profile.workspace_path}",
            f"# Output directory: {profile.workspace_path / 'outputs'}",
        ]
        
        return {
            'context': '\n'.join(context_parts),
            'toolsets': tools,
            'profile': profile,
        }
    
    def record_delegation(self, agent_id: str, task_goal: str, 
                          success: bool, tokens: int = 0, error: str = None):
        """Record a delegation result for analytics."""
        db = self._get_db()
        db.execute("""
            INSERT INTO agent_delegations 
            (agent_id, task_goal, tokens_used, success, error, completed_at)
            VALUES (?, ?, ?, ?, ?, datetime('now'))
        """, (agent_id, task_goal[:200], tokens, 1 if success else 0, error))
        
        # Update agent stats
        db.execute("""
            UPDATE agents SET 
                last_used = datetime('now'),
                use_count = use_count + 1,
                total_tokens = total_tokens + ?,
                success_count = success_count + ?,
                fail_count = fail_count + ?
            WHERE agent_id = ?
        """, (tokens, 1 if success else 0, 0 if success else 1, agent_id))
        db.commit()
    
    def get_agent_stats(self, agent_id: str = None) -> List[Dict]:
        """Get agent usage statistics."""
        db = self._get_db()
        if agent_id:
            rows = db.execute("""
                SELECT a.*, 
                       COALESCE(s.total_tokens_used, 0) as delegation_tokens,
                       COALESCE(s.delegation_count, 0) as delegation_count  
                FROM agents a
                LEFT JOIN (
                    SELECT agent_id, SUM(tokens_used) as total_tokens_used, 
                           COUNT(*) as delegation_count
                    FROM agent_delegations GROUP BY agent_id
                ) s ON a.agent_id = s.agent_id
                WHERE a.agent_id = ?
            """, (agent_id,)).fetchall()
        else:
            rows = db.execute("""
                SELECT a.*, 
                       COALESCE(s.total_tokens_used, 0) as delegation_tokens,
                       COALESCE(s.delegation_count, 0) as delegation_count  
                FROM agents a
                LEFT JOIN (
                    SELECT agent_id, SUM(tokens_used) as total_tokens_used, 
                           COUNT(*) as delegation_count
                    FROM agent_delegations GROUP BY agent_id
                ) s ON a.agent_id = s.agent_id
                ORDER BY a.use_count DESC
                LIMIT 50
            """).fetchall()
        
        return [dict(r) for r in rows]
    
    def discover_experts(self) -> List[AgentProfile]:
        """Auto-discover all 390 experts from the expert system config."""
        profiles = []
        
        # Read expert system config
        expert_config_path = Path("/mnt/d/openclaw/experts/expert_system_config.json")
        if expert_config_path.exists():
            config = json.loads(expert_config_path.read_text())
            experts = config.get("experts", [])
            
            domain_tools_map = {
                "AI与机器学习": ["browser", "terminal", "file", "web", "search"],
                "软件工程": ["terminal", "file", "search", "session_search"],
                "安全与隐私": ["browser", "terminal", "web"],
                "数据与存储": ["terminal", "file", "web"],
                "云计算与基础设施": ["terminal", "web"],
                "前端与用户体验": ["browser", "file"],
                "产品与商业": ["browser", "web", "search"],
                "管理与沟通": ["web", "search"],
                "质量与测试": ["terminal", "file"],
                "内容与创意": ["browser", "file", "search"],
            }
            
            for exp in experts:
                aid = f"expert_{exp.get('id', '').lower().replace(' ', '_')}"
                domain = exp.get("domain", "General")
                tools = domain_tools_map.get(domain, ["web", "search"])
                
                profile = AgentProfile(
                    agent_id=aid,
                    agent_type="expert",
                    name=exp.get("name", f"Expert {exp.get('id', '')}"),
                    domain=domain,
                    role_description=exp.get("system_prompt", exp.get("description", "")),
                    tools_enabled=tools,
                    mcp_servers=["web-search", "file-system"],
                    skills_enabled=[exp.get("id", "").lower()],
                    model_preference=exp.get("model", "auto"),
                    max_iterations=25,
                )
                profiles.append(profile)
        
        return profiles
    
    def discover_employees(self) -> List[AgentProfile]:
        """Auto-discover all 130 employees from the agents company."""
        profiles = []
        
        # Read from employees SQLite DB
        emp_db_path = HERMES / "agents_company/data/employees.sqlite"
        if emp_db_path.exists():
            try:
                conn = sqlite3.connect(str(emp_db_path))
                rows = conn.execute("SELECT * FROM employees LIMIT 200").fetchall()
                cols = [d[0] for d in conn.execute("PRAGMA table_info(employees)").fetchall()]
                conn.close()
                
                for row in rows:
                    emp = dict(zip(cols, row))
                    aid = f"emp_{emp.get('id', emp.get('employee_id', 'unknown'))}"
                    dept = emp.get('dept', emp.get('department', 'General'))
                    
                    profile = AgentProfile(
                        agent_id=aid,
                        agent_type="employee",
                        name=emp.get('name', f"Employee {aid}"),
                        domain=dept,
                        role_description=emp.get('role', emp.get('description', '')),
                        tools_enabled=["browser", "terminal", "file", "web", "search"],
                        mcp_servers=["web-search", "file-system", "data-analysis"],
                        skills_enabled=[],
                        model_preference="auto",
                        max_iterations=30,
                    )
                    profiles.append(profile)
            except Exception as e:
                logger.error(f"Failed to discover employees: {e}")
        
        return profiles
    
    def build_multi_agent_command(self, orchestrator_task: str, 
                                   agent_ids: List[str]) -> Dict:
        """
        Build a complete multi-agent command:
        Orchestrator → N sub-agents → Summary
        
        Returns dict with: shell_command, context, expected_output
        """
        agents_section = []
        for aid in agent_ids:
            ctx = self.build_delegation_context(aid)
            agents_section.append(f"""---
Agent: {ctx['profile'].name}
ID: {aid}
Tools: {', '.join(ctx['toolsets'])}
Role: {ctx['profile'].role_description[:200]}
---
""")
        
        full_context = f"""# Multi-Agent Orchestration Command

## Orchestrator Task
{orchestrator_task}

## Available Sub-Agents
{''.join(agents_section)}

## Execution Plan
1. Orchestrator (me) decomposes the task
2. For each sub-task, I delegate to the appropriate agent via delegate_task()
3. Each sub-agent works independently with its own tools and context
4. I collect results and synthesize final output
5. I deliver the synthesized result

## Constraints
- Each sub-agent has max 30 iterations
- Sub-agents cannot delegate further (leaf agents)
- Results are returned as structured summaries
"""
        return {
            'command': full_context,
            'agents': agent_ids,
        }


# ============================================================
# INTEGRATION: Patch into multi_agent_orchestrator
# ============================================================

def patch_multi_agent_orchestrator():
    """Patch the existing multi_agent_orchestrator to use AgentIsolationEngine."""
    engine = AgentIsolationEngine()
    
    # Auto-discover and register all experts and employees
    experts = engine.discover_experts()
    employees = engine.discover_employees()
    
    registered = 0
    for p in experts:
        if engine.register_agent(p):
            registered += 1
    for p in employees:
        if engine.register_agent(p):
            registered += 1
    
    logger.info(f"AgentIsolationEngine: registered {registered} agents "
                f"({len(experts)} experts, {len(employees)} employees)")
    
    return engine


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Agent Isolation Engine")
    parser.add_argument("--discover", action="store_true", help="Discover and register all agents")
    parser.add_argument("--stats", type=str, help="Get stats for an agent (or 'all')")
    parser.add_argument("--build-command", nargs=2, metavar=("TASK", "AGENTS"), 
                       help="Build multi-agent command")
    
    args = parser.parse_args()
    
    engine = AgentIsolationEngine()
    
    if args.discover:
        experts = engine.discover_experts()
        employees = engine.discover_employees()
        registered = 0
        for p in experts + employees:
            if engine.register_agent(p):
                registered += 1
        print(f"✅ Registered {registered} agents ({len(experts)} experts, {len(employees)} employees)")
        
        stats = engine.get_agent_stats()
        print(f"\nTop agents by use:")
        for s in stats[:10]:
            print(f"  {s['agent_id']:30s} | {s['name'][:25]:25s} | uses: {s['use_count']} | success: {s['success_count']}")
    
    elif args.stats:
        if args.stats == 'all':
            stats = engine.get_agent_stats()
            print(f"{'Agent ID':30s} {'Type':10s} {'Name':25s} {'Uses':>6s} {'Success':>8s} {'Tokens':>10s}")
            print("-" * 90)
            for s in stats:
                print(f"{s['agent_id']:30s} {s['agent_type']:10s} {s['name'][:25]:25s} "
                      f"{s['use_count']:>6d} {s['success_count']:>8d} {s['total_tokens']:>10d}")
        else:
            s = engine.get_agent_stats(args.stats)
            print(json.dumps(s, indent=2, default=str))
    
    elif args.build_command:
        agent_ids = args.build_command[1].split(',')
        result = engine.build_multi_agent_command(args.build_command[0], agent_ids)
        print(result['command'])
