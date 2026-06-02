#!/usr/bin/env python3
"""
Hermes Dashboard — 文本三视图
==============================
1. 并发流图 — Actor拓扑,数据边权重,背压热点
2. Token预算仪表盘 — RTK动态裁剪阈值,Token消耗曲线
3. 本体漂移追踪 — 概念图演化速率,分支聚类

用法:
    python3 hermes_dashboard.py flow       # 并发流图
    python3 hermes_dashboard.py token      # Token预算
    python3 hermes_dashboard.py ontology   # 本体漂移
    python3 hermes_dashboard.py all        # 三视图全显
"""

import os, sys, json, time, math
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_scripts = os.path.join(_root, "scripts")
for p in [_root, _scripts]:
    if p not in sys.path:
        sys.path.insert(0, p)


def _safe_import(module, attr=None):
    try:
        mod = __import__(module, fromlist=[attr] if attr else [])
        return getattr(mod, attr) if attr else mod
    except:
        return None


class Dashboard:
    """文本三视图"""
    
    def __init__(self):
        self.bus = _safe_import("synapse_bus", "get_bus")
        self.bus = self.bus() if self.bus else None
        self.fed = _safe_import("memory_federation", "get_federation")
        self.fed = self.fed() if self.fed else None
        self.topology = _safe_import("topology_engine", "TopologyEngine")
        self.topology = self.topology() if self.topology else None
    
    # ══════════════════════════════════════════════════════════════
    # 视图1: 并发流图
    # ══════════════════════════════════════════════════════════════
    
    def show_flow_map(self):
        """并发流图 — Actor拓扑 + 事件流 + 背压热点"""
        print("=" * 60)
        print("  🌊 并发流图 (Concurrent Flow Map)")
        print("=" * 60)
        
        if not self.bus:
            print("  ⚠️ SynapseBus 未加载")
            return
        
        stats = self.bus.get_stats()
        actors = self.bus.list_actors()
        topics = self.bus.list_topics()
        
        # ── Actor 拓扑 ──
        print(f"\n  📍 Actor 拓扑 ({stats.get('actors', {}).get('total', 0)} 节点)")
        print(f"  {'ID':<25} {'状态':<10} {'调用':<6} {'成功率':<8} {'背压':<6}")
        print(f"  {'-'*55}")
        
        for a in sorted(actors, key=lambda x: x.priority.value):
            m = a.metrics
            calls = m.total_calls if m else 0
            rate = f"{m.success_rate*100:.0f}%" if m and calls > 0 else "-"
            bp = self.bus.backpressure.get_level(a.id) if hasattr(self.bus, 'backpressure') else 0
            bp_str = {0: "🟢", 1: "🟡", 2: "🟠", 3: "🔴"}.get(bp, "⚪")
            s_icon = {"ACTIVE": "🟢", "BUSY": "🟡", "SUSPENDED": "⚪", "ERROR": "🔴"}.get(a.status.name, "❓")
            print(f"  {s_icon} {a.id:<23} {a.status.name:<10} {calls:<6} {rate:<8} {bp_str}")
        
        # ── 事件流 ──
        print(f"\n  📨 事件流 (订阅 {stats.get('topics', 0)} 个 Topic)")
        
        # 按订阅者数量分组
        sorted_t = sorted(topics.items(), key=lambda x: -x[1])
        if sorted_t:
            print(f"  {'Topic':<30} {'订阅者':<8}")
            print(f"  {'-'*38}")
            for topic, count in sorted_t[:15]:
                bar = "█" * min(count, 10)
                print(f"  {topic:<30} {count:<4} {bar}")
            if len(sorted_t) > 15:
                print(f"  ... 及 {len(sorted_t)-15} 个更多 Topic")
        else:
            print("  (无 Topic 订阅)")
        
        # ── 合并窗口 ──
        if hasattr(self.bus, 'merge_window'):
            pending = self.bus.merge_window.get_pending_count()
            if pending > 0:
                print(f"\n  ⏳ 等待中的合并窗口: {pending}")
        
        # ── 背压热点 ──
        bp_level = stats.get('backpressure_level', 0)
        if bp_level > 0:
            print(f"\n  🔥 背压热点: 级别 {bp_level}/3")
            if bp_level >= 2:
                print("  ⚠️ 建议降级非核心 Actor")
            if bp_level >= 3:
                print("  🚨 熔断风险!立即检查 Actor 负载")
        else:
            print(f"\n  ✅ 背压正常")
    
    # ══════════════════════════════════════════════════════════════
    # 视图2: Token预算仪表盘
    # ══════════════════════════════════════════════════════════════
    
    def show_token_budget(self):
        """Token 预算仪表盘"""
        print("=" * 60)
        print("  💰 Token 预算仪表盘")
        print("=" * 60)
        
        # 尝试从 state.db 读取近期 Token 消耗
        try:
            import sqlite3
            db_path = os.path.join(os.path.expanduser("~/.hermes"), "state.db")
            if os.path.exists(db_path):
                conn = sqlite3.connect(db_path)
                
                # 最近24小时
                rows = conn.execute("""
                    SELECT SUM(token_count), AVG(token_count), COUNT(*)
                    FROM messages WHERE timestamp > ?
                """, (time.time() - 86400,)).fetchone()
                conn.close()
                
                if rows and rows[0]:
                    total_tok, avg_tok, count = rows
                    print(f"\n  📊 最近24小时 Token 统计")
                    print(f"  {'-'*40}")
                    print(f"  总消耗:     {total_tok:>10,} tokens")
                    print(f"  平均消息:   {avg_tok:>10,.0f} tokens/条")
                    print(f"  消息数:     {count:>10,} 条")
                    
                    # 模型估算成本
                    cost_per_1k = 0.002  # DeepSeek 约 $0.002/1K tokens
                    est_cost = total_tok / 1000 * cost_per_1k
                    print(f"  估算成本:   ${est_cost:.4f}")
                else:
                    print("\n  📊 无近期 Token 数据")
            else:
                print("\n  ⚠️ state.db 不存在")
        except Exception as e:
            print(f"\n  ⚠️ 读取失败: {e}")
        
        # Actor Token 统计
        if self.bus:
            actors = self.bus.list_actors()
            if actors:
                print(f"\n  🎭 Actor Token 分布")
                print(f"  {'Actor':<25} {'调用':<8} {'总耗时(ms)':<12}")
                print(f"  {'-'*45}")
                for a in sorted(actors, key=lambda x: x.metrics.total_calls if x.metrics else 0, reverse=True):
                    m = a.metrics
                    if m and m.total_calls > 0:
                        tok_est = m.total_duration_ms * 2  # 粗略估算
                        print(f"  {a.id:<25} {m.total_calls:<8} {m.total_duration_ms:<12,.0f}")
        
        # RTK 压缩建议
        print(f"\n  🔧 RTK 压缩建议")
        bp = self.bus.backpressure.get_global_level() if self.bus and hasattr(self.bus, 'backpressure') else 0
        ratios = {0: "0.5x (标准)", 1: "0.3x (轻度压缩)", 2: "0.15x (强制压缩)", 3: "0.05x (极限压缩)"}
        print(f"  当前背压: {bp}/3 → 推荐压缩比: {ratios.get(bp, '?')}")
    
    # ══════════════════════════════════════════════════════════════
    # 视图3: 本体漂移追踪
    # ══════════════════════════════════════════════════════════════
    
    def show_ontology_drift(self):
        """本体漂移追踪"""
        print("=" * 60)
        print("  🧬 本体漂移追踪 (Ontology Drift)")
        print("=" * 60)
        
        # 从自进化引擎获取轨迹
        evo = None
        if self.bus:
            evo = self.bus.get_actor("xingbu:evolution")
        
        if evo and hasattr(evo, 'engine'):
            engine = evo.engine
            stats = engine.get_stats()
            
            print(f"\n  📈 进化指标")
            print(f"  {'-'*40}")
            print(f"  已处理任务:     {stats['total_tasks']}")
            print(f"  近期成功率:     {stats['recent_success_rate']}%")
            print(f"  平均延迟:       {stats['avg_latency_ms']}ms")
            
            # 降级路径分析
            degraded = stats.get('degraded_paths', [])
            if degraded:
                print(f"\n  ☠️ 降级路径 ({len(degraded)} 条)")
                print(f"  {'路径':<30} {'权重':<8} {'失败率':<10}")
                print(f"  {'-'*48}")
                for p in degraded[:5]:
                    fail_rate = f"{p['failures']/max(p['calls'],1)*100:.0f}%"
                    print(f"  {p['key']:<30} {p['weight']:<8.2f} {fail_rate:<10}")
            else:
                print(f"\n  ✅ 无降级路径")
            
            # 最佳路径分析
            top = stats.get('top_performers', [])
            if top:
                print(f"\n  🏆 最佳路径 ({len(top)} 条)")
                for p in top[:5]:
                    print(f"  ✅ {p['key']:<30} 评分:{p['score']:<6.2f} 调用:{p['calls']}次")
            
            # 概念漂移分析
            print(f"\n  🧠 概念漂移分析")
            if stats['total_tasks'] >= 3:
                # 简单漂移检测
                recent_stats = engine._log_history[-3:] if hasattr(engine, '_log_history') else []
                if recent_stats:
                    rates = [e.success_rate for e in recent_stats]
                    drift = max(rates) - min(rates) if rates else 0
                    print(f"  近3次成功率波动: {drift*100:.0f}%")
                    if drift > 0.5:
                        print(f"  ⚠️ 高漂移 — 建议检查任务输入一致性")
                    else:
                        print(f"  ✅ 低漂移 — 系统稳定")
            else:
                print(f"  (数据不足,需至少3个任务)")
        else:
            print(f"\n  ⚠️ 自进化引擎未加载或未运行")
            
            # Fallback: 显示 YAML 配置
            yaml_path = os.path.join(os.path.expanduser("~/.hermes"), "topology.yaml")
            if os.path.exists(yaml_path):
                import yaml
                try:
                    with open(yaml_path) as f:
                        cfg = yaml.safe_load(f) or {}
                    mins = cfg.get("ministries", {})
                    print(f"\n  📋 YAML 策略 (静态)")
                    for mid, mcfg in mins.items():
                        w = mcfg.get("weight", "?")
                        adj = " ⚡自调整" if mcfg.get("_auto_adjusted") else ""
                        print(f"  {mid:<12} weight={w}{adj}")
                except:
                    pass
    
    # ══════════════════════════════════════════════════════════════
    # 三视图全显
    # ══════════════════════════════════════════════════════════════
    
    def show_all(self):
        """三视图全显"""
        self.show_flow_map()
        print()
        self.show_token_budget()
        print()
        self.show_ontology_drift()


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Hermes Dashboard 三视图")
    parser.add_argument("view", nargs="?", default="all",
                        choices=["flow", "token", "ontology", "all"],
                        help="视图类型")
    args = parser.parse_args()
    
    dash = Dashboard()
    
    if args.view == "flow":
        dash.show_flow_map()
    elif args.view == "token":
        dash.show_token_budget()
    elif args.view == "ontology":
        dash.show_ontology_drift()
    else:
        dash.show_all()


if __name__ == "__main__":
    main()
