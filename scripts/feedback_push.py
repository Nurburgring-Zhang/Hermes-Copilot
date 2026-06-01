#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Hermes 任务进度主动反馈 v1.0
==========================
在长时间任务执行过程中，自动向微信推送进度报告。
由齿轮系统(task_driver/driver.py)每检测到任务状态变化时调用。

用法：
  python3 scripts/feedback_push.py "消息内容"
  python3 scripts/feedback_push.py --stage "阶段名" "当前做完了什么" "下一步做什么"

如果是长任务，每完成一个子阶段就调一次，用户能看到进度。
"""
import json, sys, urllib.request, yaml
from pathlib import Path
from datetime import datetime

HERMES = Path("/home/administrator/.hermes")

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

def push_wechat(title, content):
    token = get_pushplus_token()
    if not token: return False
    try:
        data = json.dumps({"token": token, "title": title, "content": content, "template": "markdown"}).encode()
        req = urllib.request.Request("https://www.pushplus.plus/send", data=data, headers={"Content-Type": "application/json"})
        resp = urllib.request.urlopen(req, timeout=15)
        r = json.loads(resp.read().decode())
        return r.get("code") == 200
    except: return False

def main():
    args = sys.argv[1:]
    if not args:
        print("用法: feedback_push.py <消息>")
        print("  或: feedback_push.py --stage <阶段> <已完成> <下一步>")
        sys.exit(1)
    
    if args[0] == "--stage" and len(args) >= 3:
        stage = args[1]
        done = args[2]
        nxt = args[3] if len(args) > 3 else ""
        
        # 读取当前任务状态
        task_info = ""
        try:
            wg = json.loads((HERMES / "reports" / "wake_guide.json").read_text())
            t = wg.get("interrupted_task", {})
            if t.get("task_id"):
                task_info = f"\n#{t['task_id'][:20]}..."
        except: pass
        
        lines = [f"⚙️ **{stage}**{task_info}"]
        lines.append(f"")
        lines.append(f"✅ {done}")
        if nxt:
            lines.append(f"")
            lines.append(f"→ 下一步: {nxt}")
        
        ok = push_wechat(f"🤖 任务进度 · {stage}", "\n".join(lines))
        print(f"推送{'成功' if ok else '失败'}: {stage}")
    else:
        msg = " ".join(args)
        ok = push_wechat("🤖 Hermes 反馈", msg)
        print(f"推送{'成功' if ok else '失败'}: {msg[:40]}...")

if __name__ == "__main__":
    main()

