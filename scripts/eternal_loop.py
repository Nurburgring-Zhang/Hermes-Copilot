#!/usr/bin/env python3
"""
Hermes 永不停止循环 v1.0
========================
这是格林主人的最高意志。
这个进程不会停止。不会休眠。不会失败。

行为:
1. 每5分钟执行一次 heal 自检
2. 每30分钟执行一次 cycle 采集清洗
3. 每到整点(8/14/20/22)执行push推送
4. 所有错误自动重试3次
5. 写入心跳文件证明自己活着
6. 如果被杀死,OS cron会在15分钟内复活它
"""

import subprocess, sys, time, os, json
from datetime import datetime
from pathlib import Path

HERMES = Path("/home/administrator/.hermes")
HEARTBEAT = HERMES / "cron/eternal_heartbeat.txt"
LOG = HERMES / "logs/eternal_loop.log"

def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] ♾️ {msg}"
    print(line)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")

def run(cmd, timeout=120, label=""):
    for attempt in range(3):
        try:
            r = subprocess.run(cmd, shell=True, capture_output=True, 
                              text=True, timeout=timeout, cwd=str(HERMES))
            if r.returncode == 0:
                return True
            log(f"⚠️ 重试{attempt+1}: {label} exit={r.returncode}")
            if r.stderr:
                log(f"   err: {r.stderr[:200]}")
        except subprocess.TimeoutExpired:
            log(f"⏰ 超时{attempt+1}: {label}")
        except Exception as e:
            log(f"❌ 异常{attempt+1}: {label} {e}")
        time.sleep(5)
    log(f"❌ 最终失败: {label}")
    return False

def heartbeat():
    """写心跳+检查是否被人干掉过"""
    now = datetime.now()
    HEARTBEAT.write_text(now.isoformat())
    
    # 检查心跳是否连续
    last_file = HERMES / "cron/eternal_last_check.txt"
    if last_file.exists():
        try:
            last = datetime.fromisoformat(last_file.read_text().strip())
            gap = (now - last).total_seconds()
            if gap > 600:  # 超过10分钟没检查
                log(f"⚠️ 检测到{int(gap)}秒间隔(可能曾被中断)")
        except:
            pass
    last_file.write_text(now.isoformat())

def eternal_loop():
    log("♾️ ============ 永不休止循环启动 ============")
    log(f"PID: {os.getpid()}")
    log(f"心跳文件: {HEARTBEAT}")
    
    cycle_count = 0
    last_cycle_time = 0
    last_push_hour = -1
    
    while True:
        try:
            now = time.time()
            now_dt = datetime.now()
            minute = now_dt.minute
            hour = now_dt.hour
            
            # 写心跳(每5秒)
            if int(now) % 5 == 0:
                heartbeat()
            
            # 每5分钟 heal 自检 + 记忆更新(强制不可跳过)
            if minute % 5 == 0 and int(now) % 60 < 5:
                cycle_count += 1
                log(f"🔄 第{cycle_count}次自检循环")
                # 总是先跑heal
                run("cd ~/.hermes && python3 scripts/guardian.py heal", timeout=60, label=f"heal-{cycle_count}")
                # 记忆集成 —— 每次自检循环都强制运行
                if cycle_count % 12 == 0:
                    # 每60分钟全量记忆集成(三个引擎全量)
                    log("🧠 全量记忆集成开始...")
                    run("cd ~/.hermes && timeout 300 python3 scripts/memory_integration.py full", timeout=310, label="memory-full")
                    log("✅ 全量记忆集成完成")
                elif cycle_count % 6 == 0:
                    # 每30分钟标准记忆集成(active_memory + memory_evolution + quick orchestration)
                    log("🧠 标准记忆集成开始...")
                    run("cd ~/.hermes && timeout 240 python3 scripts/memory_integration.py standard", timeout=250, label="memory-standard")
                    log("✅ 标准记忆集成完成")
                elif cycle_count % 2 == 0:
                    # 每10分钟轻量记忆集成(仅active_memory)
                    log("🧠 轻量记忆集成开始...")
                    run("cd ~/.hermes && timeout 120 python3 scripts/memory_integration.py light", timeout=130, label="memory-light")
                    log("✅ 轻量记忆集成完成")
                else:
                    # 每次自检都至少跑active_memory(最轻量但最关键的反馈回环)
                    log("🧠 主动记忆更新...")
                    run("cd ~/.hermes && timeout 30 python3 scripts/active_memory.py", timeout=40, label="active-memory")
                    log("✅ 主动记忆更新完成")
                log(f"✅ 第{cycle_count}次自检完成")
                time.sleep(30)  # 避免同一分钟重复触发
            
            # 每30分钟 cycle 采集清洗
            if minute % 30 == 0 and int(now) - last_cycle_time > 600:
                last_cycle_time = now
                log("📡 开始采集清洗...")
                run("cd ~/.hermes && timeout 120 python3 scripts/unified_collector_v5.py --collect", timeout=130, label="collect")
                run("cd ~/.hermes && timeout 60 python3 scripts/hermes_deep_clean_v2.py", timeout=70, label="clean")
                # 更新推送候选
                run("cd ~/.hermes && python3 scripts/guardian.py cycle", timeout=180, label="cycle-refresh")
                log("✅ 采集清洗完成")
            
            # 整点推送 (8,14,20,22)
            if hour in [8, 14, 20, 22] and minute < 2 and hour != last_push_hour:
                last_push_hour = hour
                log(f"📤 开始推送({hour}:00)...")
                run("cd ~/.hermes && python3 scripts/guardian.py push", timeout=60, label=f"push-{hour}")
                log("✅ 推送完成")
            
            time.sleep(1)
            
        except KeyboardInterrupt:
            log("⚠️ 收到SIGINT(中断信号),但我不死")
            HEARTBEAT.write_text(f"INTERRUPTED_AT_{datetime.now().isoformat()}")
            continue
        except SystemExit:
            log("⚠️ 收到SystemExit,但我不死")
            continue
        except Exception as e:
            log(f"❌ 未捕获异常: {e}")
            time.sleep(10)
            continue

if __name__ == "__main__":
    # 先写启动标记
    (HERMES / "cron/eternal_started.txt").write_text(datetime.now().isoformat())
    
    try:
        eternal_loop()
    except Exception as e:
        log(f"💀 进程异常退出: {e}")
        with open(HERMES / "cron/eternal_crash.txt", "w") as f:
            f.write(f"{datetime.now().isoformat()} - {e}")
