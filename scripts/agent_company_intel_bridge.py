#!/usr/bin/env python3
"""
agent_company_intel_bridge.py - 情报桥接: 将最新的高价值情报投递到Agent Company
每天8:30/20:30自动执行,由cron触发
"""
import json, os, sqlite3
from datetime import datetime

DB_PATH = "/home/administrator/.hermes/intelligence.db"
OUTPUT_DIR = "/mnt/d/Hermes/daily_report"
os.makedirs(OUTPUT_DIR, exist_ok=True)

def get_fresh_intel(hours=12, limit=50):
    """获取最近hours小时内的高价值情报"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("""
        SELECT id, title, content, platform, importance_score, value_level, url, category, tags
        FROM cleaned_intelligence
        WHERE collected_at >= datetime('now', ? || ' hours')
        AND value_level >= 3
        ORDER BY importance_score DESC
        LIMIT ?
    """, (f"-{hours}", limit))
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows

def build_report(intel_items):
    """构建投递给Agent Company的情报报告"""
    now = datetime.now().strftime("%Y-%m-%d_%H%M")
    
    # 按平台分类统计
    platforms = {}
    for item in intel_items:
        plat = item.get("platform", "未知")
        if plat not in platforms:
            platforms[plat] = 0
        platforms[plat] += 1
    
    report = {
        "timestamp": datetime.now().isoformat(),
        "total_items": len(intel_items),
        "platforms": platforms,
        "platform_count": len(platforms),
        "items": [
            {
                "title": item["title"],
                "platform": item["platform"],
                "score": round(item.get("importance_score", 0), 1),
                "url": item.get("url", ""),
                "category": item.get("category", ""),
                "tags": item.get("tags", "")
            }
            for item in intel_items[:30]
        ],
        "summary": {
            "top_platform": max(platforms, key=platforms.get) if platforms else "无",
            "hot_topics": [item["title"] for item in intel_items[:5]]
        }
    }
    
    # 保存
    path = os.path.join(OUTPUT_DIR, f"intel_bridge_{now}.json")
    with open(path, "w") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    
    return path, report

if __name__ == "__main__":
    print("🔄 Agent Company 情报桥接启动...")
    intel = get_fresh_intel(hours=12, limit=50)
    print(f"   获取到 {len(intel)} 条高价值情报")
    
    path, report = build_report(intel)
    print(f"   报告已保存: {path}")
    print(f"   覆盖 {report['platform_count']} 个平台")
    print(f"   最热平台: {report['summary']['top_platform']}")
    print(f"   热门话题: {', '.join(report['summary']['hot_topics'])}")
    print("✅ 情报桥接完成")
