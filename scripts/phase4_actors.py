#!/usr/bin/env python3
"""
Self-Improving Topology — 三省六部自适应循环
==============================================
刑部核心:每次任务输出后自动复盘,自动调整权重,自动更新拓扑。
不依赖重型RLHF,用轻量级对比学习。

流程:
1. 任务完成 → Hindsight 生成决策日志
2. 对比学习: 预期输出 vs 实际输出的语义距离
3. 偏差 > 阈值 → 在知识图谱中调整节点权重或边权值
4. 连续高延迟/低信息增益路径 → 自动降权或替换备用Skill
5. 三省六部YAML自动更新
"""

import os, sys, json, time, yaml, logging, random, hashlib
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from pathlib import Path

_script_dir = os.path.dirname(os.path.abspath(__file__))
_root_dir = os.path.dirname(_script_dir)
for p in [_root_dir, os.path.join(_root_dir, "scripts")]:
    if p and p not in sys.path:
        sys.path.insert(0, p)

from actor_base import Actor, Event, ActorPriority, ActorStatus
from synapse_bus import get_bus, SynapseBus

logger = logging.getLogger("hermes.self_improving")


@dataclass
class DecisionLog:
    """一次任务的决策日志"""
    dag_id: str
    task_description: str
    started_at: str
    completed_at: str = ""
    duration_ms: float = 0
    node_count: int = 0
    success_count: int = 0
    fail_count: int = 0
    total_tokens: int = 0
    user_feedback: int = 0  # -1 负面, 0 无, 1 正面
    skill_chain: List[str] = field(default_factory=list)
    error_paths: List[str] = field(default_factory=list)
    latency_by_node: Dict[str, float] = field(default_factory=dict)
    
    def to_dict(self) -> Dict:
        return {
            "dag_id": self.dag_id,
            "task": self.task_description[:40],
            "duration_ms": self.duration_ms,
            "success_rate": round(self.success_count / max(self.node_count, 1) * 100, 1),
            "total_tokens": self.total_tokens,
            "errors": self.fail_count,
            "skill_chain": self.skill_chain[:5],
        }
    
    @property
    def success_rate(self) -> float:
        return self.success_count / max(self.node_count, 1)
    
    @property
    def is_degraded(self) -> bool:
        return self.success_rate < 0.5 or self.duration_ms > 30000


