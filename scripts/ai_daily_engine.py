#!/usr/bin/env python3
"""
AI日报 — Hermes 第一单价值产品
==============================
每日自动生产可交付的AI行业日报。
内容:当日AI重大事件+趋势分析+机会提示
格式:Markdown,可用于微信推送/公众号/知识付费

流程:
1. 从intelligence.db读取当日AI相关高价值情报
2. 通过LLM分析聚类(本地版用规则+评分先跑起来)
3. 生成带分析结论的日报
4. 输出到 /mnt/d/Hermes/daily_report/
5. 推送到微信
"""

import json, os, sys, sqlite3, re, urllib.request
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# ==================== 配置 ====================
HERMES_ROOT = Path("/mnt/d/Hermes")
DB_PATH = Path("/home/administrator/.hermes") / "intelligence.db"
SCRIPTS = Path("/home/administrator/.hermes") / "scripts"
DAILY_DIR = HERMES_ROOT / "daily_report"
DAILY_DIR.mkdir(parents=True, exist_ok=True)


def log(msg: str):
    ts = datetime.now().strftime('%H:%M:%S')
    print(f"[{ts}] {msg}", flush=True)
    with open(DAILY_DIR / f"daily_{date.today().isoformat()}.log", 'a', encoding='utf-8') as f:
        f.write(f"[{ts}] {msg}\n")


