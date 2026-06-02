#!/usr/bin/env python3
"""
Hermes 情报清洗管道 v2 (Enhanced)
====================================
带热点保底 + 宽泛白名单过滤规则

规则:
1. 每个平台每个子方向前8条 → 直接放行(热点保底)
2. 8条之后 → 仅保留匹配宽泛白名单320+关键词的内容
3. 白名单覆盖16大分类
"""
import sqlite3, hashlib, re, json, logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional, Tuple, Set

HERMES = Path("/home/administrator/.hermes")
DB_PATH = HERMES / "intelligence.db"
LOG_PATH = HERMES / "logs" / f"cleaning_{datetime.now().strftime('%Y%m%d')}.log"
LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

def merge_tags(tags: str, category_tags: str) -> str:
    """合并raw_intelligence.tags和category_tags到cleaned_intelligence.tags"""
    parts = set()
    for src in [tags, category_tags]:
        for p in str(src).split('|'):
            p = p.strip()
            if p:
                parts.add(p)
    return '|'.join(sorted(parts)) if parts else ''

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler(LOG_PATH, encoding="utf-8"), logging.StreamHandler()]
)
log = logging.getLogger("cleaning_pipeline_v2")

# ═══════════════════════════════════════════════════════════════════════════════
# 宽泛白名单 — 320+ 关键词,覆盖16大分类
# ═══════════════════════════════════════════════════════════════════════════════
BROAD_WHITELIST = [
    # ═══ 1. AI / 大模型(30+ 词)═══
    "ai", "人工智能", "大模型", "llm", "gpt", "chatgpt", "openai", "claude",
    "anthropic", "gemini", "deepseek", "qwen", "yi", "mistral", "llama",
    "phi", "grok", "sora", "aigc", "生成式", "扩散模型", "transformer",
    "attention", "神经网络", "深度学习", "机器学习", "强化学习", "rlhf",
    "dpo", "grpo", "ppo", "fine-tuning", "微调", "rag", "embedding",
    "向量数据库", "langchain", "autogen", "crewai", "agent", "多智能体",
    "multi-agent", "mcp", "function calling", "tool use", "function call",
    "推理", "reasoning", "思维链", "chain-of-thought", "cot",

    # ═══ 2. IT / 开发(50+ 词)═══
    "python", "rust", "golang", "go语言", "typescript", "javascript", "java",
    "c++", "csharp", "c#", "kotlin", "swift", "ruby", "php", "scala",
    "zig", "mojo", "haskell", "elixir", "erlang", "dart", "lua",
    "react", "vue", "angular", "svelte", "nextjs", "nuxt", "solidjs",
    "node", "bun", "deno", "spring", "django", "flask", "fastapi",
    "torch", "pytorch", "tensorflow", "jax", "cuda", "triton",
    "docker", "kubernetes", "k8s", "容器", "微服务", "serverless",
    "api", "rest", "graphql", "grpc", "websocket", "http",
    "git", "github", "gitlab", "ci/cd", "devops", "mlops",
    "linux", "unix", "bash", "shell", "vim", "neovim", "vscode",
    "ide", "编译器", "interpreter", "debug", "调试", "测试",
    "pytest", "jest", "单元测试", "e2e", "集成测试",
    "redis", "kafka", "rabbitmq", "nginx", "postgresql", "mysql",
    "mongodb", "sqlite", "elasticsearch", "clickhouse", "doris",
    "orm", "sql", "nosql", "数据库",
    "架构", "设计模式", "重构", "代码质量", "技术债务",
    "开源", "open source", "oss", "license", "许可证",
    "云原生", "cloud native", "分布式", "分布式系统",
    "webassembly", "wasm", "边缘计算", "edge computing",

    # ═══ 3. 消费电子 / 硬件(30+ 词)═══
    "iphone", "apple", "macbook", "ipad", "airpods", "vision pro",
    "samsung", "galaxy", "华为", "huawei", "mate", "p系列",
    "小米", "xiaomi", "oppo", "vivo", "荣耀", "honor",
    "一加", "oneplus", "谷歌", "pixel", "android", "ios",
    "芯片", "chip", "soc", "骁龙", "snapdragon", "a系列芯片",
    "m系列", "m4", "m3", "a18", "amd", "intel", "nvidia",
    "rtx", "gpu", "cpu", "内存", "ram", "存储", "ssd",
    "屏幕", "display", "oled", "mini-led", "刷新率",
    "充电", "快充", "电池", "battery", "续航",
    "折叠屏", "foldable", "可折叠",

    # ═══ 4. 通信 / 网络(20+ 词)═══
    "5g", "6g", "wifi", "wifi7", "蓝牙", "bluetooth", "lora",
    "卫星通信", "星链", "starlink", "卫星互联网",
    "光通信", "光纤", "光模块", "800g", "1.6t",
    "ipv6", "dns", "cdn", "vpn", "代理", "proxy",
    "tcp/ip", "quic", "http/3",
    "物联网", "iot", "nb-iot", "cat.1",

    # ═══ 5. 新能源汽车(30+ 词)═══
    "特斯拉", "tesla", "比亚迪", "byd", "蔚来", "nio",
    "小鹏", "xpeng", "理想", "li auto", "问界", "aito",
    "极氪", "zeekr", "小米汽车", "su7", "yu7",
    "华为汽车", "鸿蒙智行", "智界", "享界",
    "电动汽车", "ev", "新能源车", "混动", "phev",
    "自动驾驶", "autopilot", "fsd", "智能驾驶", "智驾",
    "激光雷达", "lidar", "雷达", "摄像头",
    "固态电池", "固态电池", "锂电", "磷酸铁锂", "刀片电池",
    "超充", "换电", "充电桩", "续航里程",
    "车内", "座舱", "智能座舱", "hud",

    # ═══ 6. 军事 / 国防(20+ 词)═══
    "军事", "国防", "军队", "导弹", "火箭", "卫星军事",
    "战斗机", "航母", "舰船", "潜艇", "无人机军事",
    "东风", "歼", "运", "直", "核武器",
    "军演", "演习", "北约", "nato", "美军",
    "台海", "南海", "地缘政治", "制裁", "国防预算",
    "网络安全", "cyber warfare", "网络战",

    # ═══ 7. 体育(20+ 词)═══
    "体育", "sports", "nba", "cba", "足球", "篮球",
    "世界杯", "奥运会", "亚运会", "欧冠",
    "c罗", "梅西", "姆巴佩", "勒布朗", "库里",
    "ufc", "拳击", "格斗", "mma",
    "乒乓球", "羽毛球", "游泳", "田径",
    "中超", "英超", "西甲", "意甲",

    # ═══ 8. 格斗 / MMA 专项(15+ 词)═══
    "ufc", "mma", "bellator", "one冠军赛",
    "综合格斗", "拳击", "散打", "泰拳", "柔术",
    "张伟丽", "李景亮", "骨头", "琼斯", "康纳",
    "嘴炮", "骨头琼斯", "ko", "tko", "降服",
    "裸绞", "十字固", "三角锁", "断头台",

    # ═══ 9. 美女 / 写真 / 摄影(30+ 词)═══
    "写真", "摄影", "photography", "人像", "肖像",
    "时尚", "fashion", "模特", "model", "超模",
    "妆容", "化妆", "美容", "美妆", "护肤",
    "穿搭", "街拍", "街拍", "ootd",
    "壁纸", "wallpaper", "高清", "4k",
    "相机", "camera", "镜头", "索尼", "canon",
    "尼康", "nikon", "富士", "fujifilm",
    "徕卡", "leica", "哈苏", "hasselblad",
    "胶片", "film", "数码", "cmos",
    "vlog", "短视频", "短视频创作",
    "cosplay", "cos", "二次元", "动漫",

    # ═══ 10. 电影 / 娱乐(20+ 词)═══
    "电影", "movie", "film", "票房", "上映",
    "导演", "演员", "明星", "好莱坞", "hollywood",
    "漫威", "marvel", "dc", "迪士尼", "netflix",
    "奥斯卡", "戛纳", "金鸡", "金马",
    "纪录片", "动画电影", "科幻", "动作片",
    "剧集", "电视剧", "美剧", "韩剧", "日剧",
    "综艺", "真人秀", "b站", "抖音", "tiktok",

    # ═══ 11. 旅游 / 地理(15+ 词)═══
    "旅游", "旅行", "travel", "景点", "风景",
    "酒店", "民宿", "度假", "自驾", "背包",
    "签证", "免签", "护照", "海关",
    "国内游", "出境游", "跟团", "自由行",
    "攻略", "游记", "打卡", "网红景点",
    "自然风光", "城市", "古镇", "海岛",

    # ═══ 12. 科学 / 科普(20+ 词)═══
    "科学", "science", "物理", "化学", "生物",
    "数学", "数学", "天文", "宇宙", "太空",
    "nasa", "spacex", "火箭", "探测器", "火星",
    "基因", "基因组", "dna", "rna", "crispr",
    "量子", "quantum", "量子计算", "量子通信",
    "材料", "新材料", "超导", "纳米",
    "考古", "化石", "恐龙", "进化",
    "气候", "环境", "环保", "碳中和",

    # ═══ 13. 安全(15+ 词)═══
    "安全", "security", "黑客", "hacker", "渗透",
    "漏洞", "cve", "exploit", "0day",
    "加密", "encryption", "密码学", "cryptography",
    "隐私", "privacy", "数据安全", "个人信息保护",
    "反诈", "钓鱼", "phishing", "勒索", "ransomware",
    "防火墙", "防火墙", "入侵检测", "ids", "ips",
    "杀毒", "antivirus", "edr", "xdr",

    # ═══ 14. 游戏(20+ 词)═══
    "游戏", "gaming", "game", "steam", "epic",
    "ps5", "playstation", "xbox", "switch", "任天堂",
    "nintendo", "pc游戏", "主机", "手游",
    "原神", "genshin", "王者荣耀", "lol", "英雄联盟",
    "绝地求生", "pubg", "apex", "valorant", "csgo",
    "3a", "3a大作", "独立游戏", "indie",
    "游戏开发", "game dev", "unity", "unreal",
    "元宇宙", "metaverse", "web3", "nft",
    "电竞", "esports", "电竞赛事",

    # ═══ 15. 机器人(15+ 词)═══
    "机器人", "robot", "robotics", "人形机器人",
    "humanoid", "擎天柱", "optimus", "tesla bot",
    "机器狗", "四足", "宇树", "unitree",
    "figure", "波士顿动力", "boston dynamics",
    "协作机器人", "cobot", "工业机器人",
    "机器臂", "机械手", "gripper",
    "自主导航", "slam", "运动控制",

    # ═══ 16. 社会热点(20+ 词)═══
    "新闻", "热点", "热搜", "突发",
    "政策", "法规", "法律", "立法",
    "经济", "经济", "股市", "a股", "美股",
    "央行", "利率", "通胀", "gdp",
    "贸易", "关税", "出口", "供应链",
    "教育", "就业", "房价", "医保",
    "人口", "老龄化", "生育", "三孩",
    "民生", "消费", "物价",
    "地震", "台风", "洪水", "灾害",
    "抗议", "罢工", "选举", "总统",
    "中东", "乌克兰", "俄罗斯", "美国",
    "中国", "中美", "中欧", "一带一路",
]

