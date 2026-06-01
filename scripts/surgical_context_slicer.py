#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Hermes 外科式上下文切分器 v2.0
=================================
按任务类型(fix/push/develop/research/review/memory/security/general/collect/score)
从SOUL.md中精准切分只与该任务相关的规则、工具、上下文。

输出: reports/surgical_context.json

核心逻辑:
1. 从wake_guide.json读取当前任务类型
2. 根据task_type选择对应的规则子集、工具列表、工作上下文
3. 所有任务必须保留: 核心身份+永久禁令+8条规则标题
4. 额外保留: 该任务类型需要的规则完整内容
5. 输出 JSON 到 reports/surgical_context.json
6. 任务类型映射参考已有的分层策略
"""

import json, sys, re
from pathlib import Path
from datetime import datetime

HERMES = Path("/home/administrator/.hermes")
SOUL_PATH = HERMES / "SOUL.md"
WAKE_PATH = HERMES / "reports" / "wake_guide.json"
TASK_TYPE_CONFIG = HERMES / "reports" / "task_type_config.json"
OUTPUT_PATH = HERMES / "reports" / "surgical_context.json"

# 所有任务必须保留的核心内容ID
CORE_SECTIONS = {
    "一核心身份",
    "二永久禁令",
    "永久禁令",
}

def estimate_tokens(text: str) -> int:
    cn = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    en = len(text) - cn
    return int(cn * 1.5 + en * 1.3)


def load_config() -> dict:
    """加载任务类型配置"""
    if TASK_TYPE_CONFIG.exists():
        try:
            cfg = json.loads(TASK_TYPE_CONFIG.read_text(encoding="utf-8"))
            return cfg.get("task_types", {})
        except Exception:
            pass
    # 硬编码默认配置（如果配置文件丢失）
    return {
        "general": {"label":"通用任务","rules":["规则1","规则2","规则3","规则4","规则5","规则6","规则7"],"tools":["terminal","read_file","write_file","patch","search_files","session_search","delegate_task","cronjob","web_search"],"context_hint":"执行前回顾历史+全局预判。中断自动拆解恢复。每阶段复盘+最终全局复盘。真实实现+3轮完善审核测试循环。"},
        "fix": {"label":"修复任务","rules":["规则1","规则2","规则3","规则4","规则5","规则6","规则7"],"tools":["terminal","read_file","write_file","patch","search_files","session_search","delegate_task"],"context_hint":"先排查根因（查日志/数据库/cron状态/齿轮系统）。修复前备份原始文件。修复完必须跑一次真实测试。测试后审核+完善+再测试（至少3轮）。AI评分中断：检查DeepSeek model名(deepseek-chat)。推送失败：检查PushPlus字数限制+URL转义。"},
        "push": {"label":"推送任务","rules":["规则1","规则5","规则7"],"tools":["terminal","read_file","write_file","patch","cronjob"],"context_hint":"推送管道正常，候选池有数据。PushPlus 2万字限制，TARGET_COUNT=25。URL中的&必须转义为&amp;。推送失败自动重试2次。记录24h去重，等级分5级。"},
        "develop": {"label":"开发任务","rules":["规则1","规则2","规则5","规则6","规则7"],"tools":["terminal","read_file","write_file","patch","search_files","delegate_task"],"context_hint":"分阶段执行，每阶段写checkpoint。完整3轮循环：完善→审核→测试。严禁降级实现，端到端完整实现。修改后测试所有边界条件。"},
        "research": {"label":"研究任务","rules":["规则1","规则5","规则8"],"tools":["terminal","web_search","read_file","write_file"],"context_hint":"搜索时多源交叉验证。优先官方文档+社区公认方案。下载方案核验HTTPS+校验和(SHA256)。汇总后输出结构化报告。"},
        "review": {"label":"审核任务","rules":["规则1","规则3","规则4","规则5","规则7"],"tools":["terminal","read_file","search_files","patch"],"context_hint":"逐行检查代码逻辑，是否存在降级/模拟/占位符。测试所有边界条件，输出完整审核报告。至少3轮：完善→审核→测试循环。"},
        "memory": {"label":"记忆任务","rules":["规则1","规则5"],"tools":["terminal","read_file","write_file","session_search","memory"],"context_hint":"记忆压缩归档。StructMem+Claw+RAG协同。"},
        "security": {"label":"安全任务","rules":["规则1","规则5","规则7"],"tools":["terminal","read_file","search_files","patch"],"context_hint":"安全审计。确保无降级实现。检查权限和访问控制。"},
        "collect": {"label":"采集任务","rules":["规则5","规则8"],"tools":["terminal","read_file","cronjob"],"context_hint":"35+采集器运行中，每4小时全量采集。采集时质量预筛，低质内容不进库。国内网络受限时用ghproxy等镜像。"},
        "score": {"label":"评分任务","rules":["规则5"],"tools":["terminal","read_file"],"context_hint":"AI评分用DeepSeek API。model必须是deepseek-chat。六维评分：scarcity/impact/tech_depth/timeliness/preference/credibility。每批2条。"},
        "dev": {"label":"开发任务","rules":["规则1","规则2","规则5","规则6","规则7"],"tools":["terminal","read_file","write_file","patch","search_files","delegate_task"],"context_hint":"分阶段执行，每阶段写checkpoint。完整3轮循环：完善→审核→测试。严禁降级实现。"},
    }


def read_wake_guide() -> dict:
    """从wake_guide.json读取当前任务类型"""
    result = {
        "task_type": "general",
        "task_id": "unknown",
        "next_action": "",
        "detail": ""
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
            # 检查wake_guide是否直接指定了task_type
            if "task_type" in wg:
                result["task_type"] = wg["task_type"]
        except Exception:
            pass
    return result


def extract_section_from_soul(text: str, section_title: str, max_lines: int = 0) -> str:
    """从SOUL.md中提取指定章节的内容"""
    # 尝试多种匹配模式
    patterns = [
        f"## {section_title}",           # 标准标题
        f"## {section_title}（",          # 带括号
        f"## {section_title} ",           # 空格后
        f"### {section_title}",           # 三级标题
        f"## {section_title}_",           # 下划线
    ]
    
    start_pos = -1
    for pat in patterns:
        pos = text.find(pat)
        if pos != -1:
            start_pos = pos
            break
    
    if start_pos == -1:
        return ""
    
    # 找章节结束（下一个同级标题）
    rest = text[start_pos + 1:]
    next_same = -1
    # 找 ## 开头的新章节（但跳过 ###）
    for m in re.finditer(r"\n## (?!#)", rest):
        next_same = start_pos + 1 + m.start()
        break
    
    if max_lines > 0:
        lines = text[start_pos:].split("\n")
        return "\n".join(lines[:max_lines])
    
    if next_same != -1:
        return text[start_pos:next_same].strip()
    
    return text[start_pos:].strip()


def extract_all_rules_summary(text: str) -> str:
    """提取8条规则的标题/摘要（所有任务都需要）"""
    lines = ["## 8条永久规则（压缩版）"]
    
    for i in range(1, 9):
        # 找规则i
        pat = f"### 规则{i}："
        pos = text.find(pat)
        if pos == -1:
            pat2 = f"### 规则{i}（"
            pos = text.find(pat2)
        if pos == -1:
            pat3 = f"### 规则{i} "
            pos = text.find(pat3)
        
        if pos != -1:
            end_pos = text.find("\n###", pos + 1)
            if end_pos == -1:
                end_pos = pos + 300
            block = text[pos:end_pos]
            first_line = block.split("\n")[0].strip().lstrip("#").strip()
            # 提取第一句说明
            body = block.split("\n", 1)[1] if "\n" in block else ""
            # 找核心句子（第一个非列表、非空的行）
            core = ""
            for bl in body.split("\n")[:5]:
                bl = bl.strip()
                if bl and not bl.startswith("-") and not bl.startswith("*") and not bl.startswith("|") and len(bl) > 5:
                    core = bl[:120]
                    break
            if core:
                lines.append(f"  {first_line}: {core}")
            else:
                lines.append(f"  {first_line}")
        else:
            # 规则描述（已知）
            rule_descs = {
                1: "任务执行前必须全面回顾+全局预判",
                2: "超限/中断时自动拆解+继续执行",
                3: "每阶段完成后必须复盘",
                4: "完整执行后全局复盘",
                5: "真实实现+联网最佳方案+严苛测试",
                6: "强制循环的完善→审核→测试循环（至少3轮）",
                7: "严禁所有形式的降级实现",
                8: "下载受限时寻找第三方正规链接",
            }
            lines.append(f"  规则{i}：{rule_descs.get(i, '')}")
    
    return "\n".join(lines)


def extract_specific_rules(text: str, rule_numbers: list) -> str:
    """提取指定规则号的完整内容"""
    parts = []
    for rn in rule_numbers:
        # 提取数字
        num = re.search(r"\d+", str(rn))
        if not num:
            continue
        n = num.group()
        
        # 找规则n的完整内容
        for pat in [
            f"### 规则{n}：",
            f"### 规则{n}（",
            f"### 规则{n} ",
            f"## 规则{n}：",
        ]:
            pos = text.find(pat)
            if pos != -1:
                # 找到开头
                end_pos = text.find("\n### 规则", pos + 1)
                if end_pos == -1:
                    # 也可能是 ## 开头
                    end_pos = text.find("\n## 规则", pos + 1)
                if end_pos == -1:
                    end_pos = pos + 500
                block = text[pos:end_pos].strip()
                if len(block) > 30:
                    parts.append(block)
                break
    
    return "\n\n".join(parts)


def build_surgical_context() -> dict:
    """构建外科式上下文"""
    if not SOUL_PATH.exists():
        return {"error": "SOUL.md not found"}
    
    text = SOUL_PATH.read_text(encoding="utf-8")
    
    # 1. 读取任务类型
    wake_info = read_wake_guide()
    task_type = wake_info.get("task_type", "general")
    
    # 2. 加载任务类型配置
    configs = load_config()
    task_cfg = configs.get(task_type, configs.get("general", {}))
    if task_type == "dev" and "dev" not in configs:
        task_cfg = configs.get("develop", configs.get("general", {}))
    
    # 3. 构建输出
    # --- 核心内容（所有任务保留）---
    core_parts = []
    
    # 核心身份
    identity = extract_section_from_soul(text, "一、核心身份", 4)
    if identity:
        core_parts.append(identity)
    else:
        core_parts.append("## 核心身份\n你是Hermes — 格林主人的数字伙伴。目的: 关键时刻精准支持（智囊/极客）+ 日常情绪价值（伴侣）+ 持续进化。")
    
    # 永久禁令
    bans = extract_section_from_soul(text, "二、永久禁令", 15)
    if bans:
        core_parts.append(bans)
    else:
        core_parts.append("## 永久禁令\n0.反幻觉铁律 1.禁止批量生成 2.禁止降级实现 3.禁止Docker 4.禁止虚假实现 5.必须全面深度复盘")
    
    # 5大行为准则
    conduct = extract_section_from_soul(text, "四、5大行为准则", 10)
    if conduct:
        core_parts.append(conduct)
    else:
        core_parts.append("## 5大行为准则\n1.不凭旧结论 2.工具=整个OS 3.失败换方法 4.质疑=换角度 5.完善≠可用")
    
    # 8条规则标题（所有任务保留）
    rules_summary = extract_all_rules_summary(text)
    core_parts.append(rules_summary)
    
    # --- 额外规则完整内容（按任务类型）---
    extra_rules = task_cfg.get("rules", [])
    extra_rule_text = extract_specific_rules(text, extra_rules)
    if extra_rule_text:
        core_parts.append(extra_rule_text)
    
    core_content = "\n\n".join(core_parts)
    
    # --- 工具列表 ---
    tools = task_cfg.get("tools", ["terminal", "read_file", "write_file", "patch", "search_files"])
    tools_str = "## 分配工具\n" + "\n".join(f"- {t}" for t in tools)
    
    # --- 工作上下文 ---
    context_hint = task_cfg.get("context_hint", "")
    task_context = f"## 工作上下文（{task_cfg.get('label', '通用')}）\n{context_hint}" if context_hint else ""
    
    # 中断任务信息
    interrupt_info = ""
    if wake_info.get("task_id") and wake_info["task_id"] != "unknown":
        interrupt_info = f"## 当前任务\nID: {wake_info['task_id']}\n下一步: {wake_info.get('next_action', '')}\n详情: {wake_info.get('detail', '')[:200]}"
    
    # 组装
    all_parts = []
    all_parts.append(core_content)
    all_parts.append(tools_str)
    if task_context:
        all_parts.append(task_context)
    if interrupt_info:
        all_parts.append(interrupt_info)
    
    # 备份规则
    all_parts.append("## ⚠️ 备份规则\n所有删除/覆盖写/批量修改前先备份到 /mnt/d/Hermes/备份/")
    
    final_text = "\n\n".join(all_parts)
    final_text = re.sub(r"\n{3,}", "\n\n", final_text).strip()
    total_tokens = estimate_tokens(final_text)
    
    # 输出
    result = {
        "ts": datetime.now().isoformat(),
        "task_type": task_type,
        "task_id": wake_info.get("task_id", "unknown"),
        "next_action": wake_info.get("next_action", ""),
        "total_tokens": total_tokens,
        "total_chars": len(final_text),
        "content": final_text,
        "sliced_rules_count": len(extra_rules),
        "tools_allocated": len(tools),
        "rules_included": extra_rules,
        "tools_list": tools,
    }
    
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def main():
    result = build_surgical_context()
    if "error" in result:
        print(f"❌ {result['error']}")
        sys.exit(1)
    
    print(f"🔪 surgical_context_slicer v2.0")
    print(f"  task_type={result.get('task_type', '?')}")
    print(f"  task_id={result.get('task_id', '?')}")
    print(f"  tokens={result.get('total_tokens', 0)}")
    print(f"  规则数={result.get('sliced_rules_count', 0)}")
    print(f"  工具数={result.get('tools_allocated', 0)}")
    print(f"  输出: {OUTPUT_PATH}")
    # 摘要
    content_preview = result.get("content", "")[:150]
    if content_preview:
        print(f"  摘要: {content_preview}...")


if __name__ == "__main__":
    main()
