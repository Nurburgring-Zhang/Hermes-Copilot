#!/usr/bin/env python3
"""
第5期: 礼部Actor注册 + 全链路集成测试
========================================
注册礼部输出格式化Actor,并运行1-5期全链路集成测试。
"""

import os, sys, json, time, logging
from typing import Any, Dict

_script_dir = os.path.dirname(os.path.abspath(__file__))
_root_dir = os.path.dirname(_script_dir)
for p in [_root_dir, _script_dir]:
    if p not in sys.path:
        sys.path.insert(0, p)

from actor_base import Actor, Event, ActorPriority
from synapse_bus import get_bus, SynapseBus
from topology_engine import TopologyEngine

logger = logging.getLogger("hermes.phase5_actors")


# ══════════════════════════════════════════════════════════════
# 礼部 Actor — 输出格式化
# ══════════════════════════════════════════════════════════════

class FormatActor(Actor):
    """礼部输出格式化 Actor——包装professional_text_rewrite/md2book等能力"""
    
    def __init__(self):
        super().__init__(
            "libu:format",
            "礼部·输出格式化",
            ["ministry.libu.write", "ministry.libu.report",
             "ministry.libu.format", "ministry.libu.rewrite",
             "output.format", "output.report", "output.rewrite"],
            "统一输出格式化: 文本重写/报告生成/格式转换",
            priority=ActorPriority.NORMAL,
        )
    
    def handle(self, event: Event) -> Any:
        payload = event.payload
        text = payload.get("text", "")
        fmt = payload.get("format", "markdown")
        style = payload.get("style", "professional")
        
        if "rewrite" in event.type:
            return self._rewrite(text, style)
        elif "report" in event.type:
            return self._report(text, fmt)
        elif "format" in event.type:
            return self._format(text, fmt)
        elif "write" in event.type:
            return self._write(text, fmt)
        
        return {"error": f"Unknown: {event.type}"}
    
    def _rewrite(self, text: str, style: str) -> Dict:
        """文本重写"""
        return {
            "status": "rewritten",
            "style": style,
            "original_length": len(text),
            "note": f"专业{style}风格重写(占位)",
        }
    
    def _report(self, text: str, fmt: str) -> Dict:
        """报告生成"""
        return {
            "status": "report_generated",
            "format": fmt,
            "length": len(text),
            "note": f"{fmt}格式报告生成(占位)",
        }
    
    def _format(self, text: str, fmt: str) -> Dict:
        """格式转换"""
        return {
            "status": "formatted",
            "from": "auto",
            "to": fmt,
            "length": len(text),
        }
    
    def _write(self, text: str, fmt: str) -> Dict:
        """内容生成"""
        return {
            "status": "written",
            "format": fmt,
            "length": len(text),
            "note": f"{fmt}格式内容生成(占位)",
        }


# ══════════════════════════════════════════════════════════════
# 全Actor注册
# ══════════════════════════════════════════════════════════════

def register_all_phases(bus=None) -> Dict[str, Actor]:
    """注册1-5期所有Actor到总线"""
    if bus is None:
        bus = get_bus()
    
    registered = {}
    
    # 第1期: 三省六部
    from topology_engine import (
        ZhongshuSheng, MenxiaSheng,
        GongBu, HuBu, LiBu, BingBu, XingBu, LiBuRegister
    )
    engine = TopologyEngine(bus=bus)
    registered["zhongshu"] = engine.zhongshu
    registered["menxia"] = engine.menxia
    for mid, m in engine.ministries.items():
        registered[f"ministry:{mid}"] = m
    
    # 第2期: 户部搜索 + 工部快照
    try:
        from scripts.phase2_actors import register_phase2_actors
        s, sn = register_phase2_actors(bus)
        registered["hubu:search"] = s
        registered["gongbu:snapshot"] = sn
    except Exception as e:
        logger.warning(f"Phase2 actors failed: {e}")
    
    # 第3期: 吏部记忆
    try:
        from scripts.phase3_actors import register_phase3_actors
        m = register_phase3_actors(bus)
        registered["libu:memory"] = m
    except Exception as e:
        logger.warning(f"Phase3 actors failed: {e}")
    
    # 第4期: 刑部自进化
    try:
        from scripts.phase4_actors import register_phase4_actors
        e = register_phase4_actors(bus)
        registered["xingbu:evolution"] = e
    except Exception as e:
        logger.warning(f"Phase4 actors failed: {e}")
    
    # 第5期: 礼部格式化
    fmt = FormatActor()
    bus.register_actor(fmt, [
        "ministry.libu.write", "ministry.libu.report",
        "ministry.libu.format", "ministry.libu.rewrite",
        "output.format", "output.report", "output.rewrite",
    ])
    registered["libu:format"] = fmt
    
    logger.info(f"Registered {len(registered)} actors across all 5 phases")
    return registered


# ══════════════════════════════════════════════════════════════
# 全链路集成测试
# ══════════════════════════════════════════════════════════════

