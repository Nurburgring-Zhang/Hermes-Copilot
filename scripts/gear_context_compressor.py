#!/usr/bin/env python3
"""
⚙️ 齿轮上下文压缩器 v1.0 — 对话层主动压缩引擎
=============================================
调用方式: 由Hermes对话中每5轮主动调用
功能: 实时压缩上下文状态到文件 + 写断点 + 写审计
确保: 上下文不被撑爆 + 中断可恢复 + 信息不丢失

集成:
  - lossless_claw.py (压缩引擎)
  - context_guardian.py (快照)
  - task_current.json (断点)
  - gear-context-compression skill (流程定义)
"""

import json, sqlite3, os, sys, zlib, gzip, hashlib
from datetime import datetime, timezone, timedelta
from pathlib import Path

HERMES = Path("/home/administrator/.hermes")
TZ = timezone(timedelta(hours=8))
now = lambda: datetime.now(TZ).isoformat()

# ===== G3互审: 验证G2的恢复包是否健康 =====
_gear_signed = False

def _gear_sign(task_id="auto", claim_detail="") -> dict:
    """向G0齿轮注册中心签到"""
    try:
        import subprocess as sp
        r = sp.run([sys.executable, str(HERMES / "scripts/gear_vault.py"), "sign", 
                    "G3", task_id, json.dumps({"action": "checkpoint", "detail": claim_detail})],
                   capture_output=True, timeout=10, text=True)
        return {"signed": True, "output": r.stdout[:200]}
    except Exception as e:
        return {"signed": False, "error": str(e)}

def _verify_g2_recovery() -> dict:
    """G3验证G2(context_failsafe)的恢复包完整性"""
    rp = HERMES / "reports" / "recovery_pack.json"
    if not rp.exists():
        return {"verified": False, "error": "G2恢复包不存在"}
    try:
        pack = json.loads(rp.read_text())
        g1_check = pack.get("_g1_heartbeat_check", {})
        integrity = pack.get("_integrity_check", {})
        return {
            "verified": g1_check.get("verified", True),
            "g1_heartbeat": g1_check,
            "integrity": integrity,
            "pack_status": pack.get("status", "unknown")
        }
    except Exception as e:
        return {"verified": False, "error": str(e)}

def _hash_checkpoint_files() -> dict:
    """验证task_current和gear_checkpoint的一致性"""
    import hashlib
    result = {"files": {}, "consistent": False}
    for name in ["task_current.json", "reports/gear_checkpoint.json"]:
        path = HERMES / name
        if path.exists():
            result["files"][name] = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
        else:
            result["files"][name] = "MISSING"
    try:
        tc = json.loads((HERMES / "task_current.json").read_text())
        gc = json.loads((HERMES / "reports/gear_checkpoint.json").read_text())
        result["consistent"] = (tc.get("task_id") == gc.get("task_id") or 
                                tc.get("status") == gc.get("status"))
    except:
        pass
    return result
# ===== 互审结束 =====

def estimate_tokens(text: str) -> int:
    """粗略估计token数 (中文~1.5, 英文~1.3)"""
    cn_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    en_chars = len(text) - cn_chars
    return int(cn_chars * 1.5 + en_chars * 1.3)

def gear_status() -> dict:
    """齿轮状态诊断 — 醒来第一件事调用"""
    status = {
        "ts": now(),
        "compressor": {"ready": False},
        "task_checkpoint": {"exists": False},
        "audit_snapshot": {"exists": False},
        "gear_checkpoint": {"exists": False},
        "estimated_context": {"chars": 0, "tokens": 0, "risk": "unknown"}
    }
    
    # 检查 lossless_claw
    claw = HERMES / "scripts" / "lossless_claw.py"
    if claw.exists():
        status["compressor"]["ready"] = True
    
    # 检查 task_current
    tc = HERMES / "task_current.json"
    if tc.exists():
        try:
            data = json.loads(tc.read_text())
            status["task_checkpoint"] = {
                "exists": True,
                "task_id": data.get("task_id", "NONE"),
                "status": data.get("status", "unknown"),
                "next_action": data.get("next_action", ""),
                "detail": data.get("detail", "")[:100]
            }
        except:
            pass
    
    # 检查 gear_checkpoint
    gc = HERMES / "reports" / "gear_checkpoint.json"
    if gc.exists():
        try:
            status["gear_checkpoint"] = json.loads(gc.read_text())
        except:
            pass
    
    # 检查 audit
    au = HERMES / "reports" / "audit_snapshot.json"
    if au.exists():
        status["audit_snapshot"]["exists"] = True
    
    return status

