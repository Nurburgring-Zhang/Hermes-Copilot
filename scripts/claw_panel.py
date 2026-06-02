#!/usr/bin/env python3
"""
ClawPanel — Hermes 三省六部 CLI 控制面板
=============================================
无需浏览器,直接在终端查看系统状态,Actor拓扑,事件统计。
支持: 状态查看,Actor管理,配置热更新,一键测试。

用法:
    python3 claw_panel.py            # 完整面板
    python3 claw_panel.py --status   # 仅状态摘要
    python3 claw_panel.py --actors   # Actor列表
    python3 claw_panel.py --topology # 三省六部状态
    python3 claw_panel.py --memory   # 记忆联邦状态
    python3 claw_panel.py --test     # 运行集成测试
    python3 claw_panel.py --watch    # 实时监控(每5秒刷新)
"""

import os, sys, json, time, yaml, logging
from datetime import datetime
from typing import Any, Dict, List, Optional

# ── 路径 ──────────────────────────────────────────────────────────
_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_scripts = os.path.join(_root, "scripts")
for p in [_root, _scripts]:
    if p not in sys.path:
        sys.path.insert(0, p)

logging.basicConfig(level=logging.WARNING)


def _try_import(module: str, attr: str = None):
    """安全导入"""
    try:
        mod = __import__(module, fromlist=[attr] if attr else [])
        return getattr(mod, attr) if attr else mod
    except:
        return None


