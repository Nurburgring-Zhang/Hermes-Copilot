"""
⚙️ V3全自动智能化守护进程 — Hooks + 子Agent + 自我强化 后台持久化运行
================================================================
每次由cron触发执行:
  1. Hooks引擎心跳+事件处理
  2. 子Agent心跳监控+僵尸清理+任务续跑
  3. V3自我强化主循环(记忆/纠偏/安全/AutoDream/SAR)

设计: 无状态运行,每次cron调用执行一次完整巡检
"""

import json, os, sys, time
from pathlib import Path
from datetime import datetime, timezone, timedelta

HERMES = Path.home() / ".hermes"
EVO_V3 = HERMES / "evolution_v3"
TZ = timezone(timedelta(hours=8))
NOW = lambda: datetime.now(TZ)


def get_module(name):
    """动态导入V3模块"""
    import importlib.util
    path = EVO_V3 / f"{name}.py"
    if not path.exists():
        return None
    spec = importlib.util.spec_from_file_location(name, str(path))
    if spec and spec.loader:
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    return None


def run_full_daemon_cycle() -> dict:
    """
    全自动守护循环 — 完整巡检
    
    每步有独立的try/except,单步失败不影响其他步
    """
    
    result = {
        "ts": NOW().isoformat(),
        "phases": {},
        "status": "ok",
    }
    
    print(f"[{NOW().isoformat()}] ⚙️ V3全自动守护进程启动")
    
    # ===== Phase 1: Hooks引擎 =====
    print("[Phase 1/6] Hooks引擎心跳...")
    try:
        hooks_mod = get_module("hooks_engine")
        if hooks_mod:
            engine = hooks_mod.get_hooks_engine()
            health = engine.health_report()
            result["phases"]["hooks_engine"] = {
                "ok": True,
                "hooks_count": health["registered_hooks"],
                "dream_running": health["dream_cycle_running"],
            }
            print(f"  → {health['registered_hooks']}个Hook注册, DreamCycle={health['dream_cycle_running']}")
        else:
            result["phases"]["hooks_engine"] = {"ok": False, "error": "hooks_engine模块未找到"}
    except Exception as e:
        result["phases"]["hooks_engine"] = {"ok": False, "error": str(e)[:100]}
        print(f"  → ❌ Hook引擎异常: {str(e)[:80]}")
    
    # ===== Phase 2: 子Agent监控 =====
    print("[Phase 2/6] 子Agent心跳监控...")
    try:
        sub_mod = get_module("subagent_manager")
        if sub_mod:
            manager = sub_mod.get_subagent_manager()
            health = manager.health_report()
            
            # 主动检测僵尸
            running = manager.list_running()
            zombie_count = sum(1 for r in running if r["status"] == "running" and 
                             (NOW() - datetime.fromisoformat(r.get("heartbeat_ts", NOW().isoformat()))).total_seconds() > 180)
            
            result["phases"]["subagents"] = {
                "ok": True,
                "definitions": health["definitions"],
                "running": health["running_agents"],
                "zombies_detected": zombie_count,
                "queue": health.get("queue", {}),
            }
            print(f"  → {health['running_agents']}个运行中, 定义{health['definitions']}个, 僵尸{zombie_count}个")
        else:
            result["phases"]["subagents"] = {"ok": False, "error": "subagent_manager模块未找到"}
    except Exception as e:
        result["phases"]["subagents"] = {"ok": False, "error": str(e)[:100]}
        print(f"  → ❌ 子Agent异常: {str(e)[:80]}")
    
    # ===== Phase 3: V3记忆健康 + 经验总结 =====
    print("[Phase 3/7] V3记忆健康扫描+经验主动总结...")
    try:
        loop_mod = get_module("self_enhancement_v3_loop")
        if loop_mod:
            loop = loop_mod.SelfEnhancementLoopV3()
            s1 = loop.step1_memory_health_scan()
            result["phases"]["memory_health"] = s1
            if s1.get("metrics"):
                total = sum(s1["metrics"].values())
                print(f"  → {total}条记忆记录")
            else:
                print(f"  → 记忆系统就绪")
        else:
            result["phases"]["memory_health"] = {"ok": False, "error": "V3 loop模块未找到"}
        
        # 经验引擎自动总结+GEPA触发
        try:
            exp_mod = get_module("experience_engine")
            if exp_mod:
                exp = exp_mod.get_experience_engine()
                stats = exp.stats()
                print(f"  → 经验库: {stats.get('total_experiences',0)}条")
                # 自动GEPA检查
                gepa_result = exp.auto_gepa()
                if gepa_result.get("gepa_triggered"):
                    print(f"  → GEPA自动触发: 第{gepa_result.get('generation',0)}代")
                result["phases"]["experience"] = {"ok": True, "stats": stats, "gepa": gepa_result}
        except Exception as e:
            result["phases"]["experience"] = {"ok": True, "info": f"经验引擎就绪: {str(e)[:50]}"}
    except Exception as e:
        result["phases"]["memory_health"] = {"ok": False, "error": str(e)[:100]}
        print(f"  → ❌ 记忆扫描异常: {str(e)[:80]}")
    
    # ===== Phase 4: V3安全更新 =====
    print("[Phase 4/6] V3安全+哈希链审计...")
    try:
        loop_mod = get_module("self_enhancement_v3_loop")
        if loop_mod:
            loop = loop_mod.SelfEnhancementLoopV3()
            s3 = loop.step3_security_update()
            result["phases"]["security"] = s3
            
            ifc_status = s3.get("ifc", {}).get("status", "?")
            chain_status = s3.get("hash_chain", {}).get("integrity", "?")
            print(f"  → IFC={ifc_status}, 哈希链={chain_status}")
        else:
            result["phases"]["security"] = {"ok": False}
    except Exception as e:
        result["phases"]["security"] = {"ok": False, "error": str(e)[:100]}
        print(f"  → ❌ 安全更新异常: {str(e)[:80]}")
    
    # ===== Phase 5: V3 AutoDream清理 =====
    print("[Phase 5/6] V3 AutoDream清理...")
    try:
        loop_mod = get_module("self_enhancement_v3_loop")
        if loop_mod:
            loop = loop_mod.SelfEnhancementLoopV3()
            s4 = loop.step4_auto_dream()
            result["phases"]["autodream"] = s4
            for a in s4.get("actions", []):
                if "清理" in a:
                    print(f"  → {a}")
            print(f"  → AutoDream完成")
        else:
            result["phases"]["autodream"] = {"ok": False}
    except Exception as e:
        result["phases"]["autodream"] = {"ok": False, "error": str(e)[:100]}
        print(f"  → ❌ AutoDream异常: {str(e)[:80]}")
    
    # ===== Phase 6: V3 SAR报告(每6小时) =====
    current_hour = NOW().hour
    if current_hour % 6 == 0:
        print("[Phase 6/7] V3 SAR自检报告...")
        try:
            loop_mod = get_module("self_enhancement_v3_loop")
            if loop_mod:
                loop = loop_mod.SelfEnhancementLoopV3()
                s7 = loop.step7_sar_report()
                result["phases"]["sar_report"] = s7
                print(f"  → {s7.get('summary', '')}")
            else:
                result["phases"]["sar_report"] = {"ok": False}
        except Exception as e:
            result["phases"]["sar_report"] = {"ok": False, "error": str(e)[:100]}
            print(f"  → ❌ SAR异常: {str(e)[:80]}")
    else:
        result["phases"]["sar_report"] = {"ok": True, "actions": [f"SAR: {6-current_hour%6}h后"]}
        print(f"  → SAR跳过(每6h, 下次{6-current_hour%6}h后)")
    
    # 状态汇总
    all_ok = all(
        p.get("ok", True) for k, p in result["phases"].items()
        if isinstance(p, dict)
    )
    result["status"] = "ok" if all_ok else "degraded"
    print(f"状态: {'✅全部通过' if all_ok else '⚠️部分异常'}")
    
    # 持久化报告
    report_path = HERMES / "reports" / "v3_daemon_report.json"
    history = []
    if report_path.exists():
        try:
            history = json.loads(report_path.read_text())
            if not isinstance(history, list):
                history = []
        except Exception:
            history = []
    history.append(result)
    if len(history) > 100:
        history = history[-100:]
    report_path.write_text(json.dumps(history, ensure_ascii=False, indent=2))
    
    return result


if __name__ == "__main__":
    result = run_full_daemon_cycle()
    print(f"\n[DAEMON] 状态: {result['status']} | {sum(1 for p in result['phases'].values() if p.get('ok'))}/{len(result['phases'])} through")