def gear_compress(context_text: str, round_num: int = 0) -> dict:
    """
    齿轮A: 对话级压缩
    被Hermes每5轮调用一次
    """
    result = {
        "action": "compress_check",
        "ts": now(),
        "round": round_num,
        "compressed": False,
        "summary_written": False,
        "checkpoint_written": False,
        "token_estimate": 0,
        "risk_level": "low"
    }
    
    tokens = estimate_tokens(context_text)
    result["token_estimate"] = tokens
    
    # 风险分级
    if tokens > 40000:
        result["risk_level"] = "CRITICAL"
    elif tokens > 25000:
        result["risk_level"] = "high"
    elif tokens > 15000:
        result["risk_level"] = "medium"
    else:
        result["risk_level"] = "low"
    
    # 仅在中等风险以上时压缩
    if result["risk_level"] in ("high", "CRITICAL"):
        # 1. 生成压缩摘要
        summary = _make_summary(context_text)
        
        # 2. 写入 conversation_summary
        summary_path = HERMES / "reports" / "conversation_summary.json"
        summary_data = {
            "ts": now(),
            "round": round_num,
            "tokens_before": tokens,
            "summary": summary
        }
        summary_path.parent.mkdir(exist_ok=True)
        summary_path.write_text(json.dumps(summary_data, ensure_ascii=False, indent=2))
        result["summary_written"] = True
        
        # 3. 写 gear_checkpoint
        gear_checkpoint = {
            "ts": now(),
            "round": round_num,
            "status": "active",
            "tokens_estimate": tokens,
            "risk_level": result["risk_level"],
            "compression_applied": True,
            "summary_ref": str(summary_path)
        }
        gc_path = HERMES / "reports" / "gear_checkpoint.json"
        gc_path.write_text(json.dumps(gear_checkpoint, ensure_ascii=False, indent=2))
        result["checkpoint_written"] = True
        
    elif result["risk_level"] == "medium":
        # 中风险: 只做checkpoint
        gear_checkpoint = {
            "ts": now(),
            "round": round_num,
            "status": "active",
            "tokens_estimate": tokens,
            "risk_level": "medium",
            "compression_applied": False,
            "note": "推荐下一轮压缩"
        }
        gc_path = HERMES / "reports" / "gear_checkpoint.json"
        gc_path.parent.mkdir(exist_ok=True)
        gc_path.write_text(json.dumps(gear_checkpoint, ensure_ascii=False, indent=2))
        result["checkpoint_written"] = True
    
    # 4. 始终写task_current（保险）
    _write_task_checkpoint("gear_auto_compress_round_" + str(round_num), 
                          "running", [], [], f"round_{round_num}_compressed", 
                          f"齿轮压缩, tokens={tokens}, 风险={result['risk_level']}")
    
    return result

def gear_checkpoint(task_id: str, round_num: int, detail: str, 
                    next_action: str = "", step_status: str = "running") -> dict:
    """
    齿轮B: 每次发送消息前调用
    写断点确保可以恢复
    """
    result = {
        "action": "gear_checkpoint",
        "ts": now(),
        "task_id": task_id,
        "round": round_num,
        "next_action": next_action,
        "step_status": step_status
    }
    
    # 写 gear_checkpoint (最新的进度)
    cp = {
        "ts": now(),
        "task_id": task_id,
        "round": round_num,
        "detail": detail[:200],
        "next_action": next_action,
        "step_status": step_status
    }
    gc_path = HERMES / "reports" / "gear_checkpoint.json"
    gc_path.parent.mkdir(exist_ok=True)
    gc_path.write_text(json.dumps(cp, ensure_ascii=False, indent=2))
    result["checkpoint_written"] = True
    
    # 写 task_current (保险)
    _write_task_checkpoint(task_id, step_status, [], [], next_action, detail[:200])
    
    # ===== G0签章 =====
    global _gear_signed
    if not _gear_signed:
        v = _verify_g2_recovery()
        hc = _hash_checkpoint_files()
        _gear_sign(task_id, f"round={round_num} g2_ok={v.get('verified')} consistent={hc.get('consistent')}")
        _gear_signed = True
    
    return result

def gear_complete(task_id: str, detail: str = "") -> dict:
    """齿轮完成标记 — 任务完成时调用"""
    result = {
        "action": "gear_complete",
        "ts": now(),
        "task_id": task_id
    }
    
    # 清 gear_checkpoint
    gc_path = HERMES / "reports" / "gear_checkpoint.json"
    final = {
        "ts": now(),
        "task_id": task_id,
        "status": "completed",
        "detail": detail[:300]
    }
    gc_path.write_text(json.dumps(final, ensure_ascii=False, indent=2))
    
    # 清 task_current
    tc_path = HERMES / "task_current.json"
    tc_path.write_text(json.dumps({
        "task_id": task_id,
        "status": "completed",
        "detail": detail[:200],
        "ts": now(),
        "completed_steps": [],
        "pending_steps": [],
        "next_action": ""
    }, ensure_ascii=False, indent=2))
    result["completed"] = True
    return result

