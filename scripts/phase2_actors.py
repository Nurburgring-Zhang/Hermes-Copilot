#!/usr/bin/env python3
"""
第2期: 注册户部(SearchUnifier) + 工部(PageSnapshot) 到 SynapseBus
====================================================================
将统一搜索和页面快照注册为 Actor,纳入三省六部体系。
"""

import os, sys, json, logging
from typing import Any, Dict, List

# 确保能导入上级和同级模块
_script_dir = os.path.dirname(os.path.abspath(__file__))
_root_dir = os.path.dirname(_script_dir)
for p in [_root_dir, _script_dir]:
    if p not in sys.path:
        sys.path.insert(0, p)

from actor_base import Actor, Event, ActorPriority
from synapse_bus import get_bus
from scripts.search_unifier import SearchUnifier, UnifiedResponse
from scripts.page_snapshot import PageSnapshot

logger = logging.getLogger("hermes.phase2_actors")


# ══════════════════════════════════════════════════════════════
# 户部 Actor — 搜索
# ══════════════════════════════════════════════════════════════

class SearchActor(Actor):
    """户部搜索 Actor — 包装 SearchUnifier"""
    
    def __init__(self):
        super().__init__(
            "hubu:search",
            "户部·统一搜索",
            ["ministry.hubu.fetch", "ministry.hubu.search", 
             "ministry.hubu.extract", "data.fetch", "data.search"],
            "多源统一搜索 + 内容提取",
            priority=ActorPriority.HIGH,
            max_concurrent=3,
        )
        self.unifier = SearchUnifier()
    
    def handle(self, event: Event) -> Any:
        payload = event.payload
        
        if "fetch" in event.type:
            # 数据获取: 搜索 + 内容提取
            query = payload.get("query", "")
            sources = payload.get("sources", None)
            max_results = payload.get("max_results", 10)
            
            response = self.unifier.search(
                query=query,
                sources=sources,
                max_results=max_results,
            )
            return response.to_dict()
        
        elif "search" in event.type:
            # 仅搜索
            query = payload.get("query", "")
            response = self.unifier.search(query=query)
            return response.to_dict()
        
        elif "extract" in event.type:
            # 提取指定 URL 内容
            url = payload.get("url", "")
            if not url:
                return {"error": "No URL provided"}
            
            from scripts.page_snapshot import get_page_snapshot
            result = get_page_snapshot().navigate(url)
            if result.status == "ok":
                return {
                    "url": url,
                    "title": result.title,
                    "summary": result.content[:500] if result.content else "",
                    "tokens": result.tokens_estimated,
                }
            return {"error": f"Failed: {result.status}"}
        
        return {"error": f"Unknown event: {event.type}"}


# ══════════════════════════════════════════════════════════════
# 工部 Actor — 页面快照
# ══════════════════════════════════════════════════════════════

class SnapshotActor(Actor):
    """工部页面快照 Actor — 包装 PageSnapshot"""
    
    def __init__(self):
        super().__init__(
            "gongbu:snapshot",
            "工部·页面快照",
            ["ministry.gongbu.browser", "ministry.gongbu.navigate",
             "ministry.gongbu.render", "ministry.gongbu.extract",
             "page.navigate", "page.render", "page.extract"],
            "统一页面快照: navigate→render→extract",
            priority=ActorPriority.HIGH,
        )
        self.snapshot = PageSnapshot()
    
    def handle(self, event: Event) -> Any:
        payload = event.payload
        
        if "navigate" in event.type:
            url = payload.get("url", "")
            timeout = payload.get("timeout", 15)
            if not url:
                return {"error": "No URL"}
            
            result = self.snapshot.navigate(url, timeout=timeout)
            return {
                "status": result.status,
                "url": result.url,
                "title": result.title,
                "source": result.source,
                "size_bytes": result.size_bytes,
                "tokens": result.tokens_estimated,
            }
        
        elif "render" in event.type:
            mode = payload.get("mode", "compact")
            return self.snapshot.render(mode=mode)
        
        elif "extract" in event.type:
            selectors = payload.get("selectors", {})
            return self.snapshot.extract(selectors)
        
        return {"error": f"Unknown event: {event.type}"}


