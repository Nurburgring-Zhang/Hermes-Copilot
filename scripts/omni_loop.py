#!/usr/bin/env python3
"""
Hermes 全能循环 (Omni Loop) v3.0
覆盖8个步骤: 采集→清洗→AI评分→需求挖掘→专家匹配→产品生成→推送→记忆更新
按顺序执行全部8步,输出每步完成状态。
"""
import subprocess, sys, time, os, re
from datetime import datetime, timedelta
from pathlib import Path

HERMES = Path("/home/administrator/.hermes")
PUSH_LOG = HERMES / "logs" / "v12_push.log"
PUSH_HOURS = {8, 14, 20, 22}  # 每天推送4次
PUSH_COOLDOWN = timedelta(hours=3)  # 同一来源3小时内不重复推送
STEPS = ["采集 Collection", "清洗 Cleaning", "AI评分 Scoring",
         "需求挖掘 Mining", "专家匹配 Matching", "产品生成 Product",
         "推送 Push", "记忆更新 Memory"]

results = {}
def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

def last_push_time() -> datetime | None:
    """从v12_push.log中提取最后一条推送记录的时间戳"""
    if not PUSH_LOG.exists():
        return None
    try:
        # 日志格式: [HH:MM:SS] ..., 用最后几行找最近推送完成标记
        with open(PUSH_LOG, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        # 从末尾往前找"✅ 推送成功"或"⏱️ 耗时"行
        for line in reversed(lines[-50:]):
            line = line.strip()
            if not line:
                continue
            # 匹配 [HH:MM:SS]
            m = re.match(r'\[(\d{2}:\d{2}:\d{2})\]\s*(.*)', line)
            if m:
                ts_str = m.group(1)
                msg = m.group(2)
                if '推送成功' in msg or '降级推送' in msg or '最终' in msg:
                    today = datetime.now().strftime("%Y-%m-%d")
                    return datetime.strptime(f"{today} {ts_str}", "%Y-%m-%d %H:%M:%S")
    except Exception as e:
        log(f"⚠️ 读取推送日志失败: {e}")
    return None

def should_push() -> bool:
    """检查当前是否在允许推送时段且距上次推送超过冷却期"""
    now = datetime.now()
    hour = now.hour
    if hour not in PUSH_HOURS:
        log(f"  ⏭️ 跳过推送: 当前小时 {hour}:00 不在推送时段 {sorted(PUSH_HOURS)}")
        return False
    last = last_push_time()
    if last is not None:
        elapsed = now - last
        if elapsed < PUSH_COOLDOWN:
            log(f"  ⏭️ 跳过推送: 距上次推送仅 {elapsed.seconds//3600}h{(elapsed.seconds%3600)//60}m, 冷却期 {PUSH_COOLDOWN.seconds//3600}h")
            return False
        log(f"  ✅ 距上次推送 {elapsed.seconds//3600}h{(elapsed.seconds%3600)//60}m, 允许推送")
    else:
        log(f"  ✅ 无上次推送记录, 允许推送")
    return True

def run(cmd, label="", timeout=180):
    for attempt in range(3):
        try:
            r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout, cwd=str(HERMES))
            if r.returncode == 0:
                return True, r.stdout.strip()[-400:]
            log(f"  ↻ retry {attempt+1}/3: {label} exit={r.returncode}")
            for l in r.stderr.strip().split('\n')[-3:]:
                if l.strip(): log(f"    err: {l[:300]}")
        except subprocess.TimeoutExpired:
            log(f"  ⏰ timeout {attempt+1}/3: {label} (超时{timeout}s)")
            # 记录致命超时
            fatal_timeout_path = HERMES / 'logs' / 'fatal_timeout.log'
            with open(fatal_timeout_path, 'a') as ftf:
                ftf.write(f"[{datetime.now().isoformat()}] TIMEOUT: {label} ({timeout}s) attempt {attempt+1}\n")
        except FileNotFoundError as e:
            log(f"  ❌ FILE_NOT_FOUND {attempt+1}/3: {label} — 脚本缺失: {e}")
        except PermissionError as e:
            log(f"  ❌ PERMISSION {attempt+1}/3: {label} — 权限不足: {e}")
        except OSError as e:
            log(f"  ❌ OS_ERROR {attempt+1}/3: {label} — {e}")
        except Exception as e:
            log(f"  ❌ UNKNOWN {attempt+1}/3: {label} — {type(e).__name__}: {e}")
        time.sleep(5)
    return False, "FAILED after 3 retries"

