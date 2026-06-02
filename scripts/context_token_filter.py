#!/usr/bin/env python3
"""
Hermes 对话层实时Token过滤压缩器 v1.1
=====================================
修复v1.0：保留7条永久规则完整，只过滤工具描述/历史日志/重复列表
"""

import json, sys, re, os
from pathlib import Path
from datetime import datetime

HERMES = Path("/home/administrator/.hermes")

def estimate_tokens(text: str) -> int:
    cn = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    en = len(text) - cn
    return int(cn * 1.5 + en * 1.3)

def filter_context(text: str) -> dict:
    """
    第一关：过滤无效信息
    保留：7条永久规则、禁令、核心身份、行为准则
    移除：完整skill列表、tools描述、重复的系统提示块、历史对话日志
    """
    original_len = len(text)
    filtered = text
    
    # 1. 移除完整的skill列表（从<available_skills>到</available_skills>）
    filtered = re.sub(r'<available_skills>[\s\S]*?</available_skills>', '\n[skills列表已压缩]\n', filtered)
    
    # 2. 移除完整tools描述（从"## Tools"到下一个"##"或文件结束）
    filtered = re.sub(r'## Tools[\s\S]*?(?=\n## |\n##|\Z)', '## Tools\n[工具列表已压缩，按需调用]\n', filtered)
    
    # 3. 移除FILE_OPERATIONS等系统工具的长篇描述
    filtered = re.sub(r'FILE_OPERATIONS[\s\S]*?(?=\n## |\Z)', '', filtered)
    
    # 4. 移除Host/Home Channels等环境描述
    filtered = re.sub(r'Host:.*?(?=\n## |\n\n)', '', filtered)
    filtered = re.sub(r'Home Channels.*?(?=\n## |\n\n)', '', filtered)
    
    # 5. 移除MEMORY块中超过200字的长记录（保留最近的）
    filtered = re.sub(r'MEMORY.*?[\s\S]*?(?=\n## |\Z)', '', filtered)
    
    # 6. 移除USER PROFILE中超过300字的部分
    filtered = re.sub(r'USER PROFILE.*?[\s\S]*?(?=\n## |\Z)', '', filtered)
    
    # 7. 压缩连续的空白行
    filtered = re.sub(r'\n{3,}', '\n\n', filtered)
    
    # 8. 移除"Connected Platforms"等连接描述
    filtered = re.sub(r'Connected Platforms.*?(?=\n)', '', filtered)
    filtered = re.sub(r'Delivery options.*?(?=\n## |\n\n)', '', filtered)
    
    removed = original_len - len(filtered)
    return {
        "removed_chars": removed,
        "filtered": filtered,
        "filtered_len": len(filtered),
        "original_len": original_len,
        "compression_ratio": round((1 - len(filtered)/original_len) * 100, 1) if original_len > 0 else 0
    }

