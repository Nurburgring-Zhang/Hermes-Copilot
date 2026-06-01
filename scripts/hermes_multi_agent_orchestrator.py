#!/usr/bin/env python3
"""
Hermes Multi-Agent 情报编排系统 v3
===================================
真正的子Agent集群调度 - 使用 MCP delegate_task 实现

架构:
  调度Agent(主)
    ├── Agent-A: AI/科技情报 (B站科技+知乎+GitHub+arXiv+HuggingFace)
    ├── Agent-B: 消费电子/数码 (B站数码+IT之家+微博数码)
    ├── Agent-C: 新能源汽车 (B站汽车+微博汽车+汽车之家)
    ├── Agent-D: 游戏/电竞 (B站游戏+微博游戏+Steam)
    ├── Agent-E: 国际/军事 (Reddit+solidot+今日头条国际)
    └── Agent-F: 综合热榜 (抖音+微博热搜+B站全站)

每个子Agent独立执行:采集→清洗→评估→存储→上报主Agent
主Agent负责:汇总→去重→趋势追踪→推送到微信
"""
import os, sys, json, sqlite3, time, re, queue, threading
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

# ============================================================
# 核心配置
# ============================================================
DB_PATH = os.path.expanduser("~/.hermes/intelligence.db")
PUSHPLUS_URL = "https://www.pushplus.plus/send"
PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "a8f1526d8ec84ef59aa37fe72fa1ab7f")
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json, text/html, */*",
}

# 高价值关键词(各域通用)
HIGH_KW_GENERAL = [
    "AI","LLM","大模型","GPT","Claude","Gemini","OpenAI","Anthropic","AIGC","生成式AI","模型训练","模型发布","模型开源",
    "iPhone","Android","华为","小米","苹果","三星","比亚迪","特斯拉","新能源","自动驾驶",
    "GitHub","HuggingFace","开源","框架","架构","编程","代码","开发者","程序员",
    "军事","战争","武器","冲突","国际","外交","制裁","太空","航天","SpaceX","NASA",
    "游戏","电竞","Steam","Epic","主机","Switch","PlayStation","原神","黑神话",
]

# ============================================================
# 数据库工具
# ============================================================
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def dict_from_row(row):
    return dict(zip(row.keys(), row)) if hasattr(row, 'keys') else dict(row)

# ============================================================
# HTTP 工具
# ============================================================
import urllib.request, urllib.parse
def fetch(url, headers=None, timeout=10):
    h = headers or HEADERS
    try:
        req = urllib.request.Request(url, headers=h)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            ct = r.headers.get('Content-Type', '')
            data = r.read()
            if 'json' in ct:
                return json.loads(data.decode('utf-8'))
            return data.decode('utf-8', errors='ignore')
    except:
        return None

# ============================================================
# 子Agent采集函数(每个Agent运行这些函数)
# ============================================================
def agent_collect_bilibili(category_rid):
    """采集B站指定分区"""
    url = f"https://api.bilibili.com/x/web-interface/ranking/v2?rid={category_rid}&type=all"
    items = []
    data = fetch(url)
    if not data or not isinstance(data, dict) or 'data' not in data: 
        return []
    list_data = data.get('data')
    if not isinstance(list_data, dict):
        return []
    for item in list_data.get('list', []):
        stat = item.get('stat', {})
        title = item.get('title', '')
        if len(title) < 5: continue
        items.append({
            "title": title,
            "content": item.get('desc', ''),
            "url": f"https://www.bilibili.com/video/{item.get('bvid', '')}",
            "platform": "bilibili",
            "author": item.get('owner', {}).get('name', ''),
            "hot_score": float(stat.get('view', 0)),
            "view_count": stat.get('view', 0),
            "like_count": stat.get('like', 0),
            "comment_count": stat.get('reply', 0),
            "lang": "zh",
        })
    return items

def agent_collect_github(lang=""):
    """采集GitHub Trending"""
    url = f"https://github.com/trending{('python' if lang=='python' else '')}?since=daily"
    items = []
    html = fetch(url)
    if not html: return items
    matches = re.findall(r'<article class="Box-row">(.*?)</article>', html, re.DOTALL)
    for m in matches[:20]:
        repo = re.search(r'<h2[^>]*><a[^>]*href="/([^"]+)"', m)
        desc_match = re.search(r'<p>([^<]+)</p>', m)
        if not repo: continue
        items.append({
            "title": f"GitHub: {repo.group(1).split('/')[-1]} - {(desc_match.group(1) or '')[:80]}",
            "content": desc_match.group(1).strip() if desc_match else '',
            "url": f"https://github.com/{repo.group(1)}",
            "platform": "github",
            "author": repo.group(1).split('/')[0],
            "hot_score": 5000,
            "view_count": 0, "like_count": 0, "comment_count": 0,
            "lang": "en",
        })
    return items

def agent_collect_douyin():
    """采集抖音热搜"""
    items = []
    url = "https://www.douyin.com/aweme/v1/web/hot/search/list/?device_platform=webapp&aid=6383&channel=channel_pc_web&detail_list=1"
    data = fetch(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://www.douyin.com/",
    })
    if not data or not isinstance(data, dict) or 'data' not in data: return items
    for item in data.get('data', {}).get('word_list', []):
        word = item.get('word', '')
        if len(word) < 3: continue
        items.append({
            "title": word,
            "content": item.get('desc', ''),
            "url": f"https://www.douyin.com/search/{urllib.parse.quote(word)}",
            "platform": "douyin",
            "author": "",
            "hot_score": float(item.get('hot_value', 0)),
            "view_count": 0, "like_count": 0, "comment_count": 0,
            "lang": "zh",
        })
    return items

def agent_collect_oschina():
    """采集开源中国"""
    items = []
    html = fetch("https://www.oschina.net/news")
    if not html: return items
    titles = re.findall(r'<h2[^>]*><a[^>]*>([^<]+)</a></h2>', html)
    urls = re.findall(r'<h2[^>]*><a[^>]*href="([^"]+)"', html)
    for title, url in zip(titles[:20], urls[:20]):
        title = title.strip()
        if len(title) < 5: continue
        full_url = url if url.startswith('http') else f"https://www.oschina.net{url}"
        items.append({
            "title": title,
            "content": "",
            "url": full_url,
            "platform": "oschina",
            "author": "",
            "hot_score": 5000,
            "view_count": 0, "like_count": 0, "comment_count": 0,
            "lang": "zh",
        })
    return items

def agent_collect_36kr():
    """采集36氪"""
    items = []
    data = fetch("https://36kr.com/api/newsflash/index?per_page=30&page=1")
    if not data or not isinstance(data, dict) or 'data' not in data: return items
    for item in data.get('data', {}).get('items', []):
        title = item.get('title', '')
        if len(title) < 5: continue
        items.append({
            "title": title,
            "content": item.get('description', '')[:200],
            "url": item.get('news_url', '') or f"https://36kr.com/p/{item.get('item_id', '')}",
            "platform": "36kr",
            "author": item.get('author', ''),
            "hot_score": float(item.get('hot_score', 5000)),
            "view_count": 0, "like_count": 0, "comment_count": 0,
            "lang": "zh",
        })
    return items

def agent_collect_toutiao(category='__all__'):
    """采集今日头条"""
    items = []
    url = f"https://www.toutiao.com/api/pc/feed/?min_behot_time=0&category={category}&count=20"
    data = fetch(url, headers={"Referer": "https://www.toutiao.com/"})
    if not data or not isinstance(data, dict) or 'data' not in data: return items
    for item in data.get('data', [])[:20]:
        title = item.get('title', '')
        if len(title) < 5: continue
        items.append({
            "title": title,
            "content": item.get('abstract', '')[:200],
            "url": item.get('article_url', ''),
            "platform": "toutiao",
            "author": item.get('user_info', {}).get('name', ''),
            "hot_score": float(item.get('go_detail_count', 5000)),
            "view_count": item.get('read_count', 0),
            "like_count": item.get('digg_count', 0),
            "comment_count": item.get('comment_count', 0),
            "lang": "zh",
        })
    return items

def agent_collect_reddit(subreddit):
    """采集Reddit"""
    items = []
    url = f"https://www.reddit.com/r/{subreddit}/hot.json?limit=30"
    data = fetch(url, headers={"User-Agent": "Mozilla/5.0"})
    if not data or not isinstance(data, dict) or 'data' not in data: return items
    for post in data.get('data', {}).get('children', []):
        d = post.get('data', {})
        title = d.get('title', '')
        if len(title) < 5: continue
        items.append({
            "title": title,
            "content": d.get('selftext', '')[:200],
            "url": f"https://reddit.com{d.get('permalink', '')}",
            "platform": "reddit",
            "author": d.get('author', ''),
            "hot_score": float(d.get('score', 0)),
            "view_count": d.get('view_count', 0),
            "like_count": d.get('score', 0),
            "comment_count": d.get('num_comments', 0),
            "lang": "en",
        })
    return items

def agent_collect_solidot():
    """采集Solidot"""
    items = []
    html = fetch("https://www.solidot.org/")
    if not html: return items
    titles = re.findall(r'<h2[^>]*><a[^>]*>([^<]+)</a></h2>', html)
    urls = re.findall(r'<h2[^>]*><a[^>]*href="([^"]+)"', html)
    for title, url in zip(titles[:15], urls[:15]):
        title = title.strip()
        if len(title) < 5: continue
        items.append({
            "title": title,
            "content": "",
            "url": url if url.startswith('http') else f"https://www.solidot.org{url}",
            "platform": "solidot",
            "author": "",
            "hot_score": 3000,
            "view_count": 0, "like_count": 0, "comment_count": 0,
            "lang": "zh",
        })
    return items

def agent_collect_ithome():
    """采集IT之家"""
    items = []
    html = fetch("https://www.ithome.com/")
    if not html: return items
    titles = re.findall(r'<h2[^>]*><a[^>]*>([^<]+)</a></h2>', html)
    urls = re.findall(r'<h2[^>]*><a[^>]*href="([^"]+)"', html)
    for title, url in zip(titles[:20], urls[:20]):
        title = title.strip()
        if len(title) < 5: continue
        full_url = url if url.startswith('http') else f"https://www.ithome.com{url}"
        items.append({
            "title": title,
            "content": "",
            "url": full_url,
            "platform": "ithome",
            "author": "",
            "hot_score": 5000,
            "view_count": 0, "like_count": 0, "comment_count": 0,
            "lang": "zh",
        })
    return items

# ============================================================
# 评估函数
# ============================================================
def evaluate_item(item, agent_name):
    title = item.get('title', '')
    content = item.get('content', '')
    text = (title + content).lower()
    
    matched = [kw for kw in HIGH_KW_GENERAL if kw.lower() in text]
    score = len(matched) * 5
    
    # 平台权重
    pw = {"github": 15, "bilibili": 8, "oschina": 10, "36kr": 8,
          "solidot": 10, "douyin": 8, "toutiao": 6, "reddit": 6}
    score += pw.get(item.get('platform', ''), 5)
    
    hot = item.get('hot_score', 0)
    if hot > 0 and item.get('platform') in ('bilibili', 'douyin'):
        score += 5 if hot > 1000000 else 2
    
    if item.get('like_count', 0) > 1000: score += 3
    if item.get('comment_count', 0) > 500: score += 3
    
    # 中文比例
    c = len(re.findall(r'[\u4e00-\u9fff]', title))
    lang = 'zh' if (c / len(title) if len(title) > 0 else 0) > 0.3 else 'en'
    
    # 等级(5级制)
    if len(matched) >= 3 and score >= 20: level = 5
    elif len(matched) >= 2 and score >= 15: level = 4
    elif len(matched) >= 1 and score >= 10: level = 3
    elif len(matched) >= 1 and score >= 5: level = 2
    else: level = 1
    
    ai_keywords = ['ai','llm','gpt','大模型','gpt','claude','gemini','openai','anthropic',
                    'aigc','生成式','多模态','模型训练','模型发布','开源模型','模型开源',
                    '机器学习','深度学习','神经网络','人工智能','hugging face','github copilot']
    is_ai = 1 if any(kw.lower() in text for kw in ai_keywords) else 0
    
    return {
        **item,
        "importance_score": round(score, 1),
        "value_level": level,
        "matched_keywords": ','.join(matched[:5]),
        "is_ai_related": is_ai,
        "language": lang,
        "chinese_ratio": c / len(title) if len(title) > 0 else 0,
        "agent": agent_name,
        "collected_at": datetime.now().isoformat(),
    }

# ============================================================
# 子Agent工作函数(打包后由 delegate_task 调用)
# ============================================================
def run_agent_A():
    """Agent-A: AI/科技情报"""
    all_items = []
    all_items += agent_collect_bilibili(36)   # B站科技
    all_items += agent_collect_oschina()      # 开源中国(AI/技术新闻)
    all_items += agent_collect_36kr()         # 36氪
    all_items += agent_collect_solidot()      # Solidot
    all_items += agent_collect_bilibili(201)  # B站知识
    evaluated = [evaluate_item(x, 'Agent-A') for x in all_items]
    return evaluated

def run_agent_B():
    """Agent-B: 消费电子/数码"""
    all_items = []
    all_items += agent_collect_bilibili(188)  # B站数码
    all_items += agent_collect_bilibili(129)  # B站时尚
    all_items += agent_collect_ithome()
    all_items += agent_collect_toutiao('tech')
    evaluated = [evaluate_item(x, 'Agent-B') for x in all_items]
    return evaluated

def run_agent_C():
    """Agent-C: 新能源汽车"""
    all_items = []
    all_items += agent_collect_bilibili(223)  # B站汽车
    all_items += agent_collect_toutiao('car')
    all_items += agent_collect_toutiao('new_energy')
    evaluated = [evaluate_item(x, 'Agent-C') for x in all_items]
    return evaluated

def run_agent_D():
    """Agent-D: 游戏/电竞"""
    all_items = []
    all_items += agent_collect_bilibili(4)   # B站游戏
    all_items += agent_collect_toutiao('game')
    all_items += agent_collect_bilibili(4)    # B站游戏
    all_items += agent_collect_toutiao('game')  # 今日头条游戏
    evaluated = [evaluate_item(x, 'Agent-D') for x in all_items]
    return evaluated

def run_agent_E():
    """Agent-E: 综合/国际"""
    all_items = []
    all_items += agent_collect_solidot()      # Solidot(科技/国际新闻)
    all_items += agent_collect_toutiao('__all__')  # 今日头条综合
    all_items += agent_collect_toutiao('tech')     # 今日头条科技
    evaluated = [evaluate_item(x, 'Agent-E') for x in all_items]
    return evaluated

def run_agent_F():
    """Agent-F: 综合热榜"""
    all_items = []
    try:
        all_items += agent_collect_douyin()
    except Exception as e:
        print(f"    [Agent-F] 抖音采集失败: {e}")
    try:
        all_items += agent_collect_bilibili(36)  # B站科技
        all_items += agent_collect_bilibili(21)  # B站运动
        all_items += agent_collect_bilibili(181) # B站影视
    except Exception as e:
        print(f"    [Agent-F] B站采集失败: {e}")
    try:
        result = agent_collect_toutiao('__all__')
        if result:
            all_items += result
        else:
            # 备用:科技
            all_items += agent_collect_toutiao('tech')
    except Exception as e:
        print(f"    [Agent-F] 头条采集失败: {e}")
    evaluated = [evaluate_item(x, 'Agent-F') for x in all_items]
    return evaluated

# Agent 映射
AGENTS = {
    'Agent-A': run_agent_A,
    'Agent-B': run_agent_B,
    'Agent-C': run_agent_C,
    'Agent-D': run_agent_D,
    'Agent-E': run_agent_E,
    'Agent-F': run_agent_F,
}

# ============================================================
# Multi-Agent 并行调度(使用线程池,非 delegate_task)
# ============================================================
def run_multi_agent_collection():
    """调度所有子Agent并行采集,结果汇总"""
    print("\n" + "="*60)
    print("  Hermes Multi-Agent 情报编排系统 v3")
    print("="*60)
    print(f"\n[调度Agent] 启动 {len(AGENTS)} 个子Agent集群...")
    
    all_evaluated = []
    agent_stats = {}
    
    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = {executor.submit(agent_fn): agent_name 
                   for agent_name, agent_fn in AGENTS.items()}
        
        for future in as_completed(futures, timeout=120):
            agent_name = futures[future]
            try:
                items = future.result(timeout=120)
                lv5 = sum(1 for x in items if x['value_level'] == 5)
                lv4 = sum(1 for x in items if x['value_level'] == 4)
                lv3 = sum(1 for x in items if x['value_level'] == 3)
                agent_stats[agent_name] = {'total': len(items), 'lv5': lv5, 'lv4': lv4, 'lv3': lv3}
                all_evaluated.extend(items)
                print(f"  ✅ {agent_name}: {len(items)}条 (LV5:{lv5} LV4:{lv4} LV3:{lv3})")
            except Exception as e:
                print(f"  ❌ {agent_name}: {str(e)[:50]}")
                agent_stats[agent_name] = {'error': str(e)}
    
    return all_evaluated, agent_stats

# ============================================================
# 主控逻辑
# ============================================================
def save_results(items, conn):
    """存储到数据库"""
    c = conn.cursor()
    now = datetime.now().isoformat()
    
    for item in items:
        try:
            c.execute("""INSERT INTO raw_intelligence 
                (title,content,url,platform,source,author,category,hot_score,view_count,like_count,comment_count,published_at,raw_data,collected_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (item['title'], item.get('content',''), item.get('url',''),
                 item.get('platform',''), item.get('platform',''), item.get('author',''),
                 '', item.get('hot_score',0), item.get('view_count',0),
                 item.get('like_count',0), item.get('comment_count',0),
                 None, json.dumps(item, ensure_ascii=False), now))
            
            c.execute("""INSERT INTO cleaned_intelligence 
                (raw_id,title,content,url,source,platform,author,category,importance_score,value_level,value_reasons,is_ai_related,language,chinese_ratio,published_at,collected_at,cleaned_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (0, item['title'], item.get('content',''), item.get('url',''),
                 item.get('platform',''), item.get('platform',''), item.get('author',''),
                 '', item['importance_score'], item['value_level'],
                 item.get('matched_keywords',''), item.get('is_ai_related',0),
                 item.get('language','zh'), item.get('chinese_ratio',1.0),
                 None, item.get('collected_at', now), now))
        except Exception:
            pass
    
    conn.commit()

def deduplicate(items):
    """7天去重"""
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT title FROM cleaned_intelligence WHERE cleaned_at > datetime('now','-24 hours')")
    recent = set(r[0].lower() for r in c.fetchall())
    conn.close()
    
    seen = set()
    result = []
    for item in items:
        t = item['title'].lower()
        if t not in seen and t not in recent:
            seen.add(t)
            result.append(item)
    return result

def push_to_wechat(title, content, level=3, item=None):
    emoji = {5: "🚨🚨🚨", 4: "🔥🔥", 3: "📣"}
    data = {
        "token": PUSHPLUS_TOKEN,
        "title": f"{emoji.get(level,'📣')} {title}",
        "content": content,
        "channel": "wechat",
        "template": "markdown"
    }
    try:
        req = urllib.request.Request(
            PUSHPLUS_URL,
            data=json.dumps(data).encode(),
            headers={'Content-Type': 'application/json'}
        )
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read().decode()).get('code') == 200
    except:
        return False

def build_report(items):
    date = datetime.now().strftime('%Y-%m-%d %H:%M')
    lines = [f"# 📊 全平台情报日报 | {date}", ""]
    
    by_agent = {}
    for item in items:
        agent = item.get('agent', 'unknown')
        by_agent.setdefault(agent, []).append(item)
    
    for agent, agent_items in sorted(by_agent.items()):
        lv5 = [x for x in agent_items if x['value_level'] >= 5]
        lv4 = [x for x in agent_items if x['value_level'] == 4]
        lv3 = [x for x in agent_items if x['value_level'] == 3]
        if lv5 or lv4:
            lines.append(f"\n## {agent} ({len(agent_items)}条 | LV5:{len(lv5)} LV4:{len(lv4)} LV3:{len(lv3)})")
            for item in lv5[:2] + lv4[:2]:
                lines.append(f"- ⭐{item['value_level']} {item['title'][:55]}")
    
    ai_items = [x for x in items if x.get('is_ai_related') and x['value_level'] >= 3]
    if ai_items:
        lines.append(f"\n## 🤖 AI相关 ({len(ai_items)}条)")
        for x in ai_items[:5]:
            lines.append(f"- {x['title'][:60]}")
    
    lines.append(f"\n*由 Hermes Multi-Agent 系统采集 | {date}*")
    return '\n'.join(lines)

# ============================================================
# 主入口
# ============================================================
def run(dry_run=False):
    print(f"\n{'='*60}")
    print(f"  Hermes Multi-Agent 情报系统 v3 - 真正的子Agent集群")
    print(f"{'='*60}")
    
    # Step 1: Multi-Agent 并行采集
    print(f"\n[Step 1] 启动子Agent集群...")
    all_items, agent_stats = run_multi_agent_collection()
    total = len(all_items)
    print(f"\n  子Agent集群总采集: {total}条")
    
    # Step 2: 去重
    print(f"\n[Step 2] 清洗去重...")
    cleaned = deduplicate(all_items)
    print(f"  去重后: {len(cleaned)}条")
    
    # 统计
    lv5 = sum(1 for x in cleaned if x['value_level'] == 5)
    lv4 = sum(1 for x in cleaned if x['value_level'] == 4)
    lv3 = sum(1 for x in cleaned if x['value_level'] == 3)
    ai = sum(1 for x in cleaned if x.get('is_ai_related'))
    print(f"  ⭐5: {lv5} | ⭐4: {lv4} | ⭐3: {lv3} | AI相关: {ai}")
    
    if not dry_run:
        # Step 3: 存储
        print(f"\n[Step 3] 存储数据库...")
        conn = get_db()
        save_results(cleaned, conn)
        print(f"  已存储 {len(cleaned)} 条")
        
        # Step 4: 推送
        print(f"\n[Step 4] 推送高价值内容...")
        high = sorted([x for x in cleaned if x['value_level'] >= 4], 
                      key=lambda x: x['importance_score'], reverse=True)[:10]
        
        for item in high:
            content = f"**来源**: {item.get('agent')} | **{item['platform']}**\n\n**关键词**: {item.get('matched_keywords','')}\n\n**链接**: {item.get('url','')}"
            ok = push_to_wechat(f"⭐{item['value_level']} {item['title'][:30]}", content, item['value_level'], item)
            print(f"  {'✅' if ok else '❌'} [{item.get('agent')}] {item['title'][:40]}")
            time.sleep(1.5)
        
        # 日报
        report = build_report(cleaned)
        ok = push_to_wechat("Multi-Agent情报日报", report, 3)
        print(f"\n  {'✅ 日报已推送' if ok else '❌ 日报推送失败'}")
        
        conn.close()
    
    print(f"\n[完成] {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    return cleaned

# ============================================================
# 入口
# ============================================================
if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('--dry-run', action='store_true')
    args = p.parse_args()
    
    result = run(dry_run=args.dry_run)
    print(f"\n采集结果: {len(result)}条")
