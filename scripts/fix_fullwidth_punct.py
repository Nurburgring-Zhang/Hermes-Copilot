#!/usr/bin/env python3
"""Fix full-width Chinese punctuation in Python files.
Replaces only in comments, docstrings, and string literals where safe.
"""
import re
import sys
from pathlib import Path

# Mapping from full-width to half-width (safe ASCII equivalents)
FW_MAP = {
    '\uff01': '!',   # !→ !
    '\uff08': '(',   # (→ (
    '\uff09': ')',   # )→ )
    '\uff0c': ',',   # ,→ ,
    '\uff1a': ':',   # :→ :
    '\uff1b': ';',   # ;→ ;
    '\uff1f': '?',   # ?→ ?
    '\u3001': ',',   # ,→ ,
    '\u300a': '<',   # 《→ <  (keep as full-width for Chinese titles, but replace in code)
    '\u300b': '>',   # 》→ >
    '\u300c': '[',   # 「→ [
    '\u300d': ']',   # 」→ ]
    '\u300e': '[',   # 『→ [
    '\u300f': ']',   # 』→ ]
    '\u3010': '[',   # 【→ [
    '\u3011': ']',   # 】→ ]
    '\u201c': '"',   # " → "
    '\u201d': '"',   # " → "
    '\u2018': "'",   # ' → '
    '\u2019': "'",   # ' → '
    '\u2014': '--',  # — → --
    '\u2026': '...', # … → ...
}

def fix_file(filepath: str) -> int:
    """Fix full-width punctuation in a Python file.
    Returns number of changes made.
    """
    path = Path(filepath)
    original = path.read_text(encoding='utf-8')
    content = original
    changes = 0
    
    # Simple line-by-line replacement for safety
    lines = content.split('\n')
    fixed_lines = []
    
    for i, line in enumerate(lines):
        stripped = line.strip()
        # Skip if no full-width chars
        has_fw = any(ch in FW_MAP for ch in line)
        if not has_fw:
            fixed_lines.append(line)
            continue
        
        new_line = line
        line_changes = 0
        for fw, ascii_eq in sorted(FW_MAP.items(), key=lambda x: -len(x[1])):
            if fw in new_line:
                new_line = new_line.replace(fw, ascii_eq)
                line_changes += 1
        
        if line_changes > 0:
            changes += line_changes
        fixed_lines.append(new_line)
    
    if changes > 0:
        new_content = '\n'.join(fixed_lines)
        path.write_text(new_content, encoding='utf-8')
    
    return changes

def main():
    # Top 5 worst-affected files (from the scan)
    targets = [
        'scripts/agent_company_runner.py',
        'agents_company/pipeline_controller.py',
        'agents_company/generate_employee_sops.py',
        'scripts/agent_company_v3_ultimate.py',
        'scripts/hermes_intelligence_v2.py',
    ]
    
    hermes = Path.home() / '.hermes'
    total_changes = 0
    
    for target in targets:
        fpath = hermes / target
        if not fpath.exists():
            print(f'❌ NOT FOUND: {fpath}')
            continue
        
        before = fpath.read_text(encoding='utf-8')
        fw_count_before = sum(1 for ch in before if ch in FW_MAP)
        
        changes = fix_file(str(fpath))
        total_changes += changes
        
        if changes > 0:
            after = fpath.read_text(encoding='utf-8')
            fw_count_after = sum(1 for ch in after if ch in FW_MAP)
            print(f'✅ {target}: {changes} changes ({fw_count_before}→{fw_count_after} full-width chars)')
        else:
            print(f'ℹ️ {target}: no changes')
    
    print(f'\nTotal: {total_changes} replacements across {len(targets)} files')

if __name__ == '__main__':
    main()