class ClawPanel:
    """CLI 控制面板"""
    
    def __init__(self):
        self.bus = _try_import("synapse_bus", "get_bus")
        if self.bus:
            self.bus = self.bus()
        self.topology = _try_import("topology_engine", "TopologyEngine")
        self.fed = _try_import("memory_federation", "get_federation")
        if self.fed:
            self.fed = self.fed()
    
    # ── 主要视图 ──────────────────────────────────────────────────
    
    def show_full(self):
        """完整面板"""
        self._header("Hermes 三省六部控制面板")
        self.show_system_status()
        self.show_actor_summary()
        self.show_topology_summary()
        self.show_memory_summary()
        self.show_evolution_summary()
        self._footer()
    
    def show_system_status(self):
        """系统状态摘要"""
        self._section("系统状态")
        
        if self.bus:
            stats = self.bus.get_stats()
            actors = stats.get("actors", {})
            print(f"  Actors:    {actors.get('total', '?')} (活跃{actors.get('active', '?')} 挂起{actors.get('suspended', '?')} 错误{actors.get('error', '?')})")
            print(f"  Topics:    {stats.get('topics', '?')}")
            print(f"  背压等级:  {stats.get('backpressure_level', '?')}/3")
            print(f"  等待窗口:  {stats.get('pending_windows', '?')}")
        else:
            print("  ⚠️ SynapseBus 未加载")
        
        # 系统文件
        files = {
            "actor_base.py": os.path.exists(os.path.join(_root, "actor_base.py")),
            "synapse_bus.py": os.path.exists(os.path.join(_root, "synapse_bus.py")),
            "topology_engine.py": os.path.exists(os.path.join(_root, "topology_engine.py")),
            "memory_federation.py": os.path.exists(os.path.join(_root, "memory_federation.py")),
            "topology.yaml": os.path.exists(os.path.join(_root, "topology.yaml")),
        }
        loaded = sum(1 for v in files.values() if v)
        print(f"  模块加载:  {loaded}/{len(files)}")
    
    def show_actor_summary(self):
        """Actor 列表"""
        self._section("Actor 注册表")
        
        if not self.bus:
            print("  ⚠️ 无法获取")
            return
        
        actors = self.bus.list_actors()
        if not actors:
            print("  (无 Actor 注册)")
            return
        
        # 按优先级分组
        sorted_a = sorted(actors, key=lambda a: (a.priority.value, a.id))
        for a in sorted_a:
            caps = list(a.capabilities)[:3]
            m = a.metrics
            status_icon = {"ACTIVE": "🟢", "BUSY": "🟡", "SUSPENDED": "⚪", "ERROR": "🔴", "RETIRED": "⚫"}
            icon = status_icon.get(a.status.name, "❓")
            calls = m.total_calls if m else 0
            rate = f"{m.success_rate*100:.0f}%" if m and m.total_calls > 0 else "-"
            print(f"  {icon} {a.id:<25} {a.status.name:<10} 调用{calls:<4} 成功率{rate:<5} caps={caps}")
    
    def show_topology_summary(self):
        """三省六部状态"""
        self._section("三省六部")
        
        # 读取 YAML
        yaml_path = os.path.join(_root, "topology.yaml")
        if os.path.exists(yaml_path):
            try:
                with open(yaml_path) as f:
                    cfg = yaml.safe_load(f) or {}
                plan = cfg.get("planning", {})
                valid = cfg.get("validation", {})
                mins = cfg.get("ministries", {})
                print(f"  中书省: agent={plan.get('agent','?')} threshold={plan.get('threshold','?')}")
                print(f"  门下省: format={valid.get('check_format','?')} cost={valid.get('check_cost','?')} retry={valid.get('auto_retry','?')}")
                for mid, mcfg in mins.items():
                    w = mcfg.get("weight", "?")
                    t = mcfg.get("timeout", "?")
                    adj = " ⚡自调整" if mcfg.get("_auto_adjusted") else ""
                    print(f"  {mid:<12} weight={w:<8} timeout={t}s{adj}")
            except Exception as e:
                print(f"  ⚠️ YAML读取失败: {e}")
        else:
            print("  (topology.yaml 未找到)")
    
    def show_memory_summary(self):
        """记忆联邦状态"""
        self._section("记忆联邦")
        
        if self.fed:
            sources = self.fed.get_available_sources()
            health = self.fed.health_check()
            for src in sources:
                name = src.split(" ")[0]
                h = health.get(name, False)
                icon = "✅" if h else "❌"
                print(f"  {icon} {src}")
        else:
            print("  ⚠️ MemoryFederation 未加载")
        
        # 数据库文件状态
        dbs = [
            ("state.db", os.path.join(os.path.expanduser("~/.hermes"), "state.db")),
            ("intelligence.db", os.path.join(os.path.expanduser("~/.hermes"), "intelligence.db")),
            ("main.sqlite", os.path.join(os.path.expanduser("~/.hermes"), "memory", "main.sqlite")),
        ]
        for name, path in dbs:
            if os.path.exists(path):
                sz = os.path.getsize(path) / 1024 / 1024
                print(f"  📁 {name:<20} {sz:.0f} MB")
            else:
                print(f"  📁 {name:<20} 不存在")
    
    def show_evolution_summary(self):
        """自进化状态"""
        self._section("自进化引擎")
        
        evo_actor = None
        if self.bus:
            evo_actor = self.bus.get_actor("xingbu:evolution")
        
        if evo_actor and hasattr(evo_actor, 'engine'):
            engine = evo_actor.engine
            stats = engine.get_stats()
            print(f"  总任务数:   {stats['total_tasks']}")
            print(f"  近期成功率: {stats['recent_success_rate']}%")
            print(f"  平均延迟:   {stats['avg_latency_ms']}ms")
            
            if stats['degraded_paths']:
                print(f"  降级路径:   {len(stats['degraded_paths'])}条")
                for p in stats['degraded_paths'][:3]:
                    print(f"    ☠️ {p['key']} (权重:{p['weight']})")
            if stats['top_performers']:
                print(f"  最佳表现:   {len(stats['top_performers'])}条")
                for p in stats['top_performers'][:3]:
                    print(f"    🏆 {p['key']} (评分:{p['score']})")
        else:
            print("  ⚠️ 自进化引擎未加载或未运行")
    
    # ── 操作 ──────────────────────────────────────────────────────
    
    def hot_reload_topology(self):
        """热更新拓扑 YAML"""
        if self.topology:
            try:
                engine = self.topology()
                engine.hot_reload()
                print("✅ topology.yaml 已热更新")
            except Exception as e:
                print(f"❌ 热更新失败: {e}")
        else:
            print("⚠️ TopologyEngine 未加载")
    
    def run_test(self):
        """运行测试"""
        print("\n🔬 运行三省六部集成测试...\n")
        try:
            from scripts.synapse_bus_bootstrap import full_test
            full_test()
        except Exception as e:
            print(f"  ❌ 测试失败: {e}")
    
    def show_topology_yaml(self):
        """显示 YAML 内容"""
        yaml_path = os.path.join(_root, "topology.yaml")
        if os.path.exists(yaml_path):
            with open(yaml_path) as f:
                print(f.read())
        else:
            print("topology.yaml 不存在")
    
    def watch(self, interval: int = 5):
        """实时监控"""
        try:
            while True:
                os.system("clear" if os.name == "posix" else "cls")
                print(f"Hermes 三省六部 实时监控 (刷新每{interval}s, Ctrl+C退出)")
                print(f"{'='*50}")
                self.show_system_status()
                self.show_actor_summary()
                print(f"\n{'='*50}")
                print(f"上次刷新: {datetime.now().strftime('%H:%M:%S')}")
                time.sleep(interval)
        except KeyboardInterrupt:
            print("\n监控已停止")
    
    # ── 格式化 ──────────────────────────────────────────────────────
    
    def _header(self, title: str):
        w = 60
        print(f"\n{'='*w}")
        print(f"  {title}")
        print(f"{'='*w}")
        print(f"  时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'='*w}")
    
    def _section(self, title: str):
        print(f"\n── {title} {'─'*(40-len(title))}")
    
    def _footer(self):
        print(f"\n{'='*60}")
        print(f"  Hermes 三省六部制 v1.0 | SynapseBus + Actor模型 + 记忆联邦 + 自进化")
        print(f"  https://github.com/hermes/hermes-agent")
        print(f"{'='*60}\n")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="ClawPanel - Hermes 三省六部 CLI 控制面板")
    parser.add_argument("--status", action="store_true", help="系统状态")
    parser.add_argument("--actors", action="store_true", help="Actor列表")
    parser.add_argument("--topology", action="store_true", help="三省六部状态")
    parser.add_argument("--memory", action="store_true", help="记忆联邦状态")
    parser.add_argument("--evolution", action="store_true", help="自进化状态")
    parser.add_argument("--yaml", action="store_true", help="显示 YAML 配置")
    parser.add_argument("--reload", action="store_true", help="热更新 YAML")
    parser.add_argument("--test", action="store_true", help="运行测试")
    parser.add_argument("--watch", type=int, nargs="?", const=5, metavar="N", help="实时监控(每N秒)")
    args = parser.parse_args()
    
    panel = ClawPanel()
    
    if args.yaml:
        panel.show_topology_yaml()
    elif args.reload:
        panel.hot_reload_topology()
    elif args.test:
        panel.run_test()
    elif args.watch:
        panel.watch(args.watch)
    elif args.actors:
        panel._header("Actor 注册表")
        panel.show_actor_summary()
    elif args.topology:
        panel._header("三省六部状态")
        panel.show_topology_summary()
    elif args.memory:
        panel._header("记忆联邦")
        panel.show_memory_summary()
    elif args.evolution:
        panel._header("自进化引擎")
        panel.show_evolution_summary()
    elif args.status:
        panel._header("系统状态")
        panel.show_system_status()
    else:
        panel.show_full()


if __name__ == "__main__":
    main()
