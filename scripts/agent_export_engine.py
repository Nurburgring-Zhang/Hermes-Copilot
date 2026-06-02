#!/usr/bin/env python3
"""
Agent Export — 情报驱动型 AI 分析报告引擎
===========================================
核心:不是文件搬运,而是真正的情报分析

功能:
1. 从 cleaned_intelligence 读取高价值数据
2. AI聚类分析:识别当日热点主题
3. 趋势判断:哪些话题在升温/降温
4. 机会发现:从数据中提取商业/技术机会
5. 产出报告:图文兼备,可直接用于微信推送

数据流:
  intelligence.db → 聚类分析 → AI写作 → 多格式报告

产出目录:/mnt/d/Hermes/exports/ + /mnt/d/Hermes/daily_report/
"""

import json, os, sys, sqlite3, re, urllib.request
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from collections import Counter

# ==================== 配置 ====================
HERMES_ROOT = Path("/mnt/d/Hermes")
DB_PATH = Path("/home/administrator/.hermes") / "intelligence.db"
SCRIPTS = Path("/home/administrator/.hermes") / "scripts"

# 确保目录存在
for d in ["exports", "daily_report"]:
    (HERMES_ROOT / d).mkdir(parents=True, exist_ok=True)

# ==================== 数据读取 ====================
def get_intel_data(hours: int = 48, limit: int = 300) -> Dict:
    """读取多维情报数据"""
    try:
        db = sqlite3.connect(str(DB_PATH), timeout=10)
        cur = db.cursor()
        
        # 1. 高价值情报(按评分排序,去重)
        cur.execute(f"""
            SELECT title, content, url, platform, importance_score, 
                   personal_match_score, value_level, is_ai_related,
                   category, language, source, collected_at, cleaned_at
            FROM cleaned_intelligence
            WHERE cleaned_at >= datetime('now', '-{hours} hours')
              AND importance_score >= 0.5
            ORDER BY importance_score DESC, personal_match_score DESC
            LIMIT {limit * 3}
        """)
        seen_titles = set()
        high_value = []
        for r in cur.fetchall():
            title = r[0]
            if title not in seen_titles:
                seen_titles.add(title)
                high_value.append({
                    "title": title, "content": (r[1] or "")[:500], "url": r[2],
                    "platform": r[3], "importance": r[4], "personal_match": r[5],
                    "value_level": r[6], "is_ai": r[7], "category": r[8],
                    "language": r[9], "source": r[10], "time": r[12]
                })
        
        # 2. 平台分布统计
        cur.execute(f"""
            SELECT platform, COUNT(*) as cnt, AVG(importance_score) as avg_score
            FROM cleaned_intelligence
            WHERE cleaned_at >= datetime('now', '-{hours} hours')
            GROUP BY platform
            ORDER BY cnt DESC
        """)
        platform_stats = [{"platform": r[0], "count": r[1], "avg_score": round(r[2], 2)} 
                          for r in cur.fetchall()]
        
        # 3. 类别分布
        cur.execute(f"""
            SELECT category, COUNT(*) as cnt
            FROM cleaned_intelligence
            WHERE cleaned_at >= datetime('now', '-{hours} hours')
              AND category IS NOT NULL
            GROUP BY category
            ORDER BY cnt DESC
        """)
        category_stats = [{"category": r[0], "count": r[1]} for r in cur.fetchall()]
        
        # 4. AI相关数据占比
        cur.execute(f"""
            SELECT 
                SUM(CASE WHEN is_ai_related = 1 THEN 1 ELSE 0 END) as ai_count,
                COUNT(*) as total
            FROM cleaned_intelligence
            WHERE cleaned_at >= datetime('now', '-{hours} hours')
        """)
        ai_row = cur.fetchone()
        ai_ratio = round(ai_row[0] / ai_row[1] * 100, 1) if ai_row[1] > 0 else 0
        
        # 5. 中文占比
        cur.execute(f"""
            SELECT language, COUNT(*) as cnt
            FROM cleaned_intelligence
            WHERE cleaned_at >= datetime('now', '-{hours} hours')
            GROUP BY language
        """)
        lang_stats = {r[0]: r[1] for r in cur.fetchall()}
        total_lang = sum(lang_stats.values())
        zh_ratio = round(lang_stats.get('zh', 0) / total_lang * 100, 1) if total_lang > 0 else 0
        
        db.close()
        
        return {
            "high_value": high_value,
            "platform_stats": platform_stats,
            "category_stats": category_stats,
            "ai_ratio": ai_ratio,
            "zh_ratio": zh_ratio,
            "total_items": len(high_value)
        }
    except Exception as e:
        print(f"[AGENT EXPORT] 数据读取失败: {e}")
        return {"high_value": [], "platform_stats": [], "category_stats": [], 
                "ai_ratio": 0, "zh_ratio": 0, "total_items": 0}


