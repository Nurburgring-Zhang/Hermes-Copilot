#!/usr/bin/env python3
"""
Hermes 全平台智能情报系统
===========================
采集 → 清洗 → 评估 → 存储 → 推送

Usage:
  python hermes_intelligence.py              # 完整流程
  python hermes_intelligence.py --dry-run    # 仅评估不推送
  python hermes_intelligence.py --urgent     # 仅推送紧急信息
"""
import urllib.request, json, time, sqlite3, re, os, sys
from datetime import datetime, timedelta
from html import unescape

DB_PATH = os.path.expanduser("~/.hermes/intelligence.db")
PUSHPLUS_URL = "https://www.pushplus.plus/send"
PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "a8f1526d8ec84ef59aa37fe72fa1ab7f")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/html, */*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

def get_db():
    import sqlite3
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

# ========== 采集函数 ==========
def fetch_bilibili():
    items = []
    regions = [
        ("全站", "https://api.bilibili.com/x/web-interface/ranking/v2?rid=0&type=all"),
        ("科技", "https://api.bilibili.com/x/web-interface/ranking/v2?rid=36&type=all"),
        ("游戏", "https://api.bilibili.com/x/web-interface/ranking/v2?rid=4&type=all"),
        ("汽车", "https://api.bilibili.com/x/web-interface/ranking/v2?rid=223&type=all"),
        ("生活", "https://api.bilibili.com/x/web-interface/ranking/v2?rid=160&type=all"),
        ("运动", "https://api.bilibili.com/x/web-interface/ranking/v2?rid=21&type=all"),
    ]
    for region, url in regions:
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode('utf-8'))
            for item in data.get('data', {}).get('list', []):
                stat = item.get('stat', {})
                title = unescape(item.get('title', ''))
                if len(title) < 5:
                    continue
                pub_time = item.get('pubdate', 0)
                items.append({
                    "title": title, "content": item.get('desc', ''),
                    "url": f"https://www.bilibili.com/video/{item.get('bvid', '')}",
                    "platform": "bilibili", "source": f"B站-{region}",
                    "author": item.get('owner', {}).get('name', ''),
                    "author_id": str(item.get('owner', {}).get('mid', '')),
                    "category": item.get('tname', region),
                    "hot_score": float(stat.get('view', 0)),
                    "view_count": stat.get('view', 0), "like_count": stat.get('like', 0),
                    "collect_count": stat.get('favorite', 0), "comment_count": stat.get('reply', 0),
                    "share_count": stat.get('share', 0),
                    "published_at": datetime.fromtimestamp(pub_time).isoformat() if pub_time else None,
                    "raw_data": json.dumps(item, ensure_ascii=False)
                })
            time.sleep(0.3)
        except:
            pass
    return items

def fetch_weibo():
    items = []
    try:
        req = urllib.request.Request("https://weibo.com/ajax/side/hotSearch", headers=HEADERS)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode('utf-8'))
        for item in data.get('data', {}).get('realtime', []):
            title = unescape(item.get('note', ''))
            if len(title) < 5:
                continue
            items.append({
                "title": title, "content": item.get('word_scheme', ''),
                "url": f"https://s.weibo.com/weibo?q={item.get('note', '')}",
                "platform": "weibo", "source": "微博热搜",
                "author": "", "author_id": "", "category": item.get('category', '热搜'),
                "hot_score": float(item.get('raw_hot', 0)), "view_count": 0,
                "like_count": 0, "comment_count": item.get('num', 0),
                "collect_count": 0, "share_count": 0, "published_at": None,
                "raw_data": json.dumps(item, ensure_ascii=False)
            })
    except:
        pass
    return items

def fetch_github_trending():
    items = []
    for lang in ["python", "typescript", "javascript", "go", "rust"]:
        try:
            url = f"https://api.github.com/search/repositories?q=stars:>500+created:>2024-01-01&sort=stars&order=desc&per_page=20"
            if lang: url += f"+language:{lang}"
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode('utf-8'))
            for repo in data.get('items', [])[:20]:
                items.append({
                    "title": f"[GitHub] {repo.get('full_name', '')}",
                    "content": repo.get('description', '') or '',
                    "url": repo.get('html_url', ''),
                    "platform": "github", "source": f"GitHub-{lang}",
                    "author": repo.get('owner', {}).get('login', ''),
                    "author_id": str(repo.get('owner', {}).get('id', '')),
                    "category": f"code-{lang}",
                    "hot_score": float(repo.get('stargazers_count', 0)),
                    "view_count": 0, "like_count": repo.get('stargazers_count', 0),
                    "collect_count": repo.get('forks_count', 0),
                    "comment_count": repo.get('open_issues_count', 0),
                    "share_count": 0, "published_at": repo.get('created_at', ''),
                    "raw_data": json.dumps(repo, ensure_ascii=False)
                })
            time.sleep(0.5)
        except:
            pass
    return items

def fetch_solidot():
    items = []
    try:
        req = urllib.request.Request("https://www.solidot.org/index.rss", headers=HEADERS)
        with urllib.request.urlopen(req, timeout=10) as resp:
            content = resp.read().decode('utf-8', errors='ignore')
        titles = re.findall(r'<title><!\[CDATA\[(.*?)\]\]></title>', content)
        links = re.findall(r'<link>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</link>', content)
        descriptions = re.findall(r'<description><!\[CDATA\[(.*?)\]\]></description>', content)
        pubdates = re.findall(r'<pubDate>(.*?)</pubDate>', content)
        for i, title in enumerate(titles):
            if i == 0 and '<?xml' in title: continue
            title = unescape(title.strip())
            if len(title) < 5: continue
            items.append({
                "title": title,
                "content": unescape(descriptions[i].strip()) if i < len(descriptions) else '',
                "url": links[i].strip() if i < len(links) else '',
                "platform": "solidot", "source": "Solidot",
                "author": "", "author_id": "", "category": "tech",
                "hot_score": 1000, "view_count": 0, "like_count": 0,
                "comment_count": 0, "collect_count": 0, "share_count": 0,
                "published_at": pubdates[i].strip() if i < len(pubdates) else None,
                "raw_data": "{}"
            })
    except:
        pass
    return items

def fetch_oschina():
    items = []
    try:
        req = urllib.request.Request("https://www.oschina.net/news/rss", headers=HEADERS)
        with urllib.request.urlopen(req, timeout=10) as resp:
            content = resp.read().decode('utf-8', errors='ignore')
        titles = re.findall(r'<title><!\[CDATA\[(.*?)\]\]></title>', content)
        links = re.findall(r'<link>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</link>', content)
        descriptions = re.findall(r'<description><!\[CDATA\[(.*?)\]\]></description>', content)
        pubdates = re.findall(r'<pubDate>(.*?)</pubDate>', content)
        for i, title in enumerate(titles):
            if i == 0 and '<?xml' in title: continue
            title = unescape(title.strip())
            if len(title) < 5: continue
            items.append({
                "title": title,
                "content": unescape(descriptions[i].strip()) if i < len(descriptions) else '',
                "url": links[i].strip() if i < len(links) else '',
                "platform": "oschina", "source": "开源中国",
                "author": "", "author_id": "", "category": "tech",
                "hot_score": 1000, "view_count": 0, "like_count": 0,
                "comment_count": 0, "collect_count": 0, "share_count": 0,
                "published_at": pubdates[i].strip() if i < len(pubdates) else None,
                "raw_data": "{}"
            })
    except:
        pass
    return items

def fetch_ithome():
    items = []
    try:
        req = urllib.request.Request("https://www.ithome.com/", headers=HEADERS)
        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read().decode('utf-8', errors='ignore')
        pattern = re.compile(r'<a href="(https://www\.ithome\.com/d/(\d+)\.html)" class="title">([^<]+)</a>')
        seen = set()
        for url, _, title in pattern.findall(html):
            title = unescape(title.strip())
            if len(title) < 8 or title in seen: continue
            seen.add(title)
            items.append({
                "title": title, "content": "", "url": url,
                "platform": "ithome", "source": "IT之家",
                "author": "", "author_id": "", "category": "tech",
                "hot_score": 1000, "view_count": 0, "like_count": 0,
                "comment_count": 0, "collect_count": 0, "share_count": 0,
                "published_at": None, "raw_data": "{}"
            })
    except:
        pass
    return items[:50]

# ========== 评估函数 ==========
NOISE_KW = ["明星","娱乐","八卦","绯闻","综艺","演唱会","粉丝","游戏","主播","赛事"]
HIGH_KW = [
    "AI","LLM","大模型","GPT","Claude","Gemini","OpenAI","Anthropic","Google","Meta",
    "发布","开源","突破","颠覆","革命","新模型","新功能","融资","收购","独角兽",
    "技术","架构","框架","系统","平台","漏洞","安全","攻击","机器人","自动驾驶",
    "科学","物理","化学","生物","医学","太空","军事","战争","国际形势",
    "开源","GitHub","HuggingFace","模型","训练","微调","GPU","芯片","半导体",
    "新能源汽车","电动车","iPhone","Android","华为","小米","苹果",
]

def is_noise(title, content):
    text = (title+content).lower()
    return sum(1 for kw in NOISE_KW if kw.lower() in text) >= 2

def get_chinese_ratio(text):
    c = len(re.findall(r'[\u4e00-\u9fff]', text))
    return c/len(text) if len(text) > 0 else 0

def evaluate(item):
    title, content = item.get('title',''), item.get('content','')
    hot = item.get('hot_score',0)
    plat = item.get('platform','')
    text = (title+content).lower()
    
    score = 0.0
    matched_kw = [kw for kw in HIGH_KW if kw.lower() in text]
    score += len(matched_kw) * 5
    
    if plat == 'github':
        score += 15 if hot > 10000 else (10 if hot > 1000 else 0)
    elif plat == 'bilibili':
        score += 15 if hot > 5000000 else (10 if hot > 1000000 else 5 if hot > 100000 else 0)
    elif plat in ('solidot','oschina','ithome'):
        score += 8
    
    score += 5 if item.get('like_count',0) > 10000 else 0
    score += 5 if item.get('comment_count',0) > 1000 else 0
    
    item['chinese_ratio'] = get_chinese_ratio(title+content)
    item['language'] = 'zh' if item['chinese_ratio'] > 0.5 else 'en'
    
    if len(matched_kw) >= 4 and score >= 30: level = 5
    elif len(matched_kw) >= 3 and score >= 20: level = 4
    elif len(matched_kw) >= 2 and score >= 15: level = 3
    elif len(matched_kw) >= 1 and score >= 10: level = 2
    else: level = 1
    
    item['importance_score'] = round(score, 1)
    item['value_level'] = level
    item['value_reasons'] = f"关键词: {','.join(matched_kw[:3])}"
    item['is_ai_related'] = 1 if any(kw in text for kw in ['AI','LLM','GPT','大模型','模型','神经']) else 0
    return item

def clean_dedup(items):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT title FROM cleaned_intelligence WHERE cleaned_at > datetime('now','-1 days')")
    existing = set(r[0].lower() for r in c.fetchall())
    conn.close()
    seen = set()
    result = []
    for item in items:
        t = item.get('title','').strip()
        if len(t) < 8 or t.lower() in seen or t.lower() in existing: continue
        if is_noise(t, item.get('content','')): continue
        seen.add(t.lower())
        result.append(item)
    return result

def save_all(all_items, evaluated):
    conn = get_db()
    c = conn.cursor()
    for item in all_items:
        try:
            c.execute("""INSERT INTO raw_intelligence 
                (title,content,url,platform,source,author,category,hot_score,view_count,like_count,comment_count,published_at,raw_data)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (item['title'],item.get('content',''),item.get('url',''),item['platform'],
                 item['source'],item.get('author',''),item.get('category',''),
                 item.get('hot_score',0),item.get('view_count',0),item.get('like_count',0),
                 item.get('comment_count',0),item.get('published_at'),item.get('raw_data','{}')))
        except: pass
    for item in evaluated:
        try:
            c.execute("""INSERT INTO cleaned_intelligence 
                (title,content,url,source,platform,author,category,importance_score,value_level,value_reasons,is_ai_related,language,chinese_ratio,published_at,collected_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'))""",
                (item['title'],item.get('content',''),item.get('url',''),item['source'],
                 item['platform'],item.get('author',''),item.get('category',''),
                 item['importance_score'],item['value_level'],item.get('value_reasons',''),
                 item.get('is_ai_related',0),item.get('language','zh'),item.get('chinese_ratio',1.0),
                 item.get('published_at')))
        except: pass
    conn.commit()
    conn.close()

def push_wechat(title, content, level=3):
    emoji = {5:"🚨🚨🚨",4:"🔥🔥",3:"📣",2:"📌",1:"📝"}
    data = {"token":PUSHPLUS_TOKEN,"title":f"{emoji.get(level,'📣')} {title}","content":content,"channel":"wechat","template":"markdown"}
    try:
        req = urllib.request.Request(PUSHPLUS_URL, data=json.dumps(data).encode(), headers={'Content-Type':'application/json'})
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except: return {"code":-1}

def build_report(items):
    high = [x for x in items if x['value_level']>=4]
    medium = [x for x in items if x['value_level']==3]
    date = datetime.now().strftime('%Y-%m-%d %H:%M')
    lines = [f"# 📊 全平台情报日报 | {date}","","**采集**: {}条 | **高价值**: {}条 | **中等**: {}条".format(len(items),len(high),len(medium)),""]
    if high:
        lines += ["---","","## 🚨 极端/重要信息",""] 
        for i,item in enumerate(high[:8],1):
            e = "🚨" if item['value_level']==5 else "🔥"
            lines += [f"{e} **{i}. {item['title'][:55]}**",f"   - 📍{item['source']} | ⭐{item['importance_score']} | {item.get('value_reasons','')[:50]}",""]
    if medium:
        lines += ["---","","## 📣 中等价值内容",""] 
        for i,item in enumerate(medium[:5],1):
            lines += [f"{i}. {item['title'][:60]}","   📍 {item['source']}",""]
    ai_items = [x for x in items if x.get('is_ai_related')]
    if ai_items:
        lines += ["---","",f"## 🤖 AI相关 ({len(ai_items)}条)",""] + [f"- {x['title'][:60]} [{x['source']}]" for x in ai_items[:5]] + [""]
    lines += ["---",f"*由 Hermes 全自动采集 | {date}*"]
    return '\n'.join(lines)

def run(dry_run=False, urgent_only=False):
    print(f"\n[Step 1] 采集...")
    all_items = []
    for name, func in [("B站",fetch_bilibili),("微博",fetch_weibo),("GitHub",fetch_github_trending),
                        ("Solidot",fetch_solidot),("开源中国",fetch_oschina),("IT之家",fetch_ithome)]:
        try:
            items = func()
            print(f"  {name}: +{len(items)}")
            all_items.extend(items)
        except Exception as e:
            print(f"  {name}: 失败")
    print(f"  总计: {len(all_items)}条")
    if not all_items: return
    
    print("[Step 2] 清洗...")
    cleaned = clean_dedup(all_items)
    print(f"  清洗后: {len(cleaned)}条")
    
    print("[Step 3] 评估...")
    evaluated = sorted([evaluate(i) for i in cleaned], key=lambda x: x['importance_score'], reverse=True)
    for lv in sorted(set(x['value_level'] for x in evaluated), reverse=True):
        print(f"  ⭐{lv}: {sum(1 for x in evaluated if x['value_level']==lv)}条")
    
    if not dry_run:
        print("[Step 4] 存储...")
        save_all(all_items, evaluated)
        
        print("[Step 5] 推送...")
        for item in [x for x in evaluated if x['value_level']>=4][:5]:
            c = f"**{item['title']}**\n\n来源: {item['source']}\n平台: {item['platform']}\n\n{item.get('value_reasons','')}"
            r = push_wechat(f"⭐{item['value_level']}级情报", c, item['value_level'])
            print(f"  {'✅' if r.get('code')==200 else '❌'} {item['title'][:40]}")
            time.sleep(2)
        
        report = build_report(evaluated)
        r = push_wechat("全平台情报日报", report, 3)
        print(f"  {'✅ 报告已推送' if r.get('code')==200 else '❌ 报告失败'}")

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('--dry-run', action='store_true')
    p.add_argument('--urgent', action='store_true')
    args = p.parse_args()
    run(dry_run=args.dry_run, urgent_only=args.urgent)
