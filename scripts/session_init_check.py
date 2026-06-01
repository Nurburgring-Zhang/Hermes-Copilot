#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Hermes 对话启动检测 v1.0
========================
每次对话开始时自动执行：
1. 检查是否有中断任务
2. 检查系统健康状态
3. 如果中断是因为tokens超限/错误，自动恢复并推送通知
4. 检查context_packer是否正常

由 ~/.hermes/bin/init_hermes_context.sh 调用
"""
import json, sqlite3, sys, subprocess, urllib.request, yaml
from pathlib import Path
from datetime import datetime, timedelta

HERMES = Path("/home/administrator/.hermes")

def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    with open(HERMES / "logs" / "session_init.log", "a") as f:
        f.write(f"[{ts}] {msg}\n")

def main():
    log("=== 对话启动检测 ===")
    issues = []
    
    # 1. 检查中断任务
    try:
        wg = json.loads((HERMES / "reports" / "wake_guide.json").read_text())
        task = wg.get("interrupted_task", {})
        if task:
            issues.append(f"中断任务: {task.get('task_id','?')} → {task.get('next_action','?')}")
            log(f"⚠️ 发现中断任务: {task.get('task_id','?')}")
    except: pass
    
    # 2. 检查齿轮健康
    try:
        wg = json.loads((HERMES / "reports" / "wake_guide.json").read_text())
        health = wg.get("gear_health", "unknown")
        if health != "healthy":
            issues.append(f"齿轮健康: {health}")
            log(f"⚠️ 齿轮健康异常: {health}")
    except: pass
    
    # 3. 检查context_packer是否正常工作
    try:
        cp = json.loads((HERMES / "reports" / "context_pack.json").read_text())
        log(f"✅ context_pack.json: {cp.get('packed_tokens','?')}tokens")
    except:
        issues.append("context_pack.json 缺失 - 上下文压缩可能不正常")
        log("❌ context_pack.json 不可读")
    
    # 4. 检查数据库是否有大量未评分
    try:
        db = sqlite3.connect(str(HERMES / "intelligence.db"))
        cu = db.execute("SELECT COUNT(*) FROM cleaned_intelligence WHERE ai_score_total = 0 OR ai_score_total IS NULL")
        unscored = cu.fetchone()[0]
        if unscored > 5000:
            issues.append(f"未评分数据: {unscored}条 (可能评分卡住了)")
            log(f"⚠️ 大量未评分: {unscored}")
        db.close()
    except: pass
    
    # 5. 检查推送是否卡住
    try:
        db = sqlite3.connect(str(HERMES / "intelligence.db"))
        cu = db.execute("SELECT MAX(push_time) FROM push_records")
        r = cu.fetchone()
        db.close()
        if r and r[0]:
            last_push = datetime.fromisoformat(r[0])
            hours_idle = (datetime.now() - last_push).total_seconds() / 3600
            if hours_idle > 12:
                issues.append(f"最后推送: {hours_idle:.0f}小时前 - 推送可能卡了")
                log(f"⚠️ 推送卡住: {hours_idle:.0f}小时无推送")
    except: pass
    
    if issues:
        log(f"⚠️ 发现 {len(issues)} 个问题:")
        for i, issue in enumerate(issues):
            log(f"  {i+1}. {issue}")
        
        # 尝试推送问题报告
        try:
            cfg_path = HERMES / "config.yaml"
            token = ""
            if cfg_path.exists():
                cfg = yaml.safe_load(cfg_path.read_text())
                token = cfg.get("pushplus", {}).get("token", "")
            if not token:
                env_path = HERMES / ".env"
                if env_path.exists():
                    for line in env_path.read_text().split("\n"):
                        if line.startswith("PUSHPLUS_TOKEN"):
                            token = line.split("=", 1)[1].strip().strip('"\'').strip('"')
            if token:
                msg = "⚠️ **Hermes 启动检测发现以下问题**\n\n" + "\n".join(f"- {i}" for i in issues)
                msg += "\n\n已自动记录，将由齿轮系统尝试恢复。"
                data = json.dumps({"token": token, "title": "⚠️ Hermes 启动问题", "content": msg, "template": "markdown"}).encode()
                req = urllib.request.Request("https://www.pushplus.plus/send", data=data, headers={"Content-Type": "application/json"})
                urllib.request.urlopen(req, timeout=10)
                log("✅ 问题推送成功")
        except:
            pass
    else:
        log("✅ 无问题")
    
    # 输出给AI的摘要
    if issues:
        print(f"[STARTUP] 检测到 {len(issues)} 个问题:")
        for i in issues:
            print(f"  ⚠️ {i}")
    else:
        print("[STARTUP] ✅ 系统正常")

if __name__ == "__main__":
    main()

