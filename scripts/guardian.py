#!/usr/bin/env python3
"""
Hermes 永久守护神 v2.0 — 永不中断版
======================================
格林主人最高指令:永不停止运行。

v2.0修复清单:
  BUG#3: run()返回值检查,失败时自动重调度
  BUG#4: push检查候选文件生成时间,超过2小时先采集
  BUG#5: heal自动清理cron锁定文件
  BUG#7: heal检查磁盘空间
  BUG#8: 日志自动轮转(超过10MB截断)
"""

import subprocess, json, time, os, sys, sqlite3, re, hashlib
from datetime import datetime, timedelta
from pathlib import Path

HERMES = Path("/home/administrator/.hermes")
LOG = HERMES / "logs" / f"guardian_{datetime.now().strftime('%Y%m%d')}.log"
MAX_LOG_BYTES = 10 * 1024 * 1024  # 10MB

def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] ⚡ {msg}"
    print(line)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    # 日志轮转
    if LOG.exists() and LOG.stat().st_size > MAX_LOG_BYTES:
        LOG.rename(LOG.with_suffix(".log.old"))
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")

def run(cmd, timeout=60, retries=2, label=""):
    """运行命令,失败自动重试+检查返回值"""
    for attempt in range(retries + 1):
        try:
            r = subprocess.run(cmd, shell=True, capture_output=True, 
                              text=True, timeout=timeout, cwd=str(HERMES))
            if r.returncode == 0:
                log(f"✅ {label or cmd[:50]} 成功")
                return r.stdout
            log(f"⚠️ 重试{attempt+1}/{retries}: {label or cmd[:50]} 返回{r.returncode}")
            if r.stderr:
                log(f"   stderr: {r.stderr[:200]}")
        except subprocess.TimeoutExpired:
            log(f"⏰ 超时{attempt+1}/{retries}: {label or cmd[:50]}")
        except Exception as e:
            log(f"❌ 异常{attempt+1}/{retries}: {e}")
        time.sleep(3)
    log(f"❌ 失败({retries+1}次尝试): {label or cmd[:50]}")
    return ""

def disk_check():
    """检查磁盘空间"""
    try:
        st = os.statvfs(str(HERMES))
        free_gb = st.f_frsize * st.f_bavail / (1024**3)
        if free_gb < 1.0:
            log(f"⚠️ 磁盘空间不足: {free_gb:.1f}GB")
            return [f"磁盘不足: {free_gb:.1f}GB"]
        log(f"💾 磁盘: {free_gb:.1f}GB 可用")
        return []
    except Exception as e:
        log(f"❌ 磁盘检查失败: {e}")
        return [f"磁盘检查失败: {e}"]

def clean_stale_locks():
    """清理残留锁定文件"""
    lock = HERMES / "cron" / ".tick.lock"
    if lock.exists():
        try:
            mtime = lock.stat().st_mtime
            age = time.time() - mtime
            if age > 600:  # 超过10分钟的老锁定文件
                lock.unlink()
                log(f"🔓 清理过期锁定文件(存活{age:.0f}s)")
                return [f"清理过期锁定文件"]
        except:
            pass
    return []

def health_check():
    """检查系统健康状态"""
    issues = []
    
    # DB健康
    try:
        db = sqlite3.connect(str(HERMES / "intelligence.db"))
        db.execute("SELECT 1")
        db.close()
    except Exception as e:
        issues.append(f"DB连接失败: {e}")
    
    # 今日数据
    try:
        db = sqlite3.connect(str(HERMES / "intelligence.db"))
        c = db.cursor()
        c.execute("""SELECT COUNT(*) FROM raw_intelligence 
                     WHERE DATE(collected_at) = DATE('now','localtime')""")
        raw_today = c.fetchone()[0]
        c.execute("""SELECT COUNT(*) FROM cleaned_intelligence 
                     WHERE DATE(cleaned_at) = DATE('now','localtime')""")
        clean_today = c.fetchone()[0]
        c.execute("""SELECT COUNT(*) FROM cleaned_intelligence 
                     WHERE DATE(cleaned_at) = DATE('now','localtime')
                     AND personal_match_score >= 10""")
        pref_today = c.fetchone()[0]
        c.execute("""SELECT MAX(collected_at) FROM raw_intelligence""")
        last_col = c.fetchone()[0]
        db.close()
        
        if raw_today == 0 and clean_today == 0:
            issues.append("今日0数据")
        
        log(f"📊 数据: raw={raw_today} clean={clean_today} pref≥10={pref_today} 最后采集={last_col or '无'}")
    except Exception as e:
        issues.append(f"数据检查失败: {e}")
    
    # Hermes进程
    try:
        r = subprocess.run(["pgrep", "-f", "hermes_cli.main"], 
                          capture_output=True, text=True, timeout=5)
        if not r.stdout.strip():
            issues.append("Hermes进程未运行")
        else:
            log(f"✅ Hermes进程 PID={r.stdout.strip()[:20]}")
    except:
        issues.append("无法检查Hermes进程")
    
    # 磁盘
    issues.extend(disk_check())
    # 锁定文件
    issues.extend(clean_stale_locks())
    
    return issues

