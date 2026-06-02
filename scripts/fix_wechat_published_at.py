#!/usr/bin/env python3
"""
修复微信公众号采集器遗留数据问题
=====================================
1. 修复 published_at 字段中的 <script>document.write(timeConvert('...'))</script> 残留
2. 将时间戳转换为 ISO 格式日期

执行: python3 fix_wechat_published_at.py
"""

import re
import sqlite3
from datetime import datetime
from pathlib import Path

DB_PATH = Path("/home/administrator/.hermes") / "intelligence.db"

def parse_timestamp_from_script(date_str: str) -> str:
    """
    从 date_str 中提取时间戳并转为 ISO 格式
    
    处理格式:
    - <script>document.write(timeConvert('1604152401'))</script>
    - document.write(timeConvert('1604152401'))
    - 纯时间戳 "1604152401"
    
    Returns:
        ISO 格式日期字符串, 如果无法解析则返回原字符串
    """
    if not date_str or not isinstance(date_str, str):
        return date_str
    
    # 匹配 document.write(timeConvert('1234567890'))
    m = re.search(r"timeConvert\s*\(\s*['\"](\d+)['\"]\s*\)", date_str)
    if m:
        ts = int(m.group(1))
        try:
            dt = datetime.fromtimestamp(ts)
            return dt.strftime('%Y-%m-%dT%H:%M:%S')
        except (ValueError, OSError):
            return date_str
    
    # 匹配纯时间戳 (10位以上)
    cleaned = re.sub(r'<[^>]+>', '', date_str).strip()
    if cleaned.replace('.', '').isdigit() and len(cleaned) >= 10:
        try:
            ts = int(float(cleaned))
            dt = datetime.fromtimestamp(ts)
            return dt.strftime('%Y-%m-%dT%H:%M:%S')
        except (ValueError, OSError):
            pass
    
    return date_str


def fix_dirty_published_at(dry_run: bool = False) -> int:
    """
    修复 raw_intelligence 表中损坏的 published_at 字段
    
    Args:
        dry_run: True 则只统计不修改
        
    Returns:
        int: 修复的记录数
    """
    if not DB_PATH.exists():
        print(f"数据库不存在: {DB_PATH}")
        return 0
    
    db = sqlite3.connect(str(DB_PATH), timeout=30)
    db.row_factory = sqlite3.Row
    
    try:
        # 找到所有包含 script 或 timeConvert 的记录
        dirty_rows = db.execute(
            """SELECT id, published_at, url FROM raw_intelligence 
               WHERE published_at LIKE '%script%' 
                  OR published_at LIKE '%timeConvert%'
               ORDER BY id"""
        ).fetchall()
        
        print(f"发现 {len(dirty_rows)} 条脏数据记录")
        
        fixed_count = 0
        skip_count = 0
        
        for row in dirty_rows:
            row_id = row['id']
            old_val = row['published_at']
            new_val = parse_timestamp_from_script(old_val)
            
            if new_val == old_val:
                # 无法修复
                print(f"  [跳过 #{row_id}] 无法解析: {old_val[:80]}")
                skip_count += 1
                continue
            
            # 展示修复前后对比
            old_short = old_val[:60] + "..." if len(old_val) > 60 else old_val
            print(f"  [修复 #{row_id}] {old_short} -> {new_val}")
            
            if not dry_run:
                db.execute(
                    "UPDATE raw_intelligence SET published_at = ? WHERE id = ?",
                    (new_val, row_id)
                )
            
            fixed_count += 1
        
        if not dry_run:
            db.commit()
        
        print(f"\n统计:")
        print(f"  总脏数据: {len(dirty_rows)}")
        print(f"  已修复:   {fixed_count}")
        print(f"  跳过:     {skip_count}")
        
        if dry_run:
            print(f"\n(此为试运行模式, 未修改数据库)")
            print(f"确认修复请执行: python3 fix_wechat_published_at.py --execute")
        
        return fixed_count
    
    finally:
        db.close()


def main():
    import sys
    
    dry_run = '--execute' not in sys.argv
    
    if dry_run:
        print("=" * 60)
        print("  微信公众号采集器 - 数据修复工具")
        print("  模式: 试运行 (仅统计, 不修改)")
        print("=" * 60)
    else:
        print("=" * 60)
        print("  微信公众号采集器 - 数据修复工具")
        print("  模式: 执行修复")
        print("=" * 60)
    
    fixed = fix_dirty_published_at(dry_run)
    
    if fixed > 0 and not dry_run:
        print(f"\n✓ 成功修复 {fixed} 条脏数据!")
    elif fixed == 0 and not dry_run:
        print("\n✓ 无需要修复的数据")
    
    print("=" * 60)


if __name__ == "__main__":
    main()
