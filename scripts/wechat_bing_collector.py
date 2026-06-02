#!/usr/bin/env python3
"""
微信公众号采集器 v7 - Bing搜索+微信直访方案
解决Sogou CAPTCHA问题: 用Bing替代Sogou

策略:
1. Bing搜索 "site:mp.weixin.qq.com {keyword}" → 提取文章URLs
2. 直接访问每个URL → 提取标题,内容,作者
3. 每10个关键词换新browser context (避免CAPTCHA)
4. 120+关键词覆盖全方向
"""

import asyncio, re, hashlib, time, random, sqlite3
from datetime import datetime
from typing import List, Dict
from playwright.async_api import async_playwright
from urllib.parse import quote

HERMES_DIR = "/home/administrator/.hermes"
DB_PATH = f"{HERMES_DIR}/intelligence.db"

# 120+关键词覆盖用户偏好全方向
KEYWORDS = [
    # AI/AIGC/LLM (20)
    "AI大模型", "ChatGPT", "AIGC", "LLM大模型", "GPT-4", "Claude AI", "Gemini AI", 
    "Copilot AI", "AI训练", "AI微调", "AI开发", "AI编程", "OpenAI", "DeepSeek", "Kimi AI",
    "Qwen大模型", "AI Agent", "RAG检索", "Embedding", "大模型开源", "AI行业应用",
    # IT/手机/PC (20)
    "iPhone", "华为手机", "小米手机", "OPPO手机", "vivo手机", "三星手机", "荣耀手机",
    "笔记本电脑", "Mac电脑", "Windows系统", "电脑评测", "数码评测", "旗舰手机",
    "折叠屏手机", "骁龙芯片", "天玑芯片", "iOS18", "Android15", "影像旗舰",
    # 新能源汽车 (15)
    "特斯拉", "比亚迪", "问界汽车", "蔚来汽车", "小鹏汽车", "小米汽车", "理想汽车",
    "智驾系统", "电动汽车", "自动驾驶", "问界M9", "小米SU7", "极氪汽车", "腾势汽车", "智己汽车",
    # 格斗/竞技体育 (10)
    "UFC", "拳击", "MMA", "自由搏击", "NBA", "CBA篮球", "足球", "网球", "马拉松", "电竞比赛",
    # 军事/国际形势 (10)
    "军事装备", "战斗机", "航空母舰", "俄乌战争", "中美关系", "国际新闻", "地缘政治", "台海局势", "南海问题", "导弹防御",
    # 摄影/艺术 (10)
    "人像摄影", "风光摄影", "AI绘画", "StableDiffusion", "Midjourney", "数字艺术", " Blender", "艺术展览", "相机评测", "镜头推荐",
    # 开发/开源 (10)
    "GitHub", "开源项目", "Python开发", "Rust语言", "Go语言", "前端开发", "后端架构", "Kubernetes", "Docker", "云原生",
    # 科技/消费电子 (10)
    "量子计算", "芯片技术", "光刻机", "脑机接口", "基因编辑", "机器人", "无人机", "智能手表", "AR眼镜", "游戏主机",
    # 娱乐/社会 (10)
    "电影推荐", "Netflix", "热门剧集", "明星八卦", "网红打卡", "旅游景点", "美食探店", "社会热点", "热搜新闻", "舆情分析",
    # 游戏/潮流 (10)
    "王者荣耀", "英雄联盟", "Steam新游戏", "Switch游戏", "PlayStation", "Xbox游戏", "手游推荐", "游戏评测", "潮玩", "手办模型",
    # 健康/生活方式 (5)
    "健身训练", "营养饮食", "睡眠健康", "心理健康", "户外运动",
]