# ==================== 过滤规则 ====================
# 泛社会新闻/低俗/刷榜类过滤器 — 直接降低这些内容的排序权重
SOCIAL_NOISE_TITLE_PATTERNS = [
    # 恶性社会事件
    "砸死", "撞死", "撞伤", "惨案", "悲剧", "自杀", "跳楼", "坠楼",
    "被拘", "传唤", "被捕", "刑拘", "判刑", "死刑",
    "失联", "失踪", "遇害", "身亡", "猝死", "遗体",
    # 低俗/骗局
    "约炮", "裸聊", "色情", "赌博", "赌场", "嫖娼", "卖淫",
    "被骗", "诈骗", "套路", "刷单", "杀猪盘",
    # 纯社会热榜关键词(无科技价值的猎奇内容)
    "靖国神社", "打赏主播", "黄河淤泥", "冥界", "灵异",
    "出轨", "小三", "婚外情", "婆媳", "拆迁", "上访",
    # 追星/纯娱乐(无科技价值)
    "TF家族", "演唱会", "吃播", "搞笑", "综艺", "爱豆", "偶像练习生",
    # 伪科学/养生
    "震惊", "紧急通知", "速看", "删前", "转疯",
]
# 科技/行业相关关键词 — 用于判定是否"有情报价值"的标题
TECH_INDUSTRY_KEYWORDS = [
    # AI/大模型
    "ai", "gpt", "chatgpt", "openai", "claude", "anthropic", "gemini",
    "deepseek", "大模型", "llm", "agi", "agent", "rag", "fine-tune",
    "微调", "推理", "训练", "模型", "多模态", "sora", "diffusion",
    "qwen", "kimi", "智谱", "百川", "文心", "通义", "讯飞星火",
    # 芯片/算力
    "芯片", "gpu", "nvidia", "amd", "intel", "算力", "cpu",
    "risc-v", "arm", "半导体", "制程", "光刻",
    # 具身智能/机器人
    "人形机器人", "具身智能", "宇树", "特斯拉机器人", "擎天柱",
    "机器狗", "仿生", "机器人", "半马", "马拉松",  # 人形机器人半马
    # 消费电子
    "手机", "iphone", "华为", "小米", "oppo", "vivo", "三星",
    "折叠屏", "旗舰", "发布会", "数码", "消费电子",
    # 新能源汽车
    "新能源汽车", "电车", "比亚迪", "特斯拉", "蔚来", "小鹏",
    "理想", "问界", "自动驾驶", "智能驾驶", "电池", "固态电池",
    # 开源/开发者
    "开源", "github", "gitlab", "python", "rust", "typescript",
    "docker", "kubernetes", "linux", "框架", "api", "开发",
    # 军事/国际(高价值)
    "军事", "战争", "中美", "台海", "南海", "北约", "航母",
    "战斗机", "无人机", "制裁", "地缘",
    # 航天
    "spacex", "nasa", "嫦娥", "天宫", "火星", "卫星", "火箭", "航天",
    # 通用科技
    "科技", "创新", "突破", "发布", "首发", "评测", "测评",
]


def filter_tech_relevant(items: List[Dict]) -> List[Dict]:
    """
    对items列表进行科技相关度过滤和重排序。
    排除明确的泛社会新闻,对缺少tech关键词的top_individual降权。
    """
    filtered = []
    for item in items:
        title = item.get("title", "")
        content = item.get("content", "")
        platform = item.get("platform", "")
        text = f"{title} {content}".lower()
        
        # 规则1: 标题含泛社会新闻模式 → 直接标记为低价值
        is_social_noise = False
        for p in SOCIAL_NOISE_TITLE_PATTERNS:
            if p in title:
                is_social_noise = True
                break
        
        if is_social_noise:
            # 不是完全丢弃,但权重降到极低
            item["_is_social_noise"] = True
            filtered.append(item)
            continue
        
        # 规则2: 检查是否含任何科技/行业关键词
        has_tech_kw = False
        for kw in TECH_INDUSTRY_KEYWORDS:
            if kw.lower() in text:
                has_tech_kw = True
                break
        
        # 规则3: B站纯娱乐视频 — 标题含娱乐关键词但无科技关键词
        if "bilibili" in platform or "b站" in platform:
            entertainment_kw = ["tf家族", "演唱会", "吃播", "搞笑", "挑战",
                                "娱乐", "综艺", "爱豆", "偶像", "vlog", "日常"]
            has_entertainment_kw = any(k in text for k in entertainment_kw)
            if has_entertainment_kw and not has_tech_kw:
                item["_is_social_noise"] = True
                filtered.append(item)
                continue
        
        item["_has_tech_kw"] = has_tech_kw
        # 规则4: 头条hot_board纯社会新闻 — 无tech关键词时降权
        if "toutiao" in platform and not has_tech_kw:
            item["_is_low_value_social"] = True
        filtered.append(item)
    
    return filtered