# 构建白名单集合(全部小写)
WHITELIST_SET = set(kw.lower() for kw in BROAD_WHITELIST)

# 白名单长度
WHITELIST_SIZE = len(WHITELIST_SET)
log.info(f"宽泛白名单加载完成: {WHITELIST_SIZE} 关键词,覆盖16大分类")

# ── 噪声关键词 ────────────────────────────────────────────────────────────────
NOISE_PATTERNS = [
    "广告", "推广", "抽奖", "中奖", "红包", "优惠券", "秒杀",
    "震惊", "惊人", "必看", "转疯了", "删前必看",
    "抖音带货", "快手带货", "直播带货",
    # 热度数值噪声(快手等平台产生的纯数字热度标题)
    "万热度", "热度", "播放", "点赞",
]

# 热度数值标题正则(如: "1095.9万热度", "999.7万热度")
HEAT_NUM_PATTERN = re.compile(r'^\d+(\.\d+)?万热度$')
HEAT_NUM_PATTERN2 = re.compile(r'^\d+(\.\d+)?万$')
# UI导航标签黑名单
UI_LABELS = {'快手轻量版', '快币充值', '上传视频', '我的关注', '短视频', 'AcFun', '喜番短剧', '三角洲'}

# ── 平台权重 ────────────────────────────────────────────────────────────────
PLATFORM_WEIGHTS = {
    "github": 2.0, "bilibili": 1.5, "36kr": 1.5,
    "zhihu": 1.2, "reddit": 1.3, "oschina": 1.5,
    "huxiu": 1.3, "sspai": 1.4, "ithome": 1.2,
    "weibo": 0.8, "twitter": 1.0, "youtube": 1.0,
    "solidot": 1.6, "liangziwei": 1.4, "infoq": 1.5,
    "hackernews": 1.8, "juejin": 1.5, "segmentfault": 1.5,
    "cnblogs": 1.3, "douyin": 0.6, "tieba": 0.5,
    "baidu": 1.0, "toutiao": 1.0, "kuaishou": 0.6,
    "sogou_wechat": 1.0, "sina_tech": 1.3, "tmtpost": 1.3,
    "default": 1.0,
}