# ══════════════════════════════════════════════════════════════
# 注册到 SynapseBus
# ══════════════════════════════════════════════════════════════

def register_phase2_actors(bus=None):
    """注册第2期 Actor 到总线,同时注销旧的 ministry Actor 避免冲突"""
    if bus is None:
        bus = get_bus()
    
    # 注销旧的 ministry Actor(第1期占位用,现在被专用 Actor 替代)
    old_ministry_ids = ["ministry:gongbu", "ministry:hubu"]
    for mid in old_ministry_ids:
        old = bus.get_actor(mid)
        if old:
            bus.deregister_actor(mid)
            logger.info(f"Deregistered old placeholder: {mid}")
    
    # 户部搜索
    search = SearchActor()
    bus.register_actor(search, [
        "ministry.hubu.fetch",
        "ministry.hubu.search",
        "ministry.hubu.extract",
        "data.fetch",
        "data.search",
    ])
    
    # 工部快照
    snapshot = SnapshotActor()
    bus.register_actor(snapshot, [
        "ministry.gongbu.browser",
        "ministry.gongbu.navigate",
        "ministry.gongbu.render",
        "ministry.gongbu.extract",
        "page.navigate",
        "page.render",
        "page.extract",
    ])
    
    logger.info(f"Registered phase2 actors: {search.id}, {snapshot.id}")
    return search, snapshot


def test_phase2():
    """第2期集成测试"""
    from synapse_bus import get_bus, SynapseBus
    
    bus = SynapseBus(max_workers=4)
    
    # 导入三省六部
    from topology_engine import TopologyEngine
    engine = TopologyEngine(bus=bus)
    
    # 注册第2期 Actor
    search_actor, snap_actor = register_phase2_actors(bus)
    
    print("\n" + "=" * 50)
    print("第2期集成测试")
    print("=" * 50)
    
    # Test 1: 户部搜索
    print("\n📋 测试1: 户部搜索")
    results = bus.emit("ministry.hubu.fetch", {
        "query": "test query",
        "max_results": 3,
    })
    if results:
        print(f"  搜索完成: results={results}")
    else:
        print(f"  搜索无结果 (可能需要API key)")
    
    # Test 2: 工部导航
    print("\n📋 测试2: 工部导航")
    results = bus.emit("ministry.gongbu.navigate", {
        "url": "https://httpbin.org/html",
    })
    if results:
        aid, r = results[0]
        print(f"  导航: {r.get('status')} | {r.get('url')} | tokens={r.get('tokens')}")
    
    # Test 3: 工部渲染
    print("\n📋 测试3: 工部渲染")
    results = bus.emit("ministry.gongbu.render", {
        "mode": "compact",
    })
    if results:
        aid, r = results[0]
        print(f"  渲染: summary_len={len(r.get('summary',''))}")
    
    # Test 4: 工部提取
    print("\n📋 测试4: 工部提取")
    results = bus.emit("ministry.gongbu.extract", {
        "selectors": {"title": "h1", "links": "a"},
    })
    if results:
        aid, r = results[0]
        print(f"  提取: matched={r.get('matched_selectors')}")
    
    # Test 5: 通过三省六部 DAG 调度
    print("\n📋 测试5: 三省六部 DAG")
    dag_result = engine.process(
        text="搜索 Python 最新框架信息",
        name="Python框架调研",
    )
    print(f"  DAG: {dag_result['dag']['name']} | {dag_result['dag']['progress']}%")
    
    # Test 6: 并发探针
    print("\n📋 测试6: 并发探针")
    merged = bus.emit_with_merge("data.fetch", {
        "hubu:search": {"query": "AI news"},
        "gongbu:snapshot": {"url": "https://httpbin.org/html"},
    })
    print(f"  并发: received={merged.get('received')}/{merged.get('expected')}")
    
    # 统计
    stats = bus.get_stats()
    print(f"\n📊 统计: {stats['actors']['total']} actors, {stats['topics']} topics")
    
    print("\n✅ 第2期集成测试完成")
    return engine


if __name__ == "__main__":
    test_phase2()