def step(n, name, cmd, timeout=180):
    print(f"\n{'─'*50}\n STEP {n}/8 — {name}\n{'─'*50}")
    log("  ▶ Executing...")
    t0 = time.time()
    ok, out = run(cmd, name, timeout)
    elapsed = time.time() - t0
    results[n] = (ok, elapsed, name)
    icon = "✅" if ok else "❌"
    log(f"  {icon} Completed ({elapsed:.1f}s)")
    for l in out.split('\n')[-3:]:
        l = l.strip()
        if l: log(f"    {l[:200]}")
    return ok

def write_heartbeat():
    """写入心跳文件,供监控系统检查omni_loop是否存活。"""
    hb = os.path.expanduser("~/.hermes/omni_heartbeat.txt")
    try:
        os.makedirs(os.path.dirname(hb), exist_ok=True)
        with open(hb, 'w') as f:
            f.write(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    except Exception as e:
        log(f"⚠️ 心跳写入失败: {e}")

def main():
    write_heartbeat()
    log("")
    log("="*56)
    log("  HERMES 全能循环 (Omni Loop)")
    log(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log("  8步全流程: 采集 → 清洗 → AI评分 → 需求挖掘")
    log("            → 专家匹配 → 产品生成 → 推送 → 记忆更新")
    log("="*56)

    step(1, "采集 Collection", "timeout 300 python3 scripts/hermes_ultimate_collector.py --all 2>&1 | tail -30", 310)
    step(2, "清洗 Cleaning",   "timeout 120 python3 scripts/unified_cleaning_pipeline.py 2>&1 | tail -15", 130)
    step(3, "AI评分 Scoring",  "timeout 300 python3 scripts/hermes_ai_scoring.py --ai 2>&1 | tail -30", 310)
    step(4, "需求挖掘 Mining", "timeout 120 python3 scripts/requirement_mining_auto.py 2>&1 | tail -15", 130)
    step(5, "专家匹配 Matching","timeout 120 python3 scripts/agent_matching_pipeline.py 2>&1 | tail -15", 130)
    step(6, "产品生成 Product", "timeout 180 python3 scripts/production_auto.py 2>&1 | tail -15", 190)
    if should_push():
        step(7, "推送 Push",        "timeout 120 python3 scripts/hermes_v12_push.py --push 2>&1 | tail -15", 130)
    else:
        print(f"\n{'─'*50}\n STEP 7/8 — 推送 Push\n{'─'*50}")
        log("  ⏭️ 跳过 (非推送时段或冷却期内)")
        results[7] = (True, 0, "推送 Push")
    step(8, "记忆更新 Memory",  "timeout 180 python3 scripts/memory_evolution_v2.py 2>&1 | tail -15", 190)

    print()
    log("="*56)
    log(f"  HERMES 全能循环完成")
    log(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log("="*56)
    ok = sum(1 for r in results.values() if r[0])
    fail = sum(1 for r in results.values() if not r[0])
    log(f"  总步数: 8  |  ✅ 成功: {ok}  |  ❌ 失败: {fail}")
    log("")
    log(f"  {'步':>2} {'步骤':<15} {'状态':>4} {'耗时':>7}")
    log(f"  {'─'*30}")
    for n in range(1, 9):
        r = results.get(n, (False, 0, "?"))
        icon = "✅" if r[0] else "❌"
        log(f"  {n:>2} {r[2]:<15} {icon:>4} {r[1]:>6.1f}s")
    log("")
    log("="*56)
    if ok == 8:
        log("  🎉 全能循环完美完成!全部8步成功")
    else:
        log(f"  ⚠️ {ok}/8 步成功, {fail} 步失败")
    log("="*56)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log(f"💀 全能循环崩溃: {e}")
        import traceback
        traceback.print_exc()
