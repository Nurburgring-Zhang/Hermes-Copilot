#!/usr/bin/env python3
"""
🔴🔴🔴 反幻觉铁律：严禁任何不加核实的猜想、胡编乱造、自己瞎编！
必须核实才能说/必须验证才能写/必须确认才能断言/不知道就说不知道
这是最高优先级规则，凌驾于所有其他规则之上。
"""

"""
mermaid_builder.py — 工具结果→Mermaid任务画布 (P1)
======================================================================
对应 Hy-Memory: l2-mermaid.ts (9.5KB) + mmd-injector.ts

核心逻辑：
  1. 从 offload_entries.jsonl 读取已卸载的工具结果
  2. 按时间顺序构建 Mermaid 任务画布
  3. 节点含 node_id → 可按需下钻到 refs/*.md 原文
  4. 画布注入到上下文（200-500 tokens，替代数千tokens的完整结果）

Hy-Memory 的 L2 触发条件：
  - Condition A: null entry >= l2NullThreshold(3)
  - Condition B: timeout >= l2TimeoutSeconds(60)
  
Hermes 简化版触发：
  - offload entries >= 3 时自动生成 Mermaid 图
  - 每轮对话前检查并注入

用法：
  from scripts.mermaid_builder import MermaidBuilder
  mb = MermaidBuilder()
  mmd = mb.build_graph()  # 返回 Mermaid 格式字符串
  print(mmd)              # → 可直接注入上下文
"""

import json
import time
from pathlib import Path
from typing import Optional

OFFLOAD_DB = Path.home() / ".hermes" / "offload_entries.jsonl"
REFS_DIR = Path.home() / ".hermes" / "refs"


