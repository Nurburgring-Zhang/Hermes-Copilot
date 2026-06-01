#!/usr/bin/env python3
"""
🌅 醒来指南生成器 v1.0 — 让cron替Hermes记住所有事
=================================================
cron每1分钟运行一次（集成在gear_enforcer中）。
每次醒来，Hermes只需要读一个文件：reports/wake_guide.json
就知道：
  - 有没有中断任务需要恢复
  - 有没有AI评分待办
  - 系统健康状态
  - 该做什么
"""
import json, sqlite3, sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

HERMES = Path("/home/administrator/.hermes")
TZ = timezone(timedelta(hours=8))
now = lambda: datetime.now(TZ)

# ===== G7互审: 验证G6的完整验证报告 =====
_gear_signed = False

def _gear_sign(task_id="auto", claim_detail=""):
    try:
        import subprocess as sp
        r = sp.run([sys.executable, str(HERMES / "scripts/gear_vault.py"), "sign",
                    "G7", task_id, json.dumps({"action": "wake_guide", "detail": claim_detail})],
                   capture_output=True, timeout=10, text=True)
        return {"signed": True, "output": r.stdout[:200]}
    except Exception as e:
        return {"signed": False, "error": str(e)}

def _verify_g6_validation() -> dict:
    """G7验证G6(gear_task_validator)的最后一次验证报告"""
    alert = HERMES / "reports" / "G6_VALIDATION_ALERT.json"
    vlog = HERMES / "reports" / "verification_log.json"
    
    result = {"verified": True, "last_validation": None, "alerts": []}
    
    if alert.exists():
        try:
            data = json.loads(alert.read_text())
            if not data.get("chains_pass") or not data.get("scripts_pass") or not data.get("g5_pass"):
                result["verified"] = False
                result["alerts"].append("G6验证发现齿轮链/脚本/G5有问题")
                result["g6_alert"] = data
        except:
            pass
    
    # 检查最新验收记录
    if vlog.exists():
        try:
            records = json.loads(vlog.read_text())
            if records and isinstance(records, list) and len(records) > 0:
                last = records[-1]
                result["last_validation"] = {
                    "task": last.get("task_id"),
                    "status": last.get("status"),
                    "accepted": last.get("accepted", False),
                    "ts": last.get("accepted_at") or last.get("status")
                }
        except:
            pass
    
    return result

