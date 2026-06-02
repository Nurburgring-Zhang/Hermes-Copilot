#!/usr/bin/env python3
"""
Hermes 全平台智能情报系统 v2
============================
采集 → 清洗 → 评估 → 存储 → 推送 + 趋势追踪 + Multi-Agent

核心能力:
- 50+信息源并行采集(国内+海外+RSS)
- Multi-Agent调度(子Agent并行执行)
- 5级重要性评估 + 趋势追踪 + 爆发检测
- 推送记录DB化 + 去重
- 用户偏好持久化

Usage:
  python hermes_intelligence_v2.py              # 完整流程
  python hermes_intelligence_v2.py --dry-run    # 仅评估不推送
  python hermes_intelligence_v2.py --urgent     # 仅推送紧急信息
  python hermes_intelligence_v2.py --agent=国内  # 仅国内平台
  python hermes_intelligence_v2.py --agent=海外 # 仅海外平台
"""
import urllib.request, json, time, sqlite3, re, os, sys, threading
from datetime import datetime, timedelta
from html import unescape
from concurrent.futures import ThreadPoolExecutor, as_completed
import queue

DB_PATH = os.path.expanduser("~/.hermes/intelligence.db")
PUSHPLUS_URL = "https://www.pushplus.plus/send"
PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "a8f1526d8ec84ef59aa37fe72fa1ab7f")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/html, */*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

# ============================================================
# 用户偏好配置(可动态更新)
# ============================================================
CHINESE_RATIO = 0.7       # 中文信息占比
DOMESTIC_RATIO = 0.7     # 国内信息占中文中的比例
INTL_RATIO = 0.3         # 海外信息占外语中的比例

# 高价值关键词(按用户偏好分类)
HIGH_KW_DOMESTIC = [
    # AI/科技核心
    "AI","LLM","大模型","GPT","Claude","Gemini","OpenAI","Anthropic","Google","Meta","Kimi","豆包","通义","文心","混元",
    "AIGC","生成式AI","多模态","AI训练","AI微调","AI开发","AI厂家","AI平台","AI评测","AI用户",
    "大模型发布","模型开源","模型突破","模型升级","模型更新","模型发布","模型发布","模型迭代",
    # IT/数码
    "iPhone","Android","华为","小米","苹果","三星","OPPO","vivo","荣耀","一加","魅族","联想",
    "手机发布","PC电脑","笔记本","平板","智能手表","耳机","音箱","VR","AR","折叠屏",
    "消费电子","新潮电子","潮玩","数码评测","手机评测",
    # 新能源汽车
    "新能源汽车","电动车","比亚迪","特斯拉","蔚来","小鹏","理想","问界","小米汽车","智己","极氪",
    "汽车发布","新车上市","电池技术","自动驾驶","智能驾驶","电车续航",
    # 传统汽车/机车
    "传统汽车","机车","摩托车","宝马","奔驰","奥迪","保时捷","法拉利","兰博基尼","越野","竞速","拉力赛","MotoGP",
    "汽车与运动","卡宴","赛道","赛车",
    # 科技/学术
    "物理","化学","生物","地理","天文","医学","科研","学术","量子","芯片","半导体","光刻机","GPU","CPU","H100",
    # 军事/国际
    "军事","战争","武器","冲突","国际形势","国际新闻","国际热点","外交","制裁","联合国","北约",
    "台海","南海","中美关系","俄乌","中东","欧洲","美国","中国","日本","韩国","印度",
    # 热点/爆款
    "热点","爆款","热搜","头条","热门"," trending","热搜","突发","曝光","揭秘",
    # 开发者/开源
    "开发者","开源","GitHub","HuggingFace","GitLab","程序员","编程","代码","框架","架构",
    "Vue","React","Angular","Python","JavaScript","TypeScript","Rust","Go","Kotlin","Swift",
    # 模型/AI平台
    "模型训练","模型微调","RAG","向量数据库","LangChain","Agent","MCP","Llama","Mistral","Gemma","Qwen","Yi",
    "Stable Diffusion","Midjourney","Sora","DALL-E","Flux","ComfyUI","LoRA","ControlNet",
    # 机器人/无人机
    "机器人","人形机器人","工业机器人","无人机","机器狗","自动驾驶","智能车","智慧城市",
    # 安全/漏洞
    "漏洞","安全","攻击","入侵","数据泄露","勒索","黑客","后门","恶意软件","钓鱼",
    # 游戏/电竞
    "游戏","电竞","Steam","Epic","Epic独占","手游","端游","主机游戏","Switch","PlayStation","Xbox",
    "原神","黑神话","王者荣耀","LOL","DOTA","CS2","Valorant","PUBG",
    # 体育/格斗
    "篮球","NBA","CBA","CBA","库里","詹姆斯","杜兰特","足球","世界杯","欧冠","英超","欧冠","格斗","MMA","UFC",
    "自由搏击","散打","拳击","跆拳道","柔术","竞技体育","亚运会","奥运会",
    # 娱乐/明星
    "美女","写真","颜值","女神","网红","明星","演唱会","综艺","电影","剧集","偶像","演员","歌手",
    # 艺术/创意
    "绘画","摄影","相机","人像","风景","佳作","艺术","设计","美学","潮流","时尚","现代艺术",
    "视频剪辑","短视频","Vlog","MV","电影解说","纪录片",
    # 传统文化
    "传统文化","非遗","博物馆","文物","考古","历史","人文","旅游","文旅","美食","网红打卡",
    # 太空/科技
    "太空","航天","火箭","卫星","SpaceX","NASA","星舰","探月","火星","空间站","宇宙",
]

HIGH_KW_INTL = [
    "AI","LLM","GPT","Claude","Gemini","OpenAI","Anthropic","Google DeepMind","Meta AI","Mistral","Llama",
    "generative AI","multimodal","foundation model","model release","open source model","breakthrough",
    "iPhone","Samsung","Android","smartphone","laptop","VR","AR","wearable",
    "electric vehicle","Tesla","BYD","self-driving","autonomous","battery tech",
    "physics","chemistry","biology","quantum","chip","semiconductor","GPU","H100","B100",
    "military","war","conflict","geopolitics","international","sanctions",
    "developer","open source","GitHub","HuggingFace","programming","framework",
    "robotics","humanoid","drone","autonomous vehicle","robot",
    "security","vulnerability","hack","exploit","malware","ransomware",
    "gaming","e-sports","Steam","Nintendo","PlayStation"," AAA game",
    "basketball","NBA","soccer","football","MMA","UFC","boxing","sports",
    "beauty","fashion","art","photography","cinema","music","movie",
    "space","SpaceX","NASA","rocket","satellite","Mars","Moon","ISS",
    "model fine-tuning","RAG","vector database","LangChain","Agent",
    "Stable Diffusion","Midjourney","Sora","image generation","video generation",
]

# 噪音词
NOISE_KW = [
    "明星八卦","绯闻","出轨","偷拍","狗仔","娱乐周刊","综艺预告","演唱会预告",
    "粉丝应援","打榜","控评","娱乐圈","网红带货","直播带货","搞笑配音",
    "表情包","壁纸","头像","说说","段子手","星座","塔罗","算命","占卜",
    "与我无关","日常打卡","早安晚安","今日任务","打卡","mark","分享",
]

# ============================================================
# 信息源配置(50+来源)
# ============================================================
SOURCES = [
    # --- B站(20+分区)---
    {"name":"B站-全站","platform":"bilibili","type":"api","url":"https://api.bilibili.com/x/web-interface/ranking/v2?rid=0&type=all","category":"综合","lang":"zh","weight":1.0},
    {"name":"B站-科技","platform":"bilibili","type":"api","url":"https://api.bilibili.com/x/web-interface/ranking/v2?rid=36&type=all","category":"科技","lang":"zh","weight":1.0},
    {"name":"B站-游戏","platform":"bilibili","type":"api","url":"https://api.bilibili.com/x/web-interface/ranking/v2?rid=4&type=all","category":"游戏","lang":"zh","weight":0.9},
    {"name":"B站-汽车","platform":"bilibili","type":"api","url":"https://api.bilibili.com/x/web-interface/ranking/v2?rid=223&type=all","category":"汽车","lang":"zh","weight":0.9},
    {"name":"B站-生活","platform":"bilibili","type":"api","url":"https://api.bilibili.com/x/web-interface/ranking/v2?rid=160&type=all","category":"生活","lang":"zh","weight":0.7},
    {"name":"B站-运动","platform":"bilibili","type":"api","url":"https://api.bilibili.com/x/web-interface/ranking/v2?rid=21&type=all","category":"运动","lang":"zh","weight":0.8},
    {"name":"B站-数码","platform":"bilibili","type":"api","url":"https://api.bilibili.com/x/web-interface/ranking/v2?rid=188&type=all","category":"数码","lang":"zh","weight":1.0},
    {"name":"B站-美食","platform":"bilibili","type":"api","url":"https://api.bilibili.com/x/web-interface/ranking/v2?rid=211&type=all","category":"美食","lang":"zh","weight":0.6},
    {"name":"B站-动画","platform":"bilibili","type":"api","url":"https://api.bilibili.com/x/web-interface/ranking/v2?rid=1&type=all","category":"动画","lang":"zh","weight":0.7},
    {"name":"B站-音乐","platform":"bilibili","type":"api","url":"https://api.bilibili.com/x/web-interface/ranking/v2?rid=3&type=all","category":"音乐","lang":"zh","weight":0.7},
    {"name":"B站-舞蹈","platform":"bilibili","type":"api","url":"https://api.bilibili.com/x/web-interface/ranking/v2?rid=129&type=all","category":"舞蹈","lang":"zh","weight":0.6},
    {"name":"B站-时尚","platform":"bilibili","type":"api","url":"https://api.bilibili.com/x/web-interface/ranking/v2?rid=155&type=all","category":"时尚","lang":"zh","weight":0.7},
    {"name":"B站-娱乐","platform":"bilibili","type":"api","url":"https://api.bilibili.com/x/web-interface/ranking/v2?rid=5&type=all","category":"娱乐","lang":"zh","weight":0.5},
    {"name":"B站-影视","platform":"bilibili","type":"api","url":"https://api.bilibili.com/x/web-interface/ranking/v2?rid=181&type=all","category":"影视","lang":"zh","weight":0.8},
    {"name":"B站-知识","platform":"bilibili","type":"api","url":"https://api.bilibili.com/x/web-interface/ranking/v2?rid=201&type=all","category":"知识","lang":"zh","weight":1.0},
    {"name":"B站-资讯","platform":"bilibili","type":"api","url":"https://api.bilibili.com/x/web-interface/ranking/v2?rid=202&type=all","category":"资讯","lang":"zh","weight":0.9},

    # --- 微博 ---
    {"name":"微博热搜","platform":"weibo","type":"api","url":"https://weibo.com/ajax/side/hotSearch","category":"热搜","lang":"zh","weight":1.0},
    {"name":"微博-科技","platform":"weibo","type":"api","url":"https://weibo.com/ajax/side/hotSearch","category":"科技","lang":"zh","weight":1.0},
    {"name":"微博-汽车","platform":"weibo","type":"api","url":"https://weibo.com/ajax/side/hotSearch","category":"汽车","lang":"zh","weight":0.9},
    {"name":"微博-游戏","platform":"weibo","type":"api","url":"https://weibo.com/ajax/side/hotSearch","category":"游戏","lang":"zh","weight":0.8},

    # --- 知乎 ---
    {"name":"知乎热榜","platform":"zhihu","type":"api","url":"https://www.zhihu.com/api/v3/feed/topstory/hot-lists/total?limit=50","category":"热榜","lang":"zh","weight":1.0},
    {"name":"知乎-科技","platform":"zhihu","type":"api","url":"https://www.zhihu.com/api/v3/feed/topstory/hot-lists/tech?limit=50","category":"科技","lang":"zh","weight":1.0},
    {"name":"知乎-数码","platform":"zhihu","type":"api","url":"https://www.zhihu.com/api/v3/feed/topstory/hot-lists/digital?limit=50","category":"数码","lang":"zh","weight":0.9},
    {"name":"知乎-汽车","platform":"zhihu","type":"api","url":"https://www.zhihu.com/api/v3/feed/topstory/hot-lists/car?limit=50","category":"汽车","lang":"zh","weight":0.9},
    {"name":"知乎-体育","platform":"zhihu","type":"api","url":"https://www.zhihu.com/api/v3/feed/topstory/hot-lists/sport?limit=50","category":"体育","lang":"zh","weight":0.8},

    # --- GitHub ---
    {"name":"GitHub-Trending","platform":"github","type":"html","url":"https://github.com/trending?since=daily","category":"编程","lang":"en","weight":1.0},
    {"name":"GitHub-Python","platform":"github","type":"html","url":"https://github.com/trending/python?since=daily","category":"Python","lang":"en","weight":0.9},
    {"name":"GitHub-TypeScript","platform":"github","type":"html","url":"https://github.com/trending/typescript?since=daily","category":"TypeScript","lang":"en","weight":0.9},
    {"name":"GitHub-JavaScript","platform":"github","type":"html","url":"https://github.com/trending/javascript?since=daily","category":"JavaScript","lang":"en","weight":0.8},
    {"name":"GitHub-Go","platform":"github","type":"html","url":"https://github.com/trending/go?since=daily","category":"Go","lang":"en","weight":0.8},
    {"name":"GitHub-Rust","platform":"github","type":"html","url":"https://github.com/trending/rust?since=daily","category":"Rust","lang":"en","weight":0.8},
    {"name":"GitHub-AI","platform":"github","type":"html","url":"https://github.com/trending?since=daily&q=AI+OR+llm+OR+gpt+OR+neural","category":"AI","lang":"en","weight":1.0},

    # --- 科技媒体 ---
    {"name":"36氪-首页","platform":"36kr","type":"html","url":"https://36kr.com/newsflash","category":"科技","lang":"zh","weight":1.0},
    {"name":"虎嗅-热文","platform":"huxiu","type":"html","url":"https://www.huxiu.com/article/","category":"科技","lang":"zh","weight":1.0},
    {"name":"钛媒体-首页","platform":"tmt","type":"html","url":"https://www.tmtpost.com/","category":"科技","lang":"zh","weight":0.9},
    {"name":"极客公园","platform":"geekpark","type":"html","url":"https://www.geekpark.net/","category":"科技","lang":"zh","weight":0.9},
    {"name":"少数派","platform":"sspai","type":"html","url":"https://sspai.com/","category":"数码","lang":"zh","weight":0.8},
    {"name":"IT之家","platform":"ithome","type":"html","url":"https://www.ithome.com/","category":"科技","lang":"zh","weight":1.0},
    {"name":"开源中国","platform":"oschina","type":"html","url":"https://www.oschina.net/news","category":"开源","lang":"zh","weight":1.0},
    {"name":"Solidot","platform":"solidot","type":"html","url":"https://www.solidot.org/","category":"科技","lang":"zh","weight":0.9},

    # --- Reddit ---
    {"name":"Reddit-MachineLearning","platform":"reddit","type":"json","url":"https://www.reddit.com/r/MachineLearning/hot.json?limit=50","category":"AI","lang":"en","weight":1.0},
    {"name":"Reddit-Artificial","platform":"reddit","type":"json","url":"https://www.reddit.com/r/Artificial/hot.json?limit=50","category":"AI","lang":"en","weight":1.0},
    {"name":"Reddit-Programming","platform":"reddit","type":"json","url":"https://www.reddit.com/r/programming/hot.json?limit=50","category":"编程","lang":"en","weight":0.8},
    {"name":"Reddit-Technology","platform":"reddit","type":"json","url":"https://www.reddit.com/r/technology/hot.json?limit=50","category":"科技","lang":"en","weight":0.8},
    {"name":"Reddit-science","platform":"reddit","type":"json","url":"https://www.reddit.com/r/science/hot.json?limit=50","category":"科学","lang":"en","weight":0.8},
    {"name":"Reddit-gadgets","platform":"reddit","type":"json","url":"https://www.reddit.com/r/gadgets/hot.json?limit=50","category":"数码","lang":"en","weight":0.7},
    {"name":"Reddit-games","platform":"reddit","type":"json","url":"https://www.reddit.com/r/games/hot.json?limit=50","category":"游戏","lang":"en","weight":0.7},

    # --- HuggingFace ---
    {"name":"HF-热门模型","platform":"huggingface","type":"html","url":"https://huggingface.co/models?sort=trending","category":"AI模型","lang":"en","weight":1.0},
    {"name":"HF-热门数据集","platform":"huggingface","type":"html","url":"https://huggingface.co/datasets?sort=trending","category":"数据集","lang":"en","weight":0.8},

    # --- YouTube ---
    {"name":"YouTube-热门","platform":"youtube","type":"html","url":"https://www.youtube.com/feed/trending","category":"热门","lang":"en","weight":0.8},

    # --- arXiv ---
    {"name":"arXiv-CS.AI","platform":"arxiv","type":"html","url":"https://arxiv.org/list/cs.AI/recent","category":"AI","lang":"en","weight":1.0},
    {"name":"arXiv-CS.LG","platform":"arxiv","type":"html","url":"https://arxiv.org/list/cs.LG/recent","category":"ML","lang":"en","weight":1.0},
    {"name":"arXiv-CS.CL","platform":"arxiv","type":"html","url":"https://arxiv.org/list/cs.CL/recent","category":"NLP","lang":"en","weight":1.0},

    # --- X/Twitter (via Nitter RSS) ---
    {"name":"X-AI趋势","platform":"twitter","type":"rss","url":"https://nitter.net/search?q=AI+LLM+GPT&f=tweets","category":"AI","lang":"en","weight":1.0},

    # --- 今日头条/抖音 ---
    {"name":"今日头条-科技","platform":"toutiao","type":"html","url":"https://www.toutiao.com/ch/news_tech/","category":"科技","lang":"zh","weight":0.9},
    {"name":"抖音-热搜","platform":"douyin","type":"html","url":"https://www.douyin.com/aweme/v1/web/hot/search/list/?device_platform=webapp&aid=6383","category":"热搜","lang":"zh","weight":1.0},

    # --- 快手 ---
    {"name":"快手-热搜","platform":"kuaishou","type":"html","url":"https://www.kuaishou.com/","category":"热搜","lang":"zh","weight":0.8},

    # --- RSS订阅 ---
    {"name":"RSS-36氪","platform":"rss","type":"rss","url":"https://36kr.com/feed","category":"科技","lang":"zh","weight":0.9},
    {"name":"RSS-虎嗅","platform":"rss","type":"rss","url":"https://www.huxiu.com/rss/0.xml","category":"科技","lang":"zh","weight":0.9},
    {"name":"RSS-少数派","platform":"rss","type":"rss","url":"https://sspai.com/feed","category":"数码","lang":"zh","weight":0.8},
    {"name":"RSS-爱范儿","platform":"rss","type":"rss","url":"https://www.ifanr.com/feed","category":"科技","lang":"zh","weight":0.8},
    {"name":"RSS-品玩","platform":"rss","type":"rss","url":"https://www.pingwest.com/feed","category":"科技","lang":"zh","weight":0.8},
    {"name":"RSS-动点科技","platform":"rss","type":"rss","url":"https://technode.com/feed/","category":"科技","lang":"zh","weight":0.7},
    {"name":"RSS-Engadget中文","platform":"rss","type":"rss","url":"https://cn.engadget.com/rss.xml","category":"数码","lang":"zh","weight":0.8},
    {"name":"RSS-月光博客","platform":"rss","type":"rss","url":"http://www.williamlong.com/rss.xml","category":"科技","lang":"zh","weight":0.6},
    {"name":"RSS-程序师","platform":"rss","type":"rss","url":"https://www.techug.com/feed","category":"技术","lang":"zh","weight":0.7},
    {"name":"RSS-Solidot","platform":"rss","type":"rss","url":"https://www.solidot.org/index.rss","category":"科技","lang":"zh","weight":0.9},
]

# RSSHub桥接(为微信公众号/小红书/知乎等提供RSS)
RSSHUB_BASE = "https://rsshub.app"

# ============================================================
# RSSHub 配置(本地自建时启用)
# ============================================================
LOCAL_RSSHUB_URL = os.environ.get("LOCAL_RSSHUB_URL", "")  # 如: http://localhost:1200

def check_rsshub_available():
    """检测本地RSSHub是否可用"""
    if not LOCAL_RSSHUB_URL:
        return False
    try:
        req = urllib.request.Request(LOCAL_RSSHUB_URL + "/robots.txt",
                                     headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status == 200
    except:
        return False

RSSHUB_AVAILABLE = check_rsshub_available()

SOURCES_RSSHUB = []
if RSSHUB_AVAILABLE:
    # 本地RSSHub可用时启用以下来源
    SOURCES_RSSHUB = [
        # 微信公众号(通过本地RSSHub)
        {"name":"微信公众号-AI前哨","platform":"wechat","type":"rsshub","url":f"{LOCAL_RSSHUB_URL}/wechat/mp/wx_zjqsci","category":"AI","lang":"zh","weight":1.0},
        {"name":"微信公众号-量子位","platform":"wechat","type":"rsshub","url":f"{LOCAL_RSSHUB_URL}/wechat/mp/zhonghuaxiang","category":"AI","lang":"zh","weight":1.0},
        {"name":"微信公众号-机器之心","platform":"wechat","type":"rsshub","url":f"{LOCAL_RSSHUB_URL}/wechat/mp/alafg", "category":"AI","lang":"zh","weight":1.0},
        {"name":"微信公众号-36氪","platform":"wechat","type":"rsshub","url":f"{LOCAL_RSSHUB_URL}/wechat/mp/36kr","category":"科技","lang":"zh","weight":1.0},
        {"name":"微信公众号-虎嗅","platform":"wechat","type":"rsshub","url":f"{LOCAL_RSSHUB_URL}/wechat/mp/huxiu_com","category":"科技","lang":"zh","weight":1.0},
        {"name":"微信公众号-爱范儿","platform":"wechat","type":"rsshub","url":f"{LOCAL_RSSHUB_URL}/wechat/mp/ifanr","category":"科技","lang":"zh","weight":0.9},
        {"name":"微信公众号-极客公园","platform":"wechat","type":"rsshub","url":f"{LOCAL_RSSHUB_URL}/wechat/mp/geekpark","category":"科技","lang":"zh","weight":0.9},
        {"name":"微信公众号-钛媒体","platform":"wechat","type":"rsshub","url":f"{LOCAL_RSSHUB_URL}/wechat/mp/tmtpost","category":"科技","lang":"zh","weight":0.9},
        {"name":"微信公众号-小米","platform":"wechat","type":"rsshub","url":f"{LOCAL_RSSHUB_URL}/wechat/mp/xiaomitech","category":"数码","lang":"zh","weight":0.9},
        {"name":"微信公众号-华为","platform":"wechat","type":"rsshub","url":f"{LOCAL_RSSHUB_URL}/wechat/mp/huaweiarm","category":"数码","lang":"zh","weight":0.9},
        {"name":"微信公众号-极客时间","platform":"wechat","type":"rsshub","url":f"{LOCAL_RSSHUB_URL}/wechat/mp/geektime","category":"技术","lang":"zh","weight":0.8},
        {"name":"微信公众号-CSDN","platform":"wechat","type":"rsshub","url":f"{LOCAL_RSSHUB_URL}/wechat/mp/csdn","category":"技术","lang":"zh","weight":0.8},
        {"name":"微信公众号-新能源汽车","platform":"wechat","type":"rsshub","url":f"{LOCAL_RSSHUB_URL}/wechat/mp/d1ev","category":"汽车","lang":"zh","weight":0.9},
        {"name":"微信公众号-电动星球","platform":"wechat","type":"rsshub","url":f"{LOCAL_RSSHUB_URL}/wechat/mp/ddianxing","category":"汽车","lang":"zh","weight":0.8},
        # 小红书(通过本地RSSHub)
        {"name":"小红书-科技数码","platform":"xiaohongshu","type":"rsshub","url":f"{LOCAL_RSSHUB_URL}/xiaohongshu/user/653ddacfto","category":"数码","lang":"zh","weight":0.7},
        # Telegram频道(通过本地RSSHub)
        {"name":"Telegram-AI_news","platform":"telegram","type":"rsshub","url":f"{LOCAL_RSSHUB_URL}/telegram/channel/ai_news_","category":"AI","lang":"en","weight":1.0},
        {"name":"Telegram-ML.news","platform":"telegram","type":"rsshub","url":f"{LOCAL_RSSHUB_URL}/telegram/channel/EngineerFeed","category":"AI","lang":"en","weight":0.9},
        {"name":"Telegram-StatLearning","platform":"telegram","type":"rsshub","url":f"{LOCAL_RSSHUB_URL}/telegram/channel/ak_family","category":"AI","lang":"en","weight":0.8},
    ]
    print(f"[RSSHub] 本地RSSHub可用,已加载 {len(SOURCES_RSSHUB)} 个来源")
else:
    print("[RSSHub] 本地RSSHub未配置,仅使用直接可访问来源")

# ============================================================
# 今日头条多分类来源(通过API)
# ============================================================
SOURCES_TOUTIAO_CATS = [
    {"name":"今日头条-综合","platform":"toutiao","type":"api","url":"https://www.toutiao.com/api/pc/feed/?min_behot_time=0&category=__all__&count=20","category":"综合","lang":"zh","weight":1.0},
    {"name":"今日头条-科技","platform":"toutiao","type":"api","url":"https://www.toutiao.com/api/pc/feed/?min_behot_time=0&category=tech&count=20","category":"科技","lang":"zh","weight":1.0},
    {"name":"今日头条-汽车","platform":"toutiao","type":"api","url":"https://www.toutiao.com/api/pc/feed/?min_behot_time=0&category=car&count=20","category":"汽车","lang":"zh","weight":0.9},
    {"name":"今日头条-游戏","platform":"toutiao","type":"api","url":"https://www.toutiao.com/api/pc/feed/?min_behot_time=0&category=game&count=20","category":"游戏","lang":"zh","weight":0.8},
    {"name":"今日头条-体育","platform":"toutiao","type":"api","url":"https://www.toutiao.com/api/pc/feed/?min_behot_time=0&category=sports&count=20","category":"体育","lang":"zh","weight":0.8},
    {"name":"今日头条-军事","platform":"toutiao","type":"api","url":"https://www.toutiao.com/api/pc/feed/?min_behot_time=0&category=military&count=20","category":"军事","lang":"zh","weight":0.9},
    {"name":"今日头条-国际","platform":"toutiao","type":"api","url":"https://www.toutiao.com/api/pc/feed/?min_behot_time=0&category=world&count=20","category":"国际","lang":"zh","weight":0.9},
    {"name":"今日头条-科学","platform":"toutiao","type":"api","url":"https://www.toutiao.com/api/pc/feed/?min_behot_time=0&category=science&count=20","category":"科学","lang":"zh","weight":1.0},
]

ALL_SOURCES = SOURCES + SOURCES_RSSHUB + SOURCES_TOUTIAO_CATS

# ============================================================
# 数据库工具
# ============================================================
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

# ============================================================
# 采集函数(按平台类型)
# ============================================================
def fetch_url(url, headers=None, timeout=10):
    """通用HTTP获取"""
    h = headers or HEADERS
    try:
        req = urllib.request.Request(url, headers=h)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            ct = resp.headers.get('Content-Type','')
            data = resp.read()
            if 'json' in ct:
                return json.loads(data.decode('utf-8'))
            return data.decode('utf-8', errors='ignore')
    except Exception as e:
        return None

def fetch_bilibili(source):
    """B站采集"""
    items = []
    data = fetch_url(source['url'])
    if not data or 'data' not in data: return items
    for item in data.get('data', {}).get('list', []):
        stat = item.get('stat', {})
        title = unescape(item.get('title', ''))
        if len(title) < 5: continue
        pub_time = item.get('pubdate', 0)
        items.append({
            "title": title, "content": item.get('desc', ''),
            "url": f"https://www.bilibili.com/video/{item.get('bvid', '')}",
            "platform": "bilibili", "source": source['name'],
            "author": item.get('owner', {}).get('name', ''),
            "author_id": str(item.get('owner', {}).get('mid', '')),
            "category": item.get('tname', source['category']),
            "hot_score": float(stat.get('view', 0)),
            "view_count": stat.get('view', 0), "like_count": stat.get('like', 0),
            "collect_count": stat.get('favorite', 0), "comment_count": stat.get('reply', 0),
            "share_count": stat.get('share', 0),
            "published_at": datetime.fromtimestamp(pub_time).isoformat() if pub_time else None,
            "lang": "zh",
            "raw_data": json.dumps(item, ensure_ascii=False)
        })
    return items

def fetch_weibo(source):
    """微博热搜采集"""
    items = []
    data = fetch_url(source['url'])
    if not data or 'data' not in data: return items
    for item in data.get('data', {}).get('realtime', []):
        title = unescape(item.get('note', ''))
        if len(title) < 5: continue
        items.append({
            "title": title, "content": item.get('word_scheme', ''),
            "url": f"https://s.weibo.com/weibo?q={urllib.parse.quote(item.get('note',''))}",
            "platform": "weibo", "source": source['name'],
            "author": "", "author_id": "", "category": source['category'],
            "hot_score": float(item.get('raw_hot', 0)),
            "view_count": 0, "like_count": 0, "comment_count": item.get('num', 0),
            "collect_count": 0, "share_count": 0, "published_at": None,
            "lang": "zh",
            "raw_data": json.dumps(item, ensure_ascii=False)
        })
    return items

def fetch_zhihu(source):
    """知乎热榜采集"""
    items = []
    data = fetch_url(source['url'])
    if not data: return items
    for item in data.get('data', []):
        title = unescape(item.get('target', {}).get('title', ''))
        if len(title) < 5: continue
        excerpt = unescape(item.get('target', {}).get('excerpt', ''))
        items.append({
            "title": title, "content": excerpt,
            "url": f"https://www.zhihu.com/question/{item.get('target',{}).get('id','')}",
            "platform": "zhihu", "source": source['name'],
            "author": item.get('target', {}).get('author', {}).get('name', ''),
            "author_id": item.get('target', {}).get('author', {}).get('id', ''),
            "category": source['category'],
            "hot_score": float(item.get('detail_text', '0').replace(',','').replace('万','0000') or 0),
            "view_count": 0, "like_count": item.get('target', {}).get('voteup_count', 0),
            "comment_count": item.get('target', {}).get('comment_count', 0),
            "collect_count": 0, "share_count": 0, "published_at": None,
            "lang": "zh",
            "raw_data": json.dumps(item, ensure_ascii=False)
        })
    return items

def fetch_github(source):
    """GitHub Trending采集"""
    items = []
    html = fetch_url(source['url'])
    if not html: return items
    # 解析GitHub Trending HTML
    pattern = r'<article class="Box-row">.*?<h2.*?href="/([^"]+)"[^>]*>([^<]+)</a>.*?<p>([^<]+)</p>.*?</article>'
    matches = re.findall(pattern, html, re.DOTALL)
    for m in matches[:30]:
        repo_path, repo_name, desc = m
        desc = unescape(desc.strip())
        repo_name = unescape(repo_name.strip())
        items.append({
            "title": f"{repo_name} - {desc[:80]}",
            "content": desc,
            "url": f"https://github.com/{repo_path}",
            "platform": "github", "source": source['name'],
            "author": repo_path.split('/')[0] if '/' in repo_path else '',
            "author_id": "", "category": source['category'],
            "hot_score": 1000, "lang": "en",
            "view_count": 0, "like_count": 0, "comment_count": 0,
            "collect_count": 0, "share_count": 0, "published_at": None,
            "raw_data": json.dumps({"repo": repo_path, "desc": desc}, ensure_ascii=False)
        })
    return items

def fetch_reddit(source):
    """Reddit采集"""
    items = []
    data = fetch_url(source['url'])
    if not data or 'data' not in data: return items
    for post in data.get('data', {}).get('children', []):
        d = post.get('data', {})
        title = unescape(d.get('title', ''))
        if len(title) < 5: continue
        items.append({
            "title": title, "content": unescape(d.get('selftext', '')[:200]),
            "url": f"https://reddit.com{d.get('permalink','')}",
            "platform": "reddit", "source": source['name'],
            "author": d.get('author', ''), "author_id": d.get('author_fullname',''),
            "category": source['category'],
            "hot_score": float(d.get('score', 0)),
            "view_count": d.get('view_count', 0), "like_count": d.get('score', 0),
            "comment_count": d.get('num_comments', 0),
            "collect_count": d.get('num_crossposts', 0), "share_count": d.get('num_share', 0),
            "published_at": datetime.fromtimestamp(d.get('created_utc', 0)).isoformat() if d.get('created_utc') else None,
            "lang": "en",
            "raw_data": json.dumps(d, ensure_ascii=False)
        })
    return items

def fetch_huggingface(source):
    """HuggingFace采集"""
    items = []
    html = fetch_url(source['url'])
    if not html: return items
    # 解析模型名称和描述
    patterns = re.findall(r'<a href="/([^"]+)"[^>]*class="[^"]*trending[^"]*"[^>]*>([^<]+)</a>', html)
    for path, name in patterns[:20]:
        items.append({
            "title": unescape(name.strip()),
            "content": f"https://huggingface.co/{path}",
            "url": f"https://huggingface.co/{path}",
            "platform": "huggingface", "source": source['name'],
            "author": path.split('/')[0] if '/' in path else '',
            "author_id": "", "category": source['category'],
            "hot_score": 1000, "lang": "en",
            "view_count": 0, "like_count": 0, "comment_count": 0,
            "collect_count": 0, "share_count": 0, "published_at": None,
            "raw_data": "{}"
        })
    return items

def fetch_toutiao(source):
    """今日头条采集(官方API + 多类别支持)"""
    items = []
    # 优先使用官方API(支持多类别)
    category = source.get('category', 'hot')
    cat_map = {'科技': 'tech', '汽车': 'car', '游戏': 'game', '体育': 'sports', 
               '娱乐': 'entertainment', '财经': 'finance', '军事': 'military',
               '国际': 'world', '科学': 'science', '综合': '__all__'}
    cat_param = cat_map.get(category, '__all__')
    
    url = f"https://www.toutiao.com/api/pc/feed/?min_behot_time=0&category={cat_param}&count=20&source=input"
    data = fetch_url(url, headers={"Referer": "https://www.toutiao.com/"})
    
    if data and 'data' in data:
        for item in data.get('data', [])[:20]:
            title = unescape(item.get('title', ''))
            if len(title) < 5: continue
            items.append({
                "title": title, "content": unescape(item.get('abstract','')[:200]),
                "url": item.get('article_url','') or f"https://www.toutiao.com/c/user/token/MS4wLjABAAA/{item.get('id','')}/",
                "platform": "toutiao", "source": source['name'],
                "author": item.get('user_info', {}).get('name', ''),
                "author_id": str(item.get('user_info', {}).get('user_id', '')),
                "category": item.get('chinese_tag', category),
                "hot_score": float(item.get('go_detail_count', 5000)),
                "view_count": item.get('read_count', 0), "like_count": item.get('digg_count', 0),
                "comment_count": item.get('comment_count', 0),
                "collect_count": item.get('collect_count', 0), "share_count": item.get('share_count', 0),
                "published_at": item.get('publish_time', ''),
                "lang": "zh", "raw_data": json.dumps(item, ensure_ascii=False)
            })
    return items

def fetch_douyin(source):
    """抖音热搜采集(官方API,稳定可靠)"""
    items = []
    # 优先使用官方API(稳定返回49条热搜)
    url = "https://www.douyin.com/aweme/v1/web/hot/search/list/?device_platform=webapp&aid=6383&channel=channel_pc_web&detail_list=1"
    data = fetch_url(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://www.douyin.com/",
        "Accept": "application/json"
    })
    if not data or 'data' not in data:
        # 备用:使用source['url']
        data = fetch_url(source['url'])
        if not data or 'data' not in data: return items
    for item in data.get('data', {}).get('word_list', []):
        word = item.get('word', '')
        if len(word) < 3: continue
        items.append({
            "title": unescape(word), "content": item.get('desc',''),
            "url": "https://www.douyin.com/search/" + urllib.parse.quote(word),
            "platform": "douyin", "source": source['name'],
            "author": "", "author_id": "", "category": source['category'],
            "hot_score": float(item.get('hot_value', 0)),
            "view_count": 0, "like_count": 0, "comment_count": 0,
            "collect_count": 0, "share_count": 0, "published_at": None,
            "lang": "zh",
            "raw_data": json.dumps(item, ensure_ascii=False)
        })
    return items


def fetch_kuaishou(source):
    """快手采集(多方法 fallback)"""
    items = []
    html = fetch_url(source['url'], headers={
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15"
    })
    if not html: return items
    
    # 方法1:提取 caption(视频描述)
    captions = re.findall(r'"caption":"([^"]{3,200})"', html)
    hot_values = re.findall(r'"hotValue":(\d+)', html)
    for i, cap in enumerate(captions[:20]):
        cap = unescape(cap)
        if len(cap) < 3: continue
        h = int(hot_values[i]) if i < len(hot_values) else 5000
        items.append({
            "title": cap[:80], "content": "",
            "url": "https://www.kuaishou.com/",
            "platform": "kuaishou", "source": source['name'],
            "author": "", "author_id": "", "category": source['category'],
            "hot_score": float(h), "lang": "zh",
            "view_count": 0, "like_count": 0, "comment_count": 0,
            "collect_count": 0, "share_count": 0, "published_at": None,
            "raw_data": "{}"
        })
    
    # 方法2:如果没数据,提取 name 字段(用户名)
    if not items:
        names = re.findall(r'"name":"([^"]{2,30})"', html)
        for name in names[:20]:
            name = unescape(name)
            if len(name) < 2: continue
            items.append({
                "title": f"[快手]{name}", "content": "",
                "url": "https://www.kuaishou.com/",
                "platform": "kuaishou", "source": source['name'],
                "author": name, "author_id": "", "category": source['category'],
                "hot_score": 3000, "lang": "zh",
                "view_count": 0, "like_count": 0, "comment_count": 0,
                "collect_count": 0, "share_count": 0, "published_at": None,
                "raw_data": "{}"
            })
    return items

def fetch_rss(source):
    """RSS/博客采集"""
    items = []
    data = fetch_url(source['url'], timeout=15)
    if not data: return items
    try:
        import xml.etree.ElementTree as ET
        root = ET.fromstring(data.encode('utf-8') if isinstance(data, str) else data)
        ns = {'atom': 'http://www.w3.org/2005/Atom'}
        entries = root.findall('.//entry') or root.findall('.//item') or []
        for entry in entries[:20]:
            title_el = entry.find('title') or entry.find('atom:title')
            title = unescape(title_el.text.strip()) if title_el is not None and title_el.text else ''
            if len(title) < 5: continue
            link_el = entry.find('link') or entry.find('atom:link')
            if link_el is not None:
                url = link_el.get('href') or (link_el.text if hasattr(link_el, 'text') else '')
            else:
                url = ''
            content_el = entry.find('content') or entry.find('description') or entry.find('summary')
            content = unescape(content_el.text.strip()[:300]) if content_el is not None and content_el.text else ''
            pub_el = entry.find('published') or entry.find('updated') or entry.find('pubDate')
            pub = pub_el.text.strip() if pub_el is not None and pub_el.text else None
            items.append({
                "title": title, "content": content,
                "url": url, "platform": source['platform'], "source": source['name'],
                "author": "", "author_id": "", "category": source['category'],
                "hot_score": 1000, "lang": source['lang'],
                "view_count": 0, "like_count": 0, "comment_count": 0,
                "collect_count": 0, "share_count": 0, "published_at": pub,
                "raw_data": "{}"
            })
    except Exception:
        pass
    return items

def fetch_rsshub(source):
    """RSSHub桥接采集(微信公众号/Telegram等)"""
    return fetch_rss(source)

def fetch_ithome(source):
    """IT之家采集"""
    items = []
    html = fetch_url(source['url'])
    if not html: return items
    titles = re.findall(r'<h2[^>]*><a[^>]*>([^<]+)</a></h2>', html)
    urls = re.findall(r'<h2[^>]*><a[^>]*href="([^"]+)"', html)
    for title, url in zip(titles[:20], urls[:20]):
        title = unescape(title.strip())
        if len(title) < 5: continue
        full_url = url if url.startswith('http') else f"https://www.ithome.com{url}"
        items.append({
            "title": title, "content": "",
            "url": full_url, "platform": "ithome", "source": source['name'],
            "author": "", "author_id": "", "category": source['category'],
            "hot_score": 5000, "lang": "zh",
            "view_count": 0, "like_count": 0, "comment_count": 0,
            "collect_count": 0, "share_count": 0, "published_at": None,
            "raw_data": "{}"
        })
    return items

def fetch_oschina(source):
    """开源中国采集"""
    items = []
    html = fetch_url(source['url'])
    if not html: return items
    titles = re.findall(r'<h2[^>]*><a[^>]*>([^<]+)</a></h2>', html)
    urls = re.findall(r'<h2[^>]*><a[^>]*href="([^"]+)"', html)
    for title, url in zip(titles[:20], urls[:20]):
        title = unescape(title.strip())
        if len(title) < 5: continue
        full_url = url if url.startswith('http') else f"https://www.oschina.net{url}"
        items.append({
            "title": title, "content": "",
            "url": full_url, "platform": "oschina", "source": source['name'],
            "author": "", "author_id": "", "category": source['category'],
            "hot_score": 3000, "lang": "zh",
            "view_count": 0, "like_count": 0, "comment_count": 0,
            "collect_count": 0, "share_count": 0, "published_at": None,
            "raw_data": "{}"
        })
    return items

def fetch_solidot(source):
    """Solidot采集"""
    items = []
    html = fetch_url(source['url'])
    if not html: return items
    titles = re.findall(r'<h2[^>]*><a[^>]*>([^<]+)</a></h2>', html)
    urls = re.findall(r'<h2[^>]*><a[^>]*href="([^"]+)"', html)
    summaries = re.findall(r'<p class="p_how">([^<]+)</p>', html)
    for title, url in zip(titles[:20], urls[:20]):
        title = unescape(title.strip())
        if len(title) < 5: continue
        full_url = url if url.startswith('http') else f"https://www.solidot.org{url}"
        idx = list(zip(titles[:20], urls[:20])).index((title, url))
        summary = unescape(summaries[idx]) if idx < len(summaries) else ''
        items.append({
            "title": title, "content": summary[:200],
            "url": full_url, "platform": "solidot", "source": source['name'],
            "author": "", "author_id": "", "category": source['category'],
            "hot_score": 2000, "lang": "zh",
            "view_count": 0, "like_count": 0, "comment_count": 0,
            "collect_count": 0, "share_count": 0, "published_at": None,
            "raw_data": "{}"
        })
    return items

def fetch_huxiu(source):
    """虎嗅采集"""
    items = []
    html = fetch_url(source['url'])
    if not html: return items
    titles = re.findall(r'<h2[^>]*><a[^>]*>([^<]+)</a></h2>', html)
    urls = re.findall(r'<h2[^>]*><a[^>]*href="([^"]+)"', html)
    for title, url in zip(titles[:20], urls[:20]):
        title = unescape(title.strip())
        if len(title) < 5: continue
        full_url = url if url.startswith('http') else f"https://www.huxiu.com{url}"
        items.append({
            "title": title, "content": "",
            "url": full_url, "platform": "huxiu", "source": source['name'],
            "author": "", "author_id": "", "category": source['category'],
            "hot_score": 5000, "lang": "zh",
            "view_count": 0, "like_count": 0, "comment_count": 0,
            "collect_count": 0, "share_count": 0, "published_at": None,
            "raw_data": "{}"
        })
    return items

def fetch_36kr(source):
    """36氪采集"""
    items = []
    data = fetch_url("https://36kr.com/api/newsflash/index?per_page=30&page=1")
    if not data or 'data' not in data: return items
    for item in data.get('data', {}).get('items', []):
        title = unescape(item.get('title', ''))
        if len(title) < 5: continue
        items.append({
            "title": title, "content": unescape(item.get('description','')[:200]),
            "url": item.get('news_url','') or f"https://36kr.com/p/{item.get('item_id','')}",
            "platform": "36kr", "source": source['name'],
            "author": item.get('author', ''), "author_id": str(item.get('user_id','')),
            "category": source['category'],
            "hot_score": float(item.get('hot_score', 0) or 5000),
            "view_count": 0, "like_count": 0, "comment_count": 0,
            "collect_count": 0, "share_count": 0, "published_at": item.get('published_at',''),
            "lang": "zh",
            "raw_data": json.dumps(item, ensure_ascii=False)
        })
    return items

def fetch_arxiv(source):
    """arXiv论文采集"""
    items = []
    html = fetch_url(source['url'])
    if not html: return items
    titles = re.findall(r'<div class="dt-main"><a[^>]*href="([^"]+)"[^>]*>\d+\.\d+</a></div>.*?<div class="title">(.*?)</div>', html, re.DOTALL)
    abs_pattern = r'<div class="abstract-full">(.*?)</div>'
    abstracts = re.findall(abs_pattern, html, re.DOTALL)
    for i, (url, title) in enumerate(titles[:20]):
        title = unescape(title.strip().replace('\n', ' '))
        if len(title) < 10: continue
        abstract = unescape(abstracts[i].strip()[:300]) if i < len(abstracts) else ''
        items.append({
            "title": title, "content": abstract,
            "url": f"https://arxiv.org{url}",
            "platform": "arxiv", "source": source['name'],
            "author": "", "author_id": "", "category": source['category'],
            "hot_score": 1000, "lang": "en",
            "view_count": 0, "like_count": 0, "comment_count": 0,
            "collect_count": 0, "share_count": 0, "published_at": None,
            "raw_data": "{}"
        })
    return items

def fetch_generic(source):
    """通用HTML采集"""
    items = []
    html = fetch_url(source['url'])
    if not html: return items
    titles = re.findall(r'<h[123][^>]*>\s*<a[^>]*>([^<]+)</a>', html)
    urls = re.findall(r'<h[123][^>]*>\s*<a[^>]*href="([^"]+)"[^>]*>[^<]+</a>', html)
    for title, url in zip(titles[:20], urls[:20]):
        title = unescape(title.strip())
        if len(title) < 5: continue
        full_url = url if url.startswith('http') else (source['url'].split('/')[0] + '//' + source['url'].split('/')[2] + url)
        items.append({
            "title": title, "content": "",
            "url": full_url, "platform": source['platform'], "source": source['name'],
            "author": "", "author_id": "", "category": source['category'],
            "hot_score": 1000, "lang": source['lang'],
            "view_count": 0, "like_count": 0, "comment_count": 0,
            "collect_count": 0, "share_count": 0, "published_at": None,
            "raw_data": "{}"
        })
    return items

# 采集分发器
FETCHERS = {
    'bilibili': fetch_bilibili,
    'weibo': fetch_weibo,
    'zhihu': fetch_zhihu,
    'github': fetch_github,
    'reddit': fetch_reddit,
    'huggingface': fetch_huggingface,
    'toutiao': fetch_toutiao,
    'douyin': fetch_douyin,
    'kuaishou': fetch_kuaishou,
    'rss': fetch_rss,
    'rsshub': fetch_rsshub,
    'ithome': fetch_ithome,
    'oschina': fetch_oschina,
    'solidot': fetch_solidot,
    'huxiu': fetch_huxiu,
    '36kr': fetch_36kr,
    'arxiv': fetch_arxiv,
}

def fetch_source(source, result_queue):
    """单来源采集(供线程池调用)"""
    ptype = source['type']
    fetcher_key = ptype if ptype in FETCHERS else source['platform']
    if fetcher_key not in FETCHERS:
        fetcher_key = 'generic'
    fetcher = FETCHERS.get(fetcher_key, fetch_generic)
    try:
        items = fetcher(source)
    except Exception as e:
        items = []
    result_queue.put((source['name'], items))

def collect_all(sources, max_workers=20):
    """Multi-Agent并行采集:调度Agent分发任务到多个子Agent线程"""
    all_items = []
    result_queue = queue.Queue()
    threads = []
    
    for source in sources:
        t = threading.Thread(target=fetch_source, args=(source, result_queue))
        threads.append(t)
        t.start()
    
    for t in threads:
        t.join(timeout=30)
    
    while not result_queue.empty():
        name, items = result_queue.get()
        all_items.extend(items)
    
    return all_items

# ============================================================
# 清洗去重
# ============================================================
def is_noise(title, content):
    text = (title + content).lower()
    return sum(1 for kw in NOISE_KW if kw.lower() in text) >= 1

def get_chinese_ratio(text):
    c = len(re.findall(r'[\u4e00-\u9fff]', text))
    return c / len(text) if len(text) > 0 else 0

def clean_dedup(items):
    """清洗+去重(1天内已推送的不重复)"""
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT title FROM push_records WHERE push_status='sent' AND push_time > datetime('now','-7 days')")
    sent_titles = set(r[0].lower() for r in c.fetchall())
    c.execute("SELECT title FROM cleaned_intelligence WHERE cleaned_at > datetime('now','-1 days')")
    recent_titles = set(r[0].lower() for r in c.fetchall())
    conn.close()
    
    seen = set()
    result = []
    for item in items:
        t = item.get('title', '').strip()
        if len(t) < 8: continue
        t_lower = t.lower()
        if t_lower in seen or t_lower in sent_titles or t_lower in recent_titles: continue
        if is_noise(t, item.get('content', '')): continue
        seen.add(t_lower)
        result.append(item)
    return result

# ============================================================
# 评估函数
# ============================================================
def evaluate(item, conn=None):
    """5级重要性评估 + 趋势检测"""
    title, content = item.get('title', ''), item.get('content', '')
    hot = item.get('hot_score', 0)
    plat = item.get('platform', '')
    lang = item.get('lang', 'zh')
    text = (title + content).lower()
    
    # 关键词匹配
    kw_list = HIGH_KW_DOMESTIC if lang == 'zh' else HIGH_KW_INTL
    matched = [kw for kw in kw_list if kw.lower() in text]
    
    # 基础评分
    score = 0.0
    score += len(matched) * 5
    
    # 平台权重
    plat_weights = {'github': 15, 'bilibili': 10, 'weibo': 8, 'zhihu': 8,
                   'reddit': 8, 'huggingface': 10, 'arxiv': 8,
                   '36kr': 8, 'solidot': 8, 'ithome': 8, 'huxiu': 8,
                   'telegram': 7, 'twitter': 7, 'youtube': 6}
    pw = plat_weights.get(plat, 5)
    
    if hot > 0:
        if plat == 'github':
            score += pw if hot > 5000 else (pw * 0.5 if hot > 1000 else 0)
        elif plat in ('bilibili', 'weibo', 'zhihu', 'douyin'):
            score += pw if hot > 1000000 else (pw * 0.5 if hot > 100000 else 0)
        else:
            score += pw
    
    # 互动分数
    score += 3 if item.get('like_count', 0) > 1000 else 0
    score += 3 if item.get('comment_count', 0) > 500 else 0
    
    # 语言比例偏好
    chinese_ratio = get_chinese_ratio(title + content)
    item['chinese_ratio'] = chinese_ratio
    item['language'] = 'zh' if chinese_ratio > 0.5 else 'en'
    
    # 等级判定
    if len(matched) >= 4 and score >= 30:
        level = 5
    elif len(matched) >= 3 and score >= 20:
        level = 4
    elif len(matched) >= 2 and score >= 15:
        level = 3
    elif len(matched) >= 1 and score >= 8:
        level = 2
    else:
        level = 1
    
    item['importance_score'] = round(score, 1)
    item['value_level'] = level
    item['matched_keywords'] = ','.join(matched[:5])
    item['is_ai_related'] = 1 if any(kw in text for kw in ['AI','LLM','GPT','大模型','模型','神经','AI']) else 0
    
    return item

# ============================================================
# 趋势追踪 + 爆发检测
# ============================================================
def update_trends(evaluated_items, conn):
    """更新趋势追踪:检测3日连续和爆发"""
    c = conn.cursor()
    now = datetime.now().isoformat()
    
    for item in evaluated_items:
        if item['value_level'] < 3:
            continue
        
        keyword = item.get('matched_keywords', '').split(',')[0]
        title = item['title']
        
        # 检查是否已有追踪记录
        c.execute("SELECT id, hit_count, hit_days, source_count FROM trend_tracking WHERE title=? AND status='active'",
                  (title[:100],))
        row = c.fetchone()
        
        if row:
            # 更新已有记录
            trend_id, hit_count, hit_days, src_count = row
            new_count = hit_count + 1
            new_days = hit_days + 1 if item.get('published_at') else hit_days
            new_src = src_count + 1
            
            # 判断是否爆发(单日多渠道大量采集)
            is_extreme = 1 if new_count >= 5 and src_count >= 3 else 0
            is_hot = 1 if new_days >= 3 else 0
            
            c.execute("""UPDATE trend_tracking SET hit_count=?, hit_days=?, source_count=?,
                          is_hot=?, is_extreme=?, last_seen=?, updated_at=?,
                          importance_score=MAX(importance_score,?) WHERE id=?""",
                     (new_count, new_days, new_src, is_hot, is_extreme,
                      now, now, item['importance_score'], trend_id))
        else:
            # 新建追踪记录
            c.execute("""INSERT INTO trend_tracking 
                (keyword,title,url,source,platform,importance_score,first_seen,last_seen,hit_days,hit_count,source_count,is_hot,is_extreme,status)
                VALUES (?,?,?,?,?,?,?,?,1,1,1,0,0,'active')""",
                     (keyword, title[:100], item.get('url',''), item['source'],
                      item['platform'], item['importance_score'], now, now))
    
    conn.commit()

# ============================================================
# 存储
# ============================================================
def save_all(raw_items, evaluated, conn):
    c = conn.cursor()
    now = datetime.now().isoformat()
    
    # 保存原始数据
    for item in raw_items:
        try:
            c.execute("""INSERT OR IGNORE INTO raw_intelligence 
                (title,content,url,platform,source,author,category,hot_score,view_count,like_count,comment_count,published_at,raw_data,collected_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                     (item['title'], item.get('content',''), item.get('url',''),
                      item.get('platform',''), item.get('source',''), item.get('author',''),
                      item.get('category',''), item.get('hot_score',0), item.get('view_count',0),
                      item.get('like_count',0), item.get('comment_count',0),
                      item.get('published_at'), item.get('raw_data','{}'), now))
        except Exception:
            pass
    
    # 保存清洗后数据
    for item in evaluated:
        try:
            c.execute("""INSERT INTO cleaned_intelligence 
                (raw_id,title,content,url,source,platform,author,category,importance_score,value_level,value_reasons,is_ai_related,language,chinese_ratio,published_at,collected_at,cleaned_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                     (0, item['title'], item.get('content',''), item.get('url',''),
                      item['source'], item['platform'], item.get('author',''),
                      item.get('category',''), item['importance_score'], item['value_level'],
                      item.get('matched_keywords',''), item.get('is_ai_related',0),
                      item.get('language','zh'), item.get('chinese_ratio',1.0),
                      item.get('published_at'), now, now))
        except Exception:
            pass
    
    conn.commit()

# ============================================================
# 推送(修复:写入DB)
# ============================================================
def push_wechat(title, content, level=3, item=None, conn=None):
    emoji = {5: "🚨🚨🚨", 4: "🔥🔥", 3: "📣", 2: "📌", 1: "📝"}
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
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read().decode())
        
        # 写入推送记录
        if conn and item:
            c = conn.cursor()
            c.execute("""INSERT INTO push_records 
                (cleaned_id,title,content,url,source,platform,push_level,push_channel,push_status,push_time,push_response)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                     (0, item['title'], content[:500], item.get('url',''),
                      item['source'], item['platform'], level, 'wechat', 'sent',
                      datetime.now().isoformat(), json.dumps(result)))
            conn.commit()
        
        return result
    except Exception as e:
        if conn and item:
            c = conn.cursor()
            c.execute("""INSERT INTO push_records 
                (cleaned_id,title,content,url,source,platform,push_level,push_channel,push_status,push_time,push_response)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                     (0, item['title'], content[:500], item.get('url',''),
                      item['source'], item['platform'], level, 'wechat', 'failed',
                      datetime.now().isoformat(), str(e)))
            conn.commit()
        return {"code": -1, "msg": str(e)}

# ============================================================
# 报告生成(含背景+技术分析)
# ============================================================
def build_report(items, level_filter=None):
    if level_filter:
        filtered = [x for x in items if x['value_level'] >= level_filter]
    else:
        filtered = items
    
    date = datetime.now().strftime('%Y-%m-%d %H:%M')
    lines = [
        f"# 📊 全平台情报日报 | {date}",
        "",
        f"**采集**: {len(items)}条 | **高价值(LV4+)**: {sum(1 for x in items if x['value_level']>=4)}条 | "
        f"**重要(LV3)**: {sum(1 for x in items if x['value_level']==3)}条",
        ""
    ]
    
    # 极端重要
    extreme = [x for x in filtered if x['value_level'] == 5]
    if extreme:
        lines += ["---", "", "## 🚨 极端重要(单日爆发/舆情极热)", ""]
        for i, item in enumerate(extreme[:5], 1):
            lines += [
                f"### {i}. {item['title'][:60]}",
                f"- 📍{item['source']} | ⭐{item['importance_score']} | {item.get('matched_keywords','')[:40]}",
                f"- 🔗 {item.get('url','')}",
                ""
            ]
    
    # 非常重要
    high = [x for x in filtered if x['value_level'] == 4]
    if high:
        lines += ["---", "", "## 🔥 非常重要(3日+连续监测)", ""]
        for i, item in enumerate(high[:8], 1):
            lines += [
                f"### {i}. {item['title'][:60]}",
                f"- 📍{item['source']} | ⭐{item['importance_score']} | {item.get('matched_keywords','')[:40]}",
                f"- 🔗 {item.get('url','')}",
                ""
            ]
    
    # 重要
    medium = [x for x in filtered if x['value_level'] == 3]
    if medium:
        lines += ["---", "", "## 📣 重要内容(多渠道相关联)", ""]
        for i, item in enumerate(medium[:5], 1):
            lines += [
                f"### {i}. {item['title'][:60]}",
                f"- 📍{item['source']} | {item.get('matched_keywords','')[:30]}",
                ""
            ]
    
    # AI相关汇总
    ai_items = [x for x in filtered if x.get('is_ai_related')]
    if ai_items:
        lines += ["---", "", f"## 🤖 AI相关 ({len(ai_items)}条)", ""]
        for x in ai_items[:5]:
            lines += [f"- {x['title'][:55]} [{x['source']}]", ""]
    
    lines += ["---", f"*由 Hermes 全自动采集 | {date}*"]
    return '\n'.join(lines)

# ============================================================
# 主运行函数(Multi-Agent调度)
# ============================================================
def run(dry_run=False, urgent_only=False, agent_filter=None):
    print(f"\n{'='*60}")
    print(f"  Hermes 全平台智能情报系统 v2 - Multi-Agent采集")
    print(f"{'='*60}")
    
    # 过滤来源
    if agent_filter == '国内':
        sources = [s for s in ALL_SOURCES if s.get('lang','zh') == 'zh']
    elif agent_filter == '海外':
        sources = [s for s in ALL_SOURCES if s.get('lang','en') == 'en']
    else:
        sources = ALL_SOURCES
    
    print(f"\n[调度Agent] 已分配 {len(sources)} 个采集子Agent")
    
    print(f"\n[Step 1] Multi-Agent并行采集...")
    all_items = collect_all(sources, max_workers=20)
    print(f"  总计采集: {len(all_items)}条")
    if not all_items:
        print("  ⚠️ 采集为空,尝试备用方案...")
        # 备用:只采B站+微博+GitHub
        fallback = [s for s in ALL_SOURCES if s['platform'] in ('bilibili','weibo','github','36kr','solidot')]
        all_items = collect_all(fallback, max_workers=10)
        print(f"  备用采集: {len(all_items)}条")
    
    print(f"\n[Step 2] 清洗去重...")
    cleaned = clean_dedup(all_items)
    print(f"  清洗后: {len(cleaned)}条")
    
    print(f"\n[Step 3] 评估分析...")
    evaluated = sorted([evaluate(i) for i in cleaned], key=lambda x: x['importance_score'], reverse=True)
    for lv in sorted(set(x['value_level'] for x in evaluated), reverse=True):
        cnt = sum(1 for x in evaluated if x['value_level'] == lv)
        print(f"  ⭐{lv}: {cnt}条")
    
    # 趋势更新
    conn = get_db()
    print(f"\n[Step 4] 趋势追踪更新...")
    update_trends(evaluated, conn)
    print(f"  趋势追踪已更新")
    
    if not dry_run:
        print(f"\n[Step 5] 存储数据库...")
        save_all(all_items, evaluated, conn)
        print(f"  原始+清洗数据已存储")
        
        print(f"\n[Step 6] 推送...")
        # ⭐5/⭐4 立即推送
        high_items = [x for x in evaluated if x['value_level'] >= 4]
        if urgent_only:
            high_items = [x for x in evaluated if x['value_level'] == 5]
        
        for item in high_items[:10]:
            bg = f"**来源**: {item['source']} | **平台**: {item['platform']}\n\n"
            content = bg + f"**关键词**: {item.get('matched_keywords','')}\n\n**链接**: {item.get('url','')}"
            r = push_wechat(f"⭐{item['value_level']}级情报: {item['title'][:30]}", content, item['value_level'], item, conn)
            print(f"  {'✅' if r.get('code')==200 else '❌'} [LV{item['value_level']}] {item['title'][:40]}")
            time.sleep(1.5)
        
        # 日报推送
        report = build_report(evaluated)
        r = push_wechat("全平台情报日报", report, 3, {'title': '日报', 'url': '', 'source': '系统', 'platform': 'system'}, conn)
        print(f"\n  {'✅ 日报已推送' if r.get('code')==200 else '❌ 日报推送失败'}")
    
    conn.close()
    print(f"\n[完成] {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

# ============================================================
# 入口
# ============================================================
if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description='Hermes 全平台智能情报系统 v2')
    p.add_argument('--dry-run', action='store_true', help='仅评估不推送')
    p.add_argument('--urgent', action='store_true', help='仅推送极端重要')
    p.add_argument('--agent', choices=['国内','海外'], default=None, help='指定采集范围')
    args = p.parse_args()
    run(dry_run=args.dry_run, urgent_only=args.urgent, agent_filter=args.agent)
