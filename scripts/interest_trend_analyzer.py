#!/usr/bin/env python3
"""
Hermes 用户兴趣趋势分析 (Interest Trend Analyzer)
==================================================
从推送记录和用户偏好中分析用户兴趣变化趋势。

输出:
1. 高频兴趣关键词排行
2. 兴趣变化趋势(相比7天前)
3. 新出现的兴趣点
4. 热度过气的兴趣点

用法:
  python3 interest_trend_analyzer.py           # 默认分析
  python3 interest_trend_analyzer.py --report  # 生成详细报告
"""

import sqlite3, json, re, os
from pathlib import Path
from datetime import datetime, timedelta
from collections import Counter, defaultdict
from typing import List, Dict, Tuple

HERMES = Path("/home/administrator/.hermes")
DB_PATH = HERMES / "intelligence.db"

# 兴趣分类关键词
INTEREST_CATEGORIES = {
    "AI/大模型": ["AI", "GPT", "LLM", "大模型", "人工智能", "OpenAI", "Claude", "DeepSeek", "Gemini", "ChatGPT",
                 "Stable Diffusion", "Sora", "Transformer", "Neural", "深度学习", "机器学习"],
    "IT/开发": ["开源", "GitHub", "VS Code", "TypeScript", "Rust", "Python", "Kubernetes", "Docker",
                "微服务", "云原生", "DevOps", "React", "Vue", "Linux", "数据库", "代码", "编程"],
    "消费电子": ["iPhone", "华为", "小米", "三星", "Mac", "iPad", "芯片", "骁龙", "Apple",
                "折叠屏", "AR", "VR", "手机", "平板"],
    "新能源汽车": ["比亚迪", "特斯拉", "蔚来", "理想", "小鹏", "小米汽车", "自动驾驶", "固态电池",
                  "充电", "电动车", "新能源"],
    "军事/国际": ["军事", "国防", "武器", "战机", "航母", "导弹", "战争", "国际", "外交", "美国", "中国"],
    "科技/创业": ["创业", "融资", "科技", "创新", "IPO", "收购", "投资"],
    "安全/隐私": ["安全", "隐私", "加密", "漏洞", "黑客", "数据泄露", "网络安全"],
}

def load_preferences() -> Dict[str, float]:
    """从数据库加载用户偏好权重"""
    prefs = {}
    try:
        conn = sqlite3.connect(str(DB_PATH), timeout=10)
        rows = conn.execute("SELECT keyword, weight FROM user_preferences ORDER BY weight DESC").fetchall()
        for k, w in rows:
            prefs[k] = w
        conn.close()
    except:
        pass
    return prefs

def analyze_push_history(days: int = 7) -> dict:
    """分析推送历史中的兴趣趋势"""
    conn = sqlite3.connect(str(DB_PATH), timeout=30)
    
    since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    
    # 获取推送记录
    rows = conn.execute("""
        SELECT title, content, source, platform, push_time
        FROM push_records
        WHERE push_time > ?
        ORDER BY push_time DESC
    """, (since,)).fetchall()
    
    # 分类统计
    category_counts = Counter()
    keyword_counts = Counter()
    
    for row in rows:
        title = row[0] or ""
        content = row[1] or ""
        text = f"{title} {content}".lower()
        
        # 按类别统计
        for category, keywords in INTEREST_CATEGORIES.items():
            matches = sum(1 for kw in keywords if kw.lower() in text)
            if matches >= 2:  # 至少2个关键词才算
                category_counts[category] += 1
                # 记录匹配到的关键词
                for kw in keywords:
                    if kw.lower() in text:
                        keyword_counts[kw] += 1
    
    conn.close()
    
    return {
        "total_pushed": len(rows),
        "categories": dict(category_counts.most_common(10)),
        "top_keywords": dict(keyword_counts.most_common(20)),
    }