def auto_collect():
    log("📡 开始全量采集...")
    start = time.time()
    output = run("cd ~/.hermes && timeout 120 python3 scripts/unified_collector_v5.py --collect",
                timeout=130, label="全量采集")
    elapsed = time.time() - start
    new = 0
    if output:
        for line in output.split('\n'):
            m = re.search(r'new=(\d+)', line)
            if m: new += int(m.group(1))
    log(f"📡 采集: {new}条新数据, {elapsed:.0f}s")
    # 轨迹追踪
    subprocess.run(["python3", "scripts/hermes_memory_engine_v2.py", "--track", "情报采集全流程", "success"],
                   cwd=str(HERMES), capture_output=True, timeout=10)
    return new

def auto_clean():
    log("🧹 开始清洗去重...")
    start = time.time()
    output = run("cd ~/.hermes && timeout 120 python3 scripts/hermes_deep_clean_v2.py",
                timeout=130, label="清洗去重")
    elapsed = time.time() - start
    new = 0
    if output:
        for line in output.split('\n'):
            m = re.search(r'新增: (\d+)', line)
            if m: new = int(m.group(1))
    log(f"🧹 清洗: +{new}条, {elapsed:.0f}s")
    # 清理原始数据中的重复项(标题已清洗的)
    run("cd ~/.hermes && timeout 30 python3 scripts/purge_dup_raw.py",
        timeout=30, label="清理重复原始项")
    return new
def auto_collect_cycle():
    log("🔄 ============ 闭环开始 ============")
    new_raw = auto_collect()
    new_clean = auto_clean()
    
    # AI评分:对新清洗的数据进行六维评分
    log("📊 开始AI评分...")
    scoring_result = run("cd ~/.hermes && timeout 60 python3 scripts/hermes_ai_scoring.py",
                        timeout=65, label="AI六维评分")
    if scoring_result:
        for line in scoring_result.split('\n'):
            if 'TASK_DONE' in line:
                m = re.search(r'TASK_DONE:(\d+)', line)
                if m:
                    log(f"📊 AI评分: {m.group(1)} 条")
    
    try:
        db = sqlite3.connect(str(HERMES / "intelligence.db"))
        c = db.cursor()
        c.execute("""SELECT COUNT(*) FROM cleaned_intelligence 
                     WHERE DATE(cleaned_at) = DATE('now','localtime')""")
        today_total = c.fetchone()[0]
        c.execute("""
            SELECT title, platform, personal_match_score, tags, 
                   importance_score, url, ai_score_total,
                   ai_score_scarcity, ai_score_impact, ai_score_tech_depth,
                   ai_score_timeliness, ai_score_preference, ai_score_credibility
            FROM cleaned_intelligence
            WHERE DATE(cleaned_at) = DATE('now','localtime')
              AND personal_match_score >= 5
              AND ai_score_total IS NOT NULL
            ORDER BY ai_score_total DESC, personal_match_score DESC
            LIMIT 30
        """)
        top_items = [dict(zip([d[0] for d in c.description], row)) for row in c.fetchall()]
        db.close()
        
        log(f"📊 闭环: 今日{new_raw}采集 → +{new_clean}清洗 → {today_total}总量")
        log(f"🎯 偏好匹配: {len(top_items)}条(≥10分)")
        
        with open(HERMES / "cron/push_candidates_latest.json", "w", encoding="utf-8") as f:
            json.dump({
                "generated_at": datetime.now().isoformat(),
                "total_today": today_total,
                "matched": len(top_items),
                "items": top_items
            }, f, ensure_ascii=False, indent=2)
        log(f"💾 推送候选已保存")
    except Exception as e:
        log(f"❌ 闭环分析失败: {e}")
    
    log("🔄 ============ 闭环完成 ============")
    return True

