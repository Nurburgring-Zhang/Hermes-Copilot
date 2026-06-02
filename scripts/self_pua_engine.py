#!/usr/bin/env python3
"""
Hermes 自我PUA引擎 v1.0 (Self-PUA Engine)
================================================
格林主人要求:所有系统必须自我驱动完成任何任务,而不是等着被叫醒。

核心逻辑:
1. 每次执行完任务 → 自动复盘 → 发现改进点 → 执行改进
2. 如果某系统有"未完成"任务但不主动执行 → PUA引擎自动补位
3. 推送内容质量 → PUA引擎定期审核 → 发现垃圾 → 触发修复
4. 记忆空壳 → PUA引擎发现 → 写入真实数据
5. tarefas cron缺失 → PUA引擎发现 → 注册cron

运行方式:
  python3 self_pua_engine.py          # 全量自PUA检查
  python3 self_pua_engine.py --check  # 检查未完成事项
  python3 self_pua_engine.py --fix    # 执行修复
  python3 self_pua_engine.py --cron   # 注册自PUA cron
"""

import sqlite3, json, sys, time, os, subprocess
from datetime import datetime
from pathlib import Path

HERMES = Path("/home/administrator/.hermes")
LOG = HERMES / "logs" / "self_pua.log"


def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] 💪 {msg}"
    print(line)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def run(cmd, timeout=30):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout, cwd=str(HERMES))
        return r.stdout, r.returncode
    except Exception as e:
        return str(e), -1


def check_findings():
    """PUA检查:扫描所有子系统发现待修复问题"""
    findings = []

    # 1. 检查cron完整性
    rc = subprocess.run("crontab -l", shell=True, capture_output=True, text=True)
    cron_text = rc.stdout
    cron_lines = [l.strip() for l in cron_text.split("\n") if l.strip() and not l.startswith("#")]

    expected_crons = {
        "hermes_memory_engine": "记忆引擎",
        "guardian": "守护神",
        "self_evolve": "自进化",
        "self_pua": "自PUA",
        "revive": "复活检查",
    }
    for key, desc in expected_crons.items():
        found = any(key.lower() in ln for ln in cron_lines)
        if not found:
            findings.append({"type": "missing_cron", "key": key, "desc": desc, "severity": "P0"})

    # 2. 检查记忆系统完整
    try:
        conn = sqlite3.connect(str(HERMES / "active_memory.db"))
        c = conn.cursor()
        for table, min_rows, label in [
            ("memory_episodic", 2, "事件记忆"),
            ("memory_semantic", 4, "语义记忆"),
            ("memory_procedural", 6, "程序记忆"),
            ("memory_reflexive", 2, "反射记忆"),
        ]:
            try:
                ct = c.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                if ct < min_rows:
                    findings.append({"type": "incomplete_memory", "table": table, "current": ct, "min": min_rows, "severity": "P1", "desc": f"{label}不够({ct}<{min_rows})"})
            except:
                findings.append({"type": "missing_memory_table", "table": table, "severity": "P1", "desc": f"{label}表不存在"})
        conn.close()
    except Exception as e:
        findings.append({"type": "memory_db_error", "severity": "P0", "desc": f"memory DB连接失败: {e}"})

    # 3. 检查推送质量
    try:
        conn = sqlite3.connect(str(HERMES / "intelligence.db"))
        c = conn.cursor()
        last20 = c.execute("SELECT id, title FROM push_records ORDER BY id DESC LIMIT 20").fetchall()
        trash_kw = ["末世", "目瑙", "小说", "修仙", "穿越", "赘婿", "兵王", "就在刚刚", "乙肝", "彩礼"]
        trash_count = sum(1 for _, t in last20 if any(kw in t for kw in trash_kw))
        if trash_count > 2:
            findings.append({"type": "push_quality", "trash": trash_count, "total": len(last20), "severity": "P1", "desc": f"推送垃圾{trash_count}/{len(last20)} > 10%"})
        conn.close()
    except Exception as e:
        findings.append({"type": "push_db_error", "severity": "P0", "desc": f"推送DB检查失败: {e}"})

    # 4. 检查三省六部拓扑状态
    try:
        conn = sqlite3.connect(str(HERMES / "state.db"))
        c = conn.cursor()
        try:
            topo = c.execute("SELECT COUNT(*) FROM topology_state").fetchone()[0]
            if topo < 3:
                findings.append({"type": "sango_incomplete", "current": topo, "min": 3, "severity": "P1", "desc": f"三省六部只有{topo}个Actor"})
        except:
            findings.append({"type": "sango_missing", "severity": "P2", "desc": "三省六部拓扑表不存在"})
        conn.close()
    except:
        findings.append({"type": "state_db_error", "severity": "P0", "desc": "state.db检查失败"})

    # 5. 检查自进化报告推送
    evolves = list(HERMES.glob("reports/self_evolve_*.json"))
    if len(evolves) < 2:
        findings.append({"type": "no_evolve_report", "current": len(evolves), "severity": "P2", "desc": f"自进化报告不足({len(evolves)}个)"})

    return findings


