#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Hermes 状态主动反馈系统 v1.0
===========================
当对话中断/无活跃对话时，自动通过PushPlus推送系统状态到微信。
由cron每40分钟和每2小时触发。

反馈内容：
1. 采集状态（raw/clean条数，最新采集时间）
2. 推送状态（今日推送数，最新推送时间）
3. 后台任务状态（self_enhance_loop轮次）
4. 齿轮系统健康
5. 系统正常运行时间
"""
import json, sqlite3, urllib.request, yaml, os
import sys
from pathlib import Path
from datetime import datetime, timedelta

HERMES = Path("/home/administrator/.hermes")
LOG = HERMES / "logs" / "status_reporter.log"
LAST_CHAT_FILE = HERMES / "reports" / "last_chat_time.txt"

def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    with open(LOG, "a") as f:
        f.write(f"[{ts}] {msg}\n")

def get_pushplus_token():
    try:
        cfg = yaml.safe_load((HERMES / "config.yaml").read_text())
        t = cfg.get("pushplus", {}).get("token", "")
        if t: return t
    except: pass
    try:
        for line in (HERMES / ".env").read_text().split("\n"):
            if line.startswith("PUSHPLUS_TOKEN"):
                return line.split("=", 1)[1].strip().strip('"\'').strip('"')
    except: pass
    return ""

def get_last_chat_time():
    """获取最后一次人类对话的时间"""
    try:
        if LAST_CHAT_FILE.exists():
            return datetime.fromisoformat(LAST_CHAT_FILE.read_text().strip())
    except: pass
    
    # 回退：看 gear_master 日志最后修改时间
    for p in [HERMES / "logs" / "gear_master.log", HERMES / "logs" / "gear_driver.log"]:
        if p.exists():
            return datetime.fromtimestamp(p.stat().st_mtime)
    return datetime.now() - timedelta(hours=24)

def get_system_status():
    """采集系统状态"""
    now = datetime.now()
    status = {
        "ts": now.isoformat(),
        "ts_short": now.strftime("%m-%d %H:%M"),
        "raw_count": 0, "clean_count": 0,
        "last_raw": "未知", "last_push": "未知",
        "push_today": 0, "push_total": 0,
        "self_enhance_round": "?",
        "gear_health": "unknown",
        "unscored": 0,
        "sources_active": 0,
    }
    
    # 采集数据
    try:
        db = sqlite3.connect(str(HERMES / "intelligence.db"))
        cu = db.execute("SELECT COUNT(*) FROM raw_intelligence")
        status["raw_count"] = cu.fetchone()[0]
        cu = db.execute("SELECT COUNT(*) FROM cleaned_intelligence")
        status["clean_count"] = cu.fetchone()[0]
        cu = db.execute("SELECT COUNT(*) FROM cleaned_intelligence WHERE ai_score_total = 0 OR ai_score_total IS NULL")
        status["unscored"] = cu.fetchone()[0]
        cu = db.execute("SELECT collected_at FROM raw_intelligence ORDER BY rowid DESC LIMIT 1")
        r = cu.fetchone()
        if r: status["last_raw"] = r[0][:16] if r[0] else "未知"
        db.close()
    except Exception as e:
        log(f"采集读取失败: {e}")
    
    # 推送数据
    try:
        db = sqlite3.connect(str(HERMES / "intelligence.db"))
        cu = db.execute("SELECT COUNT(*) FROM push_records")
        status["push_total"] = cu.fetchone()[0]
        today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        cu = db.execute("SELECT COUNT(*) FROM push_records WHERE push_time >= ?", (today_start,))
        status["push_today"] = cu.fetchone()[0]
        cu = db.execute("SELECT MAX(push_time) FROM push_records")
        r = cu.fetchone()
        if r and r[0]: status["last_push"] = r[0][:16]
        db.close()
    except Exception as e:
        log(f"推送读取失败: {e}")
    
    # 自我增强轮次
    try:
        for p in [HERMES / "reports" / "gear_checkpoint.json", HERMES / "reports" / "recovery_pack.json"]:
            if p.exists():
                d = json.loads(p.read_text())
                r = d.get("task_id", "").split("_")[-1] if "task_id" in d else ""
                if "self_enhance" in str(d) or r:
                    status["self_enhance_round"] = r
                    break
    except: pass
    
    # 齿轮健康
    try:
        wg = json.loads((HERMES / "reports" / "wake_guide.json").read_text())
        status["gear_health"] = wg.get("gear_health", "unknown")
        if wg.get("g6_validation"):
            status["g6_ok"] = wg["g6_validation"].get("verified", False)
    except: pass
    
    return status

def build_message(status):
    """构建推送给用户的系统状态消息"""
    s = status
    health_icon = "✅" if s["gear_health"] == "healthy" else "⚠️" if s["gear_health"] == "degraded" else "❌"
    
    # 判断消息类型——采集是否活跃
    now = datetime.now()
    active = False
    if s["last_raw"] != "未知":
        try:
            t = datetime.strptime(s["last_raw"], "%Y-%m-%d %H:%M")
            if (now - t).total_seconds() < 7200:  # 2小时内
                active = True
        except: pass
    
    # 计算系统运行时间（从gear_enforcer日志开始）
    uptime = "?"
    try:
        for p in [HERMES / "logs" / "gear_enforcer.log", HERMES / "logs" / "gear_master.log"]:
            if p.exists():
                mtime = datetime.fromtimestamp(p.stat().st_mtime)
                days = (now - mtime).days
                hours = int((now - mtime).seconds / 3600)
                uptime = f"{days}天{hours}小时"
                break
    except: pass
    
    msg_lines = [
        f"🤖 Hermes 系统状态 · {s['ts_short']}",
        f"{health_icon} 齿轮系统: {s['gear_health'].upper()}",
        f"⏱ 持续运行: {uptime}",
        f"",
        f"📡 采集: {s['raw_count']}条raw → {s['clean_count']}条clean",
        f"   最新: {s['last_raw']} | 未评分: {s['unscored']}",
        f"📤 推送: 今日{s['push_today']}条 | 累计{s['push_total']}条",
        f"   最新: {s['last_push']}",
        f"🔄 自增强循环: 第{s['self_enhance_round']}轮",
    ]
    
    if not active and s["push_today"] == 0:
        msg_lines.insert(4, f"⚠️ **当前无活跃状态: 采集2小时无新数据，今日无推送**")
        msg_lines.insert(5, "")
    
    msg_lines.append(f"")
    msg_lines.append(f"---")
    msg_lines.append(f"💬 有任务直接说，我在线")
    
    return "\n".join(msg_lines)

def push_to_wechat(title, content):
    token = get_pushplus_token()
    if not token:
        log("❌ PushPlus token未配置")
        return False
    try:
        data = json.dumps({"token": token, "title": title, "content": content, "template": "markdown"}).encode()
        req = urllib.request.Request(
            "https://www.pushplus.plus/send", data=data,
            headers={"Content-Type": "application/json"}
        )
        resp = urllib.request.urlopen(req, timeout=15)
        result = json.loads(resp.read().decode())
        if result.get("code") == 200:
            log(f"✅ 状态推送成功")
            return True
        else:
            log(f"❌ 推送失败: {result.get('msg', '?')}")
            return False
    except Exception as e:
        log(f"❌ 推送异常: {e}")
        return False

# ── 备选推送通道: 邮件 ──────────────────────────────────────────
def push_via_email(subject: str, content: str, recipient: str = "") -> bool:
    """通过SMTP邮件推送状态报告(备选通道,不改变现有微信逻辑)"""
    try:
        import smtplib
        from email.mime.text import MIMEText
        cfg_path = HERMES / "config.yaml"
        if not cfg_path.exists():
            log("⏩ 邮件通道: 无config.yaml,跳过")
            return False
        cfg = yaml.safe_load(cfg_path.read_text())
        email_cfg = cfg.get("email", {}) or {}
        smtp_host = email_cfg.get("smtp_host", "") or email_cfg.get("host", "")
        smtp_port = email_cfg.get("smtp_port", 587) or email_cfg.get("port", 587)
        smtp_user = email_cfg.get("smtp_user", "") or email_cfg.get("user", "")
        smtp_pass = email_cfg.get("smtp_pass", "") or email_cfg.get("password", "") or email_cfg.get("pass", "")
        to_addr = recipient or email_cfg.get("to", "") or email_cfg.get("recipient", "")
        if not all([smtp_host, smtp_user, smtp_pass, to_addr]):
            log("⏩ 邮件通道: 配置不完整,跳过")
            return False
        msg = MIMEText(content, "plain", "utf-8")
        msg["Subject"] = subject
        msg["From"] = smtp_user
        msg["To"] = to_addr
        with smtplib.SMTP(smtp_host, int(smtp_port), timeout=15) as server:
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.send_message(msg)
        log(f"✅ 邮件推送成功 → {to_addr}")
        return True
    except ImportError:
        log("⏩ 邮件通道: smtplib不可用")
        return False
    except Exception as e:
        log(f"❌ 邮件推送失败: {e}")
        return False

# ── 备选推送通道: Webhook ───────────────────────────────────────
def push_via_webhook(title: str, content: str, webhook_url: str = "") -> bool:
    """通过通用Webhook推送状态报告(备选通道,不改变现有微信逻辑)
    支持: Slack Webhook, Discord Webhook, 企业微信机器人, 飞书机器人等
    """
    try:
        if not webhook_url:
            cfg_path = HERMES / "config.yaml"
            if cfg_path.exists():
                cfg = yaml.safe_load(cfg_path.read_text())
                webhook_url = (cfg.get("webhook", {}) or {}).get("url", "")
        if not webhook_url:
            log("⏩ Webhook通道: 未配置URL")
            return False
        
        # 自动检测Webhook类型并格式化
        payload = json.dumps({
            "title": title,
            "content": content,
            "text": content,
            "msgtype": "markdown",
            "markdown": {"content": f"# {title}\n\n{content}"},
        }).encode()
        
        req = urllib.request.Request(
            webhook_url, data=payload,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read().decode()
            log(f"✅ Webhook推送成功 (status={resp.status})")
            return True
    except Exception as e:
        log(f"❌ Webhook推送失败: {e}")
        return False

def should_report():
    """判断是否应该发送状态报告（40分钟无对话且不重复报告）"""
    last_chat = get_last_chat_time()
    now = datetime.now()
    idle_minutes = (now - last_chat).total_seconds() / 60
    
    if idle_minutes < 30:
        return False  # 30分钟内有对话，不打扰
    
    # 检查上次推送时间，避免重复
    try:
        db = sqlite3.connect(str(HERMES / "intelligence.db"))
        cu = db.execute("SELECT MAX(push_time) FROM push_records")
        r = cu.fetchone()
        db.close()
        if r and r[0]:
            last_push = datetime.fromisoformat(r[0])
            if (now - last_push).total_seconds() < 1800:  # 30分钟内推过
                return False
    except: pass
    
    return True

def main():
    """主入口"""
    log("=" * 40)
    log("状态反馈系统启动")
    
    mode = sys.argv[1] if len(sys.argv) > 1 else "normal"
    
    if mode == "force":
        # 强制推送（对话中主动反馈用）
        status = get_system_status()
        msg = build_message(status)
        push_to_wechat(f"🤖 Hermes 状态更新 · {status['ts_short']}", msg)
        return
    
    if not should_report():
        log("对话活跃中或已推过，跳过本次推送")
        return
    
    status = get_system_status()
    msg = build_message(status)
    push_to_wechat(f"🤖 Hermes 状态更新 · {status['ts_short']}", msg)

if __name__ == "__main__":
    main()