class MermaidBuilder:
    """
    从 offload entries 构建 Mermaid 任务画布
    
    Hy-Memory 对标：
      - checkL2Trigger(): 检查触发条件
      - runL2WithBackend(): 生成 MMD
      - injectMmdIntoMessages(): 注入画布
    """
    
    def __init__(self):
        self._entries = []
        self._load_entries()
    
    def _load_entries(self):
        """加载 offload_entries.jsonl"""
        if not OFFLOAD_DB.exists():
            return
        
        with open(OFFLOAD_DB, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        self._entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
    
    def _get_node_id(self, index: int) -> str:
        """生成 node_id: 三位前缀 + N + 序号"""
        prefix = int(time.time()) % 1000
        return f"{prefix:03d}-N{index}"
    
    def _get_ref_preview(self, ref_id: str, max_chars: int = 100) -> str:
        """从 ref 文件读取前几行作为预览"""
        ref_path = REFS_DIR / f"{ref_id}.md"
        if not ref_path.exists():
            return "(ref not found)"
        
        lines = ref_path.read_text(encoding='utf-8').split('\n')
        # 跳过标题头，取正文前几行
        body = [l for l in lines if l.strip() and not l.startswith('#') and not l.startswith('-')]
        preview = body[1] if len(body) > 1 else body[0] if body else ""
        preview = preview.strip()
        if len(preview) > max_chars:
            preview = preview[:max_chars] + "..."
        return preview
    
    def _normalize_summary(self, entry: dict) -> str:
        """美化和标准化摘要文本"""
        summary = entry.get("summary", entry.get("tool_name", "?"))
        # 获取原始 ref 中的内容作为补充
        ref_id = entry.get("ref_id", "")
        if ref_id:
            ref_preview = self._get_ref_preview(ref_id)
            if ref_preview and len(ref_preview) > len(summary):
                summary = ref_preview[:80]
        return summary[:60]
    
    def check_trigger(self, min_entries: int = 3) -> bool:
        """
        检查是否满足触发条件
        对应 Hy-Memory: checkL2Trigger() 中的 null_count >= nullThreshold
        """
        return len(self._entries) >= min_entries
    
    def build_graph(self, max_nodes: int = 15) -> Optional[str]:
        """
        构建 Mermaid 任务画布
        对应 Hy-Memory: generateL2Mermaid()
        
        返回 Mermaid 格式字符串:
        ```mermaid
        graph TD
            N0["read_file: 读取了 config.yaml (2500 chars)"]
            click N0 callback "cat refs/read_file_xxx.md"
            N1["terminal: 执行 build → (2600 chars)"]
            click N1 callback "cat refs/terminal_xxx.md"
            N0 --> N1
        ```
        """
        if not self._entries:
            return None
        
        # 按时间排序（最近的在前）
        sorted_entries = sorted(
            self._entries,
            key=lambda e: e.get("timestamp", 0),
            reverse=True
        )[:max_nodes]
        
        # 按时间正序排列（构建流程图走向）
        sorted_entries = list(reversed(sorted_entries))
        
        lines = []
        lines.append("```mermaid")
        lines.append("graph TD")
        lines.append("    %% 自动生成的工具调用任务画布")
        lines.append(f"    %% {len(sorted_entries)} 个节点, 生成时间: {time.strftime('%H:%M:%S')}")
        
        # 构建节点
        nodes = []
        edges = []
        prev_node_id = None
        
        for i, entry in enumerate(sorted_entries):
            node_id = self._get_node_id(i)
            tool_name = entry.get("tool_name", "tool")
            summary = self._normalize_summary(entry)
            ref_id = entry.get("ref_id", "")
            
            # 节点标签（截断到30字符以保持画布简洁）
            label = f"{tool_name}: {summary[:30]}".replace('"', "'")
            
            nodes.append(f'    {node_id}["{label}"]')
            nodes.append(f'    click {node_id} callback "cat ~/.hermes/refs/{ref_id}.md"')
            
            if prev_node_id:
                edges.append(f"    {prev_node_id} --> {node_id}")
            
            prev_node_id = node_id
        
        lines.extend(nodes)
        lines.append("")
        lines.extend(edges)
        lines.append("```")
        lines.append("")
        lines.append(f"*任务画布: {len(sorted_entries)} 个工具调用节点。")
        lines.append(f"每个节点可下钻：`cat ~/.hermes/refs/<node_id>.md` 查看完整结果*")
        
        return "\n".join(lines)
    
    def get_stats(self) -> dict:
        """获取画布状态统计"""
        return {
            "total_entries": len(self._entries),
            "trigger_ready": self.check_trigger(),
            "node_count": min(len(self._entries), 15),
        }
    
    def inject_to_context(self, current_context: str) -> str:
        """
        将 Mermaid 画布注入到已有上下文中
        对应 Hy-Memory: injectMmdIntoMessages()
        
        如果画布已存在则更新，否则追加
        """
        mmd = self.build_graph()
        if not mmd:
            return current_context
        
        # 如果已有 mermaid 块，替换
        if "```mermaid" in current_context:
            import re
            return re.sub(
                r'```mermaid\n.*?```',
                mmd.replace("```mermaid", "").replace("```", "").strip(),
                current_context,
                flags=re.DOTALL
            )
        
        # 否则追加
        return current_context + "\n\n" + mmd


# ====================== CLI ======================

if __name__ == "__main__":
    import sys
    
    mb = MermaidBuilder()
    
    if len(sys.argv) > 1 and sys.argv[1] == "stats":
        stats = mb.get_stats()
        print(f"Total entries: {stats['total_entries']}")
        print(f"Trigger ready: {stats['trigger_ready']} (>=3)")
        print(f"Max nodes: {stats['node_count']}")
    elif len(sys.argv) > 1 and sys.argv[1] == "graph":
        mmd = mb.build_graph()
        if mmd:
            print(mmd)
        else:
            print("No entries to build graph")
    else:
        mmd = mb.build_graph()
        if mmd:
            print(mmd)
        else:
            print(f"No entries. Total: {len(mb._entries)} (need 3+)")