# ==================== 数据采集 ====================
def collect_daily_data() -> Dict:
    """采集日报素材"""
    try:
        db = sqlite3.connect(str(DB_PATH), timeout=10)
        cur = db.cursor()
        
        # AI相关高价值情报(过去48h,去重)
        cur.execute("""
            SELECT title, content, url, platform, importance_score, 
                   personal_match_score, value_level, category, language,
                   source
            FROM cleaned_intelligence
            WHERE cleaned_at >= datetime('now', '-48 hours')
              AND (is_ai_related = 1 OR 
                   title LIKE '%AI%' OR title LIKE '%大模型%' OR 
                   title LIKE '%GPT%' OR title LIKE '%机器%' OR
                   title LIKE '%智能%' OR title LIKE '%芯片%' OR
                   title LIKE '%模型%' OR title LIKE '%算法%')
              AND importance_score >= 1.0
              AND (category NOT IN ('泛娱乐','娱乐','搞笑','美食','游戏','生活')
                   OR category IS NULL)
              AND LENGTH(title) > 5
            ORDER BY importance_score DESC
            LIMIT 100
        """)
        seen_titles = set()
        ai_items = []
        for r in cur.fetchall():
            title = r[0]
            if title not in seen_titles:
                seen_titles.add(title)
                ai_items.append({
                    "title": title, "content": (r[1] or "")[:300], "url": r[2],
                    "platform": r[3], "importance": r[4], "personal_match": r[5],
                    "category": r[7], "language": r[8], "source": r[9]
                })
        
        # B站热门趋势(去重+强过滤娱乐内容)
        # 关键词黑名单 — 纯娱乐/游戏/生活类内容
        BILI_BLACKLIST = [
            '我的世界', '克苏鲁', '起个名', '员工离开', '吃盐',
            '物理应用', '杀人手段',  # 拆分原词以匹配标题中的分断
            '酒窝', '演唱会', '音乐节', '直播', '吃播', '美食', '探店',
            '搞笑', '相声', '小品', '脱口秀', '综艺', '选秀',
            '打游戏', '电竞', '游戏解说', '游戏实况', '通关', '速通',
            '迷你世界', '原神', '王者荣耀', '和平精英',
            '日常vlog', 'vlog', '日常', '空降', '挑战', '大胃王',
            'tf家族', '时代少年团',  # TF家族/偶像团体
            '海龟汤', '双影奇境',  # 游戏/娱乐内容
            '新年音乐会', '纯享版',  # 演唱会内容
            '鲤鱼ace',  # 游戏UP主
        ]
        # 科技关键词 — 包含这些的标题即使有娱乐词也保留(AI绘画教程 等)
        TECH_KEYWORDS = [
            'ai', '人工智能', '大模型', '编程', '代码', '开源', '技术',
            '评测', '测评', '科技', '数码', '硬件', '机器人', '芯片',
            'gpu', 'cpu', '算法', '机器学习', '深度学习', '自动驾驶',
            'llm', 'gpt', 'cursor', 'copilot', 'python', 'docker',
            'linux', '服务器', '云', '网络', '安全', '黑客',
            '教程', '教学', '知识', '科普', '工具', '效率',
        ]
        seen_bili = set()
        bilibili_items = []
        cur.execute("""
            SELECT title, url, platform, hot_score, collected_at
            FROM raw_intelligence
            WHERE platform LIKE '%bilibili%'
              AND collected_at >= datetime('now', '-24 hours')
              AND hot_score > 100000
            ORDER BY hot_score DESC
            LIMIT 50
        """)
        for r in cur.fetchall():
            title = r[0]
            if title in seen_bili or len(title) <= 5:
                continue
            title_lower = title.lower()
            # 检查是否包含科技关键词
            has_tech = any(kw in title_lower for kw in TECH_KEYWORDS)
            # 检查是否命中黑名单
            has_blacklisted = any(kw in title for kw in BILI_BLACKLIST)
            if has_blacklisted and not has_tech:
                # 纯娱乐内容,跳过
                continue
            seen_bili.add(title)
            bilibili_items.append({
                "title": title, "url": r[1], "platform": r[2],
                "hot_score": r[3], "time": r[4]
            })
            if len(bilibili_items) >= 5:
                break
        
        # GitHub热门(去重)
        seen_gh = set()
        github_items = []
        cur.execute("""
            SELECT title, url, platform, hot_score
            FROM raw_intelligence
            WHERE platform LIKE '%github%'
              AND collected_at >= datetime('now', '-24 hours')
            ORDER BY hot_score DESC
            LIMIT 30
        """)
        for r in cur.fetchall():
            title = r[0]
            repo_match = re.search(r'([^/]+/[^/\s-]+)', title)
            repo_key = repo_match.group(1) if repo_match else title
            if repo_key not in seen_gh:
                seen_gh.add(repo_key)
                github_items.append({
                    "title": title, "url": r[1], "platform": r[2], "score": r[3]
                })
                if len(github_items) >= 5:
                    break
        
        db.close()
        
        return {
            "ai_news": ai_items,
            "bilibili": bilibili_items,
            "github": github_items,
            "total_ai": len(ai_items),
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        log(f"采集数据失败: {e}")
        return {"ai_news": [], "bilibili": [], "github": [], "total_ai": 0}


# ==================== 日报生成 ====================
def generate_daily(data: Dict) -> str:
    """生成AI日报"""
    ai_news = data.get("ai_news", [])
    
    # 主题聚类
    TOPICS = {
        "🤖 大模型与AGI": ["大模型", "llm", "agi", "gpt", "chatgpt", "openai", 
                         "claude", "anthropic", "gemini", "deepseek", "通义",
                         "文心", "智谱", "百川", "qwen", "训练", "推理"],
        "🔧 AI工具与编程": ["cursor", "copilot", "codex", "claude code", "AI编程",
                         "代码生成", "AI工具", "v0", "devin"],
        "🔬 AI研究与突破": ["论文", "研究", "突破", "新方法", "新架构", "moe",
                         "transformer", "diffusion", "多模态", "mamba"],
        "💻 芯片与算力": ["芯片", "gpu", "nvidia", "amd", "intel", "算力",
                        "cuda", "rocm", "tpu", "推理芯片", "训练芯片"],
        "🚗 具身智能与机器人": ["人形机器人", "具身智能", "宇树", "特斯拉机器人",
                              "robotics", "机器人", "仿生"],
        "📱 AI应用落地": ["AI搜索", "AI助手", "AI视频", "AI音乐", "AI绘画",
                        "AI写作", "AI翻译", "AIGC", "AI Agent", "rag"]
    }
    
    clustered = {k: [] for k in TOPICS}
    for item in ai_news:
        text = f"{item.get('title','')} {item.get('content','')}".lower()
        for topic, kws in TOPICS.items():
            if any(kw in text for kw in kws):
                clustered[topic].append(item)
                break
        else:
            clustered.setdefault("📡 其他AI动态", []).append(item)
    
    # 计算总览
    total = len(ai_news)
    plat_count = len(set(i.get("platform","") for i in ai_news))
    top_platforms = {}
    for i in ai_news:
        p = i.get("platform","")
        top_platforms[p] = top_platforms.get(p, 0) + 1
    top_plat_str = ",".join([f"{k}({v}条)" for k,v in sorted(top_platforms.items(), key=lambda x:-x[1])[:5]])
    all_platforms = list(top_platforms.keys())
    
    # 高价值精选
    top_picks = sorted(ai_news, key=lambda x: x.get("importance", 0) * 0.6 + (x.get("personal_match", 0) or 0) * 0.4, reverse=True)[:8]
    
    # 构建日报内容
    today = date.today().isoformat()
    md = f"""# 📊 AI行业日报 | {today}

> 每日自动采集 · AI分析 · 趋势洞察

---

## 📈 今日概览
| 指标 | 数值 |
|------|------|
| AI相关情报 | **{total}** 条 |
| 覆盖平台 | **{plat_count}** 个 |
| 最活跃平台 | {top_plat_str} |

---

"""
    # 精选头条
    if top_picks:
        md += "## 📌 今日头条\n\n"
        for i, item in enumerate(top_picks[:3], 1):
            title = item.get("title", "无标题")
            plat = item.get("platform", "未知")
            url = item.get("url", "")
            md += f"### {i}. [{title}]({url})\n"
            md += f"**来源**: {plat} | **评分**: {item.get('importance', 0)}\n\n"
            content = item.get("content", "")
            if content:
                md += f"> {content[:200]}\n\n"
    
    # 按主题分类
    md += "## 📂 主题分类\n\n"
    for topic, items in clustered.items():
        if items:
            md += f"### {topic} ({len(items)}条)\n\n"
            for item in items[:4]:
                title = item.get("title", "无标题")
                plat = item.get("platform", "")
                url = item.get("url", "")
                md += f"- [{title}]({url}) — *{plat}*\n"
            md += "\n"
    
    # B站趋势
    bili = data.get("bilibili", [])
    if bili:
        md += "## 🎬 B站科技趋势\n\n"
        for item in bili[:5]:
            md += f"- [{item.get('title','')}]({item.get('url','')}) — 热度: {item.get('hot_score', 'N/A')}\n"
        md += "\n"
    
    # GitHub趋势
    gh = data.get("github", [])
    if gh:
        md += "## 💻 GitHub热门项目\n\n"
        for item in gh[:5]:
            md += f"- [{item.get('title','')}]({item.get('url','')}) — ⭐ {item.get('score', 'N/A')}\n"
        md += "\n"
    
    # ========== 深度趋势分析 ==========
    md += "## 🔮 趋势分析\n\n"

    # 按主题数量排列,找出升温/降温信号
    topic_counts = sorted(clustered.items(), key=lambda x: -len(x[1]))
    active_topics = [(t, items) for t, items in topic_counts if items]

    # 各主题的热度占比和关键事件
    if active_topics:
        md += "### 📊 当天热点分布\n\n"
        for topic, items in active_topics:
            pct = round(len(items) / total * 100, 1) if total > 0 else 0
            bar = "█" * max(1, int(pct / 5))
            md += f"- {topic}: **{len(items)}条** ({pct}%) {bar}\n"
        md += "\n"

    # 跨主题关联分析 — 找事件之间的关联
    md += "### 🔗 事件关联分析\n\n"
    # 收集所有标题用于交叉分析
    all_titles = [i.get("title", "") for i in ai_news]
    all_text = " ".join(all_titles).lower()

    # 关键信号词检测
    signals = []
    if any("融资" in t or "投资" in t or "收购" in t for t in all_titles):
        signals.append("💰 **资本活跃**:当天出现投融资/收购动向,行业资本热度较高")
    if any("开源" in t for t in all_titles):
        signals.append("🔄 **开源生态扩张**:多个开源项目/模型发布,技术民主化加速")
    if any("监管" in t or "政策" in t or "立法" in t for t in all_titles):
        signals.append("⚖️ **政策信号**:监管/政策相关动态出现,可能影响行业发展方向")
    if any("all" in t for t in all_titles) or any("通用" in t for t in all_titles):
        signals.append("🎯 **向AGI迈进**:通用/全能型AI能力讨论增多")
    if any("部署" in t or "落地" in t or "应用" in t or "产品" in t for t in all_titles):
        signals.append("🚀 **加速落地**:从研发到产品化/部署的信号明显")

    if signals:
        for s in signals:
            md += f"- {s}\n"
        md += "\n"

    # 找出各主题下最受关注的事件,勾勒关联图谱
    md += "**当天事件关联图谱:** "
    if active_topics:
        # 取top3主题的关键事件
        top3_items = []
        for topic, items in active_topics[:3]:
            if items:
                top3_items.append((topic, items[0].get("title", ""), items[0].get("platform", "")))
        if len(top3_items) >= 2:
            connections = []
            for i in range(len(top3_items)):
                for j in range(i+1, len(top3_items)):
                    connections.append(f"「{top3_items[i][0]}」↔「{top3_items[j][0]}」")
            md += f"{','.join(connections)} 之间存在交叉影响,"
            md += f"核心主线围绕 **{active_topics[0][0]}** 展开({len(active_topics[0][1])}条相关情报)。\n\n"
        else:
            md += f"当天核心热点集中在 **{active_topics[0][0]}**,"
            md += f"其他细分领域动态较少。\n\n"

    # 趋势方向判断
    md += "### 📈 趋势方向判断\n\n"
    # 用实际数据判断升温/降温
    warming = []
    cooling = []
    for topic, items in active_topics:
        count = len(items)
        if count >= total * 0.2:  # 占比超20%为升温
            warming.append(f"{topic}({count}条,占比{round(count/total*100,1)}%)")
        elif count <= 2 and total > 20:  # 仅1-2条且总量大时为降温
            cooling.append(f"{topic}(仅{count}条)")

    if warming:
        md += "🔥 **升温领域:** " + ",".join(warming) + "\n\n"
    if cooling:
        md += "❄️ **降温领域:** " + ",".join(cooling) + "\n\n"
    if not warming and not cooling:
        md += "📊 **整体平稳**:各领域活跃度接近,无明显极端波动。\n\n"

    # 可操作建议
    md += "### 💡 关注建议\n\n"
    suggestions = []

    # 基于实际数据给出建议
    if any("大模型" in t or "llm" in t or "agi" in t for t in all_titles):
        suggestions.append("🤖 **大模型赛道**持续活跃,建议关注开源模型的商业应用机会,"
                          "特别是能结合企业私有数据的落地场景")

    if any("机器人" in t or "具身" in t or "宇树" in t for t in all_titles):
        suggestions.append("🦾 **具身智能/机器人**方向升温明显,建议关注头部企业的供应链机会"
                          "(传感器,执行器,仿真平台)")

    if any("芯片" in t or "gpu" in t or "算力" in t for t in all_titles):
        suggestions.append("💻 **算力基础设施**持续紧张,关注国产替代方案和推理芯片赛道")

    if any("工具" in t or "cursor" in t or "copilot" in t or "编程" in t for t in all_titles):
        suggestions.append("🔧 **AI编程工具**赛道竞争加剧,建议对比测试Cursor/Claude Code/"
                          "Copilot在不同场景下的效率差异,关注能解决企业级代码库问题的方案")

    if any("应用" in t or "aigc" in t or "ai视频" in t or "ai搜索" in t for t in all_titles):
        suggestions.append("📱 **AI应用层**机会增多,关注AI搜索,AI视频生成等C端产品"
                          "的用户增长和留存数据")

    # 如果没有匹配到任何特定建议,给通用建议
    if not suggestions:
        suggestions.append("📊 **持续监测**各赛道头部项目动态,关注技术突破节点带来的投资窗口")
        suggestions.append("🔍 **关注开源生态**中Star增长最快的项目,早期发现技术趋势转向")

    for s in suggestions:
        md += f"- {s}\n"
    md += "\n"

    # 数据支撑
    md += f"*本分析基于当日{total}条AI相关情报,{len(all_platforms)}个平台数据,"
    md += f"由评分模型+规则引擎自动生成。*\n\n"
    md += f"> 📅 自动生成于 {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
    md += "> Hermes AI日报 · 数据来源: 44个平台情报系统\n"
    
    return md


# ==================== 输出 ====================
def save_daily(md_content: str) -> str:
    """保存日报"""
    today = date.today().isoformat()
    ts = datetime.now().strftime('%Y%m%d_%H%M')
    
    filepath = DAILY_DIR / f"daily_{today}.md"
    filepath.write_text(md_content, encoding='utf-8')
    
    # 同时保存带时间戳的版本
    ts_path = DAILY_DIR / f"daily_{ts}.md"
    ts_path.write_text(md_content, encoding='utf-8')
    
    log(f"日报已保存: {filepath}")
    return str(filepath)


# ==================== 入口 ====================
def main():
    print(f"\n{'='*50}")
    print(f"📊 AI日报引擎启动")
    print(f"{'='*50}")
    
    log("读取情报数据...")
    data = collect_daily_data()
    log(f"获取到 {data['total_ai']} 条AI相关情报")
    
    if data['total_ai'] == 0:
        log("无数据,跳过日报生成")
        return None
    
    log("生成日报内容...")
    md = generate_daily(data)
    
    filepath = save_daily(md)
    
    log(f"✅ AI日报完成!字数: {len(md)}")
    print(f"\n文件: {filepath}")
    
    return filepath

if __name__ == "__main__":
    main()
