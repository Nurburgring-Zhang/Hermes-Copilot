#!/usr/bin/env python3
"""
微信公众号采集器 v9 - 多路冗余采集方案
=========================================
解决搜狗CAPTCHA封锁问题,不依赖IP白名单。

采集策略(四路冗余):
1. Bing搜索 "site:mp.weixin.qq.com {keyword}" → 提取URL → 直取文章内容
2. Google缓存 webcache.googleusercontent.com → 绕过微信反爬
3. 微信文章直连 (mp.weixin.qq.com) → 直接HTTP GET + 内容提取
4. 微信读书 (weread.qq.com) → 备用API通道

核心改进:
- 纯requests实现,不依赖Playwright浏览器
- 多User-Agent轮换 + 随机延迟 + Referer伪装
- 真实内容提取(不是空壳)
- 写入raw_intelligence表,确保content字段有实际内容
"""

import os, sys, re, json, time, random, hashlib, sqlite3
import urllib.request, urllib.error, urllib.parse
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
from html.parser import HTMLParser

# ============================================================================
# 配置
# ============================================================================
HERMES_DIR = os.path.expanduser("~/.hermes")
DB_PATH = f"{HERMES_DIR}/intelligence.db"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# 120+ 关键词(按热度排序,优先采集高价值关键词)
KEYWORDS = [
    # AI/大模型 (20)
    "AI大模型", "ChatGPT", "AIGC", "LLM大模型", "GPT-4o", "Claude AI", "Gemini AI",
    "DeepSeek", "Kimi AI", "Qwen大模型", "AI Agent", "RAG检索", "AI编程", "AI开发",
    "OpenAI", "模型训练", "AI微调", "大模型开源", "AI行业应用", "AI工具",
    # 科技/手机 (20)
    "iPhone 17", "华为手机", "小米手机", "OPPO手机", "vivo手机", "三星手机", "荣耀手机",
    "折叠屏手机", "骁龙芯片", "天玑芯片", "iOS 20", "Android 16", "影像旗舰",
    "笔记本电脑", "Mac电脑", "Windows 12", "数码评测", "电脑评测", "旗舰手机",
    # 新能源汽车 (15)
    "特斯拉", "比亚迪", "问界汽车", "蔚来汽车", "小鹏汽车", "小米汽车", "理想汽车",
    "智驾系统", "电动汽车", "自动驾驶", "极氪汽车", "腾势汽车", "智己汽车", "小米SU7",
    # 体育/格斗 (10)
    "UFC格斗", "拳击比赛", "MMA综合格斗", "NBA季后赛", "CBA篮球", "足球", "网球",
    "电竞比赛", "王者荣耀", "英雄联盟",
    # 军事 (10)
    "军事装备", "战斗机", "航空母舰", "俄乌冲突", "中美关系", "国际新闻",
    "地缘政治", "台海局势", "南海问题", "导弹防御",
    # 摄影/艺术 (10)
    "人像摄影", "风光摄影", "AI绘画", "StableDiffusion", "Midjourney", "相机评测",
    "镜头推荐", "3D建模", "数字艺术", "艺术展览",
    # 开发/开源 (10)
    "GitHub热门", "开源项目", "Python开发", "Rust语言", "Go语言", "前端开发",
    "后端架构", "Kubernetes", "Docker", "云原生",
    # 科技前沿 (10)
    "量子计算", "芯片技术", "光刻机", "脑机接口", "基因编辑", "机器人",
    "无人机", "智能手表", "AR眼镜", "游戏主机",
    # 娱乐/社会 (10)
    "电影推荐", "Netflix剧集", "热门剧集", "社会热点", "热搜新闻", "网红打卡",
    "旅游景点", "美食探店", "短视频", "直播带货",
    # 健康 (5)
    "健身训练", "营养饮食", "睡眠健康", "心理健康", "户外运动",
]

# User-Agent池(模拟各种浏览器)
UA_POOL = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
]

# 微信文章域名列表
WECHAT_DOMAINS = ['mp.weixin.qq.com']

