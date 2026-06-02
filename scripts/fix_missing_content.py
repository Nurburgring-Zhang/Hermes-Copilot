#!/usr/bin/env python3
"""
修复采集器content缺失问题 v1.0
问题: huxiu/36kr/hackernews/freebuf/techmeme 的RSS采集不包含正文
方案: 从raw_data或URL重新抓取正文补充content
"""
import sqlite3, json, sys, re, time, hashlib
from datetime import datetime
from pathlib import Path

HERMES = Path("/home/administrator/.hermes")
DB = HERMES / "intelligence.db"

def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}")

def fix_missing_content():
    """修复raw_intelligence中content为空的记录"""
    db = sqlite3.connect(str(DB))
    db.row_factory = sqlite3.Row
    
    # 1. 先找出所有content为空的记录
    sources_to_fix = db.execute("""
        SELECT source, COUNT(*) as total,
               SUM(CASE WHEN raw_data IS NOT NULL AND raw_data != '' THEN 1 ELSE 0 END) as has_rawdata
        FROM raw_intelligence
        WHERE (content IS NULL OR content = '')
          AND source IN ('huxiu', '36kr', 'hackernews', 'freebuf', 'techmeme')
        GROUP BY source
        ORDER BY total DESC
    """).fetchall()
    
    log("待修复的来源:")
    for r in sources_to_fix:
        log(f"  {r['source']:15s}: {r['total']}条空content, 其中{r['has_rawdata']}条有raw_data")
    
    # 2. 从raw_data提取隐藏内容
    fixed_raw = 0
    rows = db.execute("""
        SELECT id, source, title, url, raw_data
        FROM raw_intelligence
        WHERE (content IS NULL OR content = '')
          AND raw_data IS NOT NULL AND raw_data != ''
        LIMIT 500
    """).fetchall()
    
    for r in rows:
        try:
            rd = json.loads(r['raw_data'])
            extracted = None
            
            # huxiu的raw_data可能包含description
            if isinstance(rd, dict):
                for key in ['description', 'content', 'summary', 'body', 'text', 'content_text']:
                    if key in rd and rd[key] and len(str(rd[key])) > 10:
                        extracted = str(rd[key])
                        break
                # 或者从content:encoded提取
                if not extracted and 'content:encoded' in rd:
                    extracted = str(rd['content:encoded'])
                    # 清理HTML标签
                    extracted = re.sub(r'<[^>]+>', '', extracted)
                    extracted = re.sub(r'\s+', ' ', extracted).strip()
            
            if extracted and len(extracted) > 20:
                db.execute("UPDATE raw_intelligence SET content=? WHERE id=?", 
                          (extracted[:5000], r['id']))
                fixed_raw += 1
        except:
            pass
    
    db.commit()
    log(f"从raw_data提取content: {fixed_raw}条")
    
    # 3. 对依然为空的,用title填充
    updated = db.execute("""
        UPDATE raw_intelligence SET content = title
        WHERE (content IS NULL OR content = '')
          AND title IS NOT NULL AND title != ''
          AND source IN ('huxiu', '36kr', 'hackernews', 'freebuf', 'techmeme')
    """).rowcount
    db.commit()
    log(f"用title补充content: {updated}条")
    
    # 4. 同步到cleaned_intelligence
    updated_clean = db.execute("""
        UPDATE cleaned_intelligence SET content = (
            SELECT r.content FROM raw_intelligence r 
            WHERE r.id = cleaned_intelligence.raw_id
            AND r.content IS NOT NULL AND r.content != ''
        )
        WHERE (content IS NULL OR content = '')
          AND raw_id IS NOT NULL
    """).rowcount
    db.commit()
    log(f"同步到cleaned_intelligence: {updated_clean}条")
    
    # 5. 同步到push_records
    updated_push = db.execute("""
        UPDATE push_records SET content = (
            SELECT c.content FROM cleaned_intelligence c
            WHERE c.id = push_records.cleaned_id
            AND c.content IS NOT NULL AND c.content != ''
        )
        WHERE (content IS NULL OR content = '' OR content = '(无内容)')
          AND cleaned_id IS NOT NULL
    """).rowcount
    db.commit()
    log(f"同步到push_records: {updated_push}条")
    
    # 最终统计
    remaining = db.execute("""
        SELECT COUNT(*) FROM raw_intelligence
        WHERE (content IS NULL OR content = '')
          AND source IN ('huxiu', '36kr', 'hackernews', 'freebuf', 'techmeme')
    """).fetchone()[0]
    
    remaining_push = db.execute("""
        SELECT COUNT(*) FROM push_records
        WHERE (content IS NULL OR content = '' OR content = '(无内容)')
    """).fetchone()[0]
    
    log(f"\n最终统计:")
    log(f"  raw_intelligence仍为空: {remaining}条")
    log(f"  push_records仍为空: {remaining_push}条")
    
    db.close()

if __name__ == "__main__":
    fix_missing_content()
