#!/usr/bin/env python3
"""
Agent Export - 从热点数据生成产出报告
========================================
将情报数据导出为 multi-agent 系统可消费的格式:
1. market_intelligence/latest_report.json - 市场情报报告
2. strategy/daily_briefing.json - 战略简报
3. reports/{date}_report.json - 每日报告归档
"""
import json
from datetime import datetime
from pathlib import Path

HERMES = Path("/home/administrator/.hermes")
WS = HERMES / "workspace" / "workspace"
DELIVERY = HERMES / "agent_delivery"

def main():
    # 读取最新热点数据
    geo_file = WS / "hot_topics_daily" / "latest_geo.json"
    if not geo_file.exists():
        print(f"[AGENT EXPORT] 数据文件不存在: {geo_file}")
        return
    
    data = json.loads(geo_file.read_text(encoding='utf-8'))
    
    if not data:
        print("[AGENT EXPORT] 无数据")
        return
    
    # 按类别分组
    ai_items = [d for d in data if d.get('category') in ('AI', 'AI_LLM') or (d.get('score') or 0) > 1.0]
    ai_items.sort(key=lambda x: x.get('score', 0) or 0, reverse=True)
    top_stories = ai_items[:15]
    
    sources = set(d.get('source', '') or d.get('pub', '') for d in data)
    
    report = {
        'timestamp': datetime.now().isoformat(),
        'type': 'daily_intelligence_report',
        'total_data': len(data),
        'ai_insights': len(ai_items),
        'source_count': len(sources),
        'top_stories': [{
            'title': d.get('title', ''),
            'source': d.get('source', '') or d.get('pub', ''),
            'score': d.get('score', 0),
            'url': d.get('url', ''),
            'category': d.get('category', 'General')
        } for d in top_stories],
        'summary': f"Latest intelligence from {len(data)} items across {len(sources)} sources",
        'generate_time': datetime.now().strftime('%Y-%m-%d %H:%M')
    }
    
    # 创建输出目录
    dirs = [
        WS / "agents_company" / "market_intelligence",
        WS / "agents_company" / "strategy",
        WS / "agents_company" / "reports",
        DELIVERY / "reports",
    ]
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)
    
    # 写入3个报告文件
    (WS / "agents_company" / "market_intelligence" / "latest_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    (WS / "agents_company" / "strategy" / "daily_briefing.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    
    date_str = datetime.now().strftime('%Y-%m-%d')
    (WS / "agents_company" / "reports" / f"{date_str}_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    
    # 同时也写到 agent_delivery
    (DELIVERY / "reports" / f"export_report_{datetime.now().strftime('%Y%m%d_%H%M')}.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    
    print(f"[AGENT EXPORT] ✅ 生成 {len(top_stories)} 条精选报告")
    print(f"[AGENT EXPORT] 已输出: ")
    print(f"  - market_intelligence/latest_report.json")
    print(f"  - strategy/daily_briefing.json")
    print(f"  - reports/{date_str}_report.json")
    print(f"  - agent_delivery/reports/export_report_*.json")
    print(f"[AGENT EXPORT] 数据来源: {len(data)}条, {len(sources)}个平台")

if __name__ == '__main__':
    main()
