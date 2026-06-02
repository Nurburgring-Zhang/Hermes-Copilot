#!/usr/bin/env python3
"""
Hermes 对话初始化压缩加载器 v1.0
=================================
Hermes每次醒来/每次对话开始时调用此脚本。
它会：
1. 检查token水位
2. 如果压缩上下文存在且足够新鲜，加载压缩版
3. 写出当前对话应加载的精简上下文

用法：对话开始时
  python3 ~/.hermes/scripts/init_context_loader.py
输出：应该加载的上下文路径
"""

import json, sys, os, time
from pathlib import Path
from datetime import datetime, timedelta

HERMES = Path("/home/administrator/.hermes")

def get_optimal_context() -> dict:
    """
    返回最优上下文加载方案
    """
    result = {
        "ts": datetime.now().isoformat(),
        "mode": "full",  # full | compressed | minimal
        "load_paths": [],
        "suggested_prompt": "",
        "token_saved": 0
    }
    
    # 1. 检查是否有压缩上下文
    compressed = HERMES / "reports" / "compressed_context.md"
    full_soul = HERMES / "SOUL.md"
    
    if compressed.exists():
        compressed_age = time.time() - compressed.stat().st_mtime
        compressed_text = compressed.read_text(encoding='utf-8', errors='ignore')
        compressed_tokens = len(compressed_text)  # approx
        
        if full_soul.exists():
            full_text = full_soul.read_text(encoding='utf-8', errors='ignore')
            full_tokens = len(full_text)
            
            # 如果压缩版在1小时以内，用压缩版
            if compressed_age < 3600:
                result["mode"] = "compressed"
                result["load_paths"] = [str(compressed)]
                result["token_saved"] = full_tokens - compressed_tokens
                result["suggested_prompt"] = f"⚡ 压缩模式: 加载压缩上下文({compressed_tokens}字 vs {full_tokens}字原始)"
            else:
                # 超时了，但先用老的，同时刷新
                result["mode"] = "compressed_stale"
                result["load_paths"] = [str(compressed)]
                result["suggested_prompt"] = "⚠️ 压缩上下文超过1小时，刷新中..."
    
    # 2. 检查token水位告警
    watermark = HERMES / "reports" / "token_watermark.json"
    if watermark.exists():
        try:
            wm = json.loads(watermark.read_text())
            if wm.get("alert"):
                result["alert"] = wm["alert"]
        except:
            pass
    
    # 3. 检查是否有中断任务
    wake = HERMES / "reports" / "wake_guide.json"
    if wake.exists():
        try:
            wg = json.loads(wake.read_text())
            if wg.get("interrupted_task"):
                result["interrupted_task"] = wg["interrupted_task"]
        except:
            pass
    
    return result

def main():
    result = get_optimal_context()
    
    # 写入加载计划
    plan_path = HERMES / "reports" / "context_load_plan.json"
    plan_path.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    
    # 输出关键信息
    if result["mode"] == "compressed":
        print(f"MODE=compressed")
        print(f"LOAD={result['load_paths'][0]}")
        print(f"SAVED_TOKENS={result['token_saved']}")
    else:
        print(f"MODE=full")
        print(f"LOAD=SOUL.md")
    
    if result.get("interrupted_task"):
        print(f"INTERRUPTED={result['interrupted_task']['task_id']}")
    
    if result.get("alert"):
        print(f"ALERT={result['alert']}")

if __name__ == "__main__":
    main()