def normalize_source(source: str) -> str:
    """统一采集源名称 — 消除大小写/中英文/后缀变体"""
    if not source:
        return ""
    s = source.strip()
    # 大小写归一
    mapping = {
        "hackernews": "hackernews", "HackerNews": "hackernews",
        "ithome": "ithome", "IT之家": "ithome",
        "github": "github", "GitHub Trending": "github",
        "GitHub-Python": "github", "GitHub-javascript": "github", "GitHub-typescript": "github",
        "bilibili": "bilibili", "B站-全站": "bilibili", "B站-科技": "bilibili", "bilibili_全站": "bilibili",
        "baidu": "baidu", "百度-热搜": "baidu", "百度热搜": "baidu",
        "weibo": "weibo", "微博-微博热搜": "weibo", "微博-热搜": "weibo",
        "oschina": "oschina", "开源中国": "oschina",
        "zhihu": "zhihu", "知乎": "zhihu",
        "cnblogs": "cnblogs", "博客园": "cnblogs",
        "douyin": "douyin", "抖音-热搜": "douyin",
        "36kr": "36kr", "36氪": "36kr",
        "huxiu": "huxiu", "虎嗅": "huxiu",
        "sspai": "sspai", "少数派": "sspai",
        "juejin": "juejin", "掘金": "juejin",
        "solidot": "solidot", "奇客": "solidot",
        "tmtpost": "tmtpost", "钛媒体": "tmtpost",
    }
    if s in mapping:
        return mapping[s]
    return s


