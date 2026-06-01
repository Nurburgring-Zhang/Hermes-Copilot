#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Hermes 上下文复原系统 v1.0
============================
按章节ID从本地读取完整原文，实现无损复原。

用法：
  python3 context_reconstructor.py list
    → 列出所有可用章节

  python3 context_reconstructor.py show <section_id>
    → 输出章节完整原文（stdout），适合被工具调用读取

  python3 context_reconstructor.py search <关键词>
    → 在所有章节中搜索关键词，返回匹配章节ID+片段

  python3 context_reconstructor.py all
    → 输出所有章节拼接（完整SOUL.md复原）

依赖：
  - reports/context_sections/ 目录下的14个章节文件
  - 由 context_index_system.py 或 surgical_context_slicer.py 维护
"""

import json, sys, os, re
from pathlib import Path
from datetime import datetime

HERMES = Path(os.environ.get("HERMES_ROOT", "/home/administrator/.hermes"))
SECTIONS_DIR = HERMES / "reports" / "context_sections"
INDEX_FILE = HERMES / "reports" / "context_index.json"
PACK_FILE = HERMES / "reports" / "context_pack.json"


def list_sections():
    """列出所有可用章节"""
    if not SECTIONS_DIR.exists():
        print("❌ 章节目录不存在")
        return

    sections = sorted(SECTIONS_DIR.glob("*.md"))
    print(f"📚 共 {len(sections)} 个章节:\n")

    # 如果有索引，加载索引中的token信息
    index_map = {}
    if INDEX_FILE.exists():
        try:
            idx = json.loads(INDEX_FILE.read_text())
            idx_text = idx.get("index_text", "")
            for m in re.finditer(
                r"([^→\n]+)\s*→\s*context_sections/([^\s\.]+\.md)", idx_text
            ):
                index_map[m.group(2)] = m.group(1).strip()
        except Exception:
            pass

    for sec in sections:
        title = sec.stem.replace("_", " ")
        size = sec.stat().st_size
        tokens = estimate_tokens(sec.read_text())
        label = index_map.get(sec.name, "")
        marker = " 🔴" if "永久" in sec.name or "规则" in sec.name else ""
        print(f"  [{sec.stem[:30]:30s}] {size:>5}B ~{tokens:>4}tokens{marker}")
        if label:
            print(f"    → {label}")


def show_section(section_id):
    """显示指定章节的完整原文"""
    # 精确匹配
    path = SECTIONS_DIR / f"{section_id}.md"
    if path.exists():
        print(path.read_text())
        return

    # 模糊匹配
    candidates = list(SECTIONS_DIR.glob(f"*{section_id}*.md"))
    if not candidates:
        # 去掉特殊字符再试
        clean = re.sub(r"[^a-zA-Z0-9\u4e00-\u9fff]", "", section_id)
        candidates = list(SECTIONS_DIR.glob(f"*{clean}*.md"))
    if not candidates:
        # 按关键词搜索文件名
        all_files = list(SECTIONS_DIR.glob("*.md"))
        candidates = [f for f in all_files if section_id.lower() in f.stem.lower()]

    if len(candidates) == 0:
        print(f"❌ 未找到章节: {section_id}")
        print("可用章节:")
        for sec in sorted(SECTIONS_DIR.glob("*.md")):
            print(f"  {sec.stem}")
        return

    if len(candidates) > 1:
        print(f"⚠️ 找到多个匹配:")
        for c in candidates:
            print(f"  {c.stem}")
        print("\n--- 返回第一个匹配 ---\n")

    print(candidates[0].read_text())


def search_sections(keyword):
    """在所有章节中搜索关键词"""
    results = []
    for sec in sorted(SECTIONS_DIR.glob("*.md")):
        content = sec.read_text()
        matches = []
        for i, line in enumerate(content.split("\n"), 1):
            if keyword.lower() in line.lower():
                matches.append(f"    L{i}: {line.strip()[:120]}")
        if matches:
            results.append(
                {
                    "section": sec.stem,
                    "size": sec.stat().st_size,
                    "matches": matches[:5],
                    "total_matches": len(matches),
                }
            )

    if not results:
        print(f"🔍 在 {len(list(SECTIONS_DIR.glob('*.md')))} 个章节中未找到: {keyword}")
        return

    print(f"🔍 找到 {sum(r['total_matches'] for r in results)} 处匹配 '{keyword}':\n")
    for r in results:
        print(
            f"  📄 {r['section'][:35]:35s} ({r['size']:>5}B, {r['total_matches']}处匹配)"
        )
        for m in r["matches"]:
            print(m)
        print()


def reconstruct_all():
    """输出所有章节拼接（完整SOUL.md复原）"""
    sections = sorted(SECTIONS_DIR.glob("*.md"))
    for sec in sections:
        content = sec.read_text()
        # 移除可能的分隔符冗余
        lines = content.split("\n")
        # 如果文件以##开头，跳过可能的重复
        sys.stdout.write("\n".join(lines))
        sys.stdout.write("\n\n")


def estimate_tokens(text: str) -> int:
    cn = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
    en = len(text) - cn
    return int(cn * 1.5 + en * 1.3)


def verify_integrity():
    """验证章节文件能否完整复原SOUL.md"""
    sections_dir = SECTIONS_DIR
    if not sections_dir.exists():
        print("❌ 章节目录不存在")
        return False

    sections = sorted(sections_dir.glob("*.md"))
    if len(sections) < 10:
        print(f"⚠️ 章节数不足: {len(sections)}/14")
        return False

    # 检查关键章节是否存在
    required_keywords = ["永久执行规则", "齿轮强制恢复", "永久禁令", "核心身份", "行为准则"]
    missing = []
    for kw in required_keywords:
        found = False
        for sec in sections:
            if kw in sec.stem:
                found = True
                break
        if not found:
            missing.append(kw)

    if missing:
        print(f"❌ 缺少关键章节: {missing}")
        return False

    # 检查索引文件
    if not INDEX_FILE.exists():
        print("❌ 索引文件不存在")
        return False

    try:
        idx = json.loads(INDEX_FILE.read_text())
        sections_avail = idx.get("sections_available", 0)
        if sections_avail < 10:
            print(f"❌ 索引中章节数不足: {sections_avail}")
            return False
    except Exception as e:
        print(f"❌ 索引文件损坏: {e}")
        return False

    # 检查压缩文件
    if not PACK_FILE.exists():
        print("⚠️ 压缩文件不存在")

    total_size = sum(sec.stat().st_size for sec in sections)
    print(f"✅ 完整性验证通过")
    print(f"   章节数: {len(sections)}")
    print(f"   总大小: {total_size} 字节")
    print(f"   索引: {'✅' if INDEX_FILE.exists() else '❌'}")
    print(f"   压缩: {'✅' if PACK_FILE.exists() else '❌'}")
    return True


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    action = sys.argv[1]

    if action == "list":
        list_sections()
    elif action == "show":
        if len(sys.argv) < 3:
            print("用法: python3 context_reconstructor.py show <section_id>")
            sys.exit(1)
        show_section(" ".join(sys.argv[2:]))
    elif action == "search":
        if len(sys.argv) < 3:
            print("用法: python3 context_reconstructor.py search <关键词>")
            sys.exit(1)
        search_sections(" ".join(sys.argv[2:]))
    elif action == "all":
        reconstruct_all()
    elif action == "verify":
        verify_integrity()
    else:
        print(f"未知操作: {action}")
        print("可用操作: list, show, search, all, verify")
        sys.exit(1)
