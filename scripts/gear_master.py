#!/usr/bin/env python3
"""
⚙️ 齿轮主调度器 v1.0 — 单入口集中管理所有齿轮cron
================================================
原因：之前每个齿轮有自己的cron条目，容易混乱。
现在改为单入口cron，所有齿轮通过此脚本统一调度+互审。

每15秒运行一次（通过sleep循环实现细粒度控制）。
格林主人最高指令(2026-05-11):
  此脚本是齿轮系统的"心脏"——如果它停了，整个互审系统就停了。
"""

import json, sys, os, subprocess, time
from datetime import datetime, timezone, timedelta
from pathlib import Path

HERMES = Path("/home/administrator/.hermes")
TZ = timezone(timedelta(hours=8))
now = lambda: datetime.now(TZ)

SCRIPTS = HERMES / "scripts"
LOGS = HERMES / "logs"
REPORTS = HERMES / "reports"

# 齿轮调度表：{齿轮: (脚本, cron间隔秒数, 超时秒数)}
GEAR_SCHEDULE = {
    "G1": ("gear_enforcer.py",         60,    30),    # 每1分钟
    "G2": ("context_failsafe.py",      300,   30),    # 每5分钟
    "G4": ("context_guardian.py",      300,   30),    # 每5分钟
    "G5": ("hermes_super_guardian.py", 900,   60),    # 每15分钟
    "G6": ("gear_task_validator.py",   1800,  60),    # 每30分钟
    "G7": ("wake_guide.py",            60,    30),    # 每1分钟(被G1调用)
    "G8": ("memory_orchestrator_v3.py",300,   30),    # 每5分钟 - 三冗余记忆引擎健康检查
    "DRIVER": ("gear_task_driver.py",  60,    15),    # 每1分钟(自动续跑)
}

def run_gear(gear: str, script: str, args: list = None) -> dict:
    """运行一个齿轮脚本"""
    script_path = SCRIPTS / script
    cmd = [sys.executable, str(script_path)]
    if args:
        cmd.extend(args)
    
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=60, text=True)
        return {
            "gear": gear,
            "script": script,
            "exit_code": r.returncode,
            "stdout": r.stdout[:500],
            "stderr": r.stderr[:200],
            "success": r.returncode == 0
        }
    except subprocess.TimeoutExpired:
        return {"gear": gear, "script": script, "error": "超时", "success": False}
    except Exception as e:
        return {"gear": gear, "script": script, "error": str(e)[:200], "success": False}

