#!/usr/bin/env python3
"""
今日头条采集器 v4 - 基于真实HTML结构分析
从HTML中提取: "title":"xxx" + group_id URL模式
"""

import asyncio, re, hashlib, time, random, sqlite3
from datetime import datetime
from typing import List, Dict
from playwright.async_api import async_playwright

HERMES_DIR = "/home/administrator/.hermes"
DB_PATH = f"{HERMES_DIR}/intelligence.db"

KEYWORDS = [
    # AI/科技 (20)
    "AI大模型", "ChatGPT", "AIGC", "LLM", "GPT-4", "Claude", "Gemini",
    "AI训练", "AI应用", "大模型", "深度学习", "OpenAI", "DeepSeek",
    "百度AI", "阿里通义", "字节AI", "Kimi", "智谱AI", "阶跃星辰", "AI编程", "AI开发",
    # IT/手机 (15)
    "iPhone", "华为手机", "小米手机", "OPPO", "vivo", "三星",
    "手机评测", "旗舰手机", "折叠屏", "骁龙8", "天玑9300", "鸿蒙系统", "iOS18", "Android15", "影像旗舰",
    # 汽车 (15)
    "特斯拉", "比亚迪", "小米汽车", "问界", "蔚来", "小鹏",
    "智驾", "自动驾驶", "新能源汽车", "极氪", "腾势", "理想汽车", "汽车评测", "车型对比", "电动车",
    # 体育/格斗 (10)
    "NBA", "CBA", "足球", "欧冠", "拳击", "UFC", "MMA", "格斗", "马拉松", "电竞",
    # 军事/国际 (10)
    "军事", "战斗机", "航母", "俄乌战争", "中美关系", "台海局势", "南海问题", "国际新闻", "地缘政治", "导弹防御",
    # 娱乐/社会 (10)
    "电影", "热播剧", "明星", "网红", "旅游", "美食", "社会热点", "热搜新闻", "舆情分析", "直播带货",
    # 摄影/游戏 (10)
    "摄影", "相机", "拍照技巧", "游戏", "主机游戏", "Steam", "Switch", "PlayStation", "Xbox", "手游推荐",
    # 科技/其他 (10)
    "量子计算", "芯片技术", "光刻机", "机器人", "无人机", "智能手表", "AR眼镜", "脑机接口", "3D打印", "新能源技术",
]

STEALTH = "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"

def url_hash(url):
    return hashlib.sha256(url.encode()).hexdigest()[:32]

def now_str():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')

def detect_lang(title, content=""):
    cn = len(re.findall(r'[\u4e00-\u9fff]', (title or "") + (content or "")))
    en = len(re.findall(r'[a-zA-Z]', (title or "") + (content or "")))
    return "zh" if cn > en else ("en" if en > cn else "mixed")

def extract_tags(title, content=""):
    text = ((title or "") + " " + (content or "")).lower()
    tags = []
    if any(k in text for k in ['llm','gpt','chatgpt','aigc','ai','大模型','模型']): tags.append("AI")
    if any(k in text for k in ['手机','iphone','android','小米','华为']): tags.append("Mobile")
    if any(k in text for k in ['新能源','电动','特斯拉','比亚迪','智驾']): tags.append("EV")
    if any(k in text for k in ['ufc','拳击','格斗','mma','NBA','篮球','足球']): tags.append("Sports")
    if any(k in text for k in ['军事','战争','装备','战斗机']): tags.append("Military")
    if any(k in text for k in ['摄影','相机','绘画','艺术']): tags.append("Art")
    if any(k in text for k in ['github','开源','程序员','python','rust']): tags.append("Dev")
    return "|".join(tags) if tags else "General"

def get_db():
    return sqlite3.connect(DB_PATH, timeout=30)