def extract_platform_prefix(source: str) -> str:
    """提取平台主方向,用于热点保底计数"""
    if not source:
        return "unknown"
    s = source.lower().strip()
    # 匹配已知平台名
    for plat in ["github", "bilibili", "zhihu", "weibo", "ithome", "hackernews",
                 "toutiao", "douyin", "kuaishou", "baidu", "sogou_wechat",
                 "sina_tech", "tmtpost", "tieba", "juejin", "segmentfault",
                 "cnblogs", "solidot", "oschina", "36kr", "huxiu", "sspai",
                 "infoq", "reddit", "twitter", "youtube"]:
        if plat in s:
            return plat
    # fallback: take first part before _
    if "_" in s:
        return s.split("_")[0]
    return s[:20]


def matches_whitelist(item: dict) -> bool:
    """检查内容是否匹配宽泛白名单关键词"""
    text = (
        (item.get("title", "") or "") + " " +
        (item.get("content", "") or "") + " " +
        (item.get("tags", "") or "") + " " +
        (item.get("category", "") or "")
    ).lower()
    for kw in WHITELIST_SET:
        if kw in text:
            return True
    # 也检查 source 和 platform
    source = (item.get("source", "") or "").lower()
    platform = (item.get("platform", "") or "").lower()
    for kw in WHITELIST_SET:
        if kw in source or kw in platform:
            return True
    return False


