#!/usr/bin/env python3
"""
Hermes Unified Collector v5 - All Platforms
Supports 35+ platforms with terminal + browser fallback
"""

import sqlite3, json, re, hashlib, time, sys, os
import xml.etree.ElementTree as ET
from datetime import datetime
from urllib.request import Request, urlopen
from urllib.parse import quote, urlencode, urlparse, urlunparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import List, Dict, Tuple

# 自采集器导入
sys.path.insert(0, str(Path(__file__).parent))
try:
    from weixin_account_collector import collect_weixin_accounts
except ImportError as e:
    def collect_weixin_accounts(): print(f"  weixin_accounts unavailable: {e}"); return 0,0,0
try:
    from xiaohongshu_account_collector import collect_xiaohongshu_accounts
except ImportError as e:
    def collect_xiaohongshu_accounts(): print(f"  xiaohongshu unavailable: {e}"); return 0,0,0
try:
    from douyin_account_collector import collect_douyin_hot
except ImportError as e:
    def collect_douyin_hot(): print(f"  douyin unavailable: {e}"); return 0,0,0
try:
    from csdn_blog_collector import collect_csdn_blogs
except ImportError as e:
    def collect_csdn_blogs(): print(f"  csdn unavailable: {e}"); return 0,0,0

HERMES = Path("/home/administrator/.hermes")
DB_PATH = HERMES / "intelligence.db"

UA_POOL = [
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0",
]

def get_db():
    return sqlite3.connect(str(DB_PATH), timeout=30)

def init_db():
    # Just verify DB is accessible - tables already exist with actual schema
    db = get_db()
    db.execute("SELECT 1").fetchall()
    db.close()

def url_hash(url):
    return hashlib.sha256(url.encode()).hexdigest()[:32]

def detect_language(text):
    if not text:
        return "unknown"
    chinese = len(re.findall(r'[\u4e00-\u9fff]', text))
    english = len(re.findall(r'[a-zA-Z]', text))
    if chinese > english:
        return "zh"
    elif english > chinese:
        return "en"
    return "mixed"

def extract_tags(title, content=""):
    text = (title + " " + (content or "")).lower()
    tags = []
    # ═══ 格林主人40+方向全覆盖 ═══
    
    # AI / AIGC / LLM / 模型
    ai_kw = ['llm','gpt','chatgpt','aigc','ai','artificial intelligence','large language model',
             '大模型','模型','训练','微调','fine-tune','agent','rag','embedding','diffusion',
             'stable diffusion','midjourney','claude','gemini','copilot','cursor','openai',
             'anthropic','deepseek','qwen','kimi','智谱','glm','月之暗面','百川','零一万物',
             'minimax','通义','文心','星火','tensorflow','pytorch','transformers','huggingface',
             '神经网络','深度学习','机器学习','强化学习','rlhf','dpo','grpo','ppo',
             'sora','video generation','text-to-video','text-to-image','ai绘画','ai生成',
             'ai评测','benchmark','排行榜','arena','lmsys','superclue','ceval','mmlu']
    if any(k in text for k in ai_kw):
        tags.append("AI")
    
    # IT / 手机 / 消费电子 / 新潮电子
    if any(k in text for k in ['手机','iphone','android','小米','华为','oppo','vivo','三星',
                                '一加','荣耀','iPhone','MacBook','iPad','折叠屏','可折叠',
                                '智能穿戴','手表','手环','耳机','airpods','tws','平板',
                                '笔记本','电脑','pc','台式机','显示器','屏幕','oled',
                                'mini-led','芯片','soc','骁龙','天玑','a系列','m系列',
                                '英特尔','intel','amd','nvidia','显卡','rtx','gtx','主板',
                                '内存','ram','ssd','硬盘','存储']):
        tags.append("Mobile_PC")
    
    # 新能源汽车
    if any(k in text for k in ['新能源','电动汽车','特斯拉','tesla','比亚迪','byd','问界',
                                'aito','蔚来','nio','小鹏','xpeng','理想','li auto',
                                '极氪','zeekr','小米汽车','su7','yu7','智界','享界','阿维塔',
                                '电动车','ev','混动','phev','增程','充电','超充','换电',
                                '充电桩','电池','固态电池','锂电','刀片电池','续航',
                                '自动驾驶','autopilot','fsd','智能驾驶','智驾','激光雷达']):
        tags.append("EV")
    
    # 汽车 / 机车 / 汽车运动 / 越野
    if any(k in text for k in ['汽车','车型','发动机','变速箱','赛车','越野','摩托车','机车',
                                '本田','丰田','大众','宝马','奔驰','奥迪','保时捷','法拉利',
                                '兰博基尼','迈凯伦','路虎','jeep','哈雷','川崎','雅马哈',
                                'kawasaki','yamaha','harley','赛道','竞速','漂移','改装',
                                '自驾','房车','露营车']):
        tags.append("Auto")
    
    # 格斗 / 体育 / 竞技体育 / 篮球
    if any(k in text for k in ['ufc','mma','bellator','综合格斗','拳击','散打','泰拳','柔术',
                                '张伟丽','李景亮','骨头琼斯','康纳','嘴炮','ko','tko','降服',
                                '裸绞','十字固','自由搏击','武术','搏击','格斗',
                                'nba','cba','篮球','勒布朗','库里','詹姆斯','杜兰特','科比',
                                '足球','世界杯','欧冠','梅西','c罗','姆巴佩',
                                '羽毛球','乒乓球','游泳','田径','f1','方程式','motogp',
                                '奥运会','亚运会','体育','运动员']):
        tags.append("Sports_Fight")
    
    # 军事 / 战争 / 国际形势
    if any(k in text for k in ['军事','战争','武器','军队','航母','战斗机','导弹','火箭',
                                '船舶','潜艇','无人机军事','国防','军工','军演','北约','nato',
                                '台海','南海','东海','朝鲜','韩国','日本','印度',
                                '中东','乌克兰','俄罗斯','美国','中国','中美','中欧','欧盟',
                                '外交','制裁','地缘政治','国际形势','国际新闻','国际热点',
                                '联合国','世卫','恐怖','冲突','难民']):
        tags.append("Military_Intl")
    
    # 政治 / 社会热点
    if any(k in text for k in ['政治','总统','选举','议会','国会','国务院','政策','立法',
                                '法律','法规','民生','社保','医保','房价','教育','就业',
                                '人口','老龄化','生育']):
        tags.append("Politics")
    
    # 美女 / 性感写真 / 人像
    if any(k in text for k in ['写真','摄影','模特','model','超模','人像','肖像','街拍',
                                '性感','美女','网红','cosplay','cos','壁纸','wallpaper',
                                '时尚','fashion','穿搭','ootd','妆容','化妆','美妆','护肤',
                                '比基尼','泳装','内衣']):
        tags.append("Beauty_Photo")
    
    # 开发者 / 开源 / 编程
    if any(k in text for k in ['github','开源','open source','代码','编程','程序员','开发',
                                'api','框架','库','算法','数据结构','python','rust','golang',
                                'javascript','typescript','react','vue','docker','kubernetes',
                                '微服务','分布式','devops','ci/cd','git','linux','vscode',
                                'ide','编译器','debug','调试','测试','重构']):
        tags.append("Dev_OpenSource")
    
    # 机器人
    if any(k in text for k in ['机器人','robot','robotics','人形机器人','humanoid','机器狗',
                                '擎天柱','optimus','宇树','unitree','figure','boston dynamics',
                                '协作机器人','cobot','工业机器人','机器臂']):
        tags.append("Robot")
    
    # 太空 / 航天
    if any(k in text for k in ['太空','宇宙','航天','火箭','卫星','nasa','spacex','马斯克',
                                'spacex','星链','starlink','火星','月球','探测器','空间站',
                                '天文','黑洞','星系','行星','恒星']):
        tags.append("Space")
    
    # 安全 / 网络
    if any(k in text for k in ['安全','security','黑客','hacker','渗透','漏洞','cve',
                                'exploit','0day','加密','encryption','密码学','cryptography',
                                '隐私','数据安全','反诈','钓鱼','勒索','ransomware',
                                '防火墙','ids','ips','杀毒','antivirus']):
        tags.append("Security")
    
    # 游戏
    if any(k in text for k in ['游戏','gaming','game','steam','epic','ps5','playstation',
                                'xbox','switch','任天堂','nintendo','原神','genshin','王者',
                                '英雄联盟','lol','绝地求生','apex','valorant','csgo',
                                '3a','独立游戏','indie','游戏开发','game dev','unity','unreal',
                                '电竞','esports']):
        tags.append("Game")
    
    # 科学 / 科普 (物理/化学/生物/地理)
    if any(k in text for k in ['科学','science','研究','发现','论文','nature','science期刊',
                                '物理','化学','生物','biology','基因','基因组','dna','rna',
                                'crispr','量子','quantum','量子计算','材料','新材料','超导',
                                '地理','geography','地质','海洋','气候','环境','环保','ecosystem',
                                '进化','考古','化石','恐龙','古生物']):
        tags.append("Science")
    
    # 历史 / 人文 / 传统文化 / 非遗
    if any(k in text for k in ['历史','history','人文','文化','传统','非遗','非物质文化遗产',
                                '文物','博物馆','考古','朝代','古代','民国','抗战','丝绸之路',
                                '故宫','长城','石窟','壁画','书法','国画','戏曲','唐诗',
                                '宋词','四大发明','中医','节气']):
        tags.append("History_Culture")
    
    # 摄影 / 相机 / 艺术 / 绘画
    if any(k in text for k in ['摄影','拍照','相机','镜头','索尼','canon','尼康','nikon',
                                '富士','fujifilm','徕卡','leica','哈苏','hasselblad','胶片',
                                '数码','cmos','艺术','绘画','画作','油画','水彩','素描','国画',
                                '设计','graphic design','工艺美术','潮流','潮流艺术','街头艺术',
                                'graffiti','pop art','现代艺术','当代艺术','展览','美术馆',
                                '导演','film','cinematography']):
        tags.append("Photo_Art")
    
    # 电影 / 视频 / 剪辑
    if any(k in text for k in ['电影','movie','film','票房','上映','导演','演员','明星',
                                '好莱坞','hollywood','漫威','dc','netflix','迪士尼',
                                '奥斯卡','戛纳','金鸡','纪录片','动画电影',
                                '美剧','韩剧','日剧','英剧','TV series',
                                '视频','video','vlog','剪辑','编辑','premiere','final cut',
                                'davinci resolve','调色','特效','vfx','cg','动画']):
        tags.append("Movie_Video")
    
    # 音乐 / MV
    if any(k in text for k in ['音乐','music','mv','歌曲','歌手','专辑','演唱会','live',
                                '摇滚','流行','古典','h-pop','k-pop','乐队','吉他','钢琴',
                                'spotify','apple music','网易云','qq音乐']):
        tags.append("Music")
    
    # 旅游 / 文旅 / 美食 / 网红打卡
    if any(k in text for k in ['旅游','旅行','travel','酒店','民宿','度假','景点','景区',
                                '文旅','文化旅行','美食','food','餐厅','探店','小吃','网红',
                                '网红店','网红打卡','打卡','攻略','游记','自驾游','背包',
                                '出境','签证','护照','机场','航空']):
        tags.append("Travel_Food")
    
    # 科技通识
    if any(k in text for k in ['科技','技术','创新','研发','实验室','突破','革命性',
                                '前沿','尖端','未来','趋势','预测','数字','数字化']):
        tags.append("Tech")
    
    # 热点 / 爆款 / 热门视频
    if any(k in text for k in ['热搜','热点','热门','热门视频','爆款','爆火','刷屏','疯传',
                                'top','trending','viral','hottest','最火','霸榜']):
        tags.append("Hot")

    # 平台 / 应用 / 社交
    if any(k in text for k in ['youtube','telegram','discord','twitter','x.com','tiktok',
                                'instagram','facebook','linkedin','pinterest','medium',
                                '微信公众号','微信','抖音','快手','小红书','微博','b站',
                                'bilibili','知乎','csdn','博客','blog','civitai',
                                'modelscope','huggingface','github','reddit']):
        tags.append("Platform")
    
    if not tags:
        tags.append("General")
    return "|".join(tags)