def build_wake_guide():
    guide = {
        "ts": now().isoformat(),
        "interrupted_task": None,
        "ai_scoring_pending": 0,
        "ai_scoring_today": 0,
        "ai_scoring_total_today": 0,
        "push_today": 0,
        "push_fail_today": 0,
        "omni_loop_status": "unknown",
        "gear_heartbeat_minutes": 0,
        "actions_required": []
    }
    
    # 1. 中断任务检查 (三重冗余)
    rp = HERMES / "reports" / "recovery_pack.json"
    gc = HERMES / "reports" / "gear_checkpoint.json"
    tc = HERMES / "task_current.json"
    
    for source, path in [("recovery_pack", rp), ("gear_checkpoint", gc), ("task_current", tc)]:
        if path and path.exists():
            try:
                data = json.loads(path.read_text())
                if source == "recovery_pack":
                    tc_data = data.get("task_current") or {}
                    gc_data = data.get("gear_checkpoint") or {}
                    status = data.get("status", "")
                    item = gc_data if gc_data.get("task_id") else tc_data
                else:
                    status = data.get("status", "")
                    item = data
                
                if status in ("running", "interrupted"):
                    # ===== 跳过自强化循环误判 =====
                    # self_enhance_* 是V3自我强化循环(每1分钟cron)，不是真正的中断任务
                    tid = item.get("task_id", "")
                    if tid and tid.startswith("self_enhance_"):
                        continue  # 跳过，不标记为中断任务
                    guide["interrupted_task"] = {
                        "task_id": item.get("task_id", "?"),
                        "next_action": item.get("next_action", ""),
                        "detail": item.get("detail", "")[:100],
                        "source": source
                    }
                    guide["actions_required"].append("🔄 恢复中断任务: {} → {}".format(
                        item.get("task_id","?"), item.get("next_action","?")))
                    break
            except:
                pass
    
    # 2. AI评分
    try:
        db = sqlite3.connect(str(HERMES / "intelligence.db"))
        today = db.execute("SELECT COUNT(*) FROM cleaned_intelligence WHERE date(cleaned_at) = date('now','localtime')").fetchone()[0]
        real_ai = db.execute("""SELECT COUNT(*) FROM cleaned_intelligence 
            WHERE date(cleaned_at) = date('now','localtime') AND ai_score_reasoning LIKE '%real_ai%'""").fetchone()[0]
        pending = db.execute("""SELECT COUNT(*) FROM cleaned_intelligence 
            WHERE (ai_score_reasoning IS NULL OR ai_score_reasoning = '' OR ai_score_reasoning LIKE '%规则评分%')
            AND title IS NOT NULL AND LENGTH(COALESCE(content,'')) > 50""").fetchone()[0]
        
        guide["ai_scoring_pending"] = pending
        guide["ai_scoring_today"] = real_ai
        guide["ai_scoring_total_today"] = today
        
        if pending > 0:
            # 获取最高优先级的待评分条目
            top = db.execute("""SELECT id, title, source FROM cleaned_intelligence 
                WHERE (ai_score_reasoning IS NULL OR ai_score_reasoning = '' OR ai_score_reasoning LIKE '%规则评分%')
                AND title IS NOT NULL AND LENGTH(COALESCE(content,'')) > 50
                ORDER BY id DESC LIMIT 3""").fetchall()
            guide["top_pending"] = [{"id": r[0], "title": r[1][:40], "source": r[2]} for r in top]
            guide["actions_required"].append("⭐ AI评分: {}条待评分 (今日{}已评{})".format(pending, today, real_ai))
        db.close()
    except: pass
    
    # 3. 推送
    try:
        db = sqlite3.connect(str(HERMES / "intelligence.db"))
        guide["push_today"] = db.execute("SELECT COUNT(*) FROM push_records WHERE date(push_time) = date('now','localtime')").fetchone()[0]
        guide["push_fail_today"] = db.execute("SELECT COUNT(*) FROM push_records WHERE date(push_time) = date('now','localtime') AND push_status='failed'").fetchone()[0]
        if guide["push_fail_today"] > 0:
            guide["actions_required"].append("🔧 推送失败{}条".format(guide["push_fail_today"]))
        db.close()
    except: pass
    
    # 4. Omni loop
    log = HERMES / "logs" / "omni_loop.log"
    if log.exists():
        lines = log.read_text().splitlines()
        for line in reversed(lines[-30:]):
            if "完美完成" in line or "全部8步成功" in line:
                guide["omni_loop_status"] = "✅ 正常"
                break
            elif "失败" in line or "错误" in line or "Error" in line:
                guide["omni_loop_status"] = "❌ 异常"
                guide["actions_required"].append("🔧 omni_loop状态异常")
                break
    
    # 5. 齿轮心跳
    hb = HERMES / "logs" / "gear_heartbeat.txt"
    if hb.exists():
        try:
            hb_time = datetime.fromisoformat(hb.read_text().strip())
            diff = now() - hb_time.replace(tzinfo=TZ)
            guide["gear_heartbeat_minutes"] = round(diff.total_seconds() / 60, 1)
        except: pass
    
    # ===== G7互审:G6验证结果 =====
    global _gear_signed
    g6_v = _verify_g6_validation()
    guide["g6_validation"] = g6_v
    if not g6_v.get("verified"):
        guide["gear_health"] = "degraded"
        guide["actions_required"].append(f"🔴 齿轮系统验证失败: {g6_v.get('alerts', ['未知'])}")
    else:
        guide["gear_health"] = "healthy"
        if g6_v.get("last_validation"):
            lv = g6_v["last_validation"]
            guide["actions_required"].append(f"📋 最近验收: {lv.get('task')} -> {lv.get('status')}")
    
    if not _gear_signed:
        _gear_sign("wake_guide_cron", f"interrupted={guide['interrupted_task'] is not None} pending_ai={guide['ai_scoring_pending']}")
        _gear_signed = True
    
    # 写入
    (HERMES / "reports" / "wake_guide.json").write_text(json.dumps(guide, ensure_ascii=False, indent=2))
    return guide

if __name__ == "__main__":
    guide = build_wake_guide()
    actions = guide.get("actions_required", [])
    
    print("🌅 醒来指南")
    print("=" * 50)
    if guide["interrupted_task"]:
        t = guide["interrupted_task"]
        print(f"🔴 中断任务: {t['task_id']}")
        print(f"   下一步: {t['next_action']}")
        print(f"   详情: {t['detail']}")
    else:
        print("✅ 无中断任务")
    
    print(f"\nAI评分: {guide['ai_scoring_total_today']}条今日采集, {guide['ai_scoring_today']}条已评分")
    if guide["ai_scoring_pending"] > guide["ai_scoring_total_today"]:
        print(f"       全库待评分: {guide['ai_scoring_pending']}条(主要为历史数据)")
    
    print(f"推送: 今日{guide['push_today']}条 失败{guide['push_fail_today']}条")
    print(f"Omni循环: {guide['omni_loop_status']}")
    print(f"齿轮心跳: {guide['gear_heartbeat_minutes']}分钟前")
    
    if actions:
        print(f"\n📋 待处理: {len(actions)}项")
        for a in actions:
            print(f"  {a}")
    else:
        print("\n✅ 无待处理事项")
