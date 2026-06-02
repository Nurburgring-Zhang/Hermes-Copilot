#!/usr/bin/env python3
"""
SynapseBus + 三省六部启动/测试脚本
===================================
独立启动 SynapseBus 事件总线和三省六部引擎。
支持: 启动,测试,状态查看,DAG流程演示
"""

import os, sys, json, time, logging

# ── 日志 ──────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
    ]
)

# 减少 SynapseBus/Actor 的日志噪音
logging.getLogger("hermes.synapse_bus").setLevel(logging.WARNING)
logging.getLogger("hermes.actor").setLevel(logging.WARNING)

logger = logging.getLogger("bootstrap")


def initialize_engine(yaml_path: str = None) -> 'TopologyEngine':
    """初始化并启动三省六部引擎"""
    sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
    
    from synapse_bus import SynapseBus
    from topology_engine import TopologyEngine
    
    if yaml_path is None:
        yaml_path = os.path.join(os.path.dirname(__file__), "topology.yaml")
    
    bus = SynapseBus(max_workers=4, merge_timeout=10.0)
    engine = TopologyEngine(bus=bus, yaml_path=yaml_path)
    
    logger.info("=" * 50)
    logger.info("三省六部制引擎已启动")
    logger.info("=" * 50)
    
    return engine


def test_dag_flow(engine: 'TopologyEngine'):
    """测试完整的 DAG 流程"""
    logger.info("\n📋 测试: 数据分析任务 DAG")
    
    result = engine.process(
        text="分析竞品定价策略,采集市场数据,生成分析报告",
        name="竞品定价分析",
        format="markdown",
    )
    
    dag = result["dag"]
    logger.info(f"DAG: {dag['name']} | 进度: {dag['progress']}% | 状态: {dag['status']}")
    
    for nid, node in dag["nodes"].items():
        logger.info(f"  节点 {nid}: {node['description'][:30]} → {node['status']} ({node['assigned_ministry']})")
    
    return result


def test_concurrent_demo(engine: 'TopologyEngine'):
    """演示并发事件发射 + 合并窗口"""
    from synapse_bus import get_bus
    bus = get_bus()
    
    logger.info("\n🚀 测试: 并发探针(模拟数据组+视觉组+通信组三路并行)")
    
    start = time.time()
    
    # 三路并发(通过 emit_with_merge)
    merged = bus.emit_with_merge("ministry.hubu.fetch", {
        "hubu": {"query": "实时行情", "source": "tavily"},
        "libu": {"query": "生成图表", "format": "svg"},
        "gongbu": {"query": "准备推送", "channel": "wechat"},
    }, timeout=15.0)
    
    elapsed = (time.time() - start) * 1000
    
    logger.info(f"三路并发完成 | 耗时: {elapsed:.0f}ms | 收到: {merged['received']}/{merged['expected']}")
    for actor_id, result in merged.get("results", {}).items():
        logger.info(f"  {actor_id}: {str(result)[:60]}")
    
    return merged


def test_error_handling(engine: 'TopologyEngine'):
    """测试刑部错误接管"""
    from synapse_bus import get_bus
    bus = get_bus()
    from actor_base import Actor
    
    logger.info("\n⚠️ 测试: 刑部错误接管")
    
    class FailActor(Actor):
        def handle(self, event):
            raise RuntimeError("模拟严重错误: 数据源不可达")
    
    fail = FailActor("test-fail", "故障Actor", ["test.crash"])
    bus.register_actor(fail, ["test.crash"])
    
    results = bus.emit("test.crash", {"data": "test"})
    
    xingbu = engine.ministries["xingbu"]
    errors = xingbu.get_recent_errors(5)
    
    logger.info(f"错误结果: {results}")
    logger.info(f"刑部日志: {len(errors)} 条错误记录")
    
    bus.deregister_actor("test-fail")
    return errors


def show_status(engine: 'TopologyEngine'):
    """显示引擎状态"""
    status = engine.get_status()
    
    logger.info("\n📊 三省六部状态")
    logger.info(f"  中书省: {status['zhongshu_dags']} 个DAG")
    logger.info(f"  刑部: {status['xingbu_errors']} 条错误日志")
    
    for mid, m in status["ministries"].items():
        s = m.get("status", "unknown")
        caps = m.get("capabilities", [])
        calls = m.get("metrics", {}).get("total_calls", 0)
        logger.info(f"  {mid}: {s} | {calls} calls | caps={len(caps)}")
    
    logger.info(f"  Actor统计: {status['actors']['actors']}")
    logger.info(f"  背压等级: {status['actors'].get('backpressure_level', 'N/A')}")


def full_test():
    """完整测试套件"""
    logger.info("\n" + "=" * 50)
    logger.info("三省六部制 完整集成测试")
    logger.info("=" * 50)
    
    engine = initialize_engine()
    
    # 1. 状态检查
    show_status(engine)
    
    # 2. DAG 流程
    dag_result = test_dag_flow(engine)
    assert dag_result["dag"]["status"] in ("completed", "partial")
    
    # 3. 并发演示
    merged = test_concurrent_demo(engine)
    assert merged["received"] > 0
    
    # 4. 错误处理
    errors = test_error_handling(engine)
    assert len(errors) > 0
    
    logger.info("\n" + "=" * 50)
    logger.info("✅ 全部测试通过")
    logger.info(f"  DAG节点数: {len(dag_result['dag']['nodes'])}")
    logger.info(f"  并发探针: {merged['received']}/{merged['expected']}")
    logger.info(f"  错误处理: {len(errors)} 条刑部记录")
    logger.info("=" * 50)
    
    return engine


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="SynapseBus + 三省六部启动脚本")
    parser.add_argument("--test", action="store_true", help="运行完整测试")
    parser.add_argument("--status", action="store_true", help="查看引擎状态")
    parser.add_argument("--demo", action="store_true", help="运行演示")
    args = parser.parse_args()
    
    if args.test:
        full_test()
    elif args.status:
        engine = initialize_engine()
        show_status(engine)
    elif args.demo:
        engine = initialize_engine()
        test_dag_flow(engine)
        test_concurrent_demo(engine)
        test_error_handling(engine)
    else:
        # 默认:启动 + 完整测试
        full_test()