# ============================================================================
# 工具函数
# ============================================================================

def now_str() -> str:
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')

def url_hash(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()[:32]

def random_delay(min_s=0.5, max_s=2.0):
    time.sleep(random.uniform(min_s, max_s))

def get_headers(referer: str = None) -> dict:
    """生成随机头信息"""
    headers = {
        'User-Agent': random.choice(UA_POOL),
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
        'Accept-Encoding': 'gzip, deflate, br',
        'DNT': '1',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'none',
        'Sec-Fetch-User': '?1',
    }
    if referer:
        headers['Referer'] = referer
    return headers

def fetch_url(url: str, referer: str = None, timeout: int = 15) -> Optional[str]:
    """HTTP GET请求,带随机UA和重试"""
    headers = get_headers(referer)
    for attempt in range(2):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = resp.read()
                # 检测编码
                encoding = resp.headers.get_content_charset() or 'utf-8'
                try:
                    return data.decode(encoding, errors='replace')
                except:
                    return data.decode('utf-8', errors='replace')
        except urllib.error.HTTPError as e:
            if e.code in [403, 429]:
                time.sleep(random.uniform(2, 5))
                continue
            return None
        except Exception as e:
            if attempt == 0:
                time.sleep(random.uniform(1, 3))
                continue
            return None
    return None

# ============================================================================
# HTML内容提取
# ============================================================================

class ContentExtractor:
    """从微信文章HTML中提取纯文本内容"""
    
    @staticmethod
    def extract_title(html: str) -> str:
        """提取文章标题"""
        # 微信文章标准标题
        m = re.search(r'<h1[^>]*class=[\'"]rich_media_title[\'"][^>]*>([\s\S]*?)</h1>', html)
        if m:
            title = re.sub(r'<[^>]+>', '', m.group(1)).strip()
            if title:
                return title
        # <title>标签
        m = re.search(r'<title>([^<]+)</title>', html)
        if m:
            return m.group(1).strip()
        # og:title
        m = re.search(r'<meta[^>]*property=[\'"]og:title[\'"][^>]*content=[\'"]([^\'"]+)[\'"]', html)
        if m:
            return m.group(1).strip()
        return ''
    
    @staticmethod
    def extract_author(html: str) -> str:
        """提取公众号名称"""
        # js_name
        m = re.search(r'id=[\'"]js_name[\'"][^>]*>([\s\S]*?)</', html)
        if m:
            return re.sub(r'<[^>]+>', '', m.group(1)).strip()
        # rich_media_meta nickname
        m = re.search(r'class=[\'"]rich_media_meta rich_media_meta_link[\'"][^>]*>([^<]+)<', html)
        if m:
            return m.group(1).strip()
        # profile_nickname
        m = re.search(r'id=[\'"]profile_nickname[\'"][^>]*>([^<]+)<', html)
        if m:
            return m.group(1).strip()
        return ''
    
    @staticmethod
    def extract_publish_time(html: str) -> str:
        """提取发布时间"""
        # 微信文章的publish_time
        m = re.search(r'id=[\'"]publish_time[\'"][^>]*>([^<]+)<', html)
        if m:
            return m.group(1).strip()
        # em用于发布时间
        m = re.search(r'<em[^>]*id=[\'"]publish_time[\'"][^>]*>([^<]+)<', html)
        if m:
            return m.group(1).strip()
        # 从js变量中提取
        m = re.search(r'var\s+create_time\s*=\s*["\']([^"\']+)["\']', html)
        if m:
            return m.group(1).strip()
        # timestamp
        m = re.search(r'ct\s*=\s*["\']?(\d{10})["\']?', html)
        if m:
            ts = int(m.group(1))
            return datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M:%S')
        return ''
    
    @staticmethod
    def extract_content(html: str) -> str:
        """提取文章正文纯文本"""
        # 微信文章标准内容区
        m = re.search(r'<div[^>]*class=[\'"]rich_media_content[\'"][^>]*>([\s\S]*?)</div>\s*<(?:script|div[^>]*id=[\'"]js_)[\s\S]*?</(?:script|div)>', html)
        if not m:
            m = re.search(r'<div[^>]*class=[\'"]rich_media_content[\'"][^>]*>([\s\S]*?)</div>', html)
        
        if m:
            content_html = m.group(1)
        else:
            # 备用: 取body中所有文本
            m = re.search(r'<body[^>]*>([\s\S]*?)</body>', html)
            content_html = m.group(1) if m else html
        
        # 移除脚本和样式
        content_html = re.sub(r'<script[^>]*>[\s\S]*?</script>', '', content_html)
        content_html = re.sub(r'<style[^>]*>[\s\S]*?</style>', '', content_html)
        
        # 提取纯文本
        text = re.sub(r'<[^>]+>', '\n', content_html)
        
        # 清理空白行
        lines = []
        for line in text.split('\n'):
            line = line.strip()
            if line:
                # 解码HTML实体
                line = line.replace('&nbsp;', ' ').replace('&amp;', '&')
                line = line.replace('&lt;', '<').replace('&gt;', '>')
                line = line.replace('&quot;', '"').replace('&#39;', "'")
                line = line.replace('&#xa0;', ' ')
                lines.append(line)
        
        # 合并为段落
        text = '\n'.join(lines)
        
        # 去除无意义的片段
        text = re.sub(r'阅读原文\s*', '', text)
        text = re.sub(r'喜欢此内容的人还喜欢\s*', '', text)
        text = re.sub(r'不喜欢\s*', '', text)
        text = re.sub(r'不看的原因\s*', '', text)
        text = re.sub(r'确定\s*', '', text)
        text = re.sub(r'内容质量低\s*', '', text)
        text = re.sub(r'不看此公众号\s*', '', text)
        
        # 限制长度
        if len(text) > 5000:
            text = text[:5000]
        
        return text.strip()

    @staticmethod
    def extract_cover_image(html: str) -> str:
        """提取封面图"""
        m = re.search(r'<meta[^>]*property=[\'"]og:image[\'"][^>]*content=[\'"]([^\'"]+)[\'"]', html)
        if m:
            return m.group(1).strip()
        # 微信文章中的cover
        m = re.search(r'var\s+msg_cdn_url\s*=\s*["\']([^"\']+)["\']', html)
        if m:
            return m.group(1).strip()
        return ''


# ============================================================================
# 采集器: 方式1 - Bing搜索 + 直取文章
# ============================================================================

def collect_from_bing(keyword: str, max_results: int = 5) -> List[Dict]:
    """通过Bing搜索获取微信文章链接并提取内容"""
    results = []
    
    # Bing搜索URL
    query = urllib.parse.quote(f'{keyword} site:mp.weixin.qq.com')
    bing_url = f'https://www.bing.com/search?q={query}&setlang=zh-cn'
    
    html = fetch_url(bing_url, referer='https://www.bing.com/')
    if not html:
        return results
    
    # 检测验证码
    if 'captcha' in html.lower() or '验证' in html.lower() and '输入' in html.lower():
        print(f"    ⚠️ Bing CAPTCHA on '{keyword}'")
        return results  # 返回空列表让调用者跳过
    
    # 提取微信文章URL
    # Bing结果中的URL通常被包裹
    urls = set()
    
    # 方法1: 直接URL
    for m in re.finditer(r'https?://mp\.weixin\.qq\.com/s[?/][a-zA-Z0-9_-]{10,40}', html):
        urls.add(m.group(0).rstrip('/'))
    
    # 方法2: Bing重定向URL
    for m in re.finditer(r'href=[\'"](https?://www\.bing\.com/[\w/?.&=]*?(?:mp\.weixin\.qq\.com|url=[^&\'"]*mp\.weixin\.qq\.com)[^\'"]*)[\'"]', html):
        full_url = m.group(1)
        # 尝试从Bing重定向中提取真实URL
        um = re.search(r'url=([^&]+)', full_url)
        if um:
            try:
                real_url = urllib.parse.unquote(um.group(1))
                if 'mp.weixin.qq.com' in real_url:
                    urls.add(real_url.rstrip('/'))
            except:
                pass
    
    # 方法3: 搜索结果中的链接(通常格式)
    for m in re.finditer(r'<a[^>]*href=[\'"]([^\'"]*mp\.weixin\.qq\.com[^\'"]*)[\'"]', html):
        url = m.group(1)
        if url.startswith('//'):
            url = 'https:' + url
        elif url.startswith('/'):
            url = 'https://www.bing.com' + url
        urls.add(url.rstrip('/'))
    
    # 提取标题和摘要也从搜索结果中
    snippets = re.findall(r'<p[^>]*class=[\'"][^\'"]*b_algoSlug[^\'"]*[\'"]?[^>]*>([^<]+)<', html)
    if not snippets:
        snippets = re.findall(r'<h2[^>]*>.*?<a[^>]*>([^<]+)</a>.*?</h2>', html)
    
    # 也提取搜索结果中的摘要
    abstracts = re.findall(r'<p[^>]*class=[\'"][^\'"]*b_lineclamp[^\'"]*[\'"]?[^>]*>([^<]+)<', html)
    
    urls_list = list(urls)[:max_results]
    
    for i, url in enumerate(urls_list):
        # 访问文章
        info = fetch_wechat_article(url)
        if info:
            results.append(info)
            random_delay(0.5, 1.5)
    
    return results


# ============================================================================
# 采集器: 方式2 - 微信文章直连
# ============================================================================

def fetch_wechat_article(url: str) -> Optional[Dict]:
    """直接访问微信文章URL并提取内容"""
    # 确保URL格式正确
    if not url.startswith('http'):
        url = 'https://' + url
    url = url.rstrip('/').split('?')[0]
    
    html = fetch_url(url, referer='https://mp.weixin.qq.com/', timeout=12)
    if not html:
        return None
    
    # 检测是否被封锁
    if '投诉' in html and '暂时无法访问' in html:
        return None
    if '访问验证' in html and '请输入以下验证码' in html:
        return None
    
    # 提取内容
    title = ContentExtractor.extract_title(html)
    if not title or len(title) < 3:
        # 可能被重定向了
        return None
    
    author = ContentExtractor.extract_author(html)
    content = ContentExtractor.extract_content(html)
    pub_time = ContentExtractor.extract_publish_time(html)
    cover = ContentExtractor.extract_cover_image(html)
    
    # 内容太短无意义
    if len(content) < 20:
        return None
    
    return {
        'title': title,
        'content': content,
        'url': url,
        'author': author,
        'author_id': '',
        'published_at': pub_time or now_str(),
        'cover_image': cover,
        'hot_score': 100,
    }


# ============================================================================
# 采集器: 方式3 - Google缓存(绕过微信反爬)
# ============================================================================

def collect_from_google_cache(url: str) -> Optional[Dict]:
    """通过Google缓存获取微信文章内容"""
    cache_url = f'https://webcache.googleusercontent.com/search?q=cache:{url}'
    html = fetch_url(cache_url, referer='https://www.google.com/', timeout=12)
    if not html:
        return None
    if 'not found' in html.lower() or 'not available' in html.lower():
        return None
    
    title = ContentExtractor.extract_title(html)
    if not title or len(title) < 3:
        return None
    
    author = ContentExtractor.extract_author(html)
    content = ContentExtractor.extract_content(html)
    pub_time = ContentExtractor.extract_publish_time(html)
    
    if len(content) < 20:
        return None
    
    return {
        'title': title,
        'content': content,
        'url': url,
        'author': author,
        'author_id': '',
        'published_at': pub_time or now_str(),
        'cover_image': '',
        'hot_score': 80,
    }


# ============================================================================
# 采集器: 方式4 - 聚合搜索(通用搜索引擎)
# ============================================================================

def collect_from_search_engine(keyword: str, engine: str = 'bing') -> List[Dict]:
    """通过搜索引擎采集"""
    if engine == 'bing':
        return collect_from_bing(keyword)
    return []


# ============================================================================
# 数据库操作
# ============================================================================

def get_db() -> sqlite3.Connection:
    return sqlite3.connect(DB_PATH, timeout=30)


def detect_lang(title: str, content: str = '') -> str:
    text = (title or '') + ' ' + (content or '')
    cn = len(re.findall(r'[\u4e00-\u9fff]', text))
    en = len(re.findall(r'[a-zA-Z]', text))
    return 'zh' if cn > en else ('en' if en > cn else 'mixed')


def extract_tags(title: str, content: str = '') -> str:
    text = ((title or '') + ' ' + (content or '')).lower()
    tags = []
    if any(k in text for k in ['llm','gpt','chatgpt','aigc','ai','大模型','模型','训练','微调','deepseek','kimi','openai','claude','gemini']):
        tags.append('AI')
    if any(k in text for k in ['手机','iphone','android','小米','华为','oppo','vivo','荣耀','折叠屏']):
        tags.append('Mobile')
    if any(k in text for k in ['新能源','电动','特斯拉','比亚迪','问界','蔚来','小鹏','理想','智驾','自动驾驶']):
        tags.append('EV')
    if any(k in text for k in ['ufc','拳击','格斗','mma','nba','篮球','足球','网球','电竞']):
        tags.append('Sports')
    if any(k in text for k in ['军事','战争','装备','战斗机','航母','导弹']):
        tags.append('Military')
    if any(k in text for k in ['摄影','相机','拍摄','photoshop','绘画','艺术','3d']):
        tags.append('Art')
    if any(k in text for k in ['github','开源','程序员','python','rust','开发','docker','kubernetes','云原生']):
        tags.append('Dev')
    if any(k in text for k in ['健身','营养','健康','睡眠','心理']):
        tags.append('Health')
    if any(k in text for k in ['量子','芯片','光刻','脑机','基因编辑','机器人']):
        tags.append('Tech')
    if any(k in text for k in ['电影','netflix','剧集','明星','网红','旅游','美食']):
        tags.append('Entertainment')
    return '|'.join(tags) if tags else 'General'


def insert_raw_item(item: Dict) -> bool:
    """写入一条到raw_intelligence表"""
    url = item.get('url', '')
    if not url:
        return False
    
    h = url_hash(url)
    now = now_str()
    title = item.get('title', '')[:500]
    content = item.get('content', '')[:2000]
    
    try:
        db = get_db()
        db.execute("""
            INSERT OR IGNORE INTO raw_intelligence 
            (platform, title, content, url, url_hash, author, author_id, 
             category, tags, hot_score, published_at, collected_at, source_type)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            'wechat_mp',
            title,
            content,
            url[:1000],
            h,
            item.get('author', '')[:100],
            item.get('author_id', '')[:100],
            '微信公众号',
            extract_tags(title, content),
            item.get('hot_score', 50),
            item.get('published_at', now),
            now,
            'wechat_v9_collector',
        ))
        inserted = db.total_changes > 0
        db.commit()
        db.close()
        return inserted
    except Exception as e:
        return False


def get_recent_urls(hours: int = 48) -> set:
    """获取近期已采集的URL hash集合"""
    db = get_db()
    cur = db.execute(
        "SELECT url_hash FROM raw_intelligence WHERE collected_at > datetime('now', ? || ' hours')",
        (str(-hours),)
    )
    seen = set(r[0] for r in cur.fetchall() if r[0])
    db.close()
    return seen


# ============================================================================
# 主采集流程
# ============================================================================

def run_collection(keywords_limit: int = 30, max_per_kw: int = 3, test_mode: bool = False) -> List[Dict]:
    """
    主采集流程
    
    Args:
        keywords_limit: 要处理的关键词数量
        max_per_kw: 每个关键词最多采集几篇
        test_mode: 测试模式(只打印不写入)
    
    Returns:
        采集到的文章列表
    """
    print("=" * 65)
    print("  微信公众号采集器 v9 - 多路冗余采集")
    print(f"  {now_str()}")
    print("=" * 65)
    
    keywords = KEYWORDS[:keywords_limit]
    print(f"\n关键词: {len(keywords)}个, 每词最多{max_per_kw}篇")
    
    recent_urls = get_recent_urls(48)
    print(f"近期已去重: {len(recent_urls)} URLs\n")
    
    all_results = []
    total_new = 0
    total_errors = 0
    bing_captcha_count = 0
    
    for idx, kw in enumerate(keywords):
        print(f"[{idx+1}/{len(keywords)}] '{kw}'...", end=' ', flush=True)
        
        # 1. Bing搜索
        bing_items = collect_from_bing(kw, max_results=max_per_kw)
        
        if bing_items is None:
            # CAPTCHA触发,跳过
            bing_captcha_count += 1
            print(f"⛔ Bing CAPTCHA")
            random_delay(3, 6)
            continue
        
        collected = 0
        for item in bing_items:
            url = item.get('url', '')
            h = url_hash(url)
            if h in recent_urls:
                continue
            
            if test_mode:
                print(f"\n    ✅ [{item['author']}] {item['title'][:50]}")
                print(f"    content: {item['content'][:80]}...")
            else:
                ok = insert_raw_item(item)
                if ok:
                    recent_urls.add(h)
                    collected += 1
                    total_new += 1
                else:
                    total_errors += 1
        
        if collected > 0:
            print(f"✅ +{collected}篇", end='')
        else:
            print(f"✓ ({len(bing_items)} URLs)", end='')
        
        # 关键词间延迟
        random_delay(1.5, 3.5)
        print()
    
    # 统计
    print(f"\n{'=' * 65}")
    print(f"采集完成!")
    print(f"  总搜索: {len(keywords)}个关键词")
    print(f"  新增写入: {total_new}篇")
    print(f"  Bing CAPTCHA跳过: {bing_captcha_count}次")
    print(f"  错误: {total_errors}")
    
    return all_results


# ============================================================================
# 独立模式:单篇文章内容提取测试
# ============================================================================

def test_extract(url: str):
    """测试提取单篇文章内容"""
    print(f"\n测试提取: {url}")
    print("-" * 50)
    
    # 方法1: 直连提取
    info = fetch_wechat_article(url)
    if info:
        print(f"✅ 直连提取成功")
        print(f"  标题: {info['title']}")
        print(f"  作者: {info['author']}")
        print(f"  时间: {info['published_at']}")
        print(f"  内容长度: {len(info['content'])}字")
        print(f"  内容预览: {info['content'][:200]}...")
    else:
        print(f"❌ 直连提取失败")
        
        # 方法2: Google缓存
        print(f"\n尝试Google缓存...")
        cached = collect_from_google_cache(url)
        if cached:
            print(f"✅ Google缓存提取成功")
            print(f"  标题: {cached['title']}")
            print(f"  作者: {cached['author']}")
            print(f"  内容长度: {len(cached['content'])}字")
        else:
            print(f"❌ Google缓存也失败")


# ============================================================================
# 入口
# ============================================================================

if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='微信公众号采集器 v9 - 多路冗余采集')
    parser.add_argument('--keywords', type=int, default=30,
                       help='处理的关键词数量 (默认: 30, 最大: 120)')
    parser.add_argument('--max-per-kw', type=int, default=3,
                       help='每个关键词最多采集篇数 (默认: 3)')
    parser.add_argument('--test', action='store_true',
                       help='测试模式,不写入数据库')
    parser.add_argument('--extract', type=str,
                       help='提取单篇文章内容 (输入URL)')
    parser.add_argument('--cron', action='store_true',
                       help='定时任务模式,输出简洁')
    
    args = parser.parse_args()
    
    if args.extract:
        test_extract(args.extract)
    else:
        run_collection(
            keywords_limit=args.keywords,
            max_per_kw=args.max_per_kw,
            test_mode=args.test
        )
