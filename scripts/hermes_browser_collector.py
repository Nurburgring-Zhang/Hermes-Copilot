#!/usr/bin/env python3
"""
Hermes 增强版浏览器采集器 v2.0
==================================
专为填补微信公众号,小红书,知乎,CSDN等平台数据而设计

采集策略:
1. 36氪,IT之家 - 浏览器直接采集(已验证可用)
2. 知乎 - 移动端API或RSSHub备用
3. CSDN - 浏览器直接访问
4. 微信公众号 - 搜狗微信搜索
5. 小红书 - RSSHub或其他备用源

使用方法:
  python3 hermes_browser_collector.py              # 全量采集
  python3 hermes_browser_collector.py --test      # 测试采集
"""

import os
import sys
import json
import re
import sqlite3
import time
from datetime import datetime
from typing import List, Dict, Tuple, Optional

DB_PATH = os.path.expanduser("~/.hermes/intelligence.db")

# ============================================================
# 主人偏好关键词(用于AI价值判断辅助)
# ============================================================
PERSONAL_KW = [
    "rust", "typescript", "javascript", "python", "go", "haskell", "elixir",
    "ai", "llm", "大模型", "agent", "智能体", "framework", "架构", "开源", 
    "compiler", "runtime", "functional", "函数式", "concurrent", "async", 
    "parallel", "wasm", "github", "huggingface", "ollama", "vllm", "llamacpp",
    "langchain", "autogen", "deepseek", "robot", "机器人", "自动驾驶"
]

HIGH_VALUE_KW = [
    "ai", "llm", "大模型", "gpt", "claude", "gemini", "openai", "anthropic",
    "模型", "开源", "框架", "架构", "系统", "平台", "发布", "突破", "首个", "融资",
    "chatgpt", "llama", "mistral", "transformer", "agent", "智能体", "deepseek",
    "rust", "typescript", "function", "reactive", "concurrent", "async", "parallel",
    "iphone", "华为", "小米", "苹果", "三星", "比亚迪", "特斯拉", "芯片", "gpu",
    "英伟达", "amd", "新能源", "自动驾驶", "机器人", "量子", "人形机器人",
    "github", "huggingface", "ollama", "vllm", "docker", "kubernetes", "devops"
]

NOISE_KW = [
    "明星", "娱乐", "八卦", "绯闻", "综艺", "演唱会", "粉丝", "游戏", "主播",
    "相亲", "恋爱", "分手", "结婚", "出轨", "减肥", "养生", "美妆", "穿搭",
    "赵丽颖", "郑恺", "迪丽热巴", "杨幂"
]

def is_noise(title: str, content: str = "") -> bool:
    """极窄噪音过滤"""
    text = (title + " " + content).lower()
    for kw in NOISE_KW:
        if kw in text:
            return True
    return False

def detect_lang(title: str) -> str:
    """检测语言"""
    c = len(re.findall(r'[\u4e00-\u9fff]', title))
    return "zh" if c / max(len(title), 1) > 0.3 else "en"

def score_item(title: str, content: str = "", platform: str = "", hot_score: float = 0) -> Tuple[int, int, int]:
    """
    返回 (总分, 星级, 偏好分)
    这是简化的评分 - 真正的AI判断在推送阶段由LLM执行
    """
    text = (title + " " + content).lower()
    matched = sum(1 for kw in HIGH_VALUE_KW if kw.lower() in text)
    base = matched * 8
    
    # 平台加成
    if platform in ["github", "huggingface", "oschina"]:
        base += 15
    elif platform in ["bilibili", "zhihu", "weibo", "weixin", "xiaohongshu"]:
        base += 5
    
    # 热度加成
    if hot_score > 50000:
        base += 20
    elif hot_score > 10000:
        base += 10
    elif hot_score > 1000:
        base += 5
    
    # 偏好匹配
    pref = sum(10 for kw in PERSONAL_KW if kw.lower() in text)
    base += pref
    
    # 星级计算
    if matched >= 4 and base >= 35:
        level = 5
    elif matched >= 3 and base >= 25:
        level = 4
    elif matched >= 2 and base >= 15:
        level = 3
    elif matched >= 1 and base >= 8:
        level = 2
    else:
        level = 1
    
    return base, level, pref

def normalize(item: Dict, source: str = "browser") -> Dict:
    """标准化数据"""
    title = item.get("title", "")[:200]
    content = item.get("content", "")[:300]
    url = item.get("url", "")
    platform = item.get("platform", "unknown")
    
    sc, level, pref = score_item(title, content, platform, item.get("hot_score", 0))
    lang = detect_lang(title)
    is_ai = 1 if any(k in (title+content).lower() for k in ["ai","llm","gpt","大模型","chatgpt","claude","deepseek","agent"]) else 0
    
    return {
        "title": title,
        "content": content,
        "url": url,
        "platform": platform,
        "source": source,
        "author": item.get("author", ""),
        "author_id": item.get("author_id", ""),
        "category": item.get("category", "技术"),
        "hot_score": item.get("hot_score", 0),
        "published_at": item.get("published_at"),
        "raw_data": json.dumps(item, ensure_ascii=False),
        "importance_score": sc,
        "value_level": level,
        "value_reasons": item.get("value_reasons", ""),
        "is_ai_related": is_ai,
        "language": lang,
        "chinese_ratio": len(re.findall(r'[\u4e00-\u9fff]', title)) / max(len(title), 1),
        "is_processed": 0,
        "personal_match_score": pref,
    }