# ==================== 分析引擎 ====================
def analyze_trends(data: Dict) -> Dict:
    """
    分析情报趋势:主题聚类,热度判断,机会识别
    使用关键词匹配+频次分析(后续可升级为语义聚类)
    """
    items = data.get("high_value", [])
    
    # 先过滤泛社会噪音
    items = filter_tech_relevant(items)
    
    # 主题关键词分类
    TOPIC_KEYWORDS = {
        "AI/大模型": ["gpt", "chatgpt", "openai", "claude", "anthropic", "gemini", 
                     "deepseek", "大模型", "llm", "agi", "multi-agent", "agent",
                     "rag", "fine-tune", "微调", "推理", "训练", "模型"],
        "AI编程": ["cursor", "copilot", "codex", "claude code", "AI编程", "代码生成"],
        "芯片/算力": ["芯片", "gpu", "nvidia", "amd", "intel", "算力", "cpu", 
                     "risc-v", "arm", "制程"],
        "手机/消费电子": ["手机", "iphone", "华为", "小米", "oppo", "vivo", "三星",
                        "折叠屏", "旗舰", "发布会"],
        "新能源汽车": ["新能源汽车", "电车", "比亚迪", "特斯拉", "蔚来", "小鹏",
                      "理想", "问界", "自动驾驶", "智能驾驶", "电池"],
        "军事/国际": ["军事", "战争", "中美", "台海", "南海", "北约", "俄乌",
                     "航母", "战斗机", "无人机", "制裁"],
        "航天/太空": ["spacex", "nasa", "嫦娥", "天宫", "火星", "卫星", "火箭",
                     "航天", "太空"],
        "开源/开发者": ["开源", "github", "gitlab", "python", "rust", "typescript",
                       "docker", "kubernetes", "linux", "框架", "api"],
        "体育/格斗": ["ufc", "mma", "格斗", "拳击", "nba", "足球", "马拉松", "奥运"],
        "人形机器人": ["人形机器人", "具身智能", "宇树", "特斯拉机器人", "擎天柱"]
    }
    
    topic_counts = Counter()
    topic_items = {k: [] for k in TOPIC_KEYWORDS}
    
    for item in items:
        text = f"{item.get('title','')} {item.get('content','')}".lower()
        for topic, kws in TOPIC_KEYWORDS.items():
            if any(kw in text for kw in kws):
                topic_counts[topic] += 1
                if len(topic_items[topic]) < 5:
                    topic_items[topic].append(item)
    
    # 识别热点(高频主题)
    hot_topics = topic_counts.most_common(10)
    
    # 识别最活跃的平台
    top_platforms = data.get("platform_stats", [])[:8]
    
    # 识别高价值单条(使用增强过滤:社会噪音降权到0.1,头条无科技内容降权)
    def enhanced_score(item):
        base = item.get("importance", 0) * 0.6 + (item.get("personal_match", 0) or 0) * 0.4
        # 社会噪音直接打到0.1以下
        if item.get("_is_social_noise"):
            return base * 0.05
        # 头条低价值社会新闻大幅降权
        if item.get("_is_low_value_social"):
            return base * 0.3
        # 有tech关键词的加乘
        if item.get("_has_tech_kw"):
            return base * 1.2
        return base
    
    top_individual = sorted(items, key=enhanced_score, reverse=True)[:20]
    
    return {
        "hot_topics": [{"topic": t, "count": c} for t, c in hot_topics],
        "topic_items": {k: v for k, v in topic_items.items() if v},
        "top_platforms": top_platforms,
        "top_individual": top_individual,
        "total_analyzed": len(items),
        "ai_content_ratio": data.get("ai_ratio", 0),
        "zh_content_ratio": data.get("zh_ratio", 0)
    }