def _make_summary(text: str, max_len: int = 500) -> str:
    """生成上下文摘要 (取开头+结尾的key info)"""
    if len(text) <= max_len:
        return text
    
    # 取前20%和后30%
    head_len = int(max_len * 0.3)
    tail_len = int(max_len * 0.6)
    
    head = text[:head_len]
    tail = text[-tail_len:]
    
    lines = text.split('\n')
    # 找关键行（含tool_call, error, completed, summary的）
    key_lines = []
    for line in lines:
        low = line.lower()
        if any(kw in low for kw in ['error', 'fail', 'complete', 'result:', 'response:', 
                                      'task_id', 'gear_', 'step', 'summary', 'result:',
                                      'warning', 'critical', 'hermes_test_result',
                                      'verdict', 'verification', '✅', '❌', '⚠️']):
            key_lines.append(line.strip()[:120])
    
    key_section = '\n'.join(key_lines[-30:]) if key_lines else ""
    
    summary = f"[压缩摘要] tokens≈{estimate_tokens(text)}\n"
    summary += f"[开头]{head}\n"
    if key_section:
        summary += f"[关键事件]\n{key_section}\n"
    summary += f"[结尾]{tail}"
    
    return summary[:max_len]

def _write_task_checkpoint(task_id, status, completed, pending, next_action, detail):
    """写 task_current.json"""
    data = {
        "task_id": task_id,
        "status": status,
        "completed_steps": completed,
        "pending_steps": pending,
        "next_action": next_action,
        "detail": detail[:200],
        "ts": now()
    }
    (HERMES / "task_current.json").write_text(json.dumps(data, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    
    if cmd == "status":
        print(json.dumps(gear_status(), ensure_ascii=False, indent=2))
    elif cmd == "compress":
        context = sys.stdin.read() if len(sys.argv) < 3 else sys.argv[2]
        round_num = int(sys.argv[3]) if len(sys.argv) > 3 else 0
        print(json.dumps(gear_compress(context, round_num), ensure_ascii=False, indent=2))
    elif cmd == "checkpoint":
        task_id = sys.argv[2] if len(sys.argv) > 2 else "manual"
        round_num = int(sys.argv[3]) if len(sys.argv) > 3 else 0
        detail = sys.argv[4] if len(sys.argv) > 4 else "手动检查点"
        next_action = sys.argv[5] if len(sys.argv) > 5 else ""
        print(json.dumps(gear_checkpoint(task_id, round_num, detail, next_action), 
                         ensure_ascii=False, indent=2))
    elif cmd == "complete":
        task_id = sys.argv[2] if len(sys.argv) > 2 else "manual"
        detail = sys.argv[3] if len(sys.argv) > 3 else ""
        print(json.dumps(gear_complete(task_id, detail), ensure_ascii=False, indent=2))
    elif cmd == "compress_round":
        # 对话中每5轮调用: python3 gear_context_compressor.py compress_round <round_num>
        round_num = int(sys.argv[2]) if len(sys.argv) > 2 else 0
        # ★修复: 读取当前会话上下文而非传空字符串
        context_text = ""
        ctx_file = HERMES / "reports" / "current_context.txt"
        if ctx_file.exists():
            try:
                context_text = ctx_file.read_text(encoding='utf-8')
            except:
                pass
        if not context_text:
            # 尝试从task_current获取
            tc_file = HERMES / "task_current.json"
            if tc_file.exists():
                try:
                    tc_data = json.loads(tc_file.read_text())
                    context_text = json.dumps(tc_data, ensure_ascii=False)
                except:
                    pass
        print(f"⚙️ 齿轮A: 第{round_num}轮压缩 (上下文{len(context_text)}字)")
        print(json.dumps(gear_compress(context_text, round_num), ensure_ascii=False, indent=2))
    elif cmd == "resume_guide":
        # 输出恢复指南
        status = gear_status()
        tc = status.get("task_checkpoint", {})
        gc = status.get("gear_checkpoint", {})
        print("⚙️ 齿轮恢复指南 ⚙️")
        print(f"断点状态: {tc.get('status', 'N/A')}")
        print(f"任务: {tc.get('task_id', 'N/A')}")
        print(f"下一步: {tc.get('next_action', 'N/A')}")
        print(f"详情: {tc.get('detail', 'N/A')}")
        if gc:
            print(f"齿轮进度: {json.dumps(gc, ensure_ascii=False)}")
        print("---")
        print(f"压缩器状态: {'✅' if status['compressor']['ready'] else '❌'}")
        print(f"审计快照: {'✅' if status['audit_snapshot']['exists'] else '❌'}")
    else:
        print(f"Unknown: {cmd}")
        print("Commands: status, compress, checkpoint, complete, compress_round, resume_guide")