def save(items: List[Dict], agent: str = "hermes_browser_collector") -> Tuple[int, int]:
    """保存到数据库"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    now = datetime.now().isoformat()
    saved = skipped = 0
    
    for item in items:
        title = item.get("title", "")[:200]
        url = item.get("url", "")
        
        if not title or not url or not url.startswith("http"):
            continue
        
        # URL去重
        c.execute("SELECT id FROM cleaned_intelligence WHERE url=? LIMIT 1", (url,))
        if c.fetchone():
            skipped += 1
            continue
        
        try:
            c.execute("""INSERT INTO raw_intelligence 
                (title,content,url,source,platform,author,author_id,category,tags,
                 hot_score,view_count,like_count,collect_count,comment_count,share_count,
                 published_at,collected_at,raw_data)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (title, item.get("content","")[:500], url,
                 item.get("source",""), item.get("platform",""), item.get("author",""),
                 item.get("author_id",""), item.get("category",""), "",
                 item.get("hot_score",0), 0, 0, 0, 0, 0,
                 item.get("published_at"), now, item.get("raw_data","")))
            raw_id = c.lastrowid
            
            c.execute("""INSERT INTO cleaned_intelligence
                (raw_id,title,content,url,source,platform,author,category,
                 importance_score,value_level,value_reasons,is_ai_related,personal_match_score,
                 language,chinese_ratio,is_processed,published_at,collected_at,cleaned_at,agent)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (raw_id, title, item.get("content","")[:500], url,
                 item.get("source",""), item.get("platform",""), item.get("author",""),
                 item.get("category",""), item.get("importance_score",0), item.get("value_level",1),
                 item.get("value_reasons",""), item.get("is_ai_related",0), item.get("personal_match_score",0),
                 item.get("language","zh"), item.get("chinese_ratio",1.0), 0,
                 item.get("published_at"), now, now, agent))
            saved += 1
        except Exception as e:
            pass
    
    conn.commit()
    conn.close()
    return saved, skipped

# ============================================================
# 采集源定义(浏览器可访问的平台)
# ============================================================

def get_browser_collection_instructions() -> Dict[str, str]:
    """
    返回浏览器采集指令 - 这些是指引,实际采集由delegate_task执行
    """
    return {
        "36kr": """
        1. browser_navigate("https://36kr.com/newsflashes")
        2. browser_console提取:
        ```
        const items = [];
        document.querySelectorAll('a[href*="/newsflashes/"]').forEach((el) => {
          if(el.href.match(/\\/newsflashes\\/\\d+/) && el.textContent.trim().length > 10) {
            items.push({
              title: el.textContent.trim().substring(0,80),
              url: 'https://36kr.com' + el.getAttribute('href'),
              hot_score: 50000 - items.length * 300
            });
          }
        });
        JSON.stringify({platform:'36kr', articles: items.slice(0,20)})
        ```
        """,
        
        "ithome": """
        1. browser_navigate("https://www.ithome.com/")
        2. browser_console提取:
        ```
        const items = [];
        document.querySelectorAll('a[href*="ithome.com/0/"]').forEach((el, i) => {
          if(el.href && el.textContent.trim().length > 15) {
            items.push({
              title: el.textContent.trim().substring(0,80),
              url: el.href,
              hot_score: 50000 - i * 300
            });
          }
        });
        JSON.stringify({platform:'ithome', articles: items.slice(0,20)})
        ```
        """,
        
        "zhihu": """
        尝试1: browser_navigate("https://www.zhihu.com/api/v4/featured-text-hot-list")
        尝试2: browser_navigate("https://www.zhihu.com/hot")
        尝试3: RSSHub browser_navigate("https://rsshub.app/zhihu/hotlist")
        """,
        
        "csdn": """
        1. browser_navigate("https://blog.csdn.net/")
        2. browser_console提取博客标题和链接
        如果被拦截,尝试: browser_navigate("https://www.csdn.net/")
        """,
        
        "weixin": """
        1. browser_navigate("https://weixin.sogou.com/")
        2. 搜索AI相关关键词采集
        3. 尝试RSSHub: browser_navigate("https://rsshub.app/weixin/mp/csdn")
        """,
        
        "xiaohongshu": """
        1. 尝试RSSHub: browser_navigate("https://rsshub.app/xiaohongshu/user/collection/xxx")
        2. 如果RSSHub不可用,标记为需要其他方案
        """,
    }

def main():
    import argparse
    p = argparse.ArgumentParser(description="Hermes 增强版浏览器采集器")
    p.add_argument("--source", help="指定采集源")
    p.add_argument("--test", action="store_true", help="测试模式")
    p.add_argument("--list", action="store_true", help="列出采集源")
    args = p.parse_args()
    
    if args.list:
        instructions = get_browser_collection_instructions()
        print("\n" + "="*60)
        print("  Hermes 浏览器采集源指引")
        print("="*60)
        for name, instr in instructions.items():
            print(f"\n【{name}】")
            print(instr[:200] + "..." if len(instr) > 200 else instr)
        print("="*60)
        return
    
    print("\n" + "="*60)
    print("  Hermes 增强版浏览器采集器 v2.0")
    print("  " + datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print("="*60)
    print("\n⚠️  注意:此脚本提供采集指引")
    print("   实际浏览器采集由 delegate_task(toolsets=['browser']) 执行")
    print("\n📋 采集源清单:")
    instructions = get_browser_collection_instructions()
    for name in instructions.keys():
        print(f"   - {name}")
    print("\n💡 使用方法:")
    print("   在 delegate_task 中使用 browser 工具集执行上述采集指令")
    print("="*60)

if __name__ == "__main__":
    main()
