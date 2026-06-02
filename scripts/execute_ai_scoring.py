#!/usr/bin/env python3
"""
Hermes AI 评分执行引擎 v2
==========================
由 ai_scorer.py 生成的评分请求由本脚本实际执行。
通过 delegate_task 对每条内容做真正的AI内容理解评分。

使用方式(由Hermes调用):
  python3 execute_ai_scoring.py --batch /path/to/batch.json
  
输出:
  评分结果JSON,由Hermes工具写入数据库
"""

import json, sys, os, time
from pathlib import Path
from datetime import datetime

HERMES = Path("/home/administrator/.hermes")


def generate_scoring_prompts(items: list) -> list:
    """为每条生成独立的评分prompt"""
    prompts = []
    for item in items:
        item_id = item.get("item_id", item.get("id", "?"))
        title = item.get("title", "")[:150]
        content = item.get("content", "")[:800]
        platform = item.get("platform", "")
        source = item.get("source", "")
        author = item.get("author", "")
        tags = item.get("tags", "")
        category = item.get("category", "")
        
        prompt = f"""
你是一位情报价值评估专家。请对以下情报进行**真正的AI内容理解评分**,不是关键词匹配,而是理解内容后判断。

## 格林主人偏好(供参考)
- 核心关注:AI/LLM/大模型,IT/开发/开源(Rust/TS/Python),消费电子/芯片,新能源汽车,军事/国际,开发者生态
- 次关注:格斗/UFC,美女写真摄影,电影娱乐,科技数码
- 讨厌:低俗社会新闻,震惊体标题党,泛娱乐/生活内容

## 格式要求
输出严格JSON格式(不要用markdown代码块包裹,纯JSON对象):

{{"item_id": {item_id}, "scarcity": 0-30, "impact": 0-30, "tech_depth": 0-20, "timeliness": 0-10, "preference": 0-10, "credibility": 0-10, "scarcity_reason": "原因", "impact_reason": "原因", "tech_depth_reason": "原因", "timeliness_reason": "原因", "preference_reason": "原因", "credibility_reason": "原因", "summary": "一句话价值总结"}}

## 待评分内容
- **标题**: {title}
- **内容**: {content[:500]}
- **平台**: {platform} | **来源**: {source}
- **作者**: {author} | **分类**: {category} | **标签**: {tags}

评分时请注意:
1. **稀缺性**:这是独家报道?还是转载/聚合?是否有独到视角?
2. **影响力**:影响的是一个行业,一家公司,还是一个产品?有多重大?
3. **技术深度**:内容有技术细节吗?有数据支撑吗?是深度分析还是标题党?
4. **时效性**:根据发布时间和内容主题判断新旧
5. **偏好匹配**:内容主题是否匹配格林主人的兴趣?
6. **可信度**:平台/来源的可信度如何?

## 输出
"""
        prompts.append({
            "item_id": item_id,
            "prompt": prompt,
        })
    
    return prompts


def main():
    # Fix: manual arg parsing
    args = sys.argv[1:]
    if len(args) >= 2 and args[0] == "--batch":
        batch_path = args[1]
    elif "--direct" in args:
        # Try default locations
        for p in [
            HERMES / "cron/output/ai_scoring_batch.json",
            HERMES / "scripts/ai_scoring_batch.json",
            HERMES / "scripts/ai_batch_to_score.json",
        ]:
            if p.exists():
                batch_path = str(p)
                break
        else:
            batch_path = None
    else:
        batch_path = None
    
    if batch_path:
        # 从文件读取评分请求
        with open(batch_path, "r", encoding="utf-8") as f:
            items = json.load(f)
        
        prompts = generate_scoring_prompts(items)
        
        # 输出评分prompt — 这些会被送到delegate_task
        output = {
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "total_items": len(prompts),
            "scoring_tasks": prompts,
            "note": "每条请单独用delegate_task评分,然后汇总结果"
        }
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        print("Usage: python3 execute_ai_scoring.py --batch <batch_file.json>")
        print("       python3 execute_ai_scoring.py --direct    # 从默认位置读取")


if __name__ == "__main__":
    main()
