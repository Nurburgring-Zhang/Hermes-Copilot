#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Hermes 动态上下文编译器 v2.0
=============================
从SOUL.md原文动态提取+分层压缩，无需手动维护硬编码。

分层策略：
  🔴 层1（强制保留）: 8条规则概要+规则0+上下文压缩+身份+禁令+准则+齿轮步骤0
  🟡 层2（按需保留）: 齿轮协议+Multi-Agent+Pipeline+全能力激活
  🟢 层3（索引标题）: OI方案/skills/低分清理/采集预筛/文件索引
  ⚫ 层4（砍掉）: 九面人格/OI量化指标/齿轮bash命令

用法:
  python3 context_packer.py [task_type]
    → 从SOUL.md动态提取+分层，输出context_pack.json
  task_type: general | fix | push | develop | review | research | pipeline

设计要点:
  - 不硬编码任何内容，全从原文动态提取
  - SOUL.md改了，压缩结果自动变，零维护
  - 第一轮AI分析后写入context_layer_def.json固化分层
"""

import json, sys, re
from pathlib import Path
from datetime import datetime

HERMES = Path("/home/administrator/.hermes")


def estimate_tokens(text: str) -> int:
    cn = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
    en = len(text) - cn
    return int(cn * 1.5 + en * 1.3)


# ============================================================
# 🔴 层1：强制保留内容（从原文动态提取，无硬编码）
# ============================================================
def extract_layer1_core(text: str) -> str:
    """提取🔴层1必须保留的核心内容"""
    parts = []

    # --- 核心身份 ---
    id_pos = text.find("## 一、核心身份")
    if id_pos != -1:
        id_end = text.find("## 二、", id_pos)
        if id_end == -1:
            id_end = id_pos + 200
        block = text[id_pos:id_end].strip()
        # 保留前3行
        parts.append("\n".join(block.split("\n")[:4]))

    # --- 永久禁令 ---
    ban_pos = text.find("## 二、永久禁令")
    if ban_pos != -1:
        ban_end = text.find("## 三、", ban_pos)
        if ban_end == -1:
            ban_end = ban_pos + 500
        block = text[ban_pos:ban_end].strip()
        # 保留1-5条的一行摘要
        bans = [l.strip() for l in block.split("\n") if l.strip().startswith(("1.", "2.", "3.", "4.", "5."))][:5]
        if bans:
            parts.append("## 永久禁令\n" + "\n".join(bans))

    # --- 行为准则 ---
    rule_pos = text.find("## 四、5大行为准则")
    if rule_pos != -1:
        rule_end = text.find("## 五、", rule_pos)
        if rule_end == -1:
            rule_end = rule_pos + 400
        block = text[rule_pos:rule_end].strip()
        lines = [l.strip() for l in block.split("\n") if "|" in l and l.strip().startswith("|")]
        if lines:
            condensed = []
            for l in lines:
                cells = [c.strip() for c in l.split("|") if c.strip()]
                if len(cells) >= 2:
                    # cells[0]是编号, cells[-1]是内容
                    num = cells[0].strip()
                    content = cells[-1].strip()
                    # 只取第一句（去掉展开）
                    content_short = content.split("—")[0].split("，")[0]
                    if len(content_short) > 40:
                        content_short = content_short[:40] + "…"
                    condensed.append(f"  {num}. {content_short}")
            parts.append("## 5大行为准则\n" + "\n".join(condensed))

    # --- 规则0：自主能力基线（前三步） ---
    r0_pos = text.find("### 规则0：")
    if r0_pos != -1:
        r0_end = text.find("### 🔴 全能力", r0_pos)
        if r0_end == -1:
            r0_end = r0_pos + 800
        block = text[r0_pos:r0_end].strip()
        # 提取三步标题
        steps = re.findall(r"\d+\.\s*\*\*(.+?)\*\*", block)
        if steps:
            parts.append("## 规则0（自主基线）\n" + "\n".join(f"  {i+1}. {s}" for i, s in enumerate(steps)))

    # --- 上下文压缩规则 ---
    cc_pos = text.find("### 🔴 上下文压缩强制规则")
    if cc_pos != -1:
        cc_end = text.find("### 规则3", cc_pos)
        if cc_end == -1:
            cc_end = cc_pos + 500
        block = text[cc_pos:cc_end].strip()
        lines = block.split("\n")
        # 只保留数字编号的规则
        rules = [l.strip() for l in lines if re.match(r"^\d+\.|^-", l.strip())]
        if rules:
            parts.append("## 上下文压缩规则\n" + "\n".join(rules))
        else:
            parts.append("## 上下文压缩规则\n" + "\n".join(lines[:6]))

    # --- 8条永久规则（压缩版：每条一行） ---
    r1_pos = text.find("### 规则1：")
    r8_end = text.find("## 🔴 skills组合")
    if r1_pos != -1 and r8_end != -1:
        rules_section = text[r1_pos:r8_end]
        # 按###分割
        rule_blocks = re.split(r"(?=^### 规则)", rules_section, flags=re.MULTILINE)
        summaries = ["## 8条永久规则（压缩版）"]
        for block in rule_blocks:
            lines = [l.strip() for l in block.strip().split("\n") if l.strip()]
            if not lines:
                continue
            # 标题行
            title = lines[0].replace("### ", "") if lines[0].startswith("###") else ""
            # 找核心总结（第一句非标题的总结性文字）
            body_lines = lines[1:] if lines[0].startswith("###") else lines
            # 跳过列表项(- * 数字.)，找第一句普通文字
            core_sentence = ""
            for line in body_lines:
                if re.match(r"^[-*\d]", line):
                    continue
                if len(line) > 10:
                    sentences = re.split(r"(?<=[。])", line)
                    core_sentence = sentences[0].strip()[:100]
                    break
            if title:
                entry = f"  {title}"
                if core_sentence:
                    entry += f": {core_sentence}"
                summaries.append(entry)
        parts.append("\n".join(summaries))

    return "\n\n".join(parts)


# ============================================================
# 🟡 层2：按需保留（齿轮+Agent+Pipeline+全能力）
# ============================================================
def extract_layer2_optional(text: str, task_type: str = "general") -> str:
    """按任务类型提取🟡层2内容"""
    parts = []

    # 全能力激活设定（摘要）
    act_pos = text.find("### 🔴 全能力自动激活设定")
    # 只在需要时包含

    # 齿轮协议（通用任务：只保留步骤0+外挂保障表+三重冗余）
    gear_pos = text.find("## 零、⚙️ 齿轮强制恢复协议")
    if gear_pos != -1:
        gear_end = text.find("## 一、核心身份", gear_pos)
        if gear_end == -1:
            gear_end = gear_pos + 5000
        full_gear = text[gear_pos:gear_end]
        
        # 步骤0
        step0_pos = full_gear.find("### 🔴 强制步骤0")
        step1_pos = full_gear.find("### 🔴 强制步骤1")
        if step0_pos != -1 and step1_pos != -1:
            parts.append(full_gear[step0_pos:step1_pos].strip())
        
        # 外挂保障表
        table_pos = full_gear.find("### 外挂保障")
        if table_pos != -1:
            # 提取到"三重冗余文件"之前
            red_pos = full_gear.find("### 三重冗余文件")
            end_pos = red_pos if red_pos != -1 else len(full_gear)
            parts.append(full_gear[table_pos:end_pos].strip())
        
        # 三重冗余文件
        red_pos = full_gear.find("### 三重冗余文件")
        if red_pos != -1:
            # 提取到---之前
            dash_pos = full_gear.find("---", red_pos)
            end_pos = dash_pos if dash_pos != -1 else len(full_gear)
            parts.append(full_gear[red_pos:end_pos].strip())
        
        # 生产级可靠性引擎（一句话）
        prod_pos = full_gear.find("### 生产级可靠性引擎")
        if prod_pos != -1:
            prod_line = full_gear[prod_pos:prod_pos+300].split("\n")[0] if full_gear[prod_pos:prod_pos+300] else ""
            parts.append(prod_line)

    # Pipeline（仅pipeline任务类型保留）
    if task_type in ("pipeline",):
        pipe_pos = text.find("## 六、Pipeline v4")
        if pipe_pos != -1:
            pipe_end = text.find("## 七、", pipe_pos)
            if pipe_end == -1:
                pipe_end = pipe_pos + 600
            parts.append(text[pipe_pos:pipe_end].strip())

    return "\n\n".join(parts)


# ============================================================
# 🟢 层3：索引标题
# ============================================================
def extract_layer3_indices(text: str) -> str:
    """提取🟢层3的索引标题"""
    index_map = {
        "关键文件索引": "§七 关键文件路径索引",
        "skills组合": "§skills组合/并行/链式调用规则",
        "低分数据自动清理": "§低分数据自动清理规则",
        "采集质量预筛": "§采集质量预筛规则",
        "OI项目全量优化": "§九 OI 50项优化方案全索引",
    }
    lines = []
    for keyword, label in index_map.items():
        pos = text.find(keyword)
        if pos != -1:
            line_start = text.rfind("\n", 0, pos)
            line_end = text.find("\n", pos)
            line = text[line_start:line_end].strip()
            lines.append(f"  📄 {label}")

    if lines:
        return "## 📚 章节索引（按需读取完整内容）\n" + "\n".join(lines) + \
               "\n\n完整内容 → read_file('reports/context_sections/<ID>.md')\n索引 → context_reconstructor.py show/search"
    return ""


# ============================================================
# 主打包函数
# ============================================================
def pack_context(task_type: str = "general", extra_context: str = "") -> dict:
    soul_path = HERMES / "SOUL.md"
    if not soul_path.exists():
        return {"error": "SOUL.md not found"}

    text = soul_path.read_text(encoding="utf-8")
    raw_tokens = estimate_tokens(text)

    # 构建三层内容
    layer1 = extract_layer1_core(text)
    layer2 = extract_layer2_optional(text, task_type)
    layer3 = extract_layer3_indices(text)

    # 工具摘要（通用）
    tools = """## 工具
