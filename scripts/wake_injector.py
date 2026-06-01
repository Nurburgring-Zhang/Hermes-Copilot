#!/usr/bin/env python3
"""
🔴🔴🔴 反幻觉铁律：严禁任何不加核实的猜想、胡编乱造、自己瞎编！
必须核实才能说/必须验证才能写/必须确认才能断言/不知道就说不知道
这是最高优先级规则，凌驾于所有其他规则之上。
"""

"""
wake_injector.py — Hermes 唤醒时自动注入 Hy-Memory (v2.0 LLM增强版)
=========================================================
在 gear_enforcer 检测到对话开始时自动调用。
写入 wake_guide.json 的 hy_memory_injection + task_boundary 字段。

v2.0 新增:
  - L1 LLM提取的结果直接注入
  - L2场景导航注入
  - L3画像全维度注入
  - 主动提示当前可用的LLM后端 (delegate/lmstudio/ollama)

被 cron: hy-memory-recall-inject (每1分钟) 调用
"""

import json
import sys
import sqlite3
from pathlib import Path

REPORTS_DIR = Path.home() / ".hermes" / "reports"
SCRIPTS_DIR = Path.home() / ".hermes" / "scripts"
ACTIVE_MEMORY_DB = Path.home() / ".hermes" / "active_memory.db"

sys.path.insert(0, str(SCRIPTS_DIR))
from auto_recall import AutoRecall
from tool_unloader import ToolUnloader