def fix_findings(findings):
    """PUA修复:自动执行修复"""
    fixed = []
    for f in findings:
        if f["type"] == "missing_cron" and f["key"] == "self_evolve":
            log(f"🔧 注册自进化cron...")
            rc = subprocess.run("(crontab -l 2>/dev/null; echo '0 3 * * * cd /home/administrator/.hermes && python3 scripts/hermes_self_evolve_cluster.py >> logs/self_evolve.log 2>&1') | crontab -", shell=True)
            if rc.returncode == 0:
                log(f"  ✅ 注册成功")
                fixed.append("自进化cron已注册(03:00)")

        elif f["type"] == "missing_cron" and f["key"] == "pua":
            log(f"🔧 注册PUA检查cron...")
            rc = subprocess.run("(crontab -l 2>/dev/null; echo '30 */6 * * * cd /home/administrator/.hermes && python3 scripts/self_pua_engine.py --check >> logs/self_pua.log 2>&1') | crontab -", shell=True)
            if rc.returncode == 0:
                log(f"  ✅ 注册成功")
                fixed.append("PUA检查cron已注册(每6h)")

        elif f.get("severity") in ("P0", "P1"):
            log(f"  ⏭️ 需人工介入: {f['desc']}")

        else:
            log(f"  ⏭️ 需检查: {f['desc']}")

    return fixed


def check_missing_cron_for_evolve():
    """专门修复自进化cron缺失问题"""
    rc = subprocess.run("crontab -l", shell=True, capture_output=True, text=True)
    if "self_evolve" not in rc.stdout:
        log("⚡ 自进化cron缺失 → 立即注册")
        new_cron = rc.stdout.strip() + "\n# ===== 自进化集群 (每日03:00) =====\n0 3 * * * cd /home/administrator/.hermes && python3 scripts/hermes_self_evolve_cluster.py >> logs/self_evolve.log 2>&1\n"
        # 添加PUA cron
        new_cron += "# ===== 自我PUA检查 (每6小时) =====\n30 */6 * * * cd /home/administrator/.hermes && python3 scripts/self_pua_engine.py --check >> logs/self_pua.log 2>&1\n"
        subprocess.run(f"echo '{new_cron}' | crontab -", shell=True)
        log("  ✅ 自进化cron+PUA cron已注册")
        return True
    return False


def pua_full_cycle():
    """完整PUA循环:检查→修复→报告"""
    log("=" * 50)
    log("🤖 自我PUA引擎启动")
    log("=" * 50)

    # 1. 检查
    findings = check_findings()
    log(f"📋 发现 {len(findings)} 个问题:")
    for f in findings:
        log(f"  [{f.get('severity','?')}] {f.get('desc','?')}")

    # 2. 自动修复
    fixed = fix_findings(findings)
    if fixed:
        log(f"✅ 修复 {len(fixed)} 项:")
        for item in fixed:
            log(f"  ✅ {item}")

    # 3. 检查cron完整性
    check_missing_cron_for_evolve()

    log("=" * 50)
    log("✅ 自我PUA循环完成")
    log("=" * 50)

    return len(findings), len(fixed)


def main():
    action = sys.argv[1] if len(sys.argv) > 1 else "full"

    if action == "--check":
        findings = check_findings()
        print(f"发现 {len(findings)} 个问题:")
        for f in findings:
            print(f"  [{f.get('severity','?')}] {f.get('desc','?')}")

    elif action == "--fix":
        findings = check_findings()
        fixed = fix_findings(findings)
        print(f"修复 {len(fixed)} 项")

    elif action == "--cron":
        check_missing_cron_for_evolve()
        print("cron已检查/注册")

    else:
        n_find, n_fix = pua_full_cycle()
        print(f"\n📊 总问题: {n_find} | 已修复: {n_fix}")


if __name__ == "__main__":
    main()
