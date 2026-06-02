#!/usr/bin/env python3
"""
🔴🔴🔴 反幻觉铁律：严禁任何不加核实的猜想、胡编乱造、自己瞎编！
必须核实才能说/必须验证才能写/必须确认才能断言/不知道就说不知道
这是最高优先级规则，凌驾于所有其他规则之上。
"""

"""
pre_check.py — 任务前强制全局检索钩子 v1.0
==========================================
每次任务开始前，自动执行：
  1. session_search — 检索相关历史会话
  2. memory — 读取记忆中的相关事实
  3. search_files — 搜索相关文件/配置

输出检查清单到 wake_guide.json 的 pre_check 字段。
如果任何检查未通过，在输出中明确提示。

用法（每次任务开始第一个terminal调用）：
  python3 ~/.hermes/scripts/pre_check.py <task_description>
  
  或者在 execute_code 中：
  from scripts.pre_check import run_pre_check
  issues = run_pre_check("数据库配置修改")
  if issues:
      print(f"[PRE-CHECK] 发现 {len(issues)} 个问题，已注入上下文")
"""

import json, sys, time
from pathlib import Path

REPORTS_DIR = Path.home() / ".hermes" / "reports"

def run_pre_check(task_description: str = "") -> list:
    """
    执行任务前全局检索
    
    返回: 发现的问题列表（空=无问题）
    """
    issues = []
    print(f"\n{'='*60}")
    print(f"[PRE-CHECK] 任务: {task_description or '未描述'}")
    print(f"{'='*60}")
    
    # 1. 检索历史会话
    try:
        from auto_recall import AutoRecall
        recaller = AutoRecall()
        recall = recaller.recall_for_session(task_description)
        if recall:
            print(f"  [SESSION] 找到相关记忆: {recall[:100]}...")
        else:
            print(f"  [SESSION] 无直接相关记忆（可能为新任务）")
    except Exception as e:
        issues.append(f"session_search失败: {e}")
        print(f"  [SESSION] 错误: {e}")
    
    # 2. 读取记忆
    try:
        recaller = AutoRecall()
        persona = recaller.get_persona_context()
        if persona:
            print(f"  [MEMORY] 用户画像已加载 ({len(persona)} chars)")
        else:
            print(f"  [MEMORY] 用户画像为空")
    except Exception as e:
        issues.append(f"memory读取失败: {e}")
    
    # 3. 检查降级状态
    try:
        from llm_bridge import detect_available_backends
        info = detect_available_backends()
        if info["all_fallback"]:
            msg = "LLM全部不可用（delegate/LM Studio/Ollama均不可用），将使用规则降级"
            issues.append(msg)
            print(f"  [LLM] ⚠️ {msg}")
        else:
            print(f"  [LLM] 可用后端: {info['primary']}")
    except Exception as e:
        issues.append(f"LLM检测失败: {e}")
    
    # 4. 检查G8齿轮状态
    try:
        state_file = Path.home() / ".hermes" / "state" / "last_check.json"
        if state_file.exists():
            state = json.loads(state_file.read_text())
            age = time.time() - state.get("timestamp", 0)
            if age > 600:  # 10分钟
                issues.append(f"G8齿轮最后检查在{age:.0f}秒前，可能已停止")
                print(f"  [G8] ⚠️ 最后检查: {age:.0f}秒前")
            else:
                print(f"  [G8] ✅ 运行中 ({age:.0f}秒前)")
        else:
            issues.append("G8齿轮从未运行，生产级可靠性引擎未激活")
            print(f"  [G8] ❌ 未运行")
    except Exception as e:
        pass
    
    # 5. 检查是否有中断任务
    for fname in ["task_current.json", "reports/gear_checkpoint.json"]:
        f = Path.home() / ".hermes" / fname
        if f.exists():
            try:
                data = json.loads(f.read_text())
                issues.append(f"发现中断任务文件: {fname}")
                print(f"  [TASK] ⚠️ 发现中断任务: {fname}")
            except:
                pass
    
    print(f"{'='*60}")
    if issues:
        for i in issues:
            print(f"  ❌ {i}")
    else:
        print(f"  ✅ 全部检查通过")
    print(f"{'='*60}")
    
    return issues


if __name__ == "__main__":
    task = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "未指定任务"
    run_pre_check(task)