def analyze_interest_trend() -> dict:
    """比较最近7天和之前7天的兴趣变化"""
    conn = sqlite3.connect(str(DB_PATH), timeout=30)
    
    now = datetime.now()
    recent_start = (now - timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")
    prev_start = (now - timedelta(days=14)).strftime("%Y-%m-%d %H:%M:%S")
    
    def count_keywords(since_str, until_str=""):
        """统计一段时间内的关键词频率"""
        c = Counter()
        if until_str:
            rows = conn.execute("""
                SELECT title FROM push_records
                WHERE push_time > ? AND push_time <= ?
            """, (since_str, until_str)).fetchall()
        else:
            rows = conn.execute("""
                SELECT title FROM push_records
                WHERE push_time > ?
            """, (since_str,)).fetchall()
        
        for row in rows:
            text = (row[0] or "").lower()
            for category, keywords in INTEREST_CATEGORIES.items():
                for kw in keywords:
                    if kw.lower() in text:
                        c[kw] += 1
        return c
    
    prev_end = recent_start
    
    recent_counts = count_keywords(recent_start)
    prev_counts = count_keywords(prev_start, prev_end)
    
    # 计算变化趋势
    rising = []  # 上升的兴趣
    falling = []  # 下降的兴趣
    new_interests = []  # 新出现的
    
    all_keywords = set(list(recent_counts.keys()) + list(prev_counts.keys()))
    
    for kw in all_keywords:
        recent = recent_counts.get(kw, 0)
        prev = prev_counts.get(kw, 0)
        
        if prev == 0 and recent > 1:
            new_interests.append((kw, recent))
        elif prev > 0 and recent > prev * 1.5:
            rising.append((kw, recent, prev, recent - prev))
        elif prev > 0 and recent < prev * 0.5:
            falling.append((kw, recent, prev, prev - recent))
    
    conn.close()
    
    return {
        "new_interests": sorted(new_interests, key=lambda x: x[1], reverse=True)[:10],
        "rising": sorted(rising, key=lambda x: x[3], reverse=True)[:10],
        "falling": sorted(falling, key=lambda x: x[3], reverse=True)[:10],
        "period": {"recent": "最近7天", "previous": "上7天"},
    }

def run():
    """主流程"""
    prefs = load_preferences()
    push_stats = analyze_push_history(7)
    trends = analyze_interest_trend()
    
    report = []
    report.append("# 📊 Hermes 用户兴趣趋势分析\n")
    report.append(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
    
    # 1. 推送概览
    report.append(f"## 推送概览")
    report.append(f"- 最近7天推送: **{push_stats['total_pushed']}** 条\n")
    
    # 2. 兴趣分类
    report.append(f"## 兴趣分类排行")
    for cat, cnt in push_stats['categories'].items():
        bar = "█" * min(cnt // 2, 30)
        report.append(f"- **{cat}**: {cnt}次 {bar}")
    report.append("")
    
    # 3. 新兴趣点
    if trends['new_interests']:
        report.append(f"## 🔥 新出现的兴趣点")
        for kw, cnt in trends['new_interests'][:5]:
            report.append(f"- **{kw}**: {cnt}次 (之前7天未出现)")
        report.append("")
    
    # 4. 上升趋势
    if trends['rising']:
        report.append(f"## 📈 上升趋势")
        for kw, recent, prev, diff in trends['rising'][:5]:
            report.append(f"- **{kw}**: {recent}次 (↑{diff})")
        report.append("")
    
    # 5. 下降趋势
    if trends['falling']:
        report.append(f"## 📉 下降趋势")
        for kw, recent, prev, diff in trends['falling'][:5]:
            report.append(f"- **{kw}**: {recent}次 (↓{diff})")
        report.append("")
    
    # 6. 活跃偏好关键词
    if prefs:
        report.append(f"## 用户偏好关键词 (Top 10)")
        for kw, weight in sorted(prefs.items(), key=lambda x: x[1], reverse=True)[:10]:
            report.append(f"- {kw}: 权重{weight}")
    
    report.append("\n---\n*🤖 Hermes 自动分析·兴趣趋势洞察*")
    
    return "\n".join(report)

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", action="store_true", help="生成详细报告")
    args = parser.parse_args()
    
    result = run()
    print(result)
    
    # 保存报告
    report_path = HERMES / "reports" / f"interest_trend_{datetime.now().strftime('%Y%m%d_%H%M')}.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(result, encoding="utf-8")
    print(f"\n报告已保存: {report_path}")
