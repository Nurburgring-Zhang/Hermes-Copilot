#!/usr/bin/env python3
"""
🔴🔴🔴 反幻觉铁律：严禁任何不加核实的猜想、胡编乱造、自己瞎编！
必须核实才能说/必须验证才能写/必须确认才能断言/不知道就说不知道
这是最高优先级规则，凌驾于所有其他规则之上。
"""

#!/usr/bin/env python3
"""
tool_unloader.py — Hy-Memory 风格的工其结果卸载引擎 v2.0 (LLM增强)
======================================================================
v2.0 核心改进:
  1. 智能阈值：不是所有>2KB的都卸载，LLM判断结果"价值"
  2. LLM摘要：替代简单的截断，生成语义摘要
  3. 优先级标记：高价值结果保留更久，低价值更快清理
  4. 规则降级：LLM不可用时保留v1的机械2KB阈值

核心逻辑:
  1. intercept_tool_result(tool_name, params, result)
     - LLM判断：这条结果"值得保留吗"（信息量/独特性/复用概率）
     - 值得 → 卸载到 refs/*.md + 生成LLM语义摘要
     - 不值得 → 丢弃（不卸载）
     - 规则降级 → 保留2KB阈值
  2. get_compressed_context()
     从 offload_entries.jsonl 读取已卸载条目，返回压缩上下文
"""

import os
import json
import time
import hashlib
import re
from pathlib import Path
from typing import Optional, Any

REFS_DIR = Path.home() / ".hermes" / "refs"
OFFLOAD_DB = Path.home() / ".hermes" / "offload_entries.jsonl"
UNLOAD_THRESHOLD = 2048
MAX_REFS_AGE_DAYS = 7