def is_noise(item: dict) -> bool:
    """判断是否为噪声内容"""
    title = item.get("title", "") or ""
    content = (item.get("content", "") or "") + title
    for pattern in NOISE_PATTERNS:
        if pattern in content:
            return True
    if len(title) < 6:
        return True
    # 热度数值标题过滤
    if HEAT_NUM_PATTERN.match(title) or HEAT_NUM_PATTERN2.match(title):
        return True
    # UI导航标签过滤
    if title.strip() in UI_LABELS:
        return True
    # 空内容过滤 — 只有标题没有实际内容
    content_body = (item.get("content", "") or "").strip()
    if not content_body and len(title) < 20:
        return True
    return False


def title_similarity(t1: str, t2: str) -> float:
    """计算标题相似度 (0-1)"""
    if not t1 or not t2:
        return 0
    s1 = set(t1.lower())
    s2 = set(t2.lower())
    if not s1 or not s2:
        return 0
    return len(s1 & s2) / len(s1 | s2)


def clean_batch(batch_size: int = 200, max_batches: int = 100, order_by_hot: bool = False) -> dict:
    """批量清洗原始情报(热点保底 + 宽泛白名单版)"""
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")

    stats = {
        "total_processed": 0,
        "new_cleaned": 0,
        "hot_guarantee_cleaned": 0,
        "whitelist_cleaned": 0,
        "whitelist_filtered": 0,  # 8条之后不符合白名单被过滤
        "duplicates": 0,
        "noise_filtered": 0,
        "error": 0,
        "batches_run": 0,
        "remaining": 0,
        "whitelist_size": WHITELIST_SIZE,
    }

    # 热点保底计数器: platform_prefix -> count
    hot_guarantee_counters: Dict[str, int] = {}

    order_clause = "ORDER BY r.id ASC" if not order_by_hot else "ORDER BY r.hot_score DESC, r.collected_at DESC"

    for batch_num in range(1, max_batches + 1):
        query = f"""
            SELECT r.id, r.title, r.content, r.url, r.source, r.platform,
                   r.author, r.author_id, r.category, r.tags, r.category_tags,
                   r.hot_score, r.view_count, r.like_count,
                   r.collect_count, r.comment_count, r.share_count,
                   r.published_at, r.collected_at, r.raw_data
            FROM raw_intelligence r
            WHERE r.id NOT IN (
                SELECT COALESCE(c.raw_id, 0) FROM cleaned_intelligence c WHERE c.raw_id IS NOT NULL
            )
            {order_clause}
            LIMIT ?
        """
        cur = conn.execute(query, (batch_size,))
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()

        if not rows:
            log.info(f"批次{batch_num}: 无待清洗数据,全部处理完毕")
            break

        log.info(f"批次{batch_num}: 开始清洗 {len(rows)} 条记录 (当前热点保底计数: {dict(hot_guarantee_counters)})")

        seen_titles = {}
        batch_new = 0
        batch_dup = 0
        batch_noise = 0
        batch_hot_g = 0
        batch_wl = 0
        batch_wl_filter = 0
        batch_err = 0

        for row in rows:
            try:
                item = dict(zip(cols, row))
                item_id = item["id"]

                # ── 去重检查(先数据库级别,再过内存级别)──
                title_str = (item.get("title", "") or "").strip()
                if not title_str or len(title_str) < 6:
                    batch_noise += 1
                    continue
                # 数据库级别去重
                existing = conn.execute(
                    "SELECT COUNT(*) FROM cleaned_intelligence WHERE title = ?",
                    (title_str[:500],)
                ).fetchone()[0]
                if existing > 0:
                    batch_dup += 1
                    continue
                # 内存级别去重(同批次内相似标题)
                title_key = re.sub(r'[^\w]', '', title_str[:30].lower())
                dup_found = False
                for seen_key, seen_id in seen_titles.items():
                    if title_similarity(title_key, seen_key) > 0.8:
                        dup_found = True
                        break
                if dup_found:
                    batch_dup += 1
                    continue
                seen_titles[title_key] = item_id

                # ── 噪声过滤 ──
                if is_noise(item):
                    batch_noise += 1
                    continue

                # ── 热点保底 + 白名单判断 ──
                normalized_source = normalize_source(item.get("source", "") or "")
                item["source"] = normalized_source
                platform_prefix = extract_platform_prefix(normalized_source)
                position = hot_guarantee_counters.get(platform_prefix, 0) + 1
                is_hot_guaranteed = False

                passed = False
                # 【优化】热点保底从8提高到20,减少白名单过滤率
                if position <= 20:
                    # 热点保底:前20条直接放行
                    hot_guarantee_counters[platform_prefix] = position
                    passed = True
                    is_hot_guaranteed = True
                else:
                    # 20条之后:仅保留匹配白名单的
                    if matches_whitelist(item):
                        passed = True
                        is_hot_guaranteed = False
                    else:
                        # 不匹配白名单 → 过滤
                        batch_wl_filter += 1
                        stats["whitelist_filtered"] += 1
                        continue

                if not passed:
                    continue

                # ── 成功进入清洗 ──
                now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                # 简单评分
                hot = item.get("hot_score", 0) or 0
                pweight = PLATFORM_WEIGHTS.get(platform_prefix, PLATFORM_WEIGHTS["default"])
                importance = round(hot * pweight / 100, 2)

                conn.execute("""
                    INSERT INTO cleaned_intelligence
                    (raw_id, title, content, url, source, platform, author, author_id,
                     category, tags, importance_score, value_level, value_reasons,
                     is_ai_related, language, chinese_ratio, is_processed,
                     published_at, collected_at, cleaned_at, agent,
                     personal_match_score, source_type)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    item_id,
                    (item.get("title", "") or "")[:500],
                    (item.get("content", "") or "")[:2000],
                    item.get("url", "") or "",
                    item.get("source", "") or "",
                    item.get("platform", "") or "",
                    item.get("author", "") or "",
                    item.get("author_id", "") or "",
                    item.get("category", "") or "",
                    merge_tags(item.get("tags", "") or "", item.get("category_tags", "") or ""),
                    importance,
                    1 if importance > 0 else 0,
                    f"热点保底-{platform_prefix}-第{position}条" if position <= 20 else "白名单匹配",
                    0, "zh", 1.0, 1,
                    item.get("published_at", "") or "",
                    item.get("collected_at", "") or "",
                    now,
                    "unified_cleaning_pipeline_v2",
                    0,
                    platform_prefix,
                ))
                batch_new += 1
                if is_hot_guaranteed:
                    batch_hot_g += 1
                else:
                    batch_wl += 1

            except Exception as e:
                log.error(f"清洗失败 id={item.get('id', '?')}: {e}")
                batch_err += 1

        conn.commit()

        stats["total_processed"] += len(rows)
        stats["new_cleaned"] += batch_new
        stats["hot_guarantee_cleaned"] += batch_hot_g
        stats["whitelist_cleaned"] += batch_wl
        stats["noise_filtered"] += batch_noise
        stats["duplicates"] += batch_dup
        stats["whitelist_filtered"] += batch_wl_filter
        stats["error"] += batch_err
        stats["batches_run"] = batch_num

        log.info(
            f"批次{batch_num}完成: +{batch_new} cleaned "
            f"(热点保底={batch_hot_g}, 白名单={batch_wl}), "
            f"白名单过滤={batch_wl_filter}, "
            f"{batch_dup} dup, {batch_noise} noise, {batch_err} err"
        )

        # 如果连续批次几乎全是过滤/重复,提前退出
        if batch_new == 0 and batch_num >= 3:
            log.warning("连续批次无新数据,提前结束")
            break

    # 统计剩余
    cur = conn.execute("""
        SELECT COUNT(*) FROM raw_intelligence r
        WHERE r.id NOT IN (
            SELECT COALESCE(c.raw_id, 0) FROM cleaned_intelligence c WHERE c.raw_id IS NOT NULL
        )
    """)
    stats["remaining"] = cur.fetchone()[0]

    # 清洗后自动清理本轮产生的低分数据
    low_cut = conn.execute("""
        SELECT COUNT(*) FROM cleaned_intelligence 
        WHERE ai_score_total < 20
    """).fetchone()[0]
    if low_cut > 0:
        low_items = conn.execute("""
            SELECT id, title, content, url, source, platform, 
                   ai_score_total, ai_score_reasoning
            FROM cleaned_intelligence 
            WHERE ai_score_total < 20
        """).fetchall()
        for li in low_items:
            compressed = json.dumps({
                "title": li[1], "content": (li[2] or "")[:500],
                "source": li[3], "platform": li[4], "url": li[5],
            }, ensure_ascii=False)
            conn.execute("""
                INSERT OR IGNORE INTO archive_cleaned 
                (id, title, platform, source, archived_at, compressed_data,
                 ai_score_total, ai_score_reasoning, ai_scored_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (li[0], (li[1] or "")[:500], li[4] or "", li[3] or "",
                  datetime.now().strftime("%Y-%m-%dT%H:%M:%S"), compressed[:2000], li[6], 
                  (li[7] or "")[:1000], datetime.now().strftime("%Y-%m-%dT%H:%M:%S")))
            conn.execute("DELETE FROM cleaned_intelligence WHERE id = ?", (li[0],))
        conn.commit()
        stats["auto_lowscore_archived"] = len(low_items)
        log.info(f"低分数据自动清理: 归档{len(low_items)}条")
    else:
        stats["auto_lowscore_archived"] = 0

    conn.close()

    log.info(f"清洗完成: {json.dumps(stats, ensure_ascii=False)}")
    return stats


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Hermes 情报清洗管道 v2 (热点保底 + 白名单)")
    parser.add_argument("--batch", type=int, default=2000, help="每批大小")
    parser.add_argument("--max-batches", type=int, default=100, help="最大批次数")
    parser.add_argument("--order-by-hot", action="store_true", help="按热度排序")
    args = parser.parse_args()

    result = clean_batch(
        batch_size=args.batch,
        max_batches=args.max_batches,
        order_by_hot=args.order_by_hot,
    )
    print(f"\n{'='*60}")
    print(f"清洗结果: {json.dumps(result, ensure_ascii=False, indent=2)}")
    print(f"{'='*60}")

    with open(LOG_PATH, "r", encoding="utf-8") as f:
        log_lines = f.readlines()
    log_text = "\n".join(log_lines[-5:]) if log_lines else ""
    # 检测清洗完成字样
    if "清洗完成" in log_text:
        print("✅ 检测到'清洗完成'字样 — 管道执行成功")
    else:
        print("❌ 未检测到'清洗完成'字样")
