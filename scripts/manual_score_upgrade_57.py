#!/usr/bin/env python3
"""
手动AI评分升级 — 处理57条旧格式/规则评分的积压数据
用delegate_task方式对每个item进行真正的AI理解评分
每批处理20条，分3批完成
"""
import sqlite3
import json
import sys
import os

DB_PATH = "/home/administrator/.hermes/intelligence.db"

def get_candidates():
    """获取需要AI重评的候选"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    
    # rule-only + other_format且内容好且重要度高
    cur = conn.execute("""
        SELECT id, title, content, source, url,
               ai_score_total as current_score,
               ai_score_reasoning as current_reasoning,
               importance_score
        FROM cleaned_intelligence
        WHERE 
          (ai_score_reasoning LIKE '%规则%')
          OR 
          (ai_score_reasoning NOT LIKE '%评分%'
           AND ai_score_reasoning NOT LIKE '%summary%'
           AND LENGTH(COALESCE(content,'')) > 100
           AND importance_score > 3)
        ORDER BY importance_score DESC
        LIMIT 60
    """)
    
    rows = []
    for r in cur.fetchall():
        rows.append({
            'id': r['id'],
            'title': r['title'],
            'content': (r['content'] or '')[:500],
            'source': r['source'],
            'current_score': r['current_score'],
            'reasoning_type': '规则评分' if r['current_reasoning'] and '规则' in r['current_reasoning'] else '旧格式文本',
            'importance': r['importance_score']
        })
    conn.close()
    return rows

def main():
    items = get_candidates()
    print(f"共找到 {len(items)} 条需要AI重新评分的积压数据")
    print(f"\n评分分布:")
    score_ranges = [(90,100),(80,89),(70,79),(60,69),(50,59),(40,49),(30,39),(20,29),(0,19)]
    for lo,hi in score_ranges:
        cnt = sum(1 for i in items if lo <= i['current_score'] <= hi)
        if cnt:
            print(f"  {lo:>3}-{hi}: {cnt}条")
    
    print(f"\n按来源:")
    sources = {}
    for i in items:
        s = i['source'] or 'unknown'
        sources[s] = sources.get(s, 0) + 1
    for s,c in sorted(sources.items(), key=lambda x:-x[1]):
        print(f"  {s}: {c}条")
    
    print(f"\n需要分{-(len(items)//-20)}批处理（每批20条）")
    print(f"高价值(importance>5建议优先处理): {sum(1 for i in items if i['importance'] > 5)}条")
    print(f"\n按importance排序前10:")
    for i in items[:10]:
        print(f"  ID={i['id']:>8} | score={i['current_score']:>5.0f} | imp={i['importance']:>6.1f} | {i['title'][:50]}")
    
    # 输出JSON格式给批处理
    batch1 = items[:20]
    print(f"\n\n=== 首批20条JSON（可输入到delegate_task） ===")
    print(json.dumps(batch1, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    main()