def push_to_wechat(title, content):
    import urllib.request
    import yaml
    try:
        with open(HERMES / "config.yaml") as f:
            config = yaml.safe_load(f)
        token = config.get("pushplus", {}).get("token", "")
        if not token:
            log("❌ PushPlus token未配置")
            return False
        
        data = json.dumps({
            "token": token,
            "title": title,
            "content": content,
            "template": "markdown",
        }).encode()
        req = urllib.request.Request(
            "https://www.pushplus.plus/send",
            data=data,
            headers={"Content-Type": "application/json"}
        )
        resp = urllib.request.urlopen(req, timeout=15)
        result = json.loads(resp.read().decode())
        
        if result.get("code") == 200:
            log(f"✅ 推送: {title[:40]}...")
            return True
        else:
            log(f"❌ 推送失败: {result.get('msg', '?')}")
            return False
    except Exception as e:
        log(f"❌ 推送异常: {e}")
        return False

def check_omni_loop_heartbeat():
    """检查omni_loop心跳,超过120分钟未更新则自动重启"""
    # AR-029 FIX: 只检查权威心跳文件，移除cron/下已停滞的旧文件
    heartbeat_paths = [
        HERMES / "omni_heartbeat.txt",           # omni_loop.py 写入的主心跳（唯一权威源）
    ]
    
    found_any = False
    min_age = float('inf')
    newest_path = None
    
    for hb_path in heartbeat_paths:
        if hb_path.exists():
            found_any = True
            try:
                mtime = hb_path.stat().st_mtime
                age_minutes = (time.time() - mtime) / 60
                if age_minutes < min_age:
                    min_age = age_minutes
                    newest_path = hb_path
                log(f"💓 omni心跳[{hb_path.name}]: {age_minutes:.0f}分钟前更新")
            except Exception as e:
                log(f"⚠️ 读取心跳[{hb_path.name}]失败: {e}")
    
    if not found_any:
        log("⚠️ 未找到omni_loop心跳文件,将执行恢复")
        return _restart_omni_loop()
    
    if min_age > 120:
        log(f"🚨 omni_loop心跳停滞{min_age:.0f}分钟(阈值120分钟),启动自动恢复...")
        return _restart_omni_loop()
    else:
        log(f"✅ omni_loop心跳正常(最近更新{min_age:.0f}分钟前)")
        return []

def _restart_omni_loop():
    """执行omni_loop重启命令"""
    cmd = 'cd ~/.hermes && timeout 600 python3 scripts/omni_loop.py'
    log(f"🔄 重启omni_loop: {cmd}")
    output = run(cmd, timeout=620, label="omni_loop重启恢复")
    if output:
        log(f"✅ omni_loop已成功重启")
        # 写入恢复记录
        try:
            recover_log = HERMES / "logs" / "omni_recover.log"
            with open(recover_log, "a") as f:
                f.write(f"[{datetime.now().isoformat()}] omni_loop恢复启动 (停滞>120分钟)\n")
        except:
            pass
        return [f"omni_loop已恢复重启"]
    else:
        log(f"❌ omni_loop重启失败")
        return [f"omni_loop重启失败"]

def self_heal():
    log("🏥 ============ 自愈检查 ============")
    issues = health_check()
    self_healed = False
    
    # 检查omni_loop心跳
    omni_issues = check_omni_loop_heartbeat()
    issues.extend(omni_issues)
    
    if issues:
        log(f"⚠️ 发现{len(issues)}个问题: {'; '.join(issues)}")
        for issue in issues:
            if "今日0数据" in issue:
                log("🩺 采集...")
                auto_collect()
                auto_clean()
                self_healed = True
            elif "锁定" in issue:
                self_healed = True
            elif "磁盘" in issue:
                log("🩺 磁盘空间不足,请清理")
            elif "Hermes进程" in issue:
                log("🩺 Hermes未运行,需人工启动")
        if self_healed:
            log("🏥 自愈完成")
    else:
        log("✅ 系统健康")
    
    # 轨迹追踪
    subprocess.run(["python3", "scripts/hermes_memory_engine_v2.py", "--track", "守护神自愈", "success" if not issues else "fail"],
                   cwd=str(HERMES), capture_output=True, timeout=10)
    return issues