# ===== 采集时过滤 — 命中关键词直接丢弃，不进库 =====
_FILTER_CACHE = None

def is_collect_filtered(title, content, source, platform):
    """
    采集时即过滤：命中任意 active 黑名单关键词，直接丢弃不进库。
    格林主人指令：黑名单关键词扫描到就直接拦截，不做采集。
    """
    global _FILTER_CACHE
    
    # 懒加载缓存
    if _FILTER_CACHE is None:
        try:
            db = get_db()
            rows = db.execute("""
                SELECT keyword FROM spam_filter_keywords 
                WHERE is_active = 1 AND severity >= 3
            """).fetchall()
            db.close()
            _FILTER_CACHE = [r[0].lower() for r in rows]
        except:
            _FILTER_CACHE = []
    
    if not title and not content:
        return False
    
    text = (title + " " + (content or "")[:500]).lower()
    
    # 检查所有active黑名单关键词
    for kw in _FILTER_CACHE:
        if kw in text:
            return True
    
    return False

    if any(k in text for k in ['视频','电影','剧集','综艺','bilibili','youtube','抖音','快手','直播']):
        tags.append("Video")
    if any(k in text for k in ['摄影','拍照','相机','镜头','艺术','绘画','设计','美学']):
        tags.append("Art")
    if any(k in text for k in ['篮球','足球','格斗','武术','搏击','mma','ufc','拳击','跑步','运动']):
        tags.append("Sports")
    return "|".join(tags) if tags else "General"

