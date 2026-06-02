#!/usr/bin/env python3
"""
Hermes 需求挖掘自动引擎 v1.0
============================
从intelligence.db读取今日情报数据,做需求模式挖掘。
输出:趋势分析报告 + 需求分类 + 优先级评估
纯AI驱动,全自动执行。
"""
import sqlite3, json, time, os
from datetime import datetime
from pathlib import Path

HERMES = Path("/home/administrator/.hermes")
DB_PATH = HERMES / "intelligence.db"
OUTPUT_DIR = HERMES / "outputs" / "requirement_mining"
LOG = HERMES / "logs" / "requirement_mining.log"

def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] 🔍 {msg}"
    print(line)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")

def load_today_high_value():
    """加载最近7天高价值数据(五维精度:评分>=60或偏好匹配高)"""
    db = sqlite3.connect(str(DB_PATH))
    rows = db.execute("""
        SELECT id, title, content, platform, tags, ai_score_total,
               personal_match_score, url, published_at
        FROM cleaned_intelligence
        WHERE cleaned_at >= datetime('now', '-7 days')
          AND (ai_score_total >= 50 OR personal_match_score >= 5)
        ORDER BY ai_score_total DESC
        LIMIT 80
    """).fetchall()
    db.close()
    return [dict(zip(['id','title','content','platform','tags','ai_score_total','personal_match_score','url','published_at'], r)) for r in rows]

def analyze_trends(items):
    """分析趋势:按标签聚合+时间序列分析"""
    tag_counts = {}
    platform_counts = {}
    ai_scores = []
    
    for item in items:
        tags = (item.get('tags','') or '').split('|')
        for t in tags:
            t = t.strip()
            if t and t != 'General':
                tag_counts[t] = tag_counts.get(t, 0) + 1
        p = item.get('platform','?')
        platform_counts[p] = platform_counts.get(p, 0) + 1
        ai_scores.append(item.get('ai_score_total',0))
    
    # 趋势标签排序
    top_tags = sorted(tag_counts.items(), key=lambda x: -x[1])[:10]
    top_platforms = sorted(platform_counts.items(), key=lambda x: -x[1])[:10]
    avg_score = sum(ai_scores)/len(ai_scores) if ai_scores else 0
    
    return {
        'top_tags': top_tags,
        'top_platforms': top_platforms,
        'avg_score': round(avg_score,1),
        'total_items': len(items)
    }

def classify_requirements(items, trends):
    """需求分类:按格林主人兴趣领域聚类需求"""
    requirements = {
        'AI_ML': [],
        'Dev_Tech': [],
        'Consumer_Electronics': [],
        'EV_Auto': [],
        'Fighting_Sports': [],
        'Military_Geo': [],
        'Art_Design': [],
        'Finance_Economy': [],
        'Other': []
    }
    
    kw_map = {
        'AI_ML': ['ai','llm','gpt','大模型','agent','rag','openai','claude','deepseek','人工智能','机器学习'],
        'Dev_Tech': ['rust','typescript','github','开源','代码','编程','开发者','架构','框架','api'],
        'Consumer_Electronics': ['手机','iphone','小米','华为','芯片','半导体','数码','电脑','笔记本'],
        'EV_Auto': ['新能源','电动汽车','特斯拉','比亚迪','自动驾驶','充电','电池'],
        'Fighting_Sports': ['ufc','mma','拳击','格斗','武术','搏击'],
        'Military_Geo': ['军事','国防','战争','国际','中美','俄罗斯','北约','外交'],
        'Art_Design': ['摄影','写真','美女','时尚','设计','艺术','cos'],
        'Finance_Economy': ['投资','股市','经济','金融','融资','收购','市场']
    }
    
    for item in items:
        text = (item.get('title','') + ' ' + (item.get('content','') or '')[:200]).lower()
        assigned = False
        for cat, kws in kw_map.items():
            if any(k in text for k in kws):
                requirements[cat].append(item)
                assigned = True
                break
        if not assigned:
            requirements['Other'].append(item)
    
    # 生成需求摘要
    summary = {}
    for cat, items_list in requirements.items():
        if items_list:
            summary[cat] = {
                'count': len(items_list),
                'avg_score': round(sum(i.get('ai_score_total',0) for i in items_list)/len(items_list), 1),
                'top_items': [i['title'][:60] for i in sorted(items_list, key=lambda x:-x.get('ai_score_total',0))[:3]]
            }
    
    return summary

def generate_report(trends, requirements):
    """生成结构化需求报告"""
    now = datetime.now().strftime('%Y-%m-%d-%H%M%S')
    
    report = {
        'generated_at': now,
        'data_date': datetime.now().strftime('%Y-%m-%d'),
        'trends': {
            'total_items': trends['total_items'],
            'avg_ai_score': trends['avg_score'],
            'hot_tags': [{'tag':t, 'count':c} for t,c in trends['top_tags']],
            'active_platforms': [{'platform':p, 'count':c} for p,c in trends['top_platforms']]
        },
        'requirements_by_category': {},
        'priority_recommendations': []
    }
    
    for cat, info in sorted(requirements.items(), key=lambda x: -x[1].get('count',0)):
        if info:
            report['requirements_by_category'][cat] = info
            # 按数量+平均分计算优先级
            priority = 'HIGH' if info['count'] >= 5 and info['avg_score'] >= 40 else 'MEDIUM' if info['count'] >= 2 else 'LOW'
            report['priority_recommendations'].append({
                'category': cat,
                'priority': priority,
                'count': info['count'],
                'avg_score': info['avg_score'],
                'reason': f"{info['count']}条相关情报,平均AI评分{info['avg_score']}"
            })
    
    # 输出
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    report_path = OUTPUT_DIR / f"requirements_{now}.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    
    log(f"📄 需求报告已生成: {report_path}")
    log(f"📊 共{trends['total_items']}条高价值情报,{len(report['requirements_by_category'])}个需求类别")
    for rec in report['priority_recommendations']:
        log(f"  {'🔴' if rec['priority']=='HIGH' else '🟡'} [{rec['priority']}] {rec['category']}: {rec['reason']}")
    
    return report

def main():
    log("🔍 需求挖掘引擎启动")
    
    items = load_today_high_value()
    if not items:
        log("⚠️ 今日无高价值数据")
        return
    
    log(f"📊 加载{len(items)}条高价值情报")
    
    trends = analyze_trends(items)
    log(f"📈 趋势: 热门标签={trends['top_tags'][:3]}, 活跃平台={trends['top_platforms'][:3]}")
    
    requirements = classify_requirements(items, trends)
    generate_report(trends, requirements)
    
    log("✅ 需求挖掘完成")

if __name__ == "__main__":
    main()