def print_status_report():
    try:
        db = sqlite3.connect(str(HERMES / "intelligence.db"))
        c = db.cursor()
        c.execute("SELECT COUNT(*) FROM cleaned_intelligence")
        total = c.fetchone()[0]
        c.execute("""SELECT COUNT(*) FROM cleaned_intelligence 
                     WHERE DATE(cleaned_at) = DATE('now','localtime')""")
        today = c.fetchone()[0]
        c.execute("""SELECT COUNT(*) FROM cleaned_intelligence 
                     WHERE DATE(cleaned_at) = DATE('now','localtime')
                     AND personal_match_score >= 10""")
        pref = c.fetchone()[0]
        c.execute("""SELECT COUNT(*) FROM raw_intelligence 
                     WHERE DATE(collected_at) = DATE('now','localtime')""")
        raw = c.fetchone()[0]
        c.execute("""SELECT COUNT(*) FROM cleaned_intelligence 
                     WHERE ai_score_total IS NOT NULL AND ai_score_total > 0""")
        scored = c.fetchone()[0]
        c.execute("""SELECT MAX(cleaned_at) FROM cleaned_intelligence""")
        last_clean = c.fetchone()[0]
        c.execute("""SELECT MAX(collected_at) FROM raw_intelligence""")
        last_collect = c.fetchone()[0]
        c.execute("""SELECT MAX(collected_at) FROM raw_intelligence""")
        last_col = c.fetchone()[0]
        # 守护神最后信号
        guard_time = "无"
        gf = HERMES / "cron/guardian_last.txt"
        if gf.exists():
            guard_time = gf.read_text().strip()[:19]
        db.close()
        
        report = f"""
╔══════════════════════════════════════╗
║   Hermes 守护神 v2.0 状态            ║
║   {datetime.now().strftime('%Y-%m-%d %H:%M')}           ║
╠══════════════════════════════════════╣
║  📊 数据总览                         ║
║  今日采集(raw): {raw:>6d} 条                    ║
║  今日清洗:   {today:>6d} 条                    ║
║  偏好匹配(≥10): {pref:>4d} 条                    ║
║  AI已评分:   {scored:>6d} 条                    ║
║  累计总量:   {total:>6d} 条                    ║
╠══════════════════════════════════════╣
║  🕐 最后活动                          ║
║  守护神心跳: {guard_time:21s} ║
║  最后采集: {str(last_collect or '无'):22s} ║
║  最后清洗: {str(last_clean or '无'):22s} ║
╚══════════════════════════════════════╝
"""
        print(report)
        return report
    except Exception as e:
        return f"状态报告失败: {e}"

def do_push():
    """推送——调用v12 HTML模板+可点击链接推送"""
    log("📤 调用v12 HTML推送...")
    
    v12_script = HERMES / "scripts/hermes_v12_push.py"
    if v12_script.exists():
        r = subprocess.run(
            ["python3", str(v12_script), "--push"],
            capture_output=True, text=True, timeout=120, cwd=str(HERMES)
        )
        if r.stdout:
            for line in r.stdout.strip().split("\n")[-15:]:
                log(f"  {line}")
        if r.returncode == 0:
            log("✅ v12推送完成")
            subprocess.run(["python3", "scripts/hermes_memory_engine_v2.py", "--track", "推送执行流程", "success"],
                          cwd=str(HERMES), capture_output=True, timeout=10)
        else:
            log(f"⚠️ v12推送返回码 {r.returncode}")
    else:
        log("❌ v12推送脚本不存在")
        _do_push_legacy()

