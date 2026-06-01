#!/usr/bin/env python3
"""
🔴🔴🔴 反幻觉铁律：严禁任何不加核实的猜想、胡编乱造、自己瞎编！
必须核实才能说/必须验证才能写/必须确认才能断言/不知道就说不知道
这是最高优先级规则，凌驾于所有其他规则之上。
"""

"""
emergency_compressor.py — 紧急上下文压缩引擎 (P1)
======================================================================
对应 Hy-Memory: llm-input-l3.ts 中的 emergencyCompress()

逻辑：
  当上下文token超过阈值时，自动执行三级压缩：
  1. Mild: score级联替换（低优先级结果→摘要）
  2. Aggressive: 从头删除旧轮次（保留最后N条）
  3. Emergency: 仅保留最后MIN_KEEP条

触发条件：
  - token_usage / context_window > ratio

用法：
  from scripts.emergency_compressor import EmergencyCompressor
  ec = EmergencyCompressor(context_window=128000)
  result = ec.compress(messages, current_tokens)
  # result → (compressed_messages, saved_tokens, level)
"""

import time
from pathlib import Path
from typing import Optional

OFFLOAD_DB = Path.home() / ".hermes" / "offload_entries.jsonl"


class EmergencyCompressor:
    """
    紧急上下文压缩引擎
    
    对应 Hy-Memory:
      - compressByScoreCascade(): 按分数级联替换
      - aggressiveCompressUntilBelowThreshold(): 暴力删除旧轮次
      - emergencyCompress(): 紧急压缩
    """
    
    # 对应 Hy-Memory 的配置
    MILD_RATIO = 0.50       # 50% → 温和压缩
    AGGRESSIVE_RATIO = 0.85 # 85% → 激进压缩  
    EMERGENCY_RATIO = 0.92  # 92% → 紧急压缩
    MIN_KEEP_AGGRESSIVE = 2  # 激进保留的最少轮次
    MIN_KEEP_EMERGENCY = 2   # 紧急保留的最少轮次
    
    def __init__(self, context_window: int = 128000):
        self.context_window = context_window
        
    def _estimate_tokens(self, text: str) -> int:
        """
        快速估算 token 数
        对标 tiktoken，但不引入外部依赖
        近似：中文1.5字/token，英文3.7字/token
        """
        if not text:
            return 0
        chinese_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
        ascii_chars = len(text) - chinese_chars
        return int(chinese_chars / 1.5 + ascii_chars / 3.7)
    
    def compress(self, current_text: str, 
                 mild: bool = True, 
                 aggressive: bool = True, 
                 emergency: bool = True) -> dict:
        """
        对当前文本执行三级压缩
        
        参数:
          current_text: 当前上下文字符串
          mild: 启用级联替换
          aggressive: 启用激进删除
          emergency: 启用紧急压缩
          
        返回:
          {
            "original_tokens": N,
            "compressed_text": "...",
            "compressed_tokens": N,
            "saved_tokens": N,
            "saved_percent": N.N,
            "level": "mild|aggressive|emergency|none"
          }
        """
        original_tokens = self._estimate_tokens(current_text)
        original_lines = current_text.split('\n')
        
        result = {
            "original_tokens": original_tokens,
            "compressed_text": current_text,
            "compressed_tokens": original_tokens,
            "saved_tokens": 0,
            "saved_percent": 0,
            "level": "none",
        }
        
        ratio = original_tokens / self.context_window if self.context_window > 0 else 1.0
        lines = original_lines
        
        # Level 1: Mild — score级联替换
        if mild and ratio >= self.MILD_RATIO:
            # 在上下文找 [ref:xxx] 标记，确保它们存在
            ref_markers = [l for l in lines if l.startswith("[ref:")]
            if ref_markers:
                # 已经压缩过了，不需要再压缩
                result["note"] = "already_compressed"
            else:
                # 尝试用 offload 条目替换大的工具结果块
                replaced = self._mild_cascade_replace(lines)
                if replaced > 0:
                    ratio = self._estimate_tokens('\n'.join(lines)) / self.context_window
                    result["level"] = "mild"
                    result["mild_replacements"] = replaced
        
        # Level 2: Aggressive — 从头删除旧轮次
        if aggressive and ratio >= self.AGGRESSIVE_RATIO:
            lines = self._aggressive_compress(lines)
            ratio = self._estimate_tokens('\n'.join(lines)) / self.context_window
            result["level"] = "aggressive"
        
        # Level 3: Emergency — 仅保留最后N条
        if emergency and ratio >= self.EMERGENCY_RATIO:
            lines = self._emergency_compress(lines)
            result["level"] = "emergency"
        
        compressed_text = '\n'.join(lines)
        compressed_tokens = self._estimate_tokens(compressed_text)
        
        result["compressed_text"] = compressed_text
        result["compressed_tokens"] = compressed_tokens
        result["saved_tokens"] = original_tokens - compressed_tokens
        result["saved_percent"] = round((1 - compressed_tokens / original_tokens) * 100, 1) if original_tokens > 0 else 0
        
        return result
    
    def _mild_cascade_replace(self, lines: list) -> int:
        """
        温和级联替换：将大的工具结果替换为 [ref:xxx] 摘要标记
        对应 Hy-Memory: compressByScoreCascade()
        
        简单策略：连续的行块中，如果包含大块输出（如```代码块），
        替换为 [[ref:auto_compressed]] 标记
        """
        replaced = 0
        i = 0
        while i < len(lines):
            line = lines[i]
            # 检测长的反引号代码块
            if line.startswith('```') and len(line) < 10:  # 开始反引号块
                start = i
                i += 1
                block_lines = []
                while i < len(lines) and not lines[i].startswith('```'):
                    block_lines.append(lines[i])
                    i += 1
                if i < len(lines):
                    block_lines.append(lines[i])  # 结束反引号
                    
                block_text = '\n'.join(block_lines)
                if len(block_text) > 1000:  # 大代码块
                    summary = f"[ref:auto_compressed] large block ({len(block_text)} chars compressed)"
                    lines[start] = summary
                    # 删除后续块行 + 结束行
                    del lines[start+1:i+1]
                    replaced += 1
                    i = start + 1
                    continue
            i += 1
        return replaced
    
    def _aggressive_compress(self, lines: list) -> list:
        """
        激进压缩：从头删除旧内容，保留最后 N 轮
        对应 Hy-Memory: aggressiveCompressUntilBelowThreshold()
        """
        if len(lines) <= self.MIN_KEEP_AGGRESSIVE * 20:
            return lines
        
        # 保留最后 40 行 + 一个摘要标记
        keep_count = min(len(lines) // 3, 80)  # 保留约1/3
        if keep_count < self.MIN_KEEP_AGGRESSIVE * 20:
            keep_count = self.MIN_KEEP_AGGRESSIVE * 20
        
        kept = lines[-keep_count:]
        summary = (
            f"[AUTO-COMPRESSED] "
            f"Deleted {len(lines) - len(kept)} lines of older context. "
            f"Use session_search for full history."
        )
        kept.insert(0, summary)
        return kept
    
    def _emergency_compress(self, lines: list) -> list:
        """
        紧急压缩：仅保留最后 N 条消息
        对应 Hy-Memory: emergencyCompress()
        """
        if len(lines) <= self.MIN_KEEP_EMERGENCY * 5:
            return lines
        
        keep_count = min(len(lines) // 5, 30)  # 保留约1/5
        if keep_count < self.MIN_KEEP_EMERGENCY * 5:
            keep_count = self.MIN_KEEP_EMERGENCY * 5
        
        kept = lines[-keep_count:]
        kept.insert(0, (
            "[EMERGENCY COMPRESSION ACTIVATED] "
            f"Only last {keep_count} lines preserved. "
            f"({len(lines) - keep_count} lines deleted)"
        ))
        return kept
    
    def get_status(self, current_text: str) -> dict:
        """返回压缩状态报告（不执行压缩）"""
        tokens = self._estimate_tokens(current_text)
        ratio = tokens / self.context_window if self.context_window > 0 else 0
        
        level = "none"
        if ratio >= self.EMERGENCY_RATIO:
            level = "emergency"
        elif ratio >= self.AGGRESSIVE_RATIO:
            level = "aggressive"
        elif ratio >= self.MILD_RATIO:
            level = "mild"
        
        return {
            "current_tokens": tokens,
            "context_window": self.context_window,
            "usage_ratio": round(ratio * 100, 1),
            "recommended_level": level,
        }


# ====================== CLI ======================

if __name__ == "__main__":
    import sys
    
    ec = EmergencyCompressor()
    
    if len(sys.argv) > 1 and sys.argv[1] == "status":
        text = sys.stdin.read() if not sys.stdin.isatty() else ""
        if text:
            status = ec.get_status(text)
            print(f"Usage: {status['usage_ratio']}% ({status['current_tokens']}/{status['context_window']})")
            print(f"Level: {status['recommended_level']}")
        else:
            print("Usage: echo 'text' | python3 emergency_compressor.py status")
    else:
        text = sys.stdin.read() if not sys.stdin.isatty() else ""
        if text:
            result = ec.compress(text)
            print(f"Original: {result['original_tokens']}t → Compressed: {result['compressed_tokens']}t")
            print(f"Saved: {result['saved_tokens']}t ({result['saved_percent']}%)")
            print(f"Level: {result['level']}")
        else:
            print("Usage: echo 'text' | python3 emergency_compressor.py")
            print("   or: echo 'text' | python3 emergency_compressor.py status")
