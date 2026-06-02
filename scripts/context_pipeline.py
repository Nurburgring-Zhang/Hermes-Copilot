#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Hermes 上下文切割管道 v1.0（整合版）
=====================================
合并 surgical_context_slicer.py + context_auto_assoc.py 的整合版本。

模式：
  --mode=surgical   手术刀式切分（最小上下文 ~539tokens）
  --mode=auto       自动关联+预加载章节摘要（稍大 ~3195tokens）

统一数据源：reports/task_type_config.json（由 context_packer.py 和本脚本共用）

由对话开始时调用，也由 cron 每1分钟刷新。
"""

import json, sys, re
from pathlib import Path
from datetime import datetime

HERMES = Path("/home/administrator/.hermes")
SECTIONS_DIR = HERMES / "reports" / "context_sections"
CONFIG_FILE = HERMES / "reports" / "task_type_config.json"

def estimate_tokens(text: str) -> int:
    cn = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    en = len(text) - cn
    return int(cn * 1.5 + en * 1.3)

def load_task_config() -> dict:
    """加载统一的 task_type 配置"""
    if CONFIG_FILE.exists():
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8")).get("task_types", {})
    return {}

def get_active_task() -> dict:
    """读取当前活跃任务信息（三源冗余）"""
    result = {"task_id": None, "status": None, "next_action": None, "detail": None}
    sources = [
        ("wake_guide", HERMES / "reports" / "wake_guide.json", lambda d: d.get("interrupted_task", {})),
        ("task_current", HERMES / "task_current.json", lambda d: d if d.get("status") in ("running", "active", "pending") else {}),
        ("recovery_pack", HERMES / "reports" / "recovery_pack.json", lambda d: d.get("gear_checkpoint", {}) or d.get("task_current", {})),
    ]
    for src_name, src_path, extractor in sources:
        if src_path.exists():
            try:
                d = json.loads(src_path.read_text())
                task_data = extractor(d)
                if task_data and task_data.get("task_id"):
                    result["task_id"] = task_data.get("task_id")
                    result["next_action"] = task_data.get("next_action", "")
                    result["detail"] = task_data.get("detail", "")
                    result["status"] = task_data.get("status", "running")
                    result["source"] = src_name
                    break  # 第一个找到的优先
            except Exception:
                pass
    return result

def classify_task(task_id, detail, next_action) -> str:
    """根据任务信息判断类型"""
    if not task_id and not detail:
        return "general"
    text = f"{task_id or ''} {detail or ''} {next_action or ''}".lower()
    if any(kw in text for kw in ['push', '推送', 'send']): return "push"
    if any(kw in text for kw in ['fix', 'repair', '修复', '故障', 'bug', 'error']): return "fix"
    if any(kw in text for kw in ['develop', '开发', 'feature', 'implement', '新增']): return "develop"
    if any(kw in text for kw in ['review', 'audit', '审核', '审查', 'code review']): return "review"
    if any(kw in text for kw in ['research', '研究', '调研', 'investigate']): return "research"
    if any(kw in text for kw in ['memory', '记忆', 'compress', '压缩']): return "memory"
    if any(kw in text for kw in ['security', '安全']): return "security"
    if any(kw in text for kw in ['collect', '采集', 'crawl']): return "collect"
    if any(kw in text for kw in ['clean', '清洗', 'cleaning']): return "clean"
    if any(kw in text for kw in ['score', '评分', 'grade']): return "score"
    if any(kw in text for kw in ['schedule', 'cron', '定时', '计划']): return "schedule"
    return "general"

def get_session_continuity() -> dict:
    """读取会话连续性信息"""
    result = {"last_task_type": None, "last_task_id": None}
    # 从齿轮检查点获取上一轮任务类型
    gp = HERMES / "reports" / "gear_checkpoint.json"
    if gp.exists():
        try:
            d = json.loads(gp.read_text())
            if d.get("task_id"):
                result["last_task_id"] = d["task_id"]
                result["last_status"] = d.get("status")
        except Exception:
            pass
    # 从先前输出获取上一轮类型
    for path, key in [
        (HERMES / "reports" / "surgical_context.json", "task_type"),
        (HERMES / "reports" / "context_auto_assoc.json", "task_type"),
    ]:
        if path.exists():
            try:
                d = json.loads(path.read_text())
                if d.get(key):
                    result["last_task_type"] = d[key]
                    break
            except Exception:
                pass
    return result

def find_section_file(chapter_id: str) -> Path:
    """用三重回退找章节文件"""
    # 方式1: glob模糊匹配
    found = list(SECTIONS_DIR.glob(f"*{chapter_id}*.md"))
    if found:
        return found[0]
    # 方式2: 遍历做stem包含检查
    for f in SECTIONS_DIR.glob("*.md"):
        clean_id = chapter_id.replace("_", "").replace("-", "")
        clean_stem = f.stem.replace("_", "").replace("-", "")
        if clean_id in clean_stem:
            return f
    # 方式3: 直接文件名匹配
    p = SECTIONS_DIR / f"{chapter_id}.md"
    if p.exists():
        return p
    return None

# ============================================================
# 模式1: 手术刀式切分（最小上下文）
# ============================================================
def build_surgical(task_type: str, task_info: dict) -> dict:
    """手术刀式精准切分"""
    config = load_task_config()
    task_cfg = config.get(task_type, config.get("general", {}))
    
    # 构建切分后的上下文
    parts = []
    parts.append(f"# 上下文切片 - {task_cfg.get('label', '通用')}")
    parts.append(f"任务类型: {task_type}")
    if task_info.get("task_id"):
        parts.append(f"任务ID: {task_info['task_id']}")
        parts.append(f"下一步: {task_info.get('next_action', '')}")
    
    # 规则列表
    rules = task_cfg.get("rules", [])
    if rules:
        parts.append(f"关联规则: {', '.join(rules)}")
    
    # 上下文提示
    hint = task_cfg.get("context_hint", "")
    if hint:
        parts.append(f"\n{task_cfg.get('label', '任务')}: {hint}")
    
    # 需要的工具
    tools = task_cfg.get("tools", [])
    if tools:
        parts.append(f"推荐工具: {', '.join(tools)}")
    
    # 参考章节
    sections = task_cfg.get("sections", [])
    if sections:
        parts.append("\n关联章节（按需读取完整内容）:")
        for ch in sections:
            sf = find_section_file(ch)
            if sf:
                rel_path = str(sf.relative_to(HERMES))
                parts.append(f"  {ch} → {rel_path}")
            else:
                parts.append(f"  {ch} → reports/context_sections/（未找到精确文件）")
    
    text = "\n".join(parts)
    
    result = {
        "ts": datetime.now().isoformat(),
        "task_type": task_type,
        "mode": "surgical",
        "tokens": estimate_tokens(text),
        "content": text,
        "task_info": task_info,
    }
    
    out_path = HERMES / "reports" / "surgical_context.json"
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result

# ============================================================
# 模式2: 自动关联（预加载章节摘要）
# ============================================================
def build_auto_assoc(task_type: str, task_info: dict, history: dict) -> dict:
    """自动关联+预加载相关章节"""
    config = load_task_config()
    task_cfg = config.get(task_type, config.get("general", {}))
    
    continuity = (history.get("last_task_type") == task_type)
    
    # 构建章节列表（含连续性扩充）
    chapter_list = list(task_cfg.get("sections", []))
    if continuity and history.get("last_task_type"):
        prev_cfg = config.get(history["last_task_type"], {})
        for ch in prev_cfg.get("sections", []):
            if ch not in chapter_list:
                chapter_list.append(ch)
    
    # 预加载章节摘要
    preloaded = {}
    total_tokens = 0
    for ch_id in chapter_list:
        sf = find_section_file(ch_id)
        if not sf:
            continue
        content = sf.read_text(encoding="utf-8")
        lines = content.split("\n")
        summary_lines = []
        for line in lines:
            s = line.strip()
            if not s:
                continue
            if s.startswith("#"):
                summary_lines.append(s[:100])
                continue
            if any(kw in s for kw in ['✅','❌','⚠️','🔴','必须','禁止','规则','齿轮','G0','G1','G2','G3','G4','G5','G6','G7','G8','cron','每','分钟','小时','保留','移除','任务','技能','并行','链式','激活']):
                summary_lines.append(s[:120])
            if len(summary_lines) >= 12:
                break
        summary = "\n".join(summary_lines)
        tokens = estimate_tokens(summary)
        preloaded[sf.stem] = {
            "tokens": tokens, "summary": summary, "title": ch_id,
            "file": str(sf.relative_to(HERMES)),
            "full_tokens": estimate_tokens(content)
        }
        total_tokens += tokens
    
    # 构建索引
    idx = []
    idx.append(f"# 上下文索引（自动关联版）")
    idx.append(f"任务类型: {task_type} | 延续上一轮: {'是' if continuity else '否'}")
    if task_info.get("task_id"):
        idx.append(f"任务: {task_info['task_id']} | 下一步: {task_info.get('next_action', '')}")
    
    # 工具描述（精简版）
    tool_list = task_cfg.get("tools", [])
    if tool_list:
        idx.append(f"\n推荐工具: {', '.join(tool_list)}")
    
    # 规则列表
    rules = task_cfg.get("rules", [])
    if rules:
        idx.append(f"关联规则: {', '.join(rules)}")
    
    # 章节摘要
    if preloaded:
        idx.append(f"\n预加载章节摘要 ({total_tokens}tokens):")
        for stem, info in preloaded.items():
            idx.append(f"\n[{info['title']}] ({info['tokens']}t)")
            idx.append(info["summary"][:500])
    
    text = "\n".join(idx)
    
    result = {
        "ts": datetime.now().isoformat(),
        "task_type": task_type,
        "mode": "auto",
        "tokens": estimate_tokens(text),
        "content": text,
        "preloaded_sections": len(preloaded),
        "preloaded_tokens": total_tokens,
        "continuity": continuity,
        "task_info": task_info,
    }
    
    out_path = HERMES / "reports" / "context_auto_assoc.json"
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result

def main():
    mode = "auto"  # 默认
    for arg in sys.argv[1:]:
        if arg.startswith("--mode="):
            mode = arg.split("=", 1)[1]
    
    task_info = get_active_task()
    task_type = classify_task(
        task_info.get("task_id", ""),
        task_info.get("detail", ""),
        task_info.get("next_action", "")
    )
    
    if mode == "surgical":
        result = build_surgical(task_type, task_info)
    else:
        history = get_session_continuity()
        result = build_auto_assoc(task_type, task_info, history)
    
    print(f"📋 context_pipeline [{mode}]")
    print(f"  任务: {task_type}")
    print(f"  tokens: {result['tokens']}")
    print(f"  输出: reports/context_{mode}_assoc.json")
    print("---")
    print(result["content"][:600])
    print("...")

if __name__ == "__main__":
    main()
