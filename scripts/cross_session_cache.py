#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Hermes 跨轮次上下文缓存 + 输出自动更新 v1.0
================================================
每次对话结束时调用。

功能1（跨轮次缓存）：
  - 记录本轮对话用到了哪些章节
  - 记录本轮任务进度
  - 记录本轮用到的工具
  - 写入 cross_session_cache.json，供下一轮延续

功能2（输出自动更新）：
  - 读取本轮AI的回复（stdin或参数）
  - 自动提取进度更新
  - 更新 task_current.json 中的进度
  - 更新 wake_guide 中的待办状态
"""

import json, sys, re
from pathlib import Path
from datetime import datetime

HERMES = Path("/home/administrator/.hermes")

def estimate_tokens(text: str) -> int:
    cn = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    en = len(text) - cn
    return int(cn * 1.5 + en * 1.3)

def read_context_cache() -> dict:
    """读取当前上下文中已用章节和进度"""
    result = {
        "used_sections": [],
        "used_tools": [],
        "task_progress": {},
        "session_count": 0,
        "last_task_type": None
    }
    
    # 从auto_assoc读取已预加载的章节
    aa = HERMES / "reports" / "context_auto_assoc.json"
    if aa.exists():
        try:
            d = json.loads(aa.read_text())
            result["last_task_type"] = d.get("task_type")
            result["preloaded"] = list(d.get("preloaded_summaries", {}).keys())
        except Exception:
            pass
    
    # 从跨轮次缓存读取延续数据
    cache = HERMES / "reports" / "cross_session_cache.json"
    if cache.exists():
        try:
            prev = json.loads(cache.read_text())
            result["used_sections"] = prev.get("used_sections", [])
            result["used_tools"] = prev.get("used_tools", [])
            result["session_count"] = prev.get("session_count", 0) + 1
            result["task_progress"] = prev.get("task_progress", {})
        except Exception:
            pass
    
    return result

def update_cache(ai_response: str = "") -> dict:
    """更新跨轮次缓存"""
    
    # 读取当前状态
    cache_data = read_context_cache()
    
    # 如果传入了AI回复，尝试提取进度信息
    progress_update = {}
    if ai_response:
        # 提取"已完成"标记
        done_match = re.findall(r'(?:完成|修复|实现|添加)(?:了)?[:：]?\s*(.+?)[。\n]', ai_response)
        if done_match:
            progress_update["completed"] = done_match
        
        # 提取"下一步"标记
        next_match = re.findall(r'(?:下一步|待办|TODO|pending|还需要)[：:]?\s*(.+?)[。\n]', ai_response)
        if next_match:
            progress_update["next_steps"] = next_match
        
        # 提取章节引用
        section_refs = re.findall(r'context_sections/(\S+?)\.md', ai_response)
        if section_refs:
            for ref in section_refs:
                if ref not in cache_data["used_sections"]:
                    cache_data["used_sections"].append(ref)
    
    # 合并进度
    if progress_update:
        cache_data["task_progress"].update(progress_update)
    
    # 更新时间戳
    cache_data["last_update"] = datetime.now().isoformat()
    
    # 写入缓存
    cache_path = HERMES / "reports" / "cross_session_cache.json"
    cache_path.write_text(json.dumps(cache_data, ensure_ascii=False, indent=2), encoding="utf-8")
    
    return cache_data

def update_task_progress(ai_response: str = "") -> dict:
    """基于AI回复自动更新任务进度"""
    result = {"updated": False, "changes": []}
    
    # 读取当前task_current
    tc_path = HERMES / "task_current.json"
    if not tc_path.exists():
        return result
    
    try:
        tc = json.loads(tc_path.read_text())
    except Exception:
        return result
    
    if not ai_response:
        return result
    
    # 检查是否包含"完成"标记
    if re.search(r'任务(已)?完成|全部(完成|通过)|✅.*全部|所有测试通过', ai_response):
        tc["status"] = "completed"
        tc["completed_at"] = datetime.now().isoformat()
        result["changes"].append("status→completed")
        result["updated"] = True
    
    # 检查是否包含失败
    if re.search(r'❌|失败|错误|error', ai_response):
        # 添加error标记但不停止任务
        tc["last_error"] = ai_response[:200]
        result["changes"].append("记录错误信息")
        result["updated"] = True
    
    if result["updated"]:
        tc_path.write_text(json.dumps(tc, ensure_ascii=False, indent=2), encoding="utf-8")
    
    return result

def update_wake_guide(ai_response: str = "") -> dict:
    """更新wake_guide中的待办状态"""
    wg_path = HERMES / "reports" / "wake_guide.json"
    if not wg_path.exists():
        return {"updated": False}
    
    try:
        wg = json.loads(wg_path.read_text())
    except Exception:
        return {"updated": False}
    
    changes = []
    
    # 如果AI表示任务完成，清除中断任务标记
    if ai_response and re.search(r'任务(已)?完成|全部(完成|通过)|推送成功', ai_response):
        if wg.get("interrupted_task"):
            wg["interrupted_task"] = None
            changes.append("清除中断任务")
    
    # 更新ai_scoring状态（如果提到评分完成）
    if ai_response and re.search(r'评分.*完成|已评分.*全部|0条待评分', ai_response):
        wg["ai_scoring_pending"] = 0
        changes.append("AI评分待处理→0")
    
    # 更新gear_health
    if ai_response and re.search(r'所有测试通过|全部正常|无影响', ai_response):
        wg["gear_health"] = "healthy"
        changes.append("gear_health→healthy")
    
    if changes:
        wg_path.write_text(json.dumps(wg, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"updated": True, "changes": changes}
    
    return {"updated": False}

def generate_continuity_prompt() -> str:
    """生成下一轮的延续提示（给AI读的）"""
    cache = read_context_cache()
    
    lines = [
        "# 跨轮次延续信息",
        f"对话轮次: #{cache.get('session_count', 0)}",
    ]
    
    if cache.get("last_task_type"):
        lines.append(f"上一轮任务类型: {cache['last_task_type']}")
    
    if cache.get("used_sections"):
        lines.append(f"已使用章节: {', '.join(cache['used_sections'][:5])}")
    
    if cache.get("used_tools"):
        lines.append(f"已使用工具: {', '.join(cache['used_tools'][:5])}")
    
    if cache.get("task_progress"):
        tp = cache["task_progress"]
        if tp.get("completed"):
            lines.append(f"已完成: {', '.join(tp['completed'][-3:])}")
        if tp.get("next_steps"):
            lines.append(f"待办: {', '.join(tp['next_steps'][-3:])}")
    
    return '\n'.join(lines)

def main():
    # 从stdin或参数读取AI回复
    if len(sys.argv) > 1:
        # 从参数读取
        ai_response = sys.argv[1]
    else:
        # 从stdin读取
        ai_response = sys.stdin.read() if not sys.stdin.isatty() else ""
    
    # 更新所有缓存
    cache = update_cache(ai_response)
    progress = update_task_progress(ai_response)
    wake = update_wake_guide(ai_response)
    
    # 生成延续提示
    continuity = generate_continuity_prompt()
    
    print(f"cache_updated=True")
    print(f"progress_updated={progress['updated']}")
    print(f"wake_updated={wake['updated']}")
    print(f"session_count={cache.get('session_count', 0)}")
    print("---")
    print(continuity)

if __name__ == "__main__":
    main()