def _do_push_legacy():
    """旧版推送——候选模式,保留作为回退"""
    push_data = HERMES / "cron/push_candidates_latest.json"
    
    # 检查候选是否太旧
    need_refresh = False
    if push_data.exists():
        try:
            data = json.loads(push_data.read_text(encoding="utf-8"))
            gen_time = data.get("generated_at", "")
            if gen_time:
                gen_dt = datetime.fromisoformat(gen_time)
                age = datetime.now() - gen_dt
                if age.total_seconds() > 7200:  # 超过2小时
                    log(f"⚠️ 推送候选已过期({age.total_seconds()/60:.0f}分钟), 重新采集")
                    need_refresh = True
            if len(data.get("items", [])) < 5:
                need_refresh = True
        except:
            need_refresh = True
    else:
        need_refresh = True
    
    if need_refresh:
        auto_collect_cycle()
        if not push_data.exists():
            log("❌ 重新采集后仍无推送候选")
            return
        data = json.loads(push_data.read_text(encoding="utf-8"))
    else:
        data = json.loads(push_data.read_text(encoding="utf-8"))
    
    items = data.get("items", [])[:20]
    if not items:
        log("❌ 无推送候选")
        return
    
    # 按六维评分排序
    items.sort(key=lambda x: x.get('ai_score_total', x.get('importance_score', 0)), reverse=True)
    
    # 分类聚合
    high_value = [i for i in items if i.get('ai_score_total', 0) >= 60]
    medium_value = [i for i in items if 30 <= i.get('ai_score_total', 0) < 60]
    
    # 构建推送消息
    msg_lines = [
        f"🤖 Hermes 情报推送 | {datetime.now().strftime('%m-%d %H:%M')}",
        f"━━━━━━━━━━━━━━━━━━━",
        f"今日总量: {data.get('total_today',0)}条 | 偏好匹配: {data.get('matched',0)}条",
        f"高价值(≥60): {len(high_value)}条 | 中等: {len(medium_value)}条",
        ""
    ]
    
    if high_value:
        msg_lines.append(f"🔴 高价值信息 TOP{min(5,len(high_value))}:")
        for i, item in enumerate(high_value[:5], 1):
            title = (item.get("title","") or "")[:50]
            plat = item.get("platform","?")
            score = item.get('ai_score_total', item.get('importance_score', 0))
            pref = item.get("personal_match_score",0)
            msg_lines.append(f"  {i}. {title}")
            msg_lines.append(f"     📍{plat} | AI评分{score:.0f} | 偏好{pref}")
        msg_lines.append("")
    
    if medium_value:
        msg_lines.append(f"🟡 中等价值 TOP{min(5,len(medium_value))}:")
        for i, item in enumerate(medium_value[:5], 1):
            title = (item.get("title","") or "")[:50]
            plat = item.get("platform","?")
            score = item.get('ai_score_total', item.get('importance_score', 0))
            pref = item.get("personal_match_score",0)
            msg_lines.append(f"  {i}. {title}")
            msg_lines.append(f"     📍{plat} | AI评分{score:.0f} | 偏好{pref}")
        msg_lines.append("")
    
    # 平台分布
    platforms = {}
    for item in items:
        p = item.get("platform","?")
        platforms[p] = platforms.get(p, 0) + 1
    plat_str = " | ".join([f"{p}:{c}" for p,c in sorted(platforms.items(), key=lambda x:-x[1])[:6]])
    msg_lines.append(f"📊 平台: {plat_str}")
    
    msg = "\n".join(msg_lines)
    push_to_wechat(f"🤖 Hermes 情报推送 | {len(high_value)}条高价值", msg)

def main():
    action = sys.argv[1] if len(sys.argv) > 1 else "status"
    
    # 写心跳
    (HERMES / "cron/guardian_last.txt").write_text(datetime.now().isoformat())
    
    if action == "status":
        report = print_status_report()
        print(report)
    elif action == "heal":
        self_heal()
        print_status_report()
    elif action == "cycle":
        auto_collect_cycle()
        print_status_report()
    elif action == "full":
        self_heal()
        auto_collect_cycle()
        do_push()
        print_status_report()
    elif action == "push":
        do_push()
    elif action == "collect":
        auto_collect()
        auto_clean()
        print_status_report()
    
    log(f"✅ guardian.py {action} 完成")
    return 0

if __name__ == "__main__":
    sys.exit(main())