def full_cycle() -> dict:
    """运行所有齿轮的完整循环（每5分钟执行一次）"""
    results = {}
    
    # G1: 强制器(含自动恢复)
    r = run_gear("G1", "gear_enforcer.py")
    results["G1"] = r
    
    # 读wake_guide: 如果G1检测到中断任务,额外触发一次wake_guide
    try:
        wg_path = REPORTS / "wake_guide.json"
        if wg_path.exists():
            wg_data = json.loads(wg_path.read_text())
            if wg_data.get("interrupted_task"):
                # 有中断任务,确保DRIVER也被触发
                results["G1_alert"] = wg_data["interrupted_task"]["task_id"]
    except:
        pass
    
    # G2: 防摔保险
    r = run_gear("G2", "context_failsafe.py", ["maintain"])
    results["G2"] = r
    
    # G4: 上下文守卫
    r = run_gear("G4", "context_guardian.py", ["cycle"])
    results["G4"] = r
    
    # G7: 醒来指南(每1分钟)
    r = run_gear("G7", "wake_guide.py")
    results["G7"] = r
    
    # DRIVER: 棘轮自动续跑 (如果G1检测到中断任务,确保driver能续跑)
    r = run_gear("DRIVER", "gear_task_driver.py", ["cron"])
    results["DRIVER"] = r
    
    # 每30分钟运行G6
    minute = now().minute
    if minute % 30 < 5:  # 每小时的0-4分和30-34分
        r = run_gear("G6", "gear_task_validator.py", ["cron"])
        results["G6"] = r
    
    # 每15分钟运行G5
    if minute % 15 < 5:  # 每小时的0-4,15-19,30-34,45-49分
        r = run_gear("G5", "hermes_super_guardian.py", ["cycle"])
        results["G5"] = r
    
    # 读取wake_guide,如果有中断任务时并且在恢复时间段内,再额外触发一次G1(双重保险)
    try:
        wg_path = REPORTS / "wake_guide.json"
        if wg_path.exists() and minute % 2 == 0:  # 每隔一分钟检查一次
            wg_data = json.loads(wg_path.read_text())
            if wg_data.get("interrupted_task"):
                # 有中断任务且上次G1没处理完 → 再跑一次DRIVER确保棘轮推动
                r2 = run_gear("DRIVER", "gear_task_driver.py", ["cron"])
                results["DRIVER_retry"] = r2
    except:
        pass
    
    return results


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "once"
    
    if mode == "once":
        # 运行一次所有齿轮
        results = full_cycle()
        ok = all(
            isinstance(r, dict) and r.get("success", False)
            for r in results.values()
        )
        print(f"[MASTER] {'✅' if ok else '❌'} 齿轮循环完成")
        for gear, r in results.items():
            if isinstance(r, dict):
                status = '✅' if r.get('success') else '❌'
                err = r.get('error', '') or r.get('stderr', '')[:60]
                print(f"  {gear}: {status} {err}")
            else:
                print(f"  {gear}: ⚠️ {r}")
    
    elif mode == "loop":
        # 每15秒检查一次（细粒度调度）
        print(f"[MASTER] 齿轮主调度器启动 {now().isoformat()}")
        last_runs = {g: 0 for g in GEAR_SCHEDULE}
        last_full_cycle = 0
        
        try:
            while True:
                now_ts = time.time()
                minute = now().minute
                
                for gear, (script, interval, timeout) in GEAR_SCHEDULE.items():
                    if now_ts - last_runs.get(gear, 0) >= interval:
                        args = []
                        if gear == "G2":
                            args = ["maintain"]
                        elif gear == "G4":
                            args = ["cycle"]
                        elif gear == "G5":
                            args = ["cycle"]
                        elif gear == "G6":
                            args = ["cron"]
                        elif gear == "G8":
                            args = ["health"]
                        elif gear == "DRIVER":
                            args = ["cron"]
                        
                        r = run_gear(gear, script, args)
                        last_runs[gear] = now_ts
                        
                        if not r.get("success"):
                            print(f"[MASTER] ⚠️ {gear} 运行失败: {r.get('error', '')[:80]}")
                        
                        # G6的验证结果如果有告警，写入统一告警
                        if gear == "G6" and r.get("stdout"):
                            if "告警" in r["stdout"] or "❌" in r["stdout"]:
                                print(f"[MASTER] 🔴 {gear} 告警!")
                
                time.sleep(15)  # 每15秒循环一次
                
        except KeyboardInterrupt:
            print(f"[MASTER] 调度器停止 {now().isoformat()}")
    
    elif mode == "status":
        # 检查所有齿轮的心跳状态
        gears_ok = 0
        gears_fail = 0
        print("=== 齿轮状态 ===")
        
        # 检查G1心跳
        hb = LOGS / "gear_heartbeat.txt"
        if hb.exists():
            try:
                ts = datetime.fromisoformat(hb.read_text().strip())
                if ts.tzinfo is None: ts = ts.replace(tzinfo=TZ)
                mins = (now() - ts).total_seconds() / 60
                print(f"  G1 gear_enforcer: {'✅' if mins < 3 else '❌'} {mins:.0f}分钟前")
                gears_ok += 1 if mins < 3 else 0
                gears_fail += 1 if mins >= 3 else 0
            except: pass
        
        # 棘轮队列状态
        queue = REPORTS / "gear_task_queue.json"
        if queue.exists():
            try:
                qdata = json.loads(queue.read_text())
                tasks = qdata.get("tasks", {})
                active = sum(1 for t in tasks.values() if t.get("status") == "active")
                completed = sum(1 for t in tasks.values() if t.get("status") == "completed")
                print(f"  DRIVER 棘轮队列: 活跃{active} 完成{completed} 总{len(tasks)}")
            except: pass
        
        print(f"  齿轮健康: {gears_ok}/{gears_ok + gears_fail}")
    else:
        print("用法: gear_master.py [once|loop|status]")