STEALTH = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});
Object.defineProperty(navigator, 'languages', {get: () => ['zh-CN','zh','en']});
window.chrome = {runtime: {}};
delete navigator.__proto__.webdriver;
"""

UA_POOL = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/121.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/121.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:122.0) Gecko/20100101 Firefox/122.0',
]

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
    if any(k in text for k in ['llm','gpt','chatgpt','aigc','ai','大模型','模型','训练','微调']): tags.append("AI")
    if any(k in text for k in ['手机','iphone','android','小米','华为','oppo','vivo']): tags.append("Mobile")
    if any(k in text for k in ['新能源','电动','特斯拉','比亚迪','智驾']): tags.append("EV")
    if any(k in text for k in ['ufc','拳击','格斗','mma','NBA','篮球','足球']): tags.append("Sports")
    if any(k in text for k in ['军事','战争','装备','战斗机','航母']): tags.append("Military")
    if any(k in text for k in ['摄影','相机','绘画','艺术']): tags.append("Art")
    if any(k in text for k in ['github','开源','程序员','python','rust','开发']): tags.append("Dev")
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
                item.get('platform', 'baidu_wechat'),
                item.get('title','')[:500],
                item.get('content','')[:2000],
                url[:1000], h,
                item.get('author',''), item.get('author_id',''),
                item.get('published_at', now), now,
                item.get('hot_score', 0), 'bing_wechat_v7',
                detect_lang(item.get('title',''), item.get('content','')),
                extract_tags(item.get('title',''), item.get('content',''))
            ))
            if db.total_changes > 0: new_count += 1
        except: pass
    db.commit()
    db.close()
    return new_count

async def extract_article_info(page, url: str) -> Dict:
    """直接访问微信文章URL,提取标题+作者"""
    try:
        resp = await page.goto(url, wait_until='domcontentloaded', timeout=10000)
        if not resp or resp.status != 200:
            return None
        
        await page.wait_for_timeout(1500)
        content = await page.content()
        
        # 检查是否需要验证
        if any(x in content for x in ['验证','安全','投诉','违规']):
            return None
        
        # 提取标题
        title_m = re.search(r'<h1[^>]*id=["\']activity-name["\'][^>]*>([^<]+)</h1>', content)
        if not title_m:
            title_m = re.search(r'<title[^>]*>([^<]+)</title>', content)
        title = title_m.group(1).strip() if title_m else ''
        
        # 提取作者
        author_m = re.search(r'id=["\']js_name["\'][^>]*>([^<]+)<', content)
        if not author_m:
            author_m = re.search(r'class=["\']account[^"\']*["\'][^>]*>([^<]+)<', content)
        author = author_m.group(1).strip() if author_m else ''
        
        if not title or len(title) < 5:
            return None
        
        return {
            'title': title,
            'author': author,
            'url': url
        }
    except:
        return None

async def collect_wechat_v7(kw_limit: int = 60) -> List[Dict]:
    """Bing搜索+微信直访"""
    results = []
    keywords = KEYWORDS[:kw_limit]
    
    # 每10个关键词换新context
    batch_size = 10
    batches = [keywords[i:i+batch_size] for i in range(0, len(keywords), batch_size)]
    
    print(f"总关键词: {len(keywords)}, 分{len(batches)}批 × {batch_size}个")
    
    async with async_playwright() as p:
        for batch_idx, batch in enumerate(batches):
            print(f"\n[Batch {batch_idx+1}/{len(batches)}]", flush=True)
            
            browser = None
            try:
                browser = await p.chromium.launch(
                    headless=True,
                    args=['--disable-blink-features=AutomationControlled','--no-sandbox','--disable-dev-shm-usage']
                )
                ctx = await browser.new_context(
                    user_agent=random.choice(UA_POOL),
                    locale='zh-CN',
                )
                page = await ctx.new_page()
                await page.add_init_script(script=STEALTH)
                page.set_default_timeout(15000)
                
                # 先访问Bing首页
                try:
                    await page.goto('https://www.bing.com/', wait_until='domcontentloaded', timeout=10000)
                    await page.wait_for_timeout(1500)
                except:
                    pass
                
                batch_results = []
                
                for kw_idx_on, kw in enumerate(batch):
                    try:
                        # Bing搜索
                        search_url = f'https://www.bing.com/search?q={quote(kw + " site:mp.weixin.qq.com")}&first=0'
                        await page.goto(search_url, wait_until='domcontentloaded', timeout=12000)
                        await page.wait_for_timeout(random.uniform(1.5, 3))
                        
                        content = await page.content()
                        
                        # 检测CAPTCHA
                        if any(x in content.lower() for x in ['captcha','验证码']):
                            print(f"  CAPTCHA at '{kw}', 跳过此批", flush=True)
                            break
                        
                        # 提取微信文章URL
                        article_urls = re.findall(r'https?://mp\.weixin\.qq\.com/s[?/][a-zA-Z0-9_-]{10,30}', content)
                        article_urls = list(dict.fromkeys(article_urls))  # 去重保持顺序
                        
                        n_urls = len(article_urls)
                        print(f"  [{batch_idx*batch_size+kw_idx_on+1}] '{kw}': {n_urls} URLs", flush=True)
                        
                        if n_urls == 0:
                            continue
                        
                        # 访问前3个文章URL提取标题
                        for art_url in article_urls[:3]:
                            info = await extract_article_info(page, art_url)
                            if info:
                                batch_results.append({
                                    'platform': 'baidu_wechat',
                                    'title': info['title'],
                                    'content': f"Bing KW:{kw}",
                                    'url': info['url'],
                                    'author': info['author'],
                                    'author_id': '',
                                    'published_at': now_str(),
                                    'hot_score': 100,
                                    'source_type': 'bing_wechat_v7',
                                    'category_tags': extract_tags(info['title'], kw)
                                })
                        
                        # Bing搜索之间延迟
                        await page.wait_for_timeout(random.uniform(1.5, 3))
                        
                    except Exception as e:
                        print(f"  [{batch_idx*batch_size+kw_idx_on+1}] '{kw}': ERROR {str(e)[:40]}", flush=True)
                        continue
                
                results.extend(batch_results)
                print(f"  本批: +{len(batch_results)} articles", flush=True)
                
            except Exception as e:
                print(f"Batch {batch_idx+1} ERROR: {e}", flush=True)
            
            finally:
                if browser:
                    await browser.close()
            
            # 批次间隔(让Bing冷却)
            if batch_idx < len(batches) - 1:
                wait = random.uniform(6, 12)
                print(f"  间隔{wait:.1f}s...", flush=True)
                await asyncio.sleep(wait)
    
    return results

async def run():
    print("="*60)
    print("微信公众号采集器 v7 - Bing搜索+微信直访")
    print("="*60)
    start = time.time()
    
    items = await collect_wechat_v7(kw_limit=60)
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
        
        # 显示样本
        print("\n样本:")
        for item in unique[:5]:
            print(f"  [{item['source_type']}] {item['title'][:60]}")
    else:
        print("WARNING: No articles!")

if __name__ == "__main__":
    asyncio.run(run())