# ==================== 报告生成 ====================
def generate_report(trends: Dict, data: Dict) -> Dict:
    """生成多格式报告(JSON + Markdown)"""
    
    report = {
        "report_id": f"export-{datetime.now().strftime('%Y%m%d-%H%M%S')}",
        "generated_at": datetime.now().isoformat(),
        "data_period": "过去48小时",
        "total_data": data.get("total_items", 0),
        "platforms": data.get("platform_stats", []),
        "categories": data.get("category_stats", []),
        "hot_topics": trends.get("hot_topics", []),
        "top_articles": [{
            "rank": i+1,
            "title": a.get("title",""),
            "platform": a.get("platform",""),
            "url": a.get("url",""),
            "importance": a.get("importance", 0),
            "category": a.get("category", "")
        } for i, a in enumerate(trends.get("top_individual", [])[:15])],
        "ai_ratio": data.get("ai_ratio", 0),
        "zh_ratio": data.get("zh_ratio", 0),
        "focus_topics": [],  # 由下面计算填充
        "summary": ""
    }
    
    # ── 计算 focus_topics(用户关注领域的深度分析)──
    all_items = data.get("high_value", [])
    # 经过filter_tech_relevant过滤后的items
    filtered_items = filter_tech_relevant(all_items)
    
    FOCUS_TOPIC_CONFIG = {
        "AI/大模型": {
            "keywords": ["gpt", "chatgpt", "openai", "claude", "anthropic", "gemini", "deepseek",
                         "大模型", "llm", "agi", "agent", "rag", "fine-tune", "微调", "推理", "模型",
                         "qwen", "kimi", "智谱", "多模态", "sora", "diffusion"],
            "icon": "🤖"
        },
        "具身智能/机器人": {
            "keywords": ["人形机器人", "具身智能", "宇树", "特斯拉机器人", "擎天柱",
                         "机器狗", "仿生", "机器人", "半马", "马拉松"],
            "icon": "🦾"
        },
        "芯片/消费电子": {
            "keywords": ["芯片", "gpu", "nvidia", "amd", "intel", "算力", "cpu",
                         "手机", "iphone", "华为", "小米", "oppo", "vivo", "三星",
                         "折叠屏", "旗舰", "半导体", "消费电子"],
            "icon": "📱"
        },
        "新能源汽车": {
            "keywords": ["新能源汽车", "电车", "比亚迪", "特斯拉", "蔚来", "小鹏",
                         "理想", "问界", "自动驾驶", "智能驾驶", "电池", "固态电池"],
            "icon": "🚗"
        },
        "开源/开发者生态": {
            "keywords": ["开源", "github", "gitlab", "python", "rust", "typescript",
                         "docker", "kubernetes", "linux", "框架", "api", "开发",
                         "程序员", "编程", "代码"],
            "icon": "💻"
        },
        "军事/国际": {
            "keywords": ["军事", "战争", "中美", "台海", "南海", "北约", "航母",
                         "战斗机", "无人机", "制裁", "地缘", "spacex", "nasa", "航天"],
            "icon": "🌍"
        }
    }
    
    for topic_name, config in FOCUS_TOPIC_CONFIG.items():
        topic_kws = config["keywords"]
        matched = []
        for item in filtered_items:
            text = f"{item.get('title','')} {item.get('content','')}".lower()
            if any(kw.lower() in text for kw in topic_kws):
                # 排除社会噪音
                if not item.get("_is_social_noise"):
                    score = item.get("importance", 0) * 0.7 + (item.get("personal_match", 0) or 0) * 0.3
                    matched.append({
                        "title": item.get("title",""),
                        "platform": item.get("platform",""),
                        "url": item.get("url",""),
                        "score": round(score, 1)
                    })
        matched.sort(key=lambda x: x["score"], reverse=True)
        if matched:
            report["focus_topics"].append({
                "topic": topic_name,
                "icon": config["icon"],
                "count": len(matched),
                "top_items": matched[:5]
            })
    
    # 生成文本摘要
    hot_topic_str = ",".join([f"{t['topic']}({t['count']}条)" 
                                for t in trends.get("hot_topics", [])[:5]])
    
    # 聚焦领域摘要
    focus_summary_parts = []
    for ft in report.get("focus_topics", [])[:4]:
        top_titles = [item["title"][:30] for item in ft["top_items"][:3]]
        focus_summary_parts.append(
            f"{ft['icon']} {ft['topic']}: {ft['count']}条 | {', '.join(top_titles)}"
        )
    focus_str = "\n".join(focus_summary_parts)
    
    summary = (
        f"📊 情报分析报告 | {date.today().isoformat()}\n\n"
        f"数据概览:共分析 {data.get('total_items', 0)} 条情报,"
        f"覆盖 {len(data.get('platform_stats', []))} 个平台。\n"
        f"AI相关占比 {data.get('ai_ratio', 0)}%,中文内容 {data.get('zh_ratio', 0)}%。\n\n"
        f"🔥 热点主题TOP5:{hot_topic_str}\n\n"
        f"📡 最活跃平台:{','.join([p['platform'] for p in data.get('platform_stats', [])[:5]])}\n\n"
        f"🎯 聚焦领域 TOP 情报:\n{focus_str}\n"
    )
    report["summary"] = summary
    
    return report


