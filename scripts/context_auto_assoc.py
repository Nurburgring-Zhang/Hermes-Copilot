#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Hermes 上下文自动关联预加载器 v2.0
======================================
分析当前任务，自动预加载3个最相关的章节。

输出:
  - reports/context_auto_assoc.json (结构化数据)
  - reports/context_auto_assoc.md (可读摘要)

核心逻辑:
1. 从wake_guide.json获取task_id和detail
2. 从context_sections/读取所有章节文件名
3. 根据task_type匹配对应的3个章节
4. 从这些章节中提取摘要(前200字)
5. 输出 JSON 和 MD
"""

import json, sys, re
from pathlib import Path
from datetime import datetime

HERMES = Path("/home/administrator/.hermes")
SECTIONS_DIR = HERMES / "reports" / "context_sections"
WAKE_PATH = HERMES / "reports" / "wake_guide.json"
OUTPUT_JSON = HERMES / "reports" / "context_auto_assoc.json"
OUTPUT_MD = HERMES / "reports" / "context_auto_assoc.md"


def estimate_tokens(text: str) -> int:
    cn = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    en = len(text) - cn
    return int(cn * 1.5 + en * 1.3)


def read_wake_guide() -> dict:
    """从wake_guide.json获取任务信息"""
    result = {
        "task_type": "general",
        "task_id": "unknown",
        "detail": "",
        "next_action": ""
    }
    if WAKE_PATH.exists():
        try:
            wg = json.loads(WAKE_PATH.read_text(encoding="utf-8"))
            it = wg.get("interrupted_task", {})
            if it:
                result["task_id"] = it.get("task_id", "unknown")
                result["next_action"] = it.get("next_action", "")
                result["detail"] = it.get("detail", "")
            # 从task_id推断task_type
            tid = result["task_id"]
            if tid.startswith("fix_"):
                result["task_type"] = "fix"
            elif tid.startswith("push_"):
                result["task_type"] = "push"
            elif tid.startswith("develop_") or tid.startswith("dev_"):
                result["task_type"] = "develop"
            elif tid.startswith("research_") or tid.startswith("rs_"):
                result["task_type"] = "research"
            elif tid.startswith("review_"):
                result["task_type"] = "review"
            elif tid.startswith("memory_") or tid.startswith("mem_"):
                result["task_type"] = "memory"
            elif tid.startswith("security_") or tid.startswith("sec_"):
                result["task_type"] = "security"
            elif tid.startswith("collect_") or tid.startswith("col_"):
                result["task_type"] = "collect"
            elif tid.startswith("score_") or tid.startswith("sc_"):
                result["task_type"] = "score"
            elif tid.startswith("clean_"):
                result["task_type"] = "clean"
            if "task_type" in wg:
                result["task_type"] = wg["task_type"]
        except Exception:
            pass
    return result


def find_matching_sections(task_type: str) -> list:
    """根据task_type匹配对应的3个章节关键词"""
    mapping = {
        "fix":        ["八_七条永久执行规则", "规则5_", "规则7_", "规则2_"],
        "push":       ["推送系统优化规则", "_采集质量预筛规则", "_低分数据自动清理规则"],
        "develop":    ["八_七条永久执行规则", "规则7_", "规则6_"],
        "dev":        ["八_七条永久执行规则", "规则7_", "规则6_"],
        "research":   ["规则0_自主基线", "规则5_", "九_oi项目全量优化增强方案"],
        "review":     ["八_七条永久执行规则", "规则7_", "规则5_"],
        "memory":     ["长链任务上下文管理", "零_齿轮强制恢复协议", "八_七条永久执行规则"],
        "security":   ["camel安全护栏规则", "八_七条永久执行规则", "二永久禁令"],
        "general":    ["八_七条永久执行规则", "一核心身份", "二永久禁令"],
        "collect":    ["_采集质量预筛规则", "_skills组合并行链式调用", "八_七条永久执行规则"],
        "score":      ["八_七条永久执行规则", "规则5_", "_低分数据自动清理规则"],
        "clean":      ["_低分数据自动清理规则", "八_七条永久执行规则", "_采集质量预筛规则"],
    }
    
    keywords = mapping.get(task_type, mapping["general"])
    
    if not SECTIONS_DIR.exists():
        return []
    
    all_files = sorted(SECTIONS_DIR.glob("*.md"))
    matched = []
    
    for kw in keywords:
        for f in all_files:
            if kw in f.stem:
                # 避免重复
                if f not in [m["file"] for m in matched]:
                    content = f.read_text(encoding="utf-8")[:500]  # 前500字取摘要
                    # 摘取前200字有效内容（去掉markdown头部标记）
                    summary = re.sub(r"^#+\s*.*\n", "", content[:500]).strip()
                    if len(summary) > 200:
                        summary = summary[:200] + "..."
                    matched.append({
                        "section_id": f.stem,
                        "file": str(f.relative_to(HERMES)),
                        "summary": summary,
                        "tokens": estimate_tokens(content[:500]),
                    })
                    break
    
    return matched[:5]  # 最多5个


def extract_summary_from_section(file_path: Path, max_chars: int = 200) -> str:
    """从章节文件中提取摘要"""
    try:
        content = file_path.read_text(encoding="utf-8")
    except Exception:
        return ""
    
    # 跳过title行
    lines = content.split("\n")
    body_start = 0
    for i, line in enumerate(lines):
        if line.startswith("#") or line.strip() == "" or line.startswith("---"):
            continue
        body_start = i
        break
    
    body = "\n".join(lines[body_start:]).strip()
    if len(body) > max_chars:
        # 在完整词语处截断
        body = body[:max_chars]
        # 找一个合适的截断点
        last_period = max(body.rfind("。"), body.rfind("."), body.rfind("、"))
        if last_period > max_chars // 2:
            body = body[:last_period + 1]
        else:
            body = body[:max_chars]
    
    return body.strip()


def build_auto_assoc() -> dict:
    """构建上下文自动关联"""
    wake_info = read_wake_guide()
    task_type = wake_info.get("task_type", "general")
    
    # 找到匹配的章节
    matched_sections = find_matching_sections(task_type)
    
    # 提取每个章节的摘要
    sections_data = []
    for ms in matched_sections:
        fpath = HERMES / ms["file"]
        summary = extract_summary_from_section(fpath)
        sections_data.append({
            "section_id": ms["section_id"],
            "file": ms["file"],
            "summary": summary or ms["summary"],
            "tokens": estimate_tokens(summary or ms["summary"]),
        })
    
    # 构建推荐工具
    tool_map = {
        "fix": ["terminal", "read_file", "patch", "search_files"],
        "push": ["terminal", "read_file", "cronjob"],
        "develop": ["terminal", "read_file", "write_file", "patch", "delegate_task"],
        "dev": ["terminal", "read_file", "write_file", "patch", "delegate_task"],
        "research": ["web_search", "terminal", "read_file", "write_file"],
        "review": ["read_file", "search_files", "patch"],
        "memory": ["memory", "session_search", "read_file"],
        "security": ["read_file", "search_files", "patch"],
        "general": ["terminal", "read_file", "patch", "search_files", "web_search"],
        "collect": ["terminal", "cronjob", "read_file"],
        "score": ["terminal", "read_file"],
        "clean": ["terminal", "read_file"],
    }
    recommended_tools = tool_map.get(task_type, tool_map["general"])
    
    # 构建MD内容
    md_lines = [
        f"# 上下文自动关联预加载",
        f"**任务类型**: {task_type} | **任务ID**: {wake_info['task_id']}",
        f"**详情**: {wake_info['detail'][:150]}",
        f"",
        f"## 推荐工具",
    ]
    for t in recommended_tools:
        md_lines.append(f"- `{t}`")
    
    md_lines.extend(["", f"## 预加载章节（{len(sections_data)}个）", ""])
    for sd in sections_data:
        md_lines.append(f"### 📄 {sd['section_id']}")
        md_lines.append(f"**路径**: `{sd['file']}`")
        md_lines.append(f"**摘要**:")
        md_lines.append(f"```")
        md_lines.append(sd['summary'][:300])
        md_lines.append(f"```")
        md_lines.append("")
    
    md_content = "\n".join(md_lines)
    total_tokens = estimate_tokens(md_content)
    
    result = {
        "ts": datetime.now().isoformat(),
        "task_type": task_type,
        "task_id": wake_info.get("task_id", "unknown"),
        "detail": wake_info.get("detail", ""),
        "total_tokens": total_tokens,
        "recommended_tools": recommended_tools,
        "preloaded_sections": len(sections_data),
        "sections": sections_data,
        "md_content": md_content,
        "task_info": wake_info,
    }
    
    # 输出JSON
    OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    
    # 输出MD
    OUTPUT_MD.write_text(md_content, encoding="utf-8")
    
    return result


def main():
    result = build_auto_assoc()
    
    print(f"🔗 context_auto_assoc v2.0")
    print(f"  task_type={result.get('task_type', '?')}")
    print(f"  task_id={result.get('task_id', '?')}")
    print(f"  预加载章节: {result.get('preloaded_sections', 0)}个")
    print(f"  tokens: {result.get('total_tokens', 0)}")
    print(f"  输出: {OUTPUT_JSON}")
    print(f"  输出: {OUTPUT_MD}")
    print("---")
    for s in result.get("sections", []):
        print(f"  📄 {s['section_id'][:40]:40s} {s['tokens']:>4}tokens")
    print()
    # 预览MD
    print(result.get("md_content", "")[:400])
    print("...")


if __name__ == "__main__":
    main()
