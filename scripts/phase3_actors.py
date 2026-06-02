#!/usr/bin/env python3
"""
第3期: 注册 Memory Federation 到 SynapseBus
==============================================
将 MemoryFederation 作为"吏部"注册到三省六部体系。
"""

import os, sys, json, logging
from typing import Any, Dict

_script_dir = os.path.dirname(os.path.abspath(__file__))
_root_dir = os.path.dirname(_script_dir)
for p in [_root_dir, _script_dir]:
    if p not in sys.path:
        sys.path.insert(0, p)

from actor_base import Actor, Event, ActorPriority
from synapse_bus import get_bus
from memory_federation import MemoryFederation, get_federation

logger = logging.getLogger("hermes.phase3_actors")


class MemoryActor(Actor):
    """吏部记忆 Actor — 包装 MemoryFederation"""
    
    def __init__(self):
        super().__init__(
            "libu:memory",
            "吏部·记忆联邦",
            ["ministry.libureg.search", "ministry.libureg.remember",
             "memory.query", "memory.search", "memory.remember",
             "memory.preference", "memory.vector"],
            "统一记忆联邦: FTS5+ActiveMemory+Intelligence+RAG",
            priority=ActorPriority.CRITICAL,
            max_concurrent=3,
        )
        self.federation = get_federation()
    
    def handle(self, event: Event) -> Any:
        payload = event.payload
        
        if "remember" in event.type:
            content = payload.get("content", "")
            tags = payload.get("tags", [])
            ok = self.federation.remember(content, source="synapse_bus", tags=tags)
            return {"status": "remembered" if ok else "failed"}
        
        if "preference" in event.type:
            text = payload.get("text", "")
            result = self.federation.query(text, query_type="preference")
            return result.to_dict()
        
        if "vector" in event.type:
            text = payload.get("text", "")
            result = self.federation.query(text, query_type="vector")
            return result.to_dict()
        
        # search / query
        text = payload.get("text", "")
        query_type = payload.get("query_type", "general")
        limit = payload.get("limit", 10)
        
        result = self.federation.query(text, query_type=query_type, limit=limit)
        return result.to_dict()


def register_phase3_actors(bus=None):
    """注册第3期记忆 Actor"""
    if bus is None:
        bus = get_bus()
    
    memory = MemoryActor()
    bus.register_actor(memory, [
        "ministry.libureg.search",
        "ministry.libureg.remember",
        "memory.query",
        "memory.search",
        "memory.remember",
        "memory.preference",
        "memory.vector",
    ])
    
    logger.info(f"Registered phase3 actor: {memory.id}")
    return memory


def test_phase3():
    """第3期集成测试"""
    from synapse_bus import SynapseBus
    from topology_engine import TopologyEngine
    
    bus = SynapseBus(max_workers=4)
    engine = TopologyEngine(bus=bus)
    mem_actor = register_phase3_actors(bus)
    
    print("=" * 50)
    print("第3期集成测试: 吏部·记忆联邦")
    print("=" * 50)
    
    # Test 1: 记忆搜索
    print("\n📋 记忆搜索")
    results = bus.emit("memory.search", {"text": "AI", "limit": 5})
    if results:
        aid, r = results[0]
        total = r.get("meta", {}).get("total", 0)
        print(f"  结果: {total} items")
        for item in r.get("results", [])[:3]:
            print(f"    [{item.get('source')}] {item.get('content')[:50]}")
    
    # Test 2: 偏好查询
    print("\n📋 偏好查询")
    results = bus.emit("memory.preference", {"text": "新能源汽车 军事 格斗"})
    if results:
        aid, r = results[0]
        for item in r.get("results", [])[:3]:
            print(f"    {item.get('content')[:60]}")
    
    # Test 3: 记忆写入
    print("\n📋 记忆写入")
    results = bus.emit("memory.remember", {
        "content": "用户偏好: Rust/TS/AI/新能源汽车/格斗/军事",
        "tags": ["preference", "user"],
    })
    if results:
        aid, r = results[0]
        print(f"  写入: {r.get('status')}")
    
    # Test 4: 全源查询
    print("\n📋 全源查询(所有记忆后端)")
    results = bus.emit("memory.query", {
        "text": "Hermes",
        "query_type": "all",
        "limit": 5,
    })
    if results:
        aid, r = results[0]
        total = r.get("meta", {}).get("total", 0)
        sources = r.get("meta", {}).get("sources_used", [])
        print(f"  结果: {total} items from {sources}")
    
    # Test 5: 三省六部调度
    print("\n📋 三省六部 DAG")
    dag_result = engine.process(
        text="搜索我的偏好设置并返回相关记忆",
        name="记忆查询任务",
    )
    print(f"  DAG: {dag_result['dag']['progress']}%")
    
    stats = bus.get_stats()
    print(f"\n📊 统计: {stats['actors']['total']} actors")
    
    print("\n✅ 第3期测试完成")
    return engine


if __name__ == "__main__":
    test_phase3()