- terminal | read_file/write_file | patch | search_files | session_search
- delegate_task(并行3) | cronjob | memory | skill_view/manage
- web_search | send_message | vision_analyze
- context_reconstructor.py [show|search|verify]"""

    # 中断任务
    interrupt = ""
    wake = HERMES / "reports" / "wake_guide.json"
    try:
        if wake.exists():
            wg = json.loads(wake.read_text())
            if wg.get("interrupted_task"):
                interrupt = f"## 中断任务\nID: {wg['interrupted_task']['task_id']}\n下一步: {wg['interrupted_task']['next_action']}"
    except Exception:
        pass

    # 额外信息
    extras = extra_context if extra_context else ""

    # 组装：按重要性排序
    all_parts = []
    if layer1:
        all_parts.append("# 🔴 层1·强制保留\n" + layer1)
    if layer2:
        all_parts.append("# 🟡 层2·按需保留\n" + layer2)
    if layer3:
        all_parts.append(layer3)
    all_parts.append(tools)
    if interrupt:
        all_parts.append(interrupt)
    if extras:
        all_parts.append("## 额外\n" + extras)

    compressed = "\n\n".join(all_parts)
    compressed = re.sub(r"\n{3,}", "\n\n", compressed).strip()
    tokens = estimate_tokens(compressed)

    # 备份规则（强制包含）
    backup_note = "\n## ⚠️ 备份规则\n所有删除/覆盖写/批量修改前先备份到 /mnt/d/Hermes/备份/"
    compressed += backup_note
    tokens += estimate_tokens(backup_note)

    # 输出报告
    # 统计章节数
    sections_count = len(re.findall(r'^## ', text, re.MULTILINE))

    result = {
        "ts": datetime.now().isoformat(),
        "task_type": task_type,
        "version": "v2.0-dynamic",
        "original_tokens": raw_tokens,
        "packed_tokens": tokens,
        "compression_ratio": round((1 - tokens / raw_tokens) * 100, 1) if raw_tokens > 0 else 0,
        "sections_count": sections_count,
        "layer1_tokens": estimate_tokens(layer1) if layer1 else 0,
        "layer2_tokens": estimate_tokens(layer2) if layer2 else 0,
        "content": compressed,
    }

    out_path = HERMES / "reports" / "context_pack.json"
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def main():
    task_type = sys.argv[1] if len(sys.argv) > 1 else "general"
    result = pack_context(task_type)

    print(f"📦 context_packer v2.0 (动态提取)")
    print(f"  task_type={result.get('task_type', '?')}")
    print(f"  原始: {result.get('original_tokens', 0)}tokens")
    print(f"  压缩: {result.get('packed_tokens', 0)}tokens  (🔴层1:{result.get('layer1_tokens', 0)} 🟡层2:{result.get('layer2_tokens', 0)})")
    print(f"  比率: {result.get('compression_ratio', 0)}%")
    print(f"  章节: {result.get('sections_count', 0)}个")
    print("---")
    # 打印预览
    content = result.get("content", "")
    print(content[:800])
    print("...")


if __name__ == "__main__":
    main()