class TopologyStore:
    """
    拓扑状态存储 — 基于 state.db 的 topology_state 表。
    记录每个 skill/actor 的历史表现,用于自适应调整。
    """
    
    def __init__(self, db_path: str = ""):
        self.db_path = db_path or os.path.join(
            os.path.expanduser("~/.hermes"), "state.db"
        )
        self._init_db()
    
    def _init_db(self):
        try:
            conn = self._get_conn()
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS topology_state (
                    key TEXT PRIMARY KEY,
                    value TEXT,
                    category TEXT DEFAULT 'skill',
                    score REAL DEFAULT 1.0,
                    weight REAL DEFAULT 1.0,
                    calls INTEGER DEFAULT 0,
                    failures INTEGER DEFAULT 0,
                    total_latency_ms REAL DEFAULT 0,
                    last_used TEXT,
                    last_error TEXT,
                    created_at TEXT DEFAULT (datetime('now'))
                );
                CREATE INDEX IF NOT EXISTS idx_topo_cat ON topology_state(category);
                CREATE INDEX IF NOT EXISTS idx_topo_score ON topology_state(score DESC);
            """)
            conn.commit()
            conn.close()
        except Exception as e:
            logger.warning(f"TopologyStore init: {e}")
    
    def _get_conn(self):
        import sqlite3
        return sqlite3.connect(self.db_path)
    
    def record_use(self, skill_name: str, category: str = "skill",
                   latency_ms: float = 0, success: bool = True,
                   error: str = ""):
        """记录 skill 使用"""
        conn = self._get_conn()
        now = datetime.now().isoformat()
        
        row = conn.execute(
            "SELECT calls, failures, score, weight FROM topology_state WHERE key=?",
            (skill_name,)
        ).fetchone()
        
        if row:
            calls = row[0] + 1
            failures = row[1] + (0 if success else 1)
            # 加权评分: 成功+0.1, 失败-0.3, 时间权重
            new_score = max(0.1, min(3.0, row[2] + (0.1 if success else -0.3)))
            new_weight = max(0.1, min(3.0, row[3] + (0.05 if success else -0.1)))
            
            conn.execute(
                """UPDATE topology_state 
                   SET calls=?, failures=?, score=?, weight=?,
                       total_latency_ms=total_latency_ms+?,
                       last_used=?, last_error=?
                   WHERE key=?""",
                (calls, failures, round(new_score, 2), round(new_weight, 2),
                 latency_ms, now, error[:100] if error else "", skill_name)
            )
        else:
            conn.execute(
                "INSERT INTO topology_state (key, category, score, weight, calls, failures, total_latency_ms, last_used, last_error) VALUES (?, ?, ?, ?, 1, ?, ?, ?, ?)",
                (skill_name, category, 1.0, 1.0, 0 if success else 1, latency_ms, now, error[:100] if error else "")
            )
        
        conn.commit()
        conn.close()
    
    def get_stats(self, category: str = "", min_calls: int = 0) -> List[Dict]:
        """获取统计"""
        conn = self._get_conn()
        if category:
            rows = conn.execute(
                "SELECT * FROM topology_state WHERE category=? AND calls>=? ORDER BY score DESC",
                (category, min_calls)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM topology_state WHERE calls>=? ORDER BY score DESC",
                (min_calls,)
            ).fetchall()
        conn.close()
        
        columns = ["key", "value", "category", "score", "weight", "calls", "failures", "total_latency_ms", "last_used", "last_error", "created_at"]
        return [dict(zip(columns, r)) for r in rows]
    
    def get_recommendation(self, task_type: str) -> List[Dict]:
        """获取推荐 skill 列表(按历史成功率排序)"""
        conn = self._get_conn()
        rows = conn.execute(
            """SELECT key, score, weight, calls, failures 
               FROM topology_state 
               WHERE (key LIKE ? OR category=?) AND calls >= 2
               ORDER BY score DESC, calls DESC LIMIT 5""",
            (f"%{task_type}%", task_type)
        ).fetchall()
        conn.close()
        return [
            {"skill": r[0], "score": r[1], "weight": r[2], "calls": r[3], "failures": r[4]}
            for r in rows
        ]
    
    def degrade_path(self, skill_name: str, reason: str = "high_latency"):
        """降级某条路径的权重"""
        conn = self._get_conn()
        conn.execute(
            "UPDATE topology_state SET weight = MAX(weight * 0.5, 0.1), last_error=? WHERE key=?",
            (f"degraded: {reason[:50]}", skill_name)
        )
        conn.commit()
        conn.close()
        logger.info(f"Degraded path: {skill_name} (reason: {reason})")


class SelfImprovingTopology:
    """
    三省六部自适应循环。
    
    自进化逻辑:
    1. 每次任务输出后,Hindsight 记录 {dag_id, skill_chain, latency, cost}
    2. AutoSkill 计算该技能组合的历史胜率与边际成本
    3. 连续三次"高延迟/低信息增益" → DAG图中降低边权值或替换备用Skill
    4. YAML 自动更新(不重启主进程)
    """
    
    def __init__(self, bus: Optional[SynapseBus] = None,
                 yaml_path: Optional[str] = None):
        self.bus = bus or get_bus()
        self.store = TopologyStore()
        self.yaml_path = yaml_path or os.path.join(
            _root_dir or os.path.expanduser("~/.hermes"), "topology.yaml"
        )
        self._log_history: List[DecisionLog] = []
        self._max_history = 200
        
        # 退化检测
        self._degradation_threshold = 0.5  # 成功率低于此值触发降级
        self._latency_threshold = 15000   # 延迟超过15秒触发优化
        self._review_interval = 5          # 每N次任务后自动Review
        
        logger.info("SelfImprovingTopology initialized")
    
    def record_decision(self, log: DecisionLog):
        """记录一次决策"""
        self._log_history.append(log)
        if len(self._log_history) > self._max_history:
            self._log_history.pop(0)
        
        # 记录每个 skill 的表现
        for skill in log.skill_chain:
            latency = log.latency_by_node.get(skill, 0)
            success = skill not in log.error_paths
            error = ""
            if skill in log.error_paths:
                error = f"failed in DAG {log.dag_id}"
            
            self.store.record_use(
                skill, "skill", latency, success, error
            )
        
        # 检查是否需要自动Review
        if len(self._log_history) % self._review_interval == 0:
            self.review()
    
    def review(self) -> Dict[str, Any]:
        """
        自动复盘 — 分析近期表现,提出优化建议。
        
        返回调整列表
        """
        recent = self._log_history[-self._review_interval:]
        changes = []
        
        # 1. 检测退化路径
        for entry in recent:
            if entry.is_degraded:
                for path in entry.error_paths:
                    self.store.degrade_path(path, "high_error_rate")
                    changes.append({
                        "type": "degrade",
                        "target": path,
                        "reason": f"success_rate={entry.success_rate:.0%}",
                    })
        
        # 2. 高延迟优化建议
        for entry in recent:
            if entry.duration_ms > self._latency_threshold:
                for skill, lat in entry.latency_by_node.items():
                    if lat > self._latency_threshold / entry.node_count:
                        changes.append({
                            "type": "optimize",
                            "target": skill,
                            "reason": f"latency={lat:.0f}ms",
                        })
        
        # 3. 更新 YAML
        if changes:
            self._update_yaml(changes)
        
        logger.info(f"Auto review: {len(changes)} changes from {len(recent)} tasks")
        return {"changes": changes, "tasks_reviewed": len(recent)}
    
    def _update_yaml(self, changes: List[Dict]):
        """自动更新 YAML 策略文件"""
        if not os.path.exists(self.yaml_path):
            return
        
        try:
            with open(self.yaml_path) as f:
                config = yaml.safe_load(f) or {}
            
            for change in changes:
                target = change.get("target", "")
                if "degrade" in change.get("type", ""):
                    # 在对应 ministry 中降低权重
                    for mid, mcfg in config.get("ministries", {}).items():
                        if target in str(mcfg):
                            mcfg["weight"] = max(mcfg.get("weight", 1.0) * 0.7, 0.1)
                            mcfg["_auto_adjusted"] = True
                            mcfg["_adjust_reason"] = change["reason"]
                            logger.info(f"YAML adjusted: {mid}.weight → {mcfg['weight']}")
            
            with open(self.yaml_path, "w") as f:
                yaml.dump(config, f, default_flow_style=False, allow_unicode=True)
            
            logger.info(f"YAML updated ({len(changes)} changes applied)")
        except Exception as e:
            logger.warning(f"YAML update failed: {e}")
    
    def get_recommendation(self, task_type: str) -> Dict:
        """获取任务推荐"""
        recs = self.store.get_recommendation(task_type)
        return {
            "task_type": task_type,
            "recommendations": recs[:3],
            "top_pick": recs[0] if recs else None,
        }
    
    def get_stats(self) -> Dict:
        """获取自进化统计"""
        recent = self._log_history[-10:] if self._log_history else []
        return {
            "total_tasks": len(self._log_history),
            "recent_success_rate": round(
                sum(e.success_rate for e in recent) / max(len(recent), 1) * 100, 1
            ) if recent else 0,
            "avg_latency_ms": round(
                sum(e.duration_ms for e in recent) / max(len(recent), 1)
            ) if recent else 0,
            "degraded_paths": [
                r for r in self.store.get_stats("skill")
                if r.get("weight", 1.0) < 0.5
            ],
            "top_performers": self.store.get_stats("skill", min_calls=3)[:5],
        }
    
    def get_evolution_report(self) -> str:
        """生成进化报告"""
        stats = self.get_stats()
        lines = [
            "=" * 50,
            "三省六部自进化报告",
            "=" * 50,
            f"总任务数: {stats['total_tasks']}",
            f"近期成功率: {stats['recent_success_rate']}%",
            f"平均延迟: {stats['avg_latency_ms']}ms",
            "",
        ]
        
        if stats["degraded_paths"]:
            lines.append("降级路径:")
            for p in stats["degraded_paths"][:5]:
                lines.append(f"  ☠️ {p['key']} (权重:{p['weight']}, 失败:{p['failures']}/{p['calls']})")
        
        if stats["top_performers"]:
            lines.append("\n最佳表现:")
            for p in stats["top_performers"][:5]:
                lines.append(f"  🏆 {p['key']} (评分:{p['score']}, 调用:{p['calls']}次)")
        
        return "\n".join(lines)


# ══════════════════════════════════════════════════════════════
# 刑部 Actor — 嵌入三省六部
# ══════════════════════════════════════════════════════════════

class EvolutionActor(Actor):
    """
    刑部自进化 Actor。
    
    职责:
    1. 接管 `scene.evolution` 事件
    2. 每个任务完成后自动记录决策
    3. 周期性 review 分析退化路径
    4. 自动更新 YAML 拓扑
    """
    
    def __init__(self):
        super().__init__(
            "xingbu:evolution",
            "刑部·自进化",
            ["scene.evolution", "scene.review", "evolution.record",
             "evolution.review", "evolution.recommend",
             "ministry.xingbu.retry", "ministry.xingbu.fallback"],
            "三省六部自适应循环: 记录→Review→调整YAML",
            priority=ActorPriority.CRITICAL,
        )
        self.engine = SelfImprovingTopology()
    
    def handle(self, event: Event) -> Any:
        payload = event.payload
        
        if event.type in ("scene.evolution", "evolution.record"):
            log = DecisionLog(
                dag_id=payload.get("dag_id", "unknown"),
                task_description=payload.get("task", ""),
                started_at=payload.get("started_at", datetime.now().isoformat()),
                completed_at=datetime.now().isoformat(),
                duration_ms=payload.get("duration_ms", 0),
                node_count=payload.get("node_count", 0),
                success_count=payload.get("success_count", 0),
                fail_count=payload.get("fail_count", 0),
                total_tokens=payload.get("total_tokens", 0),
                skill_chain=payload.get("skill_chain", []),
                error_paths=payload.get("error_paths", []),
                latency_by_node=payload.get("latency_by_node", {}),
            )
            self.engine.record_decision(log)
            return {"status": "recorded", "review": len(self.engine._log_history) % self.engine._review_interval == 0 and self.engine.review() or None}
        
        elif event.type in ("scene.review", "evolution.review"):
            return self.engine.review()
        
        elif event.type == "evolution.recommend":
            task_type = payload.get("task_type", "general")
            return self.engine.get_recommendation(task_type)
        
        elif event.type == "ministry.xingbu.retry":
            # 刑部重试:查历史记录判断是否应重试
            skill = payload.get("skill", "")
            recs = self.engine.store.get_recommendation(skill)
            if recs and recs[0]["score"] > 1.0:
                return {"should_retry": True, "backoff": 5, "confidence": recs[0]["score"]}
            return {"should_retry": False, "reason": "low_historical_score"}
        
        elif event.type == "ministry.xingbu.fallback":
            # 刑部降级:推荐替代方案
            skill = payload.get("skill", "")
            recs = self.engine.store.get_stats("skill", min_calls=2)
            alternatives = [r for r in recs if r["key"] != skill and r["score"] > 1.0]
            return {
                "fallback_available": len(alternatives) > 0,
                "alternatives": [r["key"] for r in alternatives[:3]],
                "reason": f"{skill} degraded to {len(alternatives)} alternatives",
            }
        
        return {"error": f"Unknown event: {event.type}"}
    
    def get_report(self) -> str:
        return self.engine.get_evolution_report()


def register_phase4_actors(bus=None):
    """注册第4期 Actor"""
    if bus is None:
        bus = get_bus()
    
    # 注销旧的刑部 Actor
    old = bus.get_actor("ministry:xingbu")
    if old:
        bus.deregister_actor("ministry:xingbu")
        logger.info("Deregistered old xingbu placeholder")
    
    evo = EvolutionActor()
    bus.register_actor(evo, [
        "scene.evolution", "scene.review",
        "evolution.record", "evolution.review", "evolution.recommend",
        "ministry.xingbu.retry", "ministry.xingbu.fallback",
    ])
    
    # 设置刑部接管
    bus.set_xingbu(evo)
    
    logger.info(f"Registered phase4 actor: {evo.id}")
    return evo


def test_phase4():
    """第4期集成测试"""
    from synapse_bus import SynapseBus
    
    bus = SynapseBus(max_workers=4)
    evo = register_phase4_actors(bus)
    
    print("=" * 50)
    print("第4期集成测试: 刑部·自进化循环")
    print("=" * 50)
    
    # Test 1: 记录成功任务
    print("\n📋 记录成功任务")
    results = bus.emit("evolution.record", {
        "dag_id": "test-dag-1",
        "task": "Python框架调研",
        "duration_ms": 2500,
        "node_count": 4,
        "success_count": 4,
        "fail_count": 0,
        "total_tokens": 2500,
        "skill_chain": ["hubu:search", "gongbu:snapshot", "libu:memory"],
        "error_paths": [],
        "latency_by_node": {"hubu:search": 500, "gongbu:snapshot": 1500, "libu:memory": 200},
    })
    print(f"  记录: {results}")
    
    # Test 2: 记录失败任务
    print("\n📋 记录失败任务")
    results = bus.emit("evolution.record", {
        "dag_id": "test-dag-2",
        "task": "慢速浏览器采集",
        "duration_ms": 35000,
        "node_count": 3,
        "success_count": 1,
        "fail_count": 2,
        "total_tokens": 5000,
        "skill_chain": ["gongbu:snapshot", "hubu:search"],
        "error_paths": ["gongbu:snapshot"],
        "latency_by_node": {"gongbu:snapshot": 30000, "hubu:search": 300},
    })
    print(f"  记录: {results}")
    
    # Test 3: Review
    print("\n📋 自动Review")
    results = bus.emit("evolution.review", {})
    print(f"  Review: changes={len(results[0][1].get('changes',[]))}")
    
    # Test 4: 推荐
    print("\n📋 推荐")
    results = bus.emit("evolution.recommend", {"task_type": "search"})
    if results:
        aid, r = results[0]
        print(f"  推荐: top={r.get('top_pick')}")
    
    # Test 5: 刑部重试判断
    print("\n📋 刑部重试")
    results = bus.emit("ministry.xingbu.retry", {"skill": "gongbu:snapshot"})
    if results:
        aid, r = results[0]
        print(f"  重试: should={r.get('should_retry')} confidence={r.get('confidence')}")
    
    # Test 6: 刑部降级
    print("\n📋 刑部降级")
    results = bus.emit("ministry.xingbu.fallback", {"skill": "gongbu:snapshot"})
    if results:
        aid, r = results[0]
        print(f"  降级: alternatives={r.get('alternatives')}")
    
    # Test 7: 报告
    print("\n📋 进化报告")
    report = evo.get_report()
    print(report[:400])
    
    # Test 8: 统计
    stats = bus.get_stats()
    print(f"\n📊 系统: {stats['actors']['total']} actors")
    
    print("\n✅ 第4期测试完成")
    return evo


if __name__ == "__main__":
    test_phase4()