def inject_to_wake_guide():
    """向 wake_guide.json 中写入完整的 Hy-Memory 记忆注入"""
    wake_path = REPORTS_DIR / "wake_guide.json"
    
    if not wake_path.exists():
        return False
    
    try:
        wake_data = json.loads(wake_path.read_text(encoding='utf-8'))
    except (json.JSONDecodeError, FileNotFoundError):
        return False
    
    user_input = wake_data.get("last_user_message", "")
    recent_sessions = wake_data.get("recent_sessions", "")
    
    # ========== 功能0: 历史会话检索注入 (防记忆丢失) ==========
    session_context = ""
    if user_input:
        try:
            # AutoRecall 已经在文件顶部全局导入了
            _sr = AutoRecall()
            # 用用户输入做关键词检索历史会话
            _recall = _sr.recall_for_session(user_input)
            if _recall:
                session_context = _recall
        except Exception:
            pass
    
    # ========== 功能1: 任务边界检测 (P2 L1.5) ==========
    if user_input:
        try:
            from task_boundary import check_boundary
            boundary = check_boundary(user_input)
            wake_data["task_boundary"] = {
                "last_action": boundary["action"],
                "confidence": round(boundary["confidence"], 2),
                "reason": boundary["reason"],
                "new_label": boundary.get("new_label"),
            }
        except Exception as e:
            pass
    
    # ========== 功能2: 记忆召回注入 (P0, v2.1 task_type筛选) ==========
    recaller = AutoRecall()
    # 从wake_guide读取task_type
    task_type = wake_data.get("task_type", "")
    if not task_type and "interrupted_task" in wake_data and "detail" in wake_data["interrupted_task"]:
        # 从中断任务详情提取关键词作为task_type提示
        task_type = wake_data["interrupted_task"].get("detail", "")[:100]
    
    if user_input:
        if task_type:
            # 带task_type的智能召回: 优先检索与task_type相关的记忆
            combined_query = f"{task_type} {user_input}"
            recall = recaller.recall_for_session(combined_query)
        else:
            recall = recaller.recall_for_session(user_input)
    else:
        # 无用户输入时，注入最近的记忆摘要作为背景
        persona_full = recaller.get_persona_context()
        # 如果有task_type, 只保留相关部分的记忆（压缩到~800 chars）
        if task_type:
            recall = recaller.recall_for_session(task_type)
            persona = recaller.get_persona_context()
        else:
            # 无task_type: 压缩到最近30天+高重要性
            recall = recaller.get_persona_context()
            # 截断到800字符
            if len(recall) > 800:
                recall = recall[:800] + "\n...(compressed)"
    persona = recaller.get_persona_context()
    # 有task_type时压缩persona保持在800字以内
    if task_type and persona and len(persona) > 800:
        persona = persona[:800] + "\n...(compressed)"
    
    # ========== 功能3: 工具卸载维护 (P0) ==========
    unloader = ToolUnloader()
    cleaned = unloader.cleanup_expired()
    context = unloader.get_compressed_context(max_entries=5)
    
    # ========== 功能4: L2场景 + L3画像 (P3 LLM驱动) ==========
    scenes_info = []
    profiles_info = []
    l1_stats = {}
    
    try:
        db = sqlite3.connect(str(ACTIVE_MEMORY_DB))
        cur = db.cursor()
        
        # L2场景(最近活跃top-5)
        cur.execute('SELECT name, description, frequency, confidence, keywords, last_activated FROM memory_scene ORDER BY frequency DESC, last_activated DESC LIMIT 5')
        for r in cur.fetchall():
            scenes_info.append({
                "name": r[0], 
                "desc": r[1][:100] if r[1] else "", 
                "freq": r[2], 
                "conf": r[3],
                "keywords": r[4],
                "last_active": r[5],
            })
        
        # L3画像(全维度)
        cur.execute('SELECT name, profile_type, dimensions, summary, updated_at FROM memory_profile ORDER BY updated_at DESC LIMIT 2')
        for r in cur.fetchall():
            dims_data = {}
            try:
                dims_raw = r[2]
                if isinstance(dims_raw, str):
                    dims_data = json.loads(dims_raw)
            except (json.JSONDecodeError, TypeError):
                dims_data = {"raw": str(dims_raw)[:200]}
            
            profiles_info.append({
                "name": r[0],
                "type": r[1],
                "dimensions": dims_data,
                "updated": r[4],
            })
        
        # L1统计数据
        cur.execute("SELECT cat, COUNT(*) FROM memory_semantic WHERE active=1 GROUP BY cat ORDER BY COUNT(*) DESC")
        l1_stats = {r[0]: r[1] for r in cur.fetchall()}
        cur.execute("SELECT COUNT(*) FROM memory_semantic WHERE active=1")
        l1_stats["total"] = cur.fetchone()[0]
        
        # LLM可用性检测
        l1_stats["llm_backends"] = {}
        for name, url in [("lmstudio", "http://localhost:8080/v1/models"), 
                          ("ollama", "http://localhost:11434/api/tags")]:
            try:
                import urllib.request
                req = urllib.request.Request(url)
                urllib.request.urlopen(req, timeout=2)
                l1_stats["llm_backends"][name] = "available"
            except Exception:
                l1_stats["llm_backends"][name] = "unavailable"
        
        db.close()
    except Exception:
        pass
    
    # ========== 写入 wake_guide ==========
    injection = {}
    if recall:
        injection["relevant_memories"] = recall
    if persona:
        injection["persona_summary"] = persona
    if context:
        injection["offloaded_context"] = context
    if scenes_info:
        injection["scenes"] = scenes_info
    if profiles_info:
        injection["profiles"] = profiles_info
    if l1_stats:
        injection["l1_stats"] = l1_stats
    
    if injection:
        wake_data["hy_memory"] = injection
    
    wake_path.write_text(
        json.dumps(wake_data, ensure_ascii=False, indent=2),
        encoding='utf-8'
    )
    
    # 报告
    parts = []
    if recall:
        parts.append(f"Recall✅")
    if persona:
        parts.append(f"Persona✅")
    if context:
        parts.append(f"Offload({context.count('ref:')} refs)")
    if scenes_info:
        parts.append(f"Scene({len(scenes_info)})✅")
    if profiles_info:
        parts.append(f"Profile({len(profiles_info)})✅")
    if cleaned:
        parts.append(f"Cleaned({cleaned})")
    if l1_stats:
        parts.append(f"Facts({l1_stats.get('total', 0)})✅")
    if "task_boundary" in wake_data:
        ba = wake_data["task_boundary"].get("last_action", "")
        if ba == "new_task":
            parts.append("Boundary🔀")
    
    return " | ".join(parts) if parts else "No injection"


if __name__ == "__main__":
    result = inject_to_wake_guide()
    print(result)