def insert_raw_item(item):
    if not item.get('url') or not item.get('title'):
        return False
    
    # ===== 采集时直接过滤：命中过滤词不进库 =====
    title = item.get('title','')
    content = item.get('content','')
    source = item.get('source', item.get('platform',''))
    platform = item.get('platform','')
    
    if is_collect_filtered(title, content, source, platform):
        return False
    
    # ===== 内容质量预筛：没实质内容的直接丢弃不进库 =====
    # 计算内容的有效信息量（去除非汉字/非英文的噪音字符）
    clean_content = re.sub(r'[\s\r\n\t<>/\[\]{}()=+#@$%^&*|\\;:\'\"~`]+', '', content).strip()
    clean_title = re.sub(r'[\s\r\n\t<>/\[\]{}()=+#@$%^&*|\\;:\'\"~`]+', '', title).strip()
    
    # 内容太短(有效字符<80)且不是特定短标题来源的 → 低质丢弃
    content_info_len = len(clean_content)
    title_info_len = len(clean_title)
    
    # 允许短内容的来源（这些来源天然就是短标题/摘要型）
    short_content_ok_sources = {'weibo', 'baidu', 'toutiao', 'tieba', 'solidot', 
                                 'hackernews', 'reddit', 'sina_tech',
                                 'zhihu', '36kr', 'bilibili', 'bilibili_tech',
                                 'baidu_hot', 'weibo_hot', 'weibo_search'}
    
    is_short_ok = platform in short_content_ok_sources or source in short_content_ok_sources
    
    # 判断标准：
    # 1. 内容完全没有实质信息（<80有效字符）且不是短内容来源 → 丢弃
    # 2. CSDN/blog来源内容<150有效字符 → 低质摘要，丢弃
    # 3. 标题有效字符<6且内容<100 → 丢弃（纯粹碎片的垃圾）
    if content_info_len < 80 and not is_short_ok:
        return False
    if content_info_len < 150 and ('blog' in source.lower() or platform in ('csdn', 'cnblogs', 'juejin', 'segmentfault', 'devto', 'oschina')):
        return False
    if title_info_len < 6 and content_info_len < 100:
        return False
    
    url_h = url_hash(item['url'])
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    try:
        db = get_db()
        db.execute("""
            INSERT OR IGNORE INTO raw_intelligence 
            (title,content,url,source,platform,author,author_id,category,tags,
             hot_score,view_count,like_count,collect_count,comment_count,share_count,
             published_at,collected_at,url_hash,source_type)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            item.get('title',''),
            item.get('content',''),
            item.get('url',''),
            item.get('source', item.get('platform','')),
            item.get('platform',''),
            item.get('author',''),
            item.get('author_id',''),
            item.get('category_tags',''),
            item.get('tags', item.get('category_tags','')),
            float(item.get('hot_score',0)),
            int(item.get('view_count',0)),
            int(item.get('like_count',0)),
            int(item.get('collect_count',0)),
            int(item.get('comment_count',0)),
            int(item.get('share_count',0)),
            item.get('published_at',now),
            now,
            url_h,
            item.get('source_type','terminal'),
        ))
        db.commit()
        new = db.total_changes > 0
        db.close()
        return new
    except Exception as e:
        return False

def insert_batch(items):
    if not items:
        return 0, 0
    total = len(items)
    new_count = sum(1 for item in items if insert_raw_item(item))
    return total, new_count

def _auto_encode_url(url):
    """URL-encode non-ASCII characters in URL path and query to prevent UnicodeEncodeError."""
    parsed = urlparse(url)
    # Encode path
    path = quote(parsed.path, safe='/:@!$&\'()*+,;=-._~')
    # Encode query string params
    query = ''
    if parsed.query:
        parts = []
        for pair in parsed.query.split('&'):
            if '=' in pair:
                k, v = pair.split('=', 1)
                # Only encode if it has non-ASCII chars, leave already-encoded alone
                if any(ord(c) > 127 for c in v) and not re.match(r'^[a-zA-Z0-9_.~-]+$', v):
                    v = quote(v, safe='')
                parts.append(f'{k}={v}')
            else:
                parts.append(pair)
        query = '&'.join(parts)
    return urlunparse((parsed.scheme, parsed.netloc, path, parsed.params, query, parsed.fragment))

def fetch(url, headers=None, timeout=15, post_data=None):
    ua = UA_POOL[int(time.time()) % len(UA_POOL)]
    h = {"User-Agent": ua}
    if headers:
        h.update(headers)
    try:
        url = _auto_encode_url(url)
        req = Request(url, data=post_data.encode() if post_data else None, headers=h)
        with urlopen(req, timeout=timeout) as resp:
            ct = resp.headers.get('content-type','')
            charset = 'utf-8'
            if 'charset=' in ct:
                charset = ct.split('charset=')[-1].split(';')[0].strip()
            return resp.read().decode(charset, errors='replace')
    except:
        return ""

def parse_rss(xml_text):
    items = []
    try:
        # Remove BOM (Zero-Width No-Break Space) that causes parse failures
        clean = xml_text.lstrip('\ufeff').lstrip('\ufffe').lstrip('\u200b')
        # Remove CDATA sections and fix common XML issues
        clean = re.sub(r'<!\[CDATA\[|\]\]>','',clean)
        # Fix undefined XML entities that cause parse failures (e.g. &#8211; in iFanr/TMTPost)
        import html
        # Replace numeric HTML entities that may be undefined
        clean = re.sub(r'&#[0-9]+;', lambda m: html.unescape(m.group()), clean)
        clean = re.sub(r'&#[xX][0-9a-fA-F]+;', lambda m: html.unescape(m.group()), clean)
        # Replace named HTML entities not defined in XML (&nbsp;, &mdash;, etc.)
        # First preserve XML built-in entities, then unescape everything else
        def safe_unescape(m):
            e = m.group(1)
            if e in ('amp','lt','gt','quot','apos'):
                return m.group(0)  # keep XML entities intact
            return html.unescape(m.group(0))
        clean = re.sub(r'&([a-zA-Z][a-zA-Z0-9]*);', safe_unescape, clean)
        root = ET.fromstring(clean)
        channel = root.find('channel') if root.find('channel') is not None else root
        # Also try to find Atom entries (for Atom feeds like cnblogs)
        all_items = channel.findall('.//item')
        if not all_items:
            # Try Atom namespace prefix
            all_items = channel.findall('.//{http://www.w3.org/2005/Atom}entry')
        if not all_items:
            # Try without namespace
            all_items = channel.findall('.//entry')
        for item in all_items:
            title = (item.findtext('title') or '').strip()
            # For Atom, link might be in href attribute
            link = (item.findtext('link') or '').strip()
            if not link:
                link_elem = item.find('link')
                if link_elem is not None:
                    link = link_elem.get('href', '')
            pub = (item.findtext('pubDate') or item.findtext('published') or item.findtext('updated') or '').strip()
            desc = (item.findtext('description') or item.findtext('summary') or item.findtext('content') or '').strip()
            desc = re.sub(r'<[^>]+>','',desc)[:500]
            if title and link:
                items.append({'title':title,'url':link,'content':desc,'published_at':pub})
    except Exception as e:
        pass
    return items

# ======== Platform Collectors ========

def collect_weibo_hot():
    items = []
    out = fetch("https://weibo.com/ajax/side/hotSearch", {
        "User-Agent":"Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)",
        "Referer":"https://weibo.com/","X-Requested-With":"XMLHttpRequest"
    })
    if not out:
        return items
    try:
        d = json.loads(out)
        for item in d.get("data",{}).get("realtime",[]):
            word = item.get('word',item.get('note',''))
            num = item.get('num',item.get('raw_hot',0))
            label = item.get('label_name','')
            items.append({
                'platform':'weibo','title':word,
                'content':f"Label:{label} Score:{num}",
                'url':f"https://s.weibo.com/weibo?q={word}&Refer=index",
                'author':'','author_id':'','published_at':datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'hot_score':int(num),'source_type':'api','category_tags':'Weibo|Hot|Trend'
            })
        for item in d.get("data",{}).get("hotgov",{}).get('bindings',[]):
            word = item.get('word','')
            num = item.get('num',0)
            if word:
                items.append({
                    'platform':'weibo','title':word,
                    'content':f"Rank:{item.get('rank','')} Score:{num}",
                    'url':f"https://s.weibo.com/weibo?q={word}&Refer=index",
                    'author':'','author_id':'','published_at':datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'hot_score':int(num),'source_type':'api','category_tags':'Weibo|Hot'
                })
    except Exception as e:
        print(f"  Weibo failed: {e}")
    return items

def collect_weibo_military():
    """微博军事频道内容采集 — 通过搜索军事关键词获取"""
    items = []
    keywords = [
        "军事", "国防", "台海", "军演", "航母", "战机",
        "解放军", "军队", "国防部", "兵器", "导弹",
        "国际军事", "军事新闻", "陆军", "海军", "空军",
        "俄乌战争", "中东局势", "朝鲜半岛", "南海"
    ]
    for kw in keywords[:10]:
        try:
            out = fetch(f"https://s.weibo.com/weibo?q={kw}&Refer=index", {
                "User-Agent":"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                "Referer":"https://weibo.com"
            })
            if not out or len(out) < 100:
                continue
            titles = re.findall(r'<p class="txt"[^>]*>(.*?)</p>', out, re.DOTALL)
            links = re.findall(r'<a href="(/weibo[^"&\s]*)\?', out)
            for i, content in enumerate(titles[:10]):
                title = re.sub(r'<[^>]+>', '', content).strip()
                if len(title) < 10:
                    continue
                link = links[i] if i < len(links) else ''
                items.append({
                    'platform':'weibo_military', 'title':title[:120],
                    'content':f"KW:{kw}",
                    'url':f"https://s.weibo.com{link}" if link.startswith('/weibo') else link,
                    'author':'', 'author_id':'', 'published_at':datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'hot_score':0, 'source_type':'search', 'category_tags':'Weibo|Military|News'
                })
            time.sleep(0.5)
        except:
            continue
    return items

def collect_zhihu_hot():
    items = []
    out = fetch("https://www.zhihu.com/api/v4/creators/rank/hot?domain=0&limit=20", {
        "User-Agent":"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
    })
    if not out:
        return items
    try:
        d = json.loads(out)
        for entry in d.get("data",[]):
            q = entry.get("question",{})
            title = q.get("title","")
            q_url = q.get("url","")
            vote = entry.get("reaction",{}).get("voteCount",0)
            answer = entry.get("reaction",{}).get("commentCount",0)
            if title:
                items.append({
                    'platform':'zhihu','title':title,
                    'content':f"Votes:{vote} Answers:{answer}",
                    'url':q_url if q_url.startswith('http') else f"https://www.zhihu.com{q_url}",
                    'author':q.get('author',{}).get('name',''),
                    'author_id':q.get('author',{}).get('id',''),
                    'published_at':datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'hot_score':int(vote)*10+int(answer),
                    'source_type':'api','category_tags':'Zhihu|Hot'
                })
    except Exception as e:
        print(f"  Zhihu failed: {e}")
    return items

def collect_36kr():
    items = []
    out = fetch("https://36kr.com/api/newsflash?per_page=30&page=1", {
        "User-Agent":"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Content-Type":"application/json","Referer":"https://36kr.com/"
    })
    if not out:
        return items
    try:
        d = json.loads(out)
        for item in d.get("data",{}).get("items",[]):
            title = item.get("title","")
            url = item.get("news_url",item.get("url",""))
            if not url:
                url = f"https://36kr.com/newsflashes/{item.get('item_id','')}"
            items.append({
                'platform':'36kr','title':title,
                'content':item.get("intro",""),
                'url':url,
                'author':item.get("author",""),'author_id':'',
                'published_at':item.get("published_at",""),
                'hot_score':item.get("hot_score",0),
                'source_type':'api','category_tags':'36kr|Tech|News'
            })
    except Exception as e:
        print(f"  36kr failed: {e}")
    return items

def collect_ithome():
    items = []
    out = fetch("https://www.ithome.com/rss/")
    if not out:
        return items
    for item in parse_rss(out):
        items.append({
            'platform':'ithome','title':item['title'],'content':item['content'],
            'url':item['url'],'author':'','author_id':'',
            'published_at':item['published_at'],'hot_score':0,
            'source_type':'rss','category_tags':'ITHouse|Tech'
        })
    return items

def collect_oschina():
    items = []
    out = fetch("https://www.oschina.net/news/rss")
    if not out:
        return items
    for item in parse_rss(out):
        items.append({
            'platform':'oschina','title':item['title'],'content':item['content'],
            'url':item['url'],'author':'','author_id':'',
            'published_at':item['published_at'],'hot_score':0,
            'source_type':'rss','category_tags':'OSChina|OpenSource|Dev'
        })
    return items

def collect_bilibili():
    items = []
    out = fetch("https://api.bilibili.com/x/web-interface/ranking/v2?type=all&rid=0", {
        "User-Agent":"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
    })
    if not out:
        return items
    try:
        d = json.loads(out)
        for v in d.get("data",{}).get("list",[]):
            stat = v.get("stat",{})
            items.append({
                'platform':'bilibili','title':v.get("title",""),'content':v.get("desc","") or v.get("title",""),
                'url':f"https://www.bilibili.com/video/{v.get('bvid','')}",
                'author':v.get("owner",{}).get("name",""),
                'author_id':str(v.get("owner",{}).get("mid","")),
                'published_at':datetime.fromtimestamp(v.get("pubdate",0)).strftime('%Y-%m-%d %H:%M:%S') if v.get("pubdate") else '',
                'hot_score':stat.get("view",0),
                'source_type':'api','category_tags':'Bilibili|Video'
            })
    except Exception as e:
        print(f"  Bilibili failed: {e}")
    return items

def collect_bilibili_tech():
    """B站科技区内容采集 — 尝试API和页面爬取两种方式"""
    items = []
    # 尝试1: B站API — rid=14是科技分区, 参考 https://api.bilibili.com/x/web-interface/ranking/v2?rid=14&type=all
    for rid in [14, 0, 1]:
        try:
            out = fetch(f"https://api.bilibili.com/x/web-interface/ranking/v2?rid={rid}&type=all", {
                "User-Agent":"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                "Referer":"https://www.bilibili.com/"
            })
            if out:
                d = json.loads(out)
                data_list = d.get("data",{}).get("list",[])
                if data_list:
                    for v in data_list:
                        stat = v.get("stat",{})
                        tname = v.get("tname","")
                        items.append({
                            'platform':'bilibili_tech','title':v.get("title",""),
                            'content':v.get("desc","") or v.get("title",""),
                            'url':f"https://www.bilibili.com/video/{v.get('bvid','')}",
                            'author':v.get("owner",{}).get("name",""),
                            'author_id':str(v.get("owner",{}).get("mid","")),
                            'published_at':datetime.fromtimestamp(v.get("pubdate",0)).strftime('%Y-%m-%d %H:%M:%S') if v.get("pubdate") else '',
                            'hot_score':stat.get("view",0),
                            'source_type':'api','category_tags':'Bilibili|Tech|Science'
                        })
                    if items:
                        break
        except:
            continue
    # 备用方案: 如果API无结果，爬取科技区页面
    if not items:
        try:
            out = fetch("https://www.bilibili.com/v/popular/science/", {
                "User-Agent":"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                "Referer":"https://www.bilibili.com/"
            })
            if out:
                titles = re.findall(r'"title":"([^"]{5,150})"', out)
                urls = re.findall(r'"url":"(//www\.bilibili\.com/video/[^"]+)"', out)
                for i, title in enumerate(titles[:15]):
                    url = f"https:{urls[i]}" if i < len(urls) else ""
                    items.append({
                        'platform':'bilibili_tech','title':title,
                        'content':title,'url':url,
                        'author':'','author_id':'',
                        'published_at':'','hot_score':0,
                        'source_type':'html','category_tags':'Bilibili|Tech|Science'
                    })
        except:
            pass
    return items

def collect_toutiao():
    items = []
    out = fetch("https://www.toutiao.com/api/pc/feed/?category=__all__&count=20&source=input", {
        "User-Agent":"Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)"
    })
    if not out:
        return items
    try:
        d = json.loads(out)
        for item in d.get("data",[]):
            if isinstance(item,dict):
                title = item.get("title","")
                url = item.get("article_url",item.get("url",""))
                if not url:
                    url = f"https://www.toutiao.com/a{item.get('item_id','')}"
                items.append({
                    'platform':'toutiao','title':title,
                    'content':item.get("abstract","") or title,
                    'url':url,
                    'author':item.get("media_name",""),'author_id':'',
                    'published_at':item.get("datetime",""),
                    'hot_score':item.get("hot_score",0),
                    'source_type':'api','category_tags':'Toutiao|News'
                })
    except Exception as e:
        print(f"  Toutiao failed: {e}")
    return items

def collect_toutiao_military():
    """头条军事频道 — 采集军事/时政类内容"""
    items = []
    # 头条军事频道API，使用category=military或搜索军事关键词
    # 尝试用头条通用feed加category过滤获取军事内容
    out = fetch("https://www.toutiao.com/api/pc/feed/?category=military&count=20&source=input", {
        "User-Agent":"Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)"
    })
    if out:
        try:
            d = json.loads(out)
            for item in d.get("data",[]):
                if isinstance(item,dict):
                    title = item.get("title","")
                    url = item.get("article_url",item.get("url",""))
                    if not url:
                        url = f"https://www.toutiao.com/a{item.get('item_id','')}"
                    items.append({
                        'platform':'toutiao_military','title':title,
                        'content':item.get("abstract","") or title,
                        'url':url,
                        'author':item.get("media_name",""),'author_id':'',
                        'published_at':item.get("datetime",""),
                        'hot_score':item.get("hot_score",0),
                        'source_type':'api','category_tags':'Toutiao|Military|News'
                    })
        except Exception as e:
            print(f"  Toutiao military failed: {e}")
    # Fallback: 如果API无返回，尝试从军事频道web页面抓取
    if not items:
        out2 = fetch("https://www.toutiao.com/ch/military/", {
            "User-Agent":"Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)"
        })
        if out2:
            titles = re.findall(r'"title":"([^"]{5,120})"', out2)
            urls = re.findall(r'"article_url":"(https?://[^"]+)"', out2)
            for i, title in enumerate(titles[:20]):
                url = urls[i] if i < len(urls) else ""
                items.append({
                    'platform':'toutiao_military','title':title,
                    'content':title,'url':url,
                    'author':'','author_id':'',
                    'published_at':'','hot_score':0,
                    'source_type':'html','category_tags':'Toutiao|Military|News'
                })
    return items

def collect_sogou_wechat():
    items = []
    keywords = [
        "AI大模型","ChatGPT","人工智能","LLM大模型","AIGC","AGI",
        "新能源汽车","电动汽车","特斯拉","比亚迪","华为汽车","问界",
        "手机评测","iPhone","小米手机","华为手机","OPPO vivo",
        "科技热点","数码科技","IT科技","技术突破","科技创新",
        "程序员","软件开发","开源项目","GitHub","代码","编程",
        "机器人","人工智能机器人","宇树","特斯拉机器人","人形机器人",
        "太空探索","NASA","SpaceX","嫦娥","天宫","火星",
        "国际新闻","美国大选","俄乌战争","中东局势","欧盟",
        "格斗比赛","MMA","UFC","拳击","自由搏击","武术",
        "篮球NBA","CBA","詹姆斯","库里","足球世界杯",
        "摄影技巧","相机评测","人像摄影","风光摄影","手机摄影",
        "电影推荐","最新电影","票房","Netflix","美剧",
        "游戏资讯","Steam","原神","黑神话","switch","PS5",
        "旅游攻略","网红打卡","美食探店","小众旅行","文旅",
        "绘画欣赏","数字艺术","AI绘画","插画","设计灵感",
    ]
    for kw in keywords[:25]:
        try:
            out = fetch(f"https://weixin.sogou.com/weixin?type=2&query={kw}&ie=utf8", {
                "User-Agent":"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
            })
            if not out or len(out) < 200:
                continue
            titles = re.findall(r'<h3[^>]*>.*?<a[^>]*>(.*?)</a>', out, re.DOTALL)
            links = re.findall(r'<h3[^>]*>.*?<a[^>]*href="(https?://[^"]+)"', out, re.DOTALL)
            dates = re.findall(r'<span[^>]*class="s2"[^>]*>(.*?)</span>', out, re.DOTALL)
            for i,(title,link) in enumerate(zip(titles,links)):
                title = re.sub(r'<[^>]+>','',title).strip()
                if len(title) < 5:
                    continue
                date = dates[i] if i < len(dates) else ''
                items.append({
                    'platform':'sogou_wechat','title':title,
                    'content':f"Source:WeChat KW:{kw}",
                    'url':link if link.startswith('http') else f"https://weixin.sogou.com{link}",
                    'author':'','author_id':'','published_at':date,
                    'hot_score':0,'source_type':'search',
                    'category_tags':extract_tags(title)
                })
            time.sleep(0.3)
        except:
            continue
    return items

def collect_infoq_rss():
    """Collect InfoQ RSS - tech news"""
    items = []
    for url in ["https://www.infoq.cn/feed","https://feed.infoq.cn/"]:
        out = fetch(url, {"User-Agent":"Mozilla/5.0"})
        if out and ('<rss' in out or '<feed' in out):
            for item in parse_rss(out):
                items.append({
                    'platform':'infoq','title':item['title'],'content':item['content'],
                    'url':item['url'],'author':'','author_id':'',
                    'published_at':item['published_at'],'hot_score':0,
                    'source_type':'rss','category_tags':'InfoQ|Tech|News'
                })
            if items:
                break
    return items

def collect_techmeme_rss():
    """Collect TechMeme RSS - tech news aggregator"""
    items = []
    out = fetch("https://techmeme.com/feed.xml")
    if not out:
        return items
    # TechMeme RSS has HTML inside <description> (no CDATA), use regex as fallback
    titles = re.findall(r'<item>.*?<title>(.*?)</title>', out, re.DOTALL)
    links = re.findall(r'<item>.*?<title>.*?</title>.*?<link>(.*?)</link>', out, re.DOTALL)
    descs = re.findall(r'<description>(.*?)</description>', out, re.DOTALL)
    dates = re.findall(r'<pubDate>(.*?)</pubDate>', out, re.DOTALL)
    for i, title in enumerate(titles):
        title = title.strip()
        link = links[i].strip() if i < len(links) else ''
        desc = re.sub(r'<[^>]+>','',(descs[i+1] if i+1 < len(descs) else '')).strip()[:500]
        pub = dates[i].strip() if i < len(dates) else ''
        if title and link:
            items.append({
                'platform':'techmeme','title':title,'content':desc or title,'url':link,
                'author':'','author_id':'','published_at':pub,
                'hot_score':0,'source_type':'rss','category_tags':'TechMeme|Tech|News'
            })
    return items

def collect_freebuf_rss():
    """Collect FreeBuf RSS - Chinese security/tech news"""
    items = []
    out = fetch("https://www.freebuf.com/feed")
    if not out:
        return items
    # FreeBuf RSS uses CDATA in titles, use regex
    titles = re.findall(r'<title>(?:<!\[CDATA\[)?\s*(.*?)(?:\]\]>)?\s*</title>', out, re.DOTALL)
    links = re.findall(r'<link>(.*?)</link>', out)
    descs = re.findall(r'<description>(?:<!\[CDATA\[)?\s*(.*?)(?:\]\]>)?\s*</description>', out, re.DOTALL)
    dates = re.findall(r'<pubDate>(.*?)</pubDate>', out)
    for i, title in enumerate(titles):
        if i == 0:  # Skip site title (first one is the channel title)
            continue
        title = title.strip()
        link = links[i].strip() if i < len(links) else ''
        desc = re.sub(r'<[^>]+>','',(descs[i-1] if i-1 < len(descs) else '')).strip()[:500]
        pub = dates[i-1].strip() if i-1 < len(dates) else ''
        if title and link:
            items.append({
                'platform':'freebuf','title':title,'content':desc or title,'url':link,
                'author':'','author_id':'','published_at':pub,
                'hot_score':0,'source_type':'rss','category_tags':'FreeBuf|Security|Tech'
            })
    return items

def collect_arxiv_new():
    """Collect latest arXiv cs.AI papers - new working endpoint"""
    items = []
    out = fetch("https://rss.arxiv.org/rss/cs.AI")
    if out and '<rss' in out:
        for item in parse_rss(out):
            items.append({
                'platform':'arxiv','title':item['title'],'content':item['content'],
                'url':item['url'],'author':'','author_id':'',
                'published_at':item['published_at'],'hot_score':0,
                'source_type':'rss','category_tags':'ArXiv|AI|Paper'
            })
    return items

def collect_hackernews():
    items = []
    out = fetch("https://hacker-news.firebaseio.com/v0/topstories.json")
    if not out:
        return items
    try:
        ids = json.loads(out)[:15]
        def fetch_item(sid):
            r = fetch(f"https://hacker-news.firebaseio.com/v0/item/{sid}.json", timeout=5)
            if r:
                try: return json.loads(r)
                except: pass
            return None
        with ThreadPoolExecutor(max_workers=5) as ex:
            futures = [ex.submit(fetch_item, sid) for sid in ids]
            for future in as_completed(futures):
                story = future.result()
                if not story: continue
                title = story.get("title","")
                url = story.get("url",f"https://news.ycombinator.com/item?id={story.get('id')}")
                if title:
                    content = story.get("text","") or title  # fallback to title if no text
                    items.append({'platform':'hackernews','title':title,'content':content,'url':url,'author':story.get("by",""),'author_id':'','published_at':datetime.fromtimestamp(story.get("time",0)).strftime('%Y-%m-%d %H:%M:%S') if story.get("time") else '','hot_score':int(story.get("score",0)),'source_type':'api','category_tags':'HN|Tech|Startup'})
    except Exception as e:
        print(f"  HN failed: {e}")
    return items

def collect_solidot():
    items = []
    out = fetch("https://www.solidot.org/index.rss")
    # NOTE: out[:10] is '<?xml vers' not '<rss', so check full text
    if out and '<rss' in out:
        for item in parse_rss(out):
            items.append({
                'platform':'solidot','title':item['title'],'content':item['content'],
                'url':item['url'],'author':'','author_id':'',
                'published_at':item['published_at'],'hot_score':0,
                'source_type':'rss','category_tags':'Solidot|Tech|News'
            })
    return items

def collect_cnblogs():
    items = []
    for url in ["https://feed.cnblogs.com/blog/sitehome/rss","https://www.cnblogs.com/rss"]:
        out = fetch(url)
        # out[:10] may be '\ufeff<?xml' due to BOM, check full text instead
        if out and ('<rss' in out or '<feed' in out or '<?xml' in out):
            for item in parse_rss(out):
                items.append({
                    'platform':'cnblogs','title':item['title'],'content':item['content'],
                    'url':item['url'],'author':'','author_id':'',
                    'published_at':item['published_at'],'hot_score':0,
                    'source_type':'rss','category_tags':'Cnblogs|Dev|Blog'
                })
            if items:
                break
    return items

def collect_juejin():
    items = []
    # NOTE: Original URL had space in it - fixed to proper API endpoint
    out = fetch("https://api.juejin.cn/content/v1/get_recommend_article_list?limit=20&category_id=1&tag_id=0", {
        "User-Agent":"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120.0",
        "Accept":"application/json"
    })
    if not out:
        return items
    try:
        d = json.loads(out)
        for item in d.get("data",[]):
            items.append({
                'platform':'juejin','title':item.get("title",""),'content':item.get("content",""),
                'url':f"https://juejin.cn/post/{item.get('id','')}",
                'author':item.get("author",{}).get("name",""),
                'author_id':item.get("author",{}).get("user_id",""),
                'published_at':item.get("created_at",""),
                'hot_score':item.get("digg_count",0),
                'source_type':'api','category_tags':'Juejin|Dev|Tech'
            })
    except:
        pass
    return items

def collect_segmentfault():
    items = []
    out = fetch("https://segmentfault.com/news/hot", {"User-Agent":"Mozilla/5.0"})
    if not out:
        return items
    titles = re.findall(r'<h3[^>]*><a[^>]*>(.*?)</a>', out)
    links = re.findall(r'<h3[^>]*><a[^>]*href="(/a/\d+[^"]*)"', out)
    for title,link in zip(titles,links):
        title = re.sub(r'<[^>]+>','',title).strip()
        if len(title) < 5:
            continue
        items.append({
            'platform':'segmentfault','title':title,'content':'',
            'url':f"https://segmentfault.com{link}" if link.startswith('/a') else link,
            'author':'','author_id':'','published_at':datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'hot_score':0,'source_type':'html','category_tags':'SegmentFault|Dev|Q&A'
        })
    return items

def collect_tencent_cloud():
    items = []
    out = fetch("https://cloud.tencent.com/developer/api/rss", {"User-Agent":"Mozilla/5.0"})
    if out:
        for item in parse_rss(out):
            items.append({
                'platform':'tencent_cloud','title':item['title'],'content':item['content'],
                'url':item['url'],'author':'','author_id':'',
                'published_at':item['published_at'],'hot_score':0,
                'source_type':'rss','category_tags':'TencentCloud|Dev'
            })
    return items

def collect_ifanr():
    items = []
    out = fetch("https://www.ifanr.com/feed", {"User-Agent":"Mozilla/5.0"})
    if out:
        for item in parse_rss(out):
            items.append({
                'platform':'ifanr','title':item['title'],'content':item['content'],
                'url':item['url'],'author':'','author_id':'',
                'published_at':item['published_at'],'hot_score':0,
                'source_type':'rss','category_tags':'Ifanr|Tech'
            })
    return items

def collect_tmtpost():
    items = []
    out = fetch("https://www.tmtpost.com/rss", {"User-Agent":"Mozilla/5.0"})
    if out:
        for item in parse_rss(out):
            items.append({
                'platform':'tmtpost','title':item['title'],'content':item['content'],
                'url':item['url'],'author':'','author_id':'',
                'published_at':item['published_at'],'hot_score':0,
                'source_type':'rss','category_tags':'TMTPost|Tech'
            })
    return items

def collect_huxiu():
    """虎嗅 — RSS feed"""
    items = []
    # Try primary RSS URL, fallback to alternative
    urls = ["https://www.huxiu.com/rss/", "https://www.huxiu.com/rss/0.xml"]
    fetched = False
    for url in urls:
        out = fetch(url, {"User-Agent":"Mozilla/5.0"})
        if out:
            for item in parse_rss(out):
                items.append({
                    'platform':'huxiu','title':item['title'],'content':item['content'],
                    'url':item['url'],'author':'','author_id':'',
                    'published_at':item['published_at'],'hot_score':0,
                    'source_type':'rss','category_tags':'Huxiu|Tech|Business'
                })
            fetched = True
            break
    if not fetched:
        print("  Huxiu RSS unavailable (both URLs tried)")
    return items

def collect_baidu():
    items = []
    out = fetch("https://top.baidu.com/board?tab=realtime", {"User-Agent":"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}, timeout=10)
    if not out:
        return items
    words = re.findall(r'"word"\s*:\s*"([^"]{3,100})"', out)
    for title in words[:30]:
        if len(title) > 3:
            items.append({'platform':'baidu','title':title,'content':'Baidu Hot Search','url':f"https://www.baidu.com/s?wd={title}",'author':'','author_id':'','published_at':datetime.now().strftime('%Y-%m-%d %H:%M:%S'),'hot_score':0,'source_type':'html','category_tags':'Baidu|Hot|Trend'})
    return items

def collect_github_trending():
    items = []
    out = fetch("https://api.github.com/search/repositories?q=stars:>1&sort=stars&order=desc&per_page=20", {
        "User-Agent":"Mozilla/5.0"
    })
    if not out:
        return items
    try:
        d = json.loads(out)
        for repo in d.get("items",[]):
            items.append({
                'platform':'github','title':f"{repo.get('full_name','')} - {repo.get('description','')}",
                'content':f"Stars:{repo.get('stargazers_count',0)} Forks:{repo.get('forks_count',0)} Lang:{repo.get('language','')}",
                'url':repo.get('html_url',''),
                'author':repo.get('owner',{}).get('login',''),
                'author_id':str(repo.get('owner',{}).get('id','')),
                'published_at':repo.get('created_at',''),
                'hot_score':repo.get('stargazers_count',0),
                'source_type':'api','category_tags':'GitHub|OpenSource|Dev'
            })
    except Exception as e:
        print(f"  GitHub failed: {e}")
    return items

def collect_huggingface():
    items = []
    out = fetch("https://huggingface.co/api/models?sort=likes&direction=-1&limit=20", {
        "User-Agent":"Mozilla/5.0"
    })
    if not out:
        return items
    try:
        d = json.loads(out)
        if isinstance(d,list):
            for model in d[:15]:
                items.append({
                    'platform':'huggingface',
                    'title':f"{model.get('id','')} - {model.get('pipeline_tag','')}",
                    'content':f"Likes:{model.get('likes',0)} Downloads:{model.get('downloads',0)}",
                    'url':f"https://huggingface.co/{model.get('id','')}",
                    'author':'','author_id':'','published_at':model.get('created_at',''),
                    'hot_score':model.get('likes',0),
                    'source_type':'api','category_tags':'HuggingFace|AI|Model'
                })
    except:
        pass
    return items

def collect_arxiv():
    items = []
    out = fetch("https://export.arxiv.org/api/query?search_query=cat:cs.AI+OR+cat:cs.LG+OR+cat:cs.CL&start=0&max_results=20&sortBy=submittedDate&sortOrder=descending", {
        "User-Agent":"Mozilla/5.0"
    })
    if not out:
        return items
    try:
        import html
        clean = re.sub(r'<!\[CDATA\[|\]\]>','',out)
        clean = re.sub(r'&#[0-9]+;', lambda m: html.unescape(m.group()), clean)
        root = ET.fromstring(clean)
        # Try all possible entry locations
        entries = root.findall('.//entry')
        if not entries:
            entries = root.findall('.//{http://www.w3.org/2005/Atom}entry')
        for entry in entries[:20]:
            title = (entry.findtext('title') or '').strip().replace('\n',' ')
            url = (entry.findtext('id') or '').strip()
            summary = (entry.findtext('summary') or entry.findtext('content') or '').strip()[:300]
            published = (entry.findtext('published') or '').strip()
            authors = ', '.join([(a.findtext('name') or '') for a in entry.findall('author')])
            items.append({
                'platform':'arxiv','title':title,'content':summary,
                'url':url,'author':authors,'author_id':'',
                'published_at':published,'hot_score':0,
                'source_type':'api','category_tags':'ArXiv|AI|Paper'
            })
    except Exception as e:
        print(f"  ArXiv failed: {e}")
    return items

def collect_reddit():
    items = []
    subreddits = ["technology","artificial","MachineLearning","programming","gadgets","android","apple","games","worldnews","science"]
    for sr in subreddits[:3]:
        try:
            out = fetch(f"https://old.reddit.com/r/{sr}/hot.json?limit=25", {
                "User-Agent":"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120.0 Safari/537.36",
                "Accept":"application/json","Accept-Language":"en-US,en;q=0.9",
                "Referer":f"https://old.reddit.com/r/{sr}/"
            })
            if not out or len(out) < 50:
                continue
            d = json.loads(out)
            for post in d.get("data",{}).get("children",[]):
                pdata = post.get("data",{})
                title = pdata.get("title","")
                if not title:
                    continue
                items.append({
                    'platform':'reddit','title':title,
                    'content':pdata.get("selftext","")[:300],
                    'url':pdata.get("url",pdata.get("permalink","")),
                    'author':pdata.get("author",""),'author_id':'',
                    'published_at':datetime.fromtimestamp(pdata.get("created_utc",0)).strftime('%Y-%m-%d %H:%M:%S') if pdata.get("created_utc") else '',
                    'hot_score':pdata.get("score",0),
                    'source_type':'api','category_tags':f'Reddit|{sr}'
                })
        except:
            continue
    return items

def collect_devto():
    items = []
    out = fetch("https://dev.to/api/articles?top=10&per_page=20", {
        "User-Agent":"Mozilla/5.0","Accept":"application/json"
    })
    if not out or len(out) < 50:
        return items
    try:
        d = json.loads(out)
        if isinstance(d,list):
            for a in d:
                items.append({
                    'platform':'devto','title':a.get("title",""),
                    'content':a.get("description",""),
                    'url':a.get("url",""),
                    'author':a.get("user",{}).get("name",""),'author_id':'',
                    'published_at':a.get("published_at",""),
                    'hot_score':a.get("positive_reactions_count",0),
                    'source_type':'api','category_tags':'DevTo|Dev|Article'
                })
    except:
        pass
    return items

def collect_baidu_weibo_search():
    items = []
    keywords = [
        "AI人工智能","大模型","ChatGPT","LLM大模型","程序员","开源","GitHub",
        "手机新品","iPhone","华为","小米","特斯拉","比亚迪","新能源汽车",
        "NBA","CBA","格斗","UFC","MMA","拳击","太空","火星",
        "机器人","宇树","无人机","电影","游戏","Steam",
        "摄影","人像","风光","绘画","设计","科技"
    ]
    for kw in keywords[:10]:
        try:
            out = fetch(f"https://s.weibo.com/weibo?q={kw}&Refer=index", {
                "User-Agent":"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                "Referer":"https://weibo.com"
            })
            if not out or len(out) < 100:
                continue
            titles = re.findall(r'<p class="txt"[^>]*>(.*?)</p>', out, re.DOTALL)
            links = re.findall(r'<a href="(/weibo[^"&\s]*)\?', out)
            for i,content in enumerate(titles[:10]):
                title = re.sub(r'<[^>]+>','',content).strip()
                if len(title) < 10:
                    continue
                link = links[i] if i < len(links) else ''
                items.append({
                    'platform':'weibo_search','title':title[:120],
                    'content':f"KW:{kw}",
                    'url':f"https://s.weibo.com{link}" if link.startswith('/weibo') else link,
                    'author':'','author_id':'','published_at':datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'hot_score':0,'source_type':'search','category_tags':extract_tags(title)
                })
            time.sleep(0.5)
        except:
            continue
    return items

def collect_zhihu_questions():
    items = []
    out = fetch("https://api.zhihu.com/topstory/hot-list?limit=20", {"User-Agent":"Mozilla/5.0"})
    if not out:
        return items
    try:
        d = json.loads(out)
        for item in d.get("data",[]):
            target = item.get("target",{})
            title = target.get("title","")
            q_url = target.get("url","")
            metrics = target.get("metrics",{})
            if title:
                items.append({
                    'platform':'zhihu','title':title,
                    'content':f"Click:{metrics.get('member_click_count',0)} Score:{metrics.get('score',0)}",
                    'url':q_url if q_url.startswith('http') else f"https://www.zhihu.com{q_url}",
                    'author':target.get("author",{}).get("name",""),
                    'author_id':target.get("author",{}).get("id",""),
                    'published_at':datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'hot_score':int(metrics.get("score",0)),
                    'source_type':'api','category_tags':'Zhihu|Questions'
                })
    except Exception as e:
        print(f"  Zhihu questions failed: {e}")
    return items

def collect_sina_tech():
    items = []
    out = fetch("https://feed.mix.sina.com.cn/api/roll/get?pageid=153&lid=2516&k=&num=20", {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Referer": "https://tech.sina.com.cn/"
    })
    if not out:
        return items
    try:
        d = json.loads(out)
        for entry in d.get("result", {}).get("data", []):
            title = entry.get("title", "")
            url = entry.get("url", "")
            intro = entry.get("intro", "")
            ctime = entry.get("ctime", 0)
            pub_time = datetime.fromtimestamp(int(ctime)).strftime('%Y-%m-%d %H:%M:%S') if ctime else datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            if title and url:
                items.append({
                    'platform': 'sina_tech', 'title': title, 'content': intro,
                    'url': url, 'author': '', 'author_id': '',
                    'published_at': pub_time, 'hot_score': 0,
                    'source_type': 'api', 'category_tags': 'SinaTech|Tech|News'
                })
    except Exception as e:
        print(f"  Sina Tech failed: {e}")
    return items

def collect_zhihu_topstory():
    items = []
    out = fetch("https://www.zhihu.com/api/v4/creators/rank/hot?domain=0&limit=20", {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Referer": "https://www.zhihu.com/"
    })
    if not out:
        return items
    try:
        d = json.loads(out)
        for entry in d.get("data", []):
            q = entry.get("question", {})
            title = q.get("title", "")
            q_url = q.get("url", "")
            excerpt = q.get("detail", entry.get("excerpt", ""))
            if not q_url.startswith('http'):
                q_url = f"https://www.zhihu.com{q_url}"
            if title:
                items.append({
                    'platform': 'zhihu_topstory', 'title': title, 'content': excerpt,
                    'url': q_url, 'author': q.get('author', {}).get('name', ''),
                    'author_id': str(q.get('author', {}).get('id', '')),
                    'published_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'hot_score': entry.get("reaction", {}).get("voteCount", 0),
                    'source_type': 'api', 'category_tags': 'Zhihu|TopStory|Hot'
                })
    except Exception as e:
        print(f"  Zhihu TopStory failed: {e}")
    return items

def collect_zhihu_daily():
    items = []
    out = fetch("https://daily.zhihu.com/api/4/stories/latest", {
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)",
        "Referer": "https://daily.zhihu.com/"
    })
    if not out:
        return items
    try:
        d = json.loads(out)
        all_stories = d.get("stories", []) + d.get("top_stories", [])
        seen_urls = set()
        for story in all_stories:
            if story.get('url') in seen_urls:
                continue
            seen_urls.add(story.get('url'))
            title = story.get("title", "")
            url_path = story.get("url", "")
            hint = story.get("hint", "")
            images = story.get("images", [])
            image_url = images[0] if images else ""
            full_url = f"https://daily.zhihu.com{url_path}" if url_path.startswith('/') else url_path
            if title and full_url:
                items.append({
                    'platform': 'zhihu_daily', 'title': title,
                    'content': f"Author: {hint}" if hint else "",
                    'url': full_url, 'author': hint, 'author_id': '',
                    'published_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'hot_score': 0, 'source_type': 'api',
                    'category_tags': 'ZhihuDaily|Digest'
                })
    except Exception as e:
        print(f"  Zhihu Daily failed: {e}")
    return items

def collect_tieba():
    items = []
    out = fetch("https://tieba.baidu.com/hottopic/browse/topicList", {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Referer": "https://tieba.baidu.com/"
    })
    if not out:
        return items
    try:
        # The page returns a JSON response directly (not HTML)
        d = json.loads(out)
        # Navigate to topic list under data.bang_topic.topic_list
        topic_list = d
        for key in ['data','bang_topic','topic_list']:
            if isinstance(topic_list, dict):
                topic_list = topic_list.get(key, [])
            else:
                topic_list = []
                break
        if not topic_list:
            # Try alternate path: data.sug_topic.topic_list
            topic_list = d
            for key in ['data','sug_topic','topic_list']:
                if isinstance(topic_list, dict):
                    topic_list = topic_list.get(key, [])
                else:
                    topic_list = []
                    break
        if not topic_list and isinstance(d, dict):
            # Try any key that looks like a topic list
            for val in d.values():
                if isinstance(val, list) and len(val) > 0 and isinstance(val[0], dict) and 'topic_name' in val[0]:
                    topic_list = val
                    break
            if not topic_list:
                for val in d.values():
                    if isinstance(val, dict):
                        for v2 in val.values():
                            if isinstance(v2, list) and len(v2) > 0 and isinstance(v2[0], dict) and 'topic_name' in v2[0]:
                                topic_list = v2
                                break
        for topic in (topic_list or []):
            title = topic.get('topic_name', '') or topic.get('title', '')
            url = topic.get('topic_url', '') or topic.get('url', '')
            desc = topic.get('topic_desc', '') or topic.get('desc', '')
            if not url.startswith('http'):
                url = f"https://tieba.baidu.com{url}" if url.startswith('/') else ''
            if not url:
                url = f"https://tieba.baidu.com/hottopic/browse/topicList?topic_id={topic.get('topic_id','')}"
            if title:
                items.append({
                    'platform': 'tieba', 'title': title, 'content': desc,
                    'url': url, 'author': '', 'author_id': '',
                    'published_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'hot_score': int(topic.get('discuss_num', 0) or topic.get('hot_score', 0)),
                    'source_type': 'api', 'category_tags': 'Tieba|Hot|Topic'
                })
    except Exception as e:
        print(f"  Tieba failed: {e}")
    return items

def collect_kuaishou():
    """快手 — delegates to enhanced collector"""
    import subprocess, json
    try:
        r = subprocess.run(
            [sys.executable, str(HERMES / 'scripts' / 'collector_kuaishou_enhanced.py')],
            capture_output=True, text=True, timeout=90, cwd=str(HERMES)
        )
        out = r.stdout.strip()
        m = re.search(r'入库(\d+)条', out)
        saved = int(m.group(1)) if m else 0
        if saved > 0:
            return [{'platform': 'kuaishou', 'title': f'kuaishou collected {saved} items', 'url': 'https://www.kuaishou.com/', 'source_type': 'api'}]
    except Exception as e:
        print(f"  Kuaishou collector failed: {e}")
    return []

# ======== Collector Registry ========
COLLECTORS = {
    'weibo_hot':(collect_weibo_hot,10,30),
    'zhihu_hot':(collect_zhihu_hot,9,30),
    'toutiao_hot':(collect_toutiao,8,30),
    'bilibili_ranking':(collect_bilibili,9,30),
    '36kr_newsflash':(collect_36kr,8,30),
    'ithome_rss':(collect_ithome,8,60),
    'oschina_rss':(collect_oschina,7,60),
    'hackernews':(collect_hackernews,7,30),
    'sogou_wechat':(collect_sogou_wechat,6,30),
    'baidu_hot':(collect_baidu,6,30),
    'weibo_search':(collect_baidu_weibo_search,6,60),
    'github_trending':(collect_github_trending,8,60),
    'arxiv_ai':(collect_arxiv_new,7,60),
    'devto':(collect_devto,6,30),
    'infoq':(collect_infoq_rss,6,60),
    'techmeme':(collect_techmeme_rss,6,60),
    'freebuf':(collect_freebuf_rss,6,60),
    'segmentfault':(collect_segmentfault,6,60),
    'cnblogs':(collect_cnblogs,5,60),
    'ifanr':(collect_ifanr,5,60),
    'tmtpost':(collect_tmtpost,5,60),
    'zhihu_questions':(collect_zhihu_questions,7,30),
    'sina_tech':(collect_sina_tech,7,30),
    'zhihu_daily':(collect_zhihu_daily,7,30),
    'zhihu_topstory':(collect_zhihu_topstory,7,30),
    'tieba':(collect_tieba,6,30),
    'kuaishou':(collect_kuaishou,6,90),
    # 已定义但未注册的采集源 — 激活
    'juejin':(collect_juejin,1,60),
    'tencent_cloud':(collect_tencent_cloud,1,60),
    'huggingface':(collect_huggingface,1,60),
    'arxiv_papers':(collect_arxiv,1,60),
    'reddit_dev':(collect_reddit,1,60),
    # 新增采集源
    'huxiu':(collect_huxiu,1,60),
    'toutiao_military':(collect_toutiao_military,1,60),
    'weibo_military':(collect_weibo_military,6,60),
    'bilibili_tech':(collect_bilibili_tech,7,60),
    # ===== 自采集器 - 独立文件 =====
    'weixin_accounts':(collect_weixin_accounts,8,120),
    'xiaohongshu_search':(collect_xiaohongshu_accounts,7,120),
    'douyin_hot':(collect_douyin_hot,6,90),
    'csdn_blogs':(collect_csdn_blogs,7,90),
}

def collect_platform(name, fn, priority):
    start = time.time()
    result = [None]
    def _run():
        try:
            items = fn()
            total, new = insert_batch(items)
            result[0] = (name, total, new)
        except Exception as e:
            print(f"  {name} exception: {e}")
            result[0] = (name, 0, 0)
    t = __import__('threading').Thread(target=_run)
    t.start()
    t.join(timeout=15)
    elapsed = int((time.time()-start)*1000)
    if t.is_alive():
        return name, 0, 0, elapsed
    if result[0]:
        name, total, new = result[0]
        return name, total, new, elapsed
    return name, 0, 0, elapsed

def collect_all(parallel=8):
    init_db()
    results = {}
    stats = {'total':0,'new':0,'platforms':0,'elapsed':0}
    start_total = time.time()
    print(f"\n{'='*60}")
    print(f"  Starting full collection (parallel={parallel})")
    print(f"  Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}")
    sorted_collectors = sorted(COLLECTORS.items(), key=lambda x:-x[1][1])
    with ThreadPoolExecutor(max_workers=parallel) as executor:
        futures = {executor.submit(collect_platform,name,fn,pri):name for name,(fn,pri,_) in sorted_collectors}
        for future in as_completed(futures):
            name = futures[future]
            try:
                pname,total,new,elapsed = future.result()
                results[pname] = {'total':total,'new':new,'elapsed_ms':elapsed}
                stats['total'] += total
                stats['new'] += new
                stats['platforms'] += 1
                if total > 0:
                    print(f"  OK {pname}: {total} new={new} {elapsed}ms")
                else:
                    print(f"  -- {pname}: no data {elapsed}ms")
            except Exception as e:
                print(f"  XX {name}: {e}")
    stats['elapsed'] = int((time.time()-start_total)*1000)
    print(f"\n{'='*60}")
    print(f"  Collection complete!")
    print(f"  Total: {stats['total']} (new {stats['new']})")
    print(f"  Platforms: {stats['platforms']}/{len(COLLECTORS)}")
    print(f"  Time: {stats['elapsed']}ms")
    print(f"{'='*60}\n")
    return stats

def get_platform_stats():
    db = get_db()
    rows = db.execute("""
        SELECT platform, COUNT(*) as cnt,
               SUM(CASE WHEN DATE(collected_at)=DATE('now') THEN 1 ELSE 0 END) as today
        FROM raw_intelligence GROUP BY platform ORDER BY cnt DESC
    """).fetchall()
    db.close()
    return {r[0]:{'total':r[1],'today':r[2]} for r in rows}

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description='Hermes Collector v5')
    parser.add_argument('--collect', action='store_true')
    parser.add_argument('--platform', type=str)
    parser.add_argument('--stats', action='store_true')
    parser.add_argument('--parallel', type=int, default=8)
    args = parser.parse_args()
    if args.stats:
        stats = get_platform_stats()
        print("\n=== Platform Stats ===")
        for p,s in sorted(stats.items(),key=lambda x:-x[1]['total']):
            print(f"  {p}: {s['total']} (today {s['today']})")
    elif args.platform:
        init_db()
        fn,pri,_ = COLLECTORS.get(args.platform,(None,0,0))
        if fn:
            r = collect_platform(args.platform, fn, pri)
            print(f"Result: {r}")
        else:
            print(f"Unknown platform: {args.platform}")
    elif args.collect:
        collect_all(parallel=args.parallel)
    else:
        parser.print_help()