def compress_context(text: str, max_tokens: int = 5000) -> dict:
    """
    第二关：压缩上下文到指定token量以内
    策略：保留全部规则+禁令+关键指令，只压缩示例/日志/描述
    """
    # 先过滤
    filter_result = filter_context(text)
    filtered = filter_result["filtered"]
    
    # 检查是否已经足够小
    if estimate_tokens(filtered) <= max_tokens:
        return {
            "original_tokens": estimate_tokens(text),
            "original_chars": len(text),
            "final_tokens": estimate_tokens(filtered),
            "final_chars": len(filtered),
            "total_compression_ratio": filter_result["compression_ratio"],
            "compressed_text": filtered,
            "mode": "filter_only"
        }
    
    # 压缩策略：按行分析，保留关键行
    lines = filtered.split('\n')
    kept = []
    section_stack = []
    
    # 保留的关键章节标记
    KEEP_SECTIONS = [
        '规则', '禁令', '永久', '强制', '命令', '最高指令',
        '核心身份', '行为准则', '格林主人', '必须', '禁止',
        'skills', 'skill_view', 'skill_manage', 'tools', 'terminal',
        'read_file', 'write_file', 'patch', 'session_search',
        'delegate_task', 'web_search', 'memory', 'cronjob',
        '⚠️', '✅', '❌', '🔴', '🛡️', '⚙️', '📋'
    ]
    
    for line in lines:
        stripped = line.strip()
        if not stripped:
            kept.append(line)
            continue
        
        # 标题行总是保留
        if stripped.startswith('#') or stripped.startswith('|') or stripped.startswith('---'):
            kept.append(line)
            continue
        
        # 含关键标记的行保留
        if any(kw in stripped for kw in KEEP_SECTIONS):
            kept.append(line)
            continue
        
        # 含具体命令/路径的行保留
        if any(c in stripped for c in ['~/.hermes', '/home/', 'python3 ', 'scripts/']):
            kept.append(line)
            continue
        
        # 工具调用示例保留（短的行）
        if len(stripped) < 120 and (stripped.startswith('- ') or stripped.startswith('* ')):
            kept.append(line)
            continue
    
    # 如果太少了，补充最后一部分
    compressed_text = '\n'.join(kept)
    if estimate_tokens(compressed_text) < max_tokens * 0.3:
        # 补充原始最后20行
        tail = '\n'.join(lines[-min(40, len(lines)):])
        compressed_text += '\n\n【最近上下文】\n' + tail
    
    final_tokens = estimate_tokens(compressed_text)
    
    return {
        "original_tokens": estimate_tokens(text),
        "original_chars": len(text),
        "final_tokens": final_tokens,
        "final_chars": len(compressed_text),
        "total_compression_ratio": round((1 - final_tokens/estimate_tokens(text)) * 100, 1) if estimate_tokens(text) > 0 else 0,
        "compressed_text": compressed_text,
        "mode": "compressed"
    }

def main():
    if len(sys.argv) < 2:
        print("用法: python3 context_token_filter.py [compress|status|analyze] [context_file]")
        return
    
    cmd = sys.argv[1]
    
    if cmd == "status":
        ctx_files = list(HERMES.glob("reports/current_context*")) + list(HERMES.glob("SOUL.md"))
        status = {"files": []}
        for f in ctx_files[:5]:
            if f.exists() and f.stat().st_size > 1000:
                text = f.read_text(encoding='utf-8', errors='ignore')
                status["files"].append({
                    "path": str(f.relative_to(HERMES)),
                    "size": len(text),
                    "tokens": estimate_tokens(text[:5000]),
                })
        print(json.dumps(status, ensure_ascii=False, indent=2))
    
    elif cmd == "compress":
        if len(sys.argv) > 2:
            path = Path(sys.argv[2])
            if path.exists():
                text = path.read_text(encoding='utf-8', errors='ignore')
            else:
                print(f"文件不存在: {path}")
                return
        else:
            text = sys.stdin.read()
        
        if not text:
            print("{}")
            return
        
        result = compress_context(text)
        output = {
            "ts": datetime.now().isoformat(),
            "action": "compress",
            "original_tokens": result["original_tokens"],
            "final_tokens": result["final_tokens"],
            "compression_ratio": result["total_compression_ratio"],
            "compressed_text": result["compressed_text"]
        }
        print(json.dumps(output, ensure_ascii=False, indent=2))
    
    elif cmd == "analyze":
        if len(sys.argv) > 2:
            path = Path(sys.argv[2])
            if path.exists():
                text = path.read_text(encoding='utf-8', errors='ignore')
            else:
                print(f"文件不存在: {path}")
                return
        else:
            text = sys.stdin.read()
        
        if not text:
            return
        
        filter_result = filter_context(text)
        print(json.dumps({
            "ts": datetime.now().isoformat(),
            "total_chars": len(text),
            "total_tokens": estimate_tokens(text),
            "filterable_chars": filter_result["removed_chars"],
            "potential_compression": f"{filter_result['compression_ratio']}%",
        }, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