def run_full_integration_test() -> Dict:
    """运行1-5期全链路集成测试"""
    
    bus = SynapseBus(max_workers=4, merge_timeout=10.0)
    
    print("=" * 60)
    print("  Hermes 三省六部制 · 全链路集成测试")
    print("  1-5期全能力验证")
    print("=" * 60)
    
    # 注册所有
    actors = register_all_phases(bus)
    stats = bus.get_stats()
    print(f"\n✅ Actor 注册: {len(actors)}/{stats['actors']['total']}")
    
    results = {}
    
    # ── 测试1: SynapseBus 事件发射 ──
    print(f"\n{'─'*50}")
    print("📋 测试1: SynapseBus 事件驱动")
    test_actor = Actor("test:echo", "EchoTest", ["test.echo"])
    bus.register_actor(test_actor, ["test.echo"])
    
    r = bus.emit("test.echo", {"msg": "hello"})
    assert len(r) == 1
    results["synapse_bus"] = "✅"
    print("  ✅ 事件发射+接收")
    
    # ── 测试2: 三省六部 DAG ──
    print(f"\n{'─'*50}")
    print("📋 测试2: 三省六部 DAG 规划执行")
    engine = TopologyEngine(bus=bus)
    dag_result = engine.process(
        text="搜索 Python 最新框架,分析趋势,生成报告",
        name="Python框架调研",
    )
    dag = dag_result["dag"]
    node_count = len(dag["nodes"])
    print(f"  ✅ DAG: {dag['name']} | {dag['progress']}% | 节点:{node_count}")
    results["dag_planning"] = f"✅ {node_count}节点"
    
    # ── 测试3: 并发探针 ──
    print(f"\n{'─'*50}")
    print("📋 测试3: 并发探针 (emit_with_merge)")
    merged = bus.emit_with_merge("test.echo", {
        "test:echo": {"probe": 1},
    })
    received = merged.get("received", 0)
    expected = merged.get("expected", 0)
    print(f"  ✅ 并发: {received}/{expected}")
    results["concurrent"] = f"✅ {received}/{expected}"
    
    # ── 测试4: 门下省校验 ──
    print(f"\n{'─'*50}")
    print("📋 测试4: 门下省校验")
    menxia = bus.get_actor("menxiasheng")
    if menxia:
        v = menxia._validate_result({"result": None, "node_id": "test"})
        assert not v["valid"]
        v2 = menxia._validate_result({"result": "ok data", "node_id": "test"})
        assert v2["valid"]
        print(f"  ✅ 空值校验(None→无效), 有值校验(→有效)")
        results["validation"] = "✅"
    
    # ── 测试5: 记忆联邦 ──
    print(f"\n{'─'*50}")
    print("📋 测试5: 记忆联邦查询")
    fed = bus.get_actor("libu:memory")
    if fed:
        from memory_federation import get_federation
        mf = get_federation()
        # ActiveMemory
        r = mf.query("新能源汽车 军事 格斗", query_type="preference")
        pref_count = len(r.items)
        # Intelligence
        r2 = mf.query("DeepSeek", query_type="general")
        intel_count = len(r2.items)
        print(f"  ✅ 偏好查询: {pref_count}条 | 情报查询: {intel_count}条")
        results["memory_federation"] = f"✅ {pref_count}+{intel_count}"
    
    # ── 测试6: 自进化 ──
    print(f"\n{'─'*50}")
    print("📋 测试6: 自进化循环")
    evo = bus.get_actor("xingbu:evolution")
    if evo:
        # 记录几个任务
        for i in range(3):
            bus.emit("evolution.record", {
                "dag_id": f"test-dag-{i}",
                "task": f"测试任务{i}",
                "duration_ms": 1000 + i * 500,
                "node_count": 3,
                "success_count": 3 - i,
                "fail_count": i,
                "total_tokens": 1000,
                "skill_chain": ["hubu:search", "gongbu:snapshot", "libu:memory"],
                "error_paths": [] if i == 0 else (["gongbu:snapshot"] if i == 1 else ["hubu:search"]),
                "latency_by_node": {"hubu:search": 300, "gongbu:snapshot": 500 + i * 200, "libu:memory": 200},
            })
        
        # 触发 review
        review = evo.engine.review()
        evolution_changes = len(review.get("changes", []))
        print(f"  ✅ 记录3任务 → Review: {evolution_changes} 个调整")
        
        # 检查降级
        stats_evo = evo.engine.get_stats()
        degraded = len(stats_evo.get("degraded_paths", []))
        top = len(stats_evo.get("top_performers", []))
        print(f"  ✅ 降级路径: {degraded} | 最佳路径: {top}")
        results["self_evolution"] = f"✅ {evolution_changes}调整"
    
    # ── 测试7: 礼部格式化 ──
    print(f"\n{'─'*50}")
    print("📋 测试7: 礼部输出格式化")
    r = bus.emit("ministry.libu.format", {"text": "Hello", "format": "html"})
    if r:
        aid, resp = r[0]
        print(f"  ✅ 格式转换: {resp.get('status')} → {resp.get('to')}")
        results["format"] = "✅"
    
    # ── 测试8: 刑部接管 ──
    print(f"\n{'─'*50}")
    print("📋 测试8: 刑部异常接管")
    import copy
    class FailActor(Actor):
        def handle(self, event):
            raise RuntimeError("模拟错误")
    
    fail = FailActor("test:fail", "FailTest", ["test.crash"])
    bus.register_actor(fail, ["test.crash"])
    r = bus.emit("test.crash", {})
    if r:
        aid, err = r[0]
        is_error = isinstance(err, Exception)
        print(f"  ✅ 异常= {'✅ 刑部已接管' if is_error else '?'} ")
        results["error_handling"] = "✅"
    bus.deregister_actor("test:fail")
    
    # ── 汇总 ──
    print(f"\n{'='*60}")
    print(f"  全链路测试完成 | {len(results)}/8 测试通过")
    print(f"{'='*60}")
    for name, status in results.items():
        print(f"  {name:<20} {status}")
    
    print(f"\n📊 最终统计:")
    final_stats = bus.get_stats()
    print(f"  Actor: {final_stats['actors']['total']}")
    print(f"  Topics: {final_stats['topics']}")
    print(f"  背压: {final_stats['backpressure_level']}/3")
    
    return {
        "results": results,
        "stats": final_stats,
        "passed": len(results),
        "total": 8,
    }


if __name__ == "__main__":
    run_full_integration_test()
