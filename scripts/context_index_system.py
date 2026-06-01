#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Hermes 索引-复原式上下文系统 v1.0
====================================
核心设计：

第一轮对话：
  → 传入全量上下文（SOUL.md全文 + 当前任务 + 规则 + 齿轮 + 工具）
  → AI全量处理，输出回复
  → 同时生成索引摘要文件（供后续轮次使用）

后续轮次：
  → 只传入索引摘要（约500-800 tokens）
    - [核心身份] 一句话
    - [规则1-8] 每行一个标题
    - [当前任务] 任务ID+进度
    - [齿轮] 一行摘要
    - [工具] 列表
  → AI处理时如果发现需要某个规则的完整原文
  → 从 ~/.hermes/reports/context_sections/ 中按ID读取完整章节
  → 输出回复

每轮结束后更新索引摘要（写入新进度）

输出文件：
  - reports/context_index.json → 索引摘要（传给AI）
  - reports/context_sections/   → 各章节完整原文（AI本地读取）
"""

import json, sys, os, re, hashlib
from pathlib import Path
from datetime import datetime

HERMES = Path("/home/administrator/.hermes")
SECTIONS_DIR = HERMES / "reports" / "context_sections"

def estimate_tokens(text: str) -> int:
    cn = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    en = len(text) - cn
    return int(cn * 1.5 + en * 1.3)

def build_sections():
    """从SOUL.md中按章节分割，每章存为一个独立文件"""
    soul = HERMES / "SOUL.md"
    if not soul.exists():
        return
    
    SECTIONS_DIR.mkdir(parents=True, exist_ok=True)
    text = soul.read_text(encoding="utf-8")
    
    sections = {}
    current_section_id = None
    current_section_title = None
    current_content = []
    
    for line in text.split('\n'):
        # 检测章节边界
        if line.startswith('## ') and not line.startswith('###'):
            # 保存上一节
            if current_section_id:
                sections[current_section_id] = {
                    "title": current_section_title,
                    "content": '\n'.join(current_content),
                    "tokens": estimate_tokens('\n'.join(current_content))
                }
            # 新章节
            title = line.strip('# ').strip()
            # 生成章节ID
            section_id = title.lower().replace(' ', '_').replace('（', '_').replace('）', '_')
            section_id = re.sub(r'[^a-z0-9_\\u4e00-\\u9fff]', '', section_id)[:40]
            current_section_id = section_id
            current_section_title = title
            current_content = [line]
        else:
            if current_section_id:
                current_content.append(line)
    
    # 最后一节
    if current_section_id:
        sections[current_section_id] = {
            "title": current_section_title,
            "content": '\n'.join(current_content),
            "tokens": estimate_tokens('\n'.join(current_content))
        }
    
    # 写入文件（增量更新: 检查mtime,只重建变更的）
    section_index = {}
    soul_mtime = soul.stat().st_mtime if soul.exists() else 0
    rebuilt = 0
    skipped = 0
    
    for sid, data in sections.items():
        if not sid or len(data["content"].strip()) < 20:
            continue
        file_path = SECTIONS_DIR / f"{sid}.md"
        
        # 增量检测: 如果文件存在且mtime晚于SOUL.md的mtime,跳过
        if file_path.exists():
            file_mtime = file_path.stat().st_mtime
            if file_mtime >= soul_mtime:
                # 文件已是最新, 跳过重建
                skipped += 1
                # 但仍需添加到索引
                section_index[sid] = {
                    "title": data["title"],
                    "file": f"context_sections/{sid}.md",
                    "tokens": data["tokens"],
                    "lines": len(data["content"].split('\n'))
                }
                continue
        
        file_path.write_text(data["content"], encoding="utf-8")
        rebuilt += 1
        section_index[sid] = {
            "title": data["title"],
            "file": f"context_sections/{sid}.md",
            "tokens": data["tokens"],
            "lines": len(data["content"].split('\n'))
        }
    
    # 写入索引
    index_path = HERMES / "reports" / "section_index.json"
    index_path.write_text(json.dumps(section_index, ensure_ascii=False, indent=2), encoding="utf-8")
    
    print(f"创建了 {len(section_index)} 个章节文件 (重建{rebuilt}, 跳过{skipped})")
    return section_index

def build_index(task_info: dict = None) -> dict:
    """构建本轮对话的索引摘要（仅500-800 tokens）"""
    
    # 读取章节索引
    index_path = HERMES / "reports" / "section_index.json"
    if not index_path.exists():
        build_sections()
    
    with open(index_path, encoding='utf-8') as f:
        section_index = json.load(f)
    
    # 读取当前任务信息
    if task_info is None:
        task_info = {}
        for src in ["wake_guide.json", "task_current.json"]:
            p = HERMES / "reports" / src
            if p.exists():
                try:
                    d = json.loads(p.read_text())
                    if d.get("interrupted_task"):
                        task_info = d["interrupted_task"]
                    elif d.get("task_id"):
                        task_info = d
                except:
                    pass
    
    # 构建索引摘要（轻量版）
    index_lines = [
        "# Hermes 上下文索引（轻量版）",
        "以下为当前上下文的索引。需要完整原文时，从 ~/.hermes/reports/context_sections/<ID>.md 读取。",
        "",
        "## [核心身份]",
        "Hermes - 格林主人的数字伙伴。智囊/极客 + 情绪价值 + 持续进化。协作者非主仆。",
        "",
        "## [永久禁令]",
        "1)禁止批量生成  2)禁止降级实现  3)禁止Docker  4)禁止虚假实现  5)必须全面深度复盘",
        "",
        "## [5大行为准则]",
        "1)不凭旧结论  2)工具=整个OS  3)失败换方法  4)质疑=换角度  5)完善≠可用",
        "",
        "## [全能力自动激活]",
        "所有能力主动运行+自动激活+强制自检+相互督促。无需人工介入。",
        "",
        "## [8条永久规则]",
    ]
    
    # 为8条规则创建独立的摘要索引行
    # 自动查找规则文件
    rules_file = None
    for f in SECTIONS_DIR.glob("*.md"):
        if "七条永久执行规则" in f.stem or "八_" in f.stem:
            rules_file = f.stem
            break
    rules_ref = f" → context_sections/{rules_file}.md" if rules_file else ""
    rules_summary = [
        f"  规则0(自主能力基线): 多路方案→核实质量→环境无关判断{rules_ref}",
        "  规则1(任务前回顾): 先查历史会话+全网信息+制定规划",
        "  规则2(超限拆解): tokens超限自动拆解+高质量恢复",
        "  规则3(阶段复盘): 每阶段完成后回顾复盘",
        "  规则4(全局复盘): 完整执行后全局复盘",
        "  规则5(真实实现): 联网最佳+商用测试+多工况",
        "  规则6(完善循环): 至少3轮完善→审核→测试",
        "  规则7(禁止降级): 严禁一切降级/模拟/占位",
        "  规则8(下载受限): 找镜像+校验和+不放弃",
    ]
    for line in rules_summary:
        index_lines.append(line)
    
    index_lines.append("")
    index_lines.append("## [齿轮系统]")
    index_lines.append("G0-G8齿轮链，每1-30分钟循环。断点文件: task_current/gear_checkpoint/recovery_pack。")
    # 齿轮路径
    gear_file = None
    for f in SECTIONS_DIR.glob("*.md"):
        if "齿轮强制恢复协议" in f.stem or "零_" in f.stem:
            gear_file = f.stem
            break
    gear_ref = f"完整齿轮结构 → context_sections/{gear_file}.md" if gear_file else "完整齿轮结构 → (需手动读取)"
    index_lines.append(gear_ref)
    index_lines.append("")
    
    # 当前任务
    if task_info:
        index_lines.append("## [当前任务]")
        index_lines.append(f"  ID: {task_info.get('task_id', 'N/A')}")
        index_lines.append(f"  进度: {task_info.get('status', 'N/A')}")
        index_lines.append(f"  下一步: {task_info.get('next_action', 'N/A')}")
        index_lines.append(f"  详情: {task_info.get('detail', '')[:100]}")
        index_lines.append("")
    # 只列出最常用的章节
    index_lines.append("")
    index_lines.append("## [关键章节索引]")
    common_sections = [
        "零_齿轮强制恢复协议", "八_七条永久执行规则",
        "一核心身份", "二永久禁令", "四5大行为准则",
        "_skills组合并行链式调用", "_低分数据自动清理",
        "九_oi项目全量优化增强方案"
    ]
    for sid, sinfo in sorted(section_index.items()):
        if any(c in sid for c in common_sections):
            index_lines.append(f"  {sinfo['title'][:50]} → context_sections/{sid}.md")
    index_lines.append(f"  还有{len(section_index)-len(common_sections)}个章节未列出，按需读取")
    
    index_text = '\n'.join(index_lines)
    tokens = estimate_tokens(index_text)
    
    index = {
        "ts": datetime.now().isoformat(),
        "version": "1.0",
        "total_tokens": tokens,
        "total_chars": len(index_text),
        "sections_available": len(section_index),
        "sections": [{"section_id": k, "section_file": f"reports/context_sections/{k}.md", "size_bytes": v.get("size", 0)} for k, v in section_index.items()],
        "index_text": index_text,
        "task_info": task_info
    }
    
    out_path = HERMES / "reports" / "context_index.json"
    out_path.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    
    return index

def resolve_section(section_id: str) -> str:
    """根据章节ID读取完整原文"""
    file_path = SECTIONS_DIR / f"{section_id}.md"
    if file_path.exists():
        return file_path.read_text(encoding="utf-8")
    
    # 尝试模糊匹配
    for f in SECTIONS_DIR.glob("*.md"):
        if section_id in f.stem:
            return f.read_text(encoding="utf-8")
    
    return f"[章节 {section_id} 未找到]"

def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "auto"
    
    if cmd == "build":
        # 构建章节文件（首次运行）
        sections = build_sections()
        print(f"章节文件: {len(sections)}个")
        for sid, data in sorted(sections.items())[:5]:
            print(f"  {sid}: {data['tokens']}tokens")
    
    elif cmd == "index":
        # 构建索引摘要
        index = build_index()
        print(f"索引摘要: {index['total_tokens']}tokens, {index['sections_available']}个章节可用")
        print("---")
        print(index['index_text'])
    
    elif cmd == "resolve":
        # 根据ID读取完整章节
        sid = sys.argv[2] if len(sys.argv) > 2 else ""
        content = resolve_section(sid)
        print(content[:500])
        print(f"... ({len(content)}字)")

    elif cmd == "auto":
        # 自动：构建章节+构建索引
        build_sections()
        index = build_index()
        print(f"索引: {index['total_tokens']}tokens")

if __name__ == "__main__":
    main()