def insert_batch(items: List[Dict]) -> int:
    if not items: return 0
    db = get_db()
    new_count = 0
    now = now_str()
    for item in items:
        url = item.get('url', '')
        h = url_hash(url)
        try:
            db.execute("""
                INSERT OR IGNORE INTO raw_intelligence 
                (platform, title, content, url, url_hash, author, author_id, 
                 published_at, collected_at, hot_score, source_type, language, category_tags)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                'toutiao',
                item.get('title','')[:500],
                item.get('content','')[:2000],
                url[:1000], h,
                item.get('author',''), item.get('author_id',''),
                item.get('published_at', now), now,
                item.get('hot_score', 0), 'toutiao_browser_v4',
                detect_lang(item.get('title',''), item.get('content','')),
                extract_tags(item.get('title',''), item.get('content',''))
            ))
            if db.total_changes > 0: new_count += 1
        except: pass
    db.commit()
    db.close()
    return new_count

def parse_toutiao_page(content: str, kw: str) -> List[Dict]:
    """从toutiao搜索页HTML提取文章"""
    items = []
    
    # 提取group_id列表
    group_ids = re.findall(r'toutiao\.com/(?:a|group)/(\d{15,22})', content)
    group_ids = list(dict.fromkeys(group_ids))
    
    # 提取所有title (去除<em>标签)
    titles_with_em = re.findall(r'"title"\s*:\s*"([^"]{5,150})"', content)
    titles_clean = re.findall(r'"title"\s*:\s*"([^"]{5,150})"', content)
    
    # Clean titles: remove \u003cem\u003e and \u003c/em\u003e
    clean_titles = []
    for t in titles_clean:
        t2 = t.replace('\u003cem\u003e', '').replace('\u003c/em\u003e', '')
        if len(t2) >= 5 and t2 not in clean_titles:
            clean_titles.append(t2)
    
    # 也提取source/author
    sources = re.findall(r'"source"\s*:\s*"([^"]{2,30})"', content)
    
    # Build article dicts - pair group_ids with titles
    for i, gid in enumerate(group_ids[:20]):
        url = f'https://www.toutiao.com/a{gid}/'
        
        # Find closest title before this gid in the content
        gid_pattern = f'toutiao\\.com/a{gid}'
        pos = re.search(re.escape(gid_pattern), content)
        if pos:
            # Get 500 chars before gid for context
            start = max(0, pos.start() - 500)
            snippet = content[start:pos.start()]
            # Find title in this snippet
            title_matches = re.findall(r'"title"\s*:\s*"([^"]{5,150})"', snippet)
            if title_matches:
                last_title = title_matches[-1].replace('\u003cem\u003e', '').replace('\u003c/em\u003e', '')
            else:
                last_title = clean_titles[i] if i < len(clean_titles) else f"Article {gid}"
        else:
            last_title = clean_titles[i] if i < len(clean_titles) else f"Article {gid}"
        
        # Get source
        source = sources[i] if i < len(sources) else ''
        
        items.append({
            'title': last_title.strip()[:200],
            'url': url,
            'author': source,
            'source': kw
        })
    
    return items

async def collect_toutiao_v4(kw_limit: int = 50) -> List[Dict]:
    """头条v4: 正确提取group_id + title"""
    results = []
    keywords = KEYWORDS[:kw_limit]
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=['--disable-blink-features=AutomationControlled','--no-sandbox']
        )
        context = await browser.new_context(
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/121.0.0.0 Safari/537.36',
            locale='zh-CN',
        )
        page = await context.new_page()
        await page.add_init_script(script=STEALTH)
        page.set_default_timeout(20000)
        page.set_default_navigation_timeout(20000)
        
        for kw_idx, kw in enumerate(keywords):
            try:
                search_url = f'https://www.toutiao.com/search/?keyword={kw}'
                await page.goto(search_url, wait_until='networkidle', timeout=15000)
                await page.wait_for_timeout(random.uniform(2, 4))
                
                content = await page.content()
                parsed = parse_toutiao_page(content, kw)
                
                n = 0
                for item in parsed[:15]:
                    if len(item['title']) < 5:
                        continue
                    results.append({
                        'platform': 'toutiao',
                        'title': item['title'],
                        'content': f"Search:{kw}",
                        'url': item['url'],
                        'author': item['author'],
                        'author_id': '',
                        'published_at': now_str(),
                        'hot_score': 100 - n * 5,
                        'source_type': 'toutiao_v4',
                        'category_tags': extract_tags(item['title'], kw)
                    })
                    n += 1
                
                print(f"[{kw_idx+1}/{len(keywords)}] '{kw}': {n} articles (total:{len(results)})")
                
                await page.wait_for_timeout(random.uniform(1, 2))
                
            except Exception as e:
                print(f"[{kw_idx+1}/{len(keywords)}] '{kw}': ERROR {str(e)[:50]}")
                continue
        
        await browser.close()
    
    return results

async def run():
    print("="*60)
    print("今日头条采集器 v4 - group_id+title提取")
    print("="*60)
    start = time.time()
    
    items = await collect_toutiao_v4(kw_limit=50)
    elapsed = time.time() - start
    
    print(f"\n完成: {len(items)} articles in {elapsed:.0f}s")
    
    if items:
        seen = set()
        unique = []
        for item in items:
            h = url_hash(item['url'])
            if h not in seen:
                seen.add(h)
                unique.append(item)
        
        count = insert_batch(unique)
        print(f"去重后: {len(unique)}, 写入DB: {count} new records")
        
        print("\n样本:")
        for item in unique[:5]:
            print(f"  {item['title'][:70]}")
    else:
        print("WARNING: No articles!")

if __name__ == "__main__":
    asyncio.run(run())