# ==================== 文件输出 ====================
def export_report(report: Dict):
    """输出报告到文件系统"""
    ts = datetime.now().strftime('%Y%m%d_%H%M')
    
    # JSON格式(完整数据,供下游消费)
    json_file = HERMES_ROOT / "exports" / f"export_{ts}.json"
    json_file.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    
    # Markdown格式(可读性好,可直接推送)
    md_content = f"""# 📊 情报分析报告
**生成时间**: {report['generated_at'][:19]} | **数据时段**: {report['data_period']}

---

## 数据概览
- 分析数据量: **{report['total_data']}** 条
- 覆盖平台: **{len(report['platforms'])}** 个
- AI内容占比: **{report['ai_ratio']}%**
- 中文内容占比: **{report['zh_ratio']}%**

## 平台活跃度
| 平台 | 数量 | 平均评分 |
|------|------|---------|
"""
    for p in report['platforms'][:8]:
        md_content += f"| {p['platform']} | {p['count']}条 | {p.get('avg_score', '-')} |\n"
    
    md_content += f"""
## 🔥 热点话题
| 话题 | 热度 |
|------|------|
"""
    for t in report['hot_topics'][:10]:
        md_content += f"| {t['topic']} | {t['count']}条 |\n"
    
    md_content += f"""
## 🎯 聚焦领域深度分析
"""
    for ft in report.get("focus_topics", []):
        md_content += f"### {ft['icon']} {ft['topic']}({ft['count']}条相关情报)\n\n"
        md_content += "| 标题 | 平台 | 评分 |\n"
        md_content += "|------|------|------|\n"
        for item in ft["top_items"][:5]:
            md_content += f"| {item['title'][:50]} | {item['platform']} | {item['score']} |\n"
        md_content += "\n"
    
    md_content += f"""
## 📌 Top 15 高价值情报
| 排名 | 标题 | 平台 | 评分 |
|------|------|------|------|
"""
    for a in report['top_articles'][:15]:
        md_content += f"| {a['rank']} | {a['title'][:50]} | {a['platform']} | {a['importance']} |\n"
    
    md_file = HERMES_ROOT / "exports" / f"export_{ts}.md"
    md_file.write_text(md_content, encoding='utf-8')
    
    # 同时保存最新版本
    latest_md = HERMES_ROOT / "exports" / "latest_export.md"
    latest_md.write_text(md_content, encoding='utf-8')
    
    print(f"[AGENT EXPORT] ✅ 报告已生成")
    print(f"  JSON: {json_file}")
    print(f"  MD:   {md_file}")
    
    return str(json_file), str(md_file)


# ==================== 主入口 ====================
def main():
    print(f"\n{'='*50}")
    print(f"🚀 Agent Export 情报分析引擎启动")
    print(f"📅 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*50}")
    
    # 1. 读取数据
    print("\n📡 读取情报数据...")
    data = get_intel_data(hours=48, limit=300)
    if not data["high_value"]:
        print("❌ 无有效数据")
        return
    
    print(f"✅ 读取 {data['total_items']} 条高价值情报,{len(data['platform_stats'])} 个平台")
    
    # 2. 趋势分析
    print("\n🔍 进行趋势分析...")
    trends = analyze_trends(data)
    
    hot_topics = trends.get("hot_topics", [])
    print(f"🔥 发现 {len(hot_topics)} 个热点主题:")
    for t in hot_topics[:5]:
        print(f"   • {t['topic']}: {t['count']}条")
    
    # 3. 生成报告
    print("\n📝 生成报告...")
    report = generate_report(trends, data)
    
    # 4. 输出
    json_file, md_file = export_report(report)
    
    print(f"\n{'='*50}")
    print(f"✅ Agent Export 完成")
    print(f"{'='*50}")

if __name__ == "__main__":
    main()