class ToolUnloader:
    """
    工其结果卸载器 v2.0 (LLM增强)
    
    LLM判断卸载优先级：
      1. 包含错误/异常的结果 → 高价值（故障排查用）
      2. 包含大量数据/配置信息 → 中价值
      3. 简单的确认/状态信息 → 低价值（直接丢弃）
    """
    
    # LLM卸载判断prompt
    UNLOAD_PROMPT = """你是上下文管理专家。判断这条工具调用的结果是否值得卸载保存。

工具: [{TOOL_NAME}]
结果预览(前500字): [{PREVIEW}]
结果大小: {SIZE} 字符

判断标准：
1. high(高价值)：包含错误信息、异常、大量数据、配置详情、代码输出——未来可能有用
2. medium(中等)：常规操作结果，可能有参考价值但非关键
3. low(低价值)：确认信息、状态正常、简单结果——上下文出现时直接丢弃

返回JSON:
{
  "value": "high|medium|low",
  "reason": "简短理由",
  "suggested_summary": "建议的摘要(20字以内)",
  "keep_days": 7
}"""

    def __init__(self):
        REFS_DIR.mkdir(parents=True, exist_ok=True)
    
    def _evaluate_with_llm(self, tool_name: str, result: str) -> Optional[dict]:
        """用LLM评估结果价值"""
        prompt = self.UNLOAD_PROMPT.format(
            TOOL_NAME=tool_name,
            PREVIEW=result[:500].replace('{','(').replace('}',')'),
            SIZE=len(result)
        )
        
        from llm_bridge import llm_call_json
        
        result = llm_call_json(
            system_prompt="",
            user_prompt=prompt,
            fallback=None,
            max_tokens=400,
            timeout=30,
        )
        
        if result.success and result.data is not None:
            return result.data
        
        return None

    def _make_ref_id(self, tool_name: str) -> str:
        ts = int(time.time())
        return f"{tool_name}_{ts}"
    
    def _write_ref_file(self, ref_id: str, tool_name: str, params: Any, result: str, llm_summary: str = "") -> Path:
        """写入ref文件（含LLM摘要）"""
        ref_path = REFS_DIR / f"{ref_id}.md"
        params_str = json.dumps(params, ensure_ascii=False, indent=2) if not isinstance(params, str) else params
        if len(params_str) > 5000:
            params_str = params_str[:5000] + "\n... (truncated)"
        
        summary_section = f"> LLM摘要: {llm_summary}\n\n" if llm_summary else ""
        
        content = f"""# {tool_name}

## 调用信息
- **时间**: {time.strftime('%Y-%m-%d %H:%M:%S')}
- **工具**: {tool_name}
- **Ref ID**: `{ref_id}`
{summary_section}
## 参数
```json
{params_str}
```

## 完整结果
```
{result}
```
"""
        ref_path.write_text(content, encoding='utf-8')
        return ref_path
    
    def _summarize(self, tool_name: str, params: Any, result: str) -> str:
        """v1机械摘要（降级用）"""
        params_str = params if isinstance(params, str) else json.dumps(params, ensure_ascii=False)
        if tool_name == "read_file":
            path = params.get("path", "?") if isinstance(params, dict) else params_str[:60]
            return f"读取了 {path} ({len(result)} chars)"
        elif tool_name == "terminal":
            cmd = params.get("command", params_str[:80]) if isinstance(params, dict) else params_str[:80]
            return f"执行: {cmd} -> ({len(result)} chars)"
        else:
            return f"{tool_name}: {result[:80].replace(chr(10), ' ').strip()}"
    
    def intercept_tool_result(self, tool_name: str, params: Any, result: str) -> str:
        """
        拦截工其结果 v2.0
        
        LLM评估→智能卸载 vs v1机械2KB阈值
        """
        result_str = result if isinstance(result, str) else str(result)
        
        # 小结果：直接返回
        if len(result_str) < UNLOAD_THRESHOLD:
            return result_str
        
        # 尝试LLM评估
        llm_eval = self._evaluate_with_llm(tool_name, result_str)
        
        if llm_eval:
            value = llm_eval.get("value", "medium")
            summary = llm_eval.get("suggested_summary", "") or self._summarize(tool_name, params, result_str)
            keep_days = llm_eval.get("keep_days", MAX_REFS_AGE_DAYS)
            
            if value == "low":
                # LLM判定低价值：不卸载，直接返回截断版本
                return f"{summary[:100]} ({len(result_str)} chars, low-value)"
            
            ref_id = self._make_ref_id(tool_name)
            ref_path = self._write_ref_file(ref_id, tool_name, params, result_str, summary)
            
            entry = {
                "ref_id": ref_id, "tool_name": tool_name, "summary": summary,
                "result_size": len(result_str), "ref_path": str(ref_path),
                "timestamp": time.time(), "llm_value": value, "keep_days": keep_days,
            }
            with open(OFFLOAD_DB, 'a', encoding='utf-8') as f:
                f.write(json.dumps(entry, ensure_ascii=False) + '\n')
            
            return f"[ref:{ref_id}] {summary}"
        else:
            # LLM不可用，v1降级
            ref_id = self._make_ref_id(tool_name)
            ref_path = self._write_ref_file(ref_id, tool_name, params, result_str)
            summary = self._summarize(tool_name, params, result_str)
            entry = {
                "ref_id": ref_id, "tool_name": tool_name, "summary": summary,
                "result_size": len(result_str), "ref_path": str(ref_path),
                "timestamp": time.time(), "llm_value": "unknown", "keep_days": MAX_REFS_AGE_DAYS,
            }
            with open(OFFLOAD_DB, 'a', encoding='utf-8') as f:
                f.write(json.dumps(entry, ensure_ascii=False) + '\n')
            return f"[ref:{ref_id}] {summary}"
    
    def get_compressed_context(self, max_entries: int = 10) -> str:
        """获取当前上下文中的工具结果摘要（同v1）"""
        if not OFFLOAD_DB.exists():
            return ""
        entries = []
        with open(OFFLOAD_DB, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        recent = sorted(entries, key=lambda e: e.get("timestamp", 0), reverse=True)[:max_entries]
        if not recent:
            return ""
        lines = ["## \u5f53\u524d\u4efb\u52a1\u4e0a\u4e0b\u6587\uff08\u5df2\u5378\u8f7d\u7684\u5de5\u5177\u7ed3\u679c\uff09"]
        for i, entry in enumerate(recent, 1):
            ref_id = entry["ref_id"]
            summary = entry.get("summary", entry.get("tool_name", "?"))
            lines.append(f"  {i}. [[{ref_id}]] {summary}")
        return "\n".join(lines)
    
    def cleanup_expired(self, max_age_days: int = MAX_REFS_AGE_DAYS) -> int:
        """清理过期refs（LLM感知：高价值保留更久）"""
        if not REFS_DIR.exists():
            return 0
        now = time.time()
        cleaned = 0
        
        # 读取offload entries中的keep_days
        keep_map = {}
        if OFFLOAD_DB.exists():
            with open(OFFLOAD_DB, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            entry = json.loads(line)
                            keep_map[entry.get("ref_id")] = entry.get("keep_days", max_age_days)
                        except json.JSONDecodeError:
                            continue
        
        for f in REFS_DIR.iterdir():
            if f.is_file() and f.suffix == '.md':
                ref_id = f.stem
                keep = keep_map.get(ref_id, max_age_days)
                cutoff = now - (keep * 86400)
                if f.stat().st_mtime < cutoff:
                    f.unlink()
                    cleaned += 1
        
        if OFFLOAD_DB.exists():
            valid = []
            with open(OFFLOAD_DB, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            entry = json.loads(line)
                            keep = entry.get("keep_days", max_age_days)
                            ts = entry.get("timestamp", 0)
                            if ts >= now - (keep * 86400):
                                valid.append(line)
                        except json.JSONDecodeError:
                            continue
            with open(OFFLOAD_DB, 'w', encoding='utf-8') as f:
                for line in valid:
                    f.write(line + '\n')
        
        return cleaned


if __name__ == "__main__":
    import sys
    unloader = ToolUnloader()
    if len(sys.argv) > 1 and sys.argv[1] == "cleanup":
        count = unloader.cleanup_expired()
        print(f"Cleaned {count} expired refs")
    elif len(sys.argv) > 1 and sys.argv[1] == "context":
        print(unloader.get_compressed_context())
    elif len(sys.argv) > 1 and sys.argv[1] == "stats":
        offload_path = OFFLOAD_DB
        if offload_path.exists():
            with open(offload_path, 'r') as f:
                lines = [l for l in f if l.strip()]
            print(f"Offload entries: {len(lines)}")
        refs = list(REFS_DIR.glob("*.md")) if REFS_DIR.exists() else []
        print(f"Ref files: {len(refs)}")
    else:
        print(__doc__)

