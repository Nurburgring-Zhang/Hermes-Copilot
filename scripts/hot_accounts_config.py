#!/usr/bin/env python3
"""
热门账号配置库 (Hot Accounts Config)
======================================
格林主人关注的各行业知名账号清单。
用于增强采集器定向采集这些账号的最新内容。

使用方法:
    from hot_accounts_config import HOT_ACCOUNTS, ALL_KEYWORDS
    accounts = HOT_ACCOUNTS["AI"]  # 获取AI行业所有账号
"""

# 各行业/方向的热门账号配置
HOT_ACCOUNTS = {
    # ===== AI/大模型 =====
    "AI": {
        "wechat": [
            "机器之心", "量子位", "新智元", "AI科技评论", "36氪AI", "虎嗅AI",
            "DeepTech深科技", "硅星人", "极客公园", "爱范儿",
            "智东西", "维科网人工智能", "人工智能那点事", "AI前线",
        ],
        "weibo": [
            "量子位", "机器之心", "新智元", "36氪", "虎嗅网",
            "新浪科技", "爱范儿", "钛媒体", "极客公园",
        ],
        "bilibili": [
            "机器之心", "量子位", "YJango", "李沐", "跟李沐学AI",
            "同济子豪兄", "3Blue1Brown", "StatQuest",
        ],
        "zhihu": [
            "量子位", "机器之心", "YJango", "李沐", "谢邀",
            "微软亚洲研究院", "亚马逊AI",
        ],
        "xiaohongshu": [
            "AI绘画", "AI教程", "ChatGPT技巧", "数字人",
        ],
        "toutiao": [
            "量子位", "机器之心", "36氪", "钛媒体", "DeepTech",
        ],
        "youtube": [
            "TwoMinutePapers", "YannicKilcher", "Andrej Karpathy",
            "sentdex", "Stanford CS229", "MIT AGI",
            "3Blue1Brown", "Computerphile",
        ],
        "x": [
            "@karpathy", "@ylecun", "@AndrewYNg", "@OpenAI",
            "@AnthropicAI", "@GoogleDeepMind", "@MetaAI",
            "@elonmusk", "@sama", "@miramurati",
        ],
    },

    # ===== IT/数码/消费电子 =====
    "IT数码": {
        "wechat": [
            "差评", "爱否科技", "数字尾巴", "ZEALER", "科技美学",
            "笔吧评测室", "大米评测", "小白测评", "科技每日推送",
            "苹果发布会", "华为发布会", "小米发布会",
        ],
        "weibo": [
            "数码闲聊站", "差评", "爱范儿", "数字尾巴",
            "ZEALER", "科技美学", "小白测评",
            "钟文泽", "李大锤同学", "NavisLi",
        ],
        "bilibili": [
            "钟文泽", "李大锤同学", "TESTV", "爱否科技",
            "小白测评", "笔吧评测室", "极客湾", "影视飓风",
        ],
        "toutiao": [
            "数码闲聊站", "IT之家", "科技美学", "差评",
        ],
        "youtube": [
            "MKBHD", "LinusTechTips", "Dave2D", "iJustine",
            "Unbox Therapy", "JerryRigEverything", "MrMobile",
        ],
    },

    # ===== 新能源汽车/汽车 =====
    "新能源汽车": {
        "wechat": [
            "电动星球", "汽车之家", "懂车帝", "新出行",
            "电动汽车观察家", "NE时代", "建约车评",
        ],
        "weibo": [
            "比亚迪汽车", "蔚来", "小鹏汽车", "理想汽车",
            "特斯拉", "华为智能汽车", "小米汽车",
            "汽车之家", "懂车帝", "新出行",
        ],
        "bilibili": [
            "极速拍档", "汽车之家", "懂车帝", "38号车评中心",
            "李老鼠说车", "高转青年",
        ],
        "youtube": [
            "Tesla Owners Online", "Inside Tesla", "Out of Spec Reviews",
            "Donut Media", "Top Gear", "CarWow",
        ],
        "x": [
            "@Tesla", "@ElonMusk", "@BYDGlobal",
            "@NIOGlobal", "@XPengMotors",
        ],
    },

    # ===== 军事/国际 =====
    "军事": {
        "wechat": [
            "局座召忠", "军武次位面", "环球时报", "观察者网",
            "凤凰军事", "中华网军事",
        ],
        "weibo": [
            "局座召忠", "军武次位面", "环球时报", "观察者网",
            "央视军事", "凤凰军事", "新浪军事",
        ],
        "bilibili": [
            "军武次位面", "观察者网", "央视军事", "凤凰军事",
            "我们的太空", "航天爱好者",
        ],
        "toutiao": [
            "局座召忠", "军武次位面", "环球时报", "观察者网",
            "凤凰军事", "中华网军事",
        ],
        "youtube": [
            "Warographics", "Military History Visualized",
            "Task & Purpose", "Covert Cabal",
        ],
        "x": [
            "@Reuters", "@AP", "@BBCWorld",
            "@CNN", "@WSJ", "@nytimes",
        ],
    },

    # ===== 体育/格斗 =====
    "体育格斗": {
        "weibo": [
            "NBA", "CBA", "英超", "UFC终极格斗",
            "拳击", "拜仁慕尼黑", "皇家马德里",
            "新浪体育", "腾讯体育", "直播吧",
        ],
        "bilibili": [
            "NBA", "足球记忆", "格斗迷",
            "健身领域", "跑步指南",
        ],
        "youtube": [
            "NBA", "UFC", "F1", "World Athletics",
            "Soccer Highlights", "SportsCenter",
        ],
        "x": [
            "@NBA", "@UFC", "@F1", "@WorldAthletics",
            "@SkySportsNews", "@ESPN",
        ],
    },

    # ===== 美女/摄影/艺术 =====
    "美女摄影": {
        "weibo": [
            "国家地理", "摄影之友", "人像摄影",
            "时尚芭莎", "VOGUE中国", "ELLE",
        ],
        "xiaohongshu": [
            "摄影教程", "人像摄影", "写真", "穿搭",
            "模特", "街拍", "时尚", "美妆",
        ],
        "bilibili": [
            "摄影教程", "人像摄影", "视频剪辑教学",
            "影视飓风", "摄影师泰罗",
        ],
        "youtube": [
            "Peter McKinnon", "Manny Ortiz", "Jessica Kobeissi",
            "The Photo Show", "DPReview", "Fstoppers",
            "Chris Hau", "Irene Rudnyk",
        ],
        "civitai": [],  # CivitAI本身是平台,关注其热门模型
    },

    # ===== 游戏/电竞 =====
    "游戏": {
        "weibo": [
            "英雄联盟", "王者荣耀", "原神", "黑神话悟空",
            "Steam", "游民星空", "游侠网",
        ],
        "bilibili": [
            "黑神话悟空", "原神", "英雄联盟", "王者荣耀",
            "Steam", "敖厂长", "芒果冰OL",
        ],
        "youtube": [
            "IGN", "GameSpot", "Digital Foundry",
            "Markiplier", "PewDiePie", "Jacksepticeye",
        ],
        "x": [
            "@IGN", "@GameSpot", "@Steam",
            "@PlayStation", "@Xbox", "@NintendoAmerica",
        ],
    },

    # ===== 科技/科学 =====
    "科技": {
        "wechat": [
            "果壳", "科普中国", "中科院之声", "中国科普博览",
            "环球科学", "科学网", "原理",
        ],
        "bilibili": [
            "果壳", "科普中国", "二次元的中科院物理所",
            "毕导", "芳斯塔芙", "李永乐老师",
        ],
        "youtube": [
            "Veritasium", "Vsauce", "SmarterEveryDay",
            "Kurzgesagt", "SciShow", "Physics Girl",
            "Real Engineering", "Practical Engineering",
        ],
    },

    # ===== 电影/娱乐 =====
    "电影娱乐": {
        "weibo": [
            "电影票房", "猫眼电影", "淘票票",
            "新浪娱乐", "腾讯娱乐", "网易娱乐",
        ],
        "bilibili": [
            "电影最TOP", "木鱼水心", "刘哔电影",
            "电影纪录片", "影视飓风",
        ],
        "youtube": [
            "Corridor Crew", "Film Riot", "Indy Mogul",
            "Every Frame a Painting", "Nerdwriter1",
        ],
    },

    # ===== 开发/开源 =====
    "开发": {
        "weibo": [
            "GitHub", "CSDN", "开源中国", "InfoQ",
            "腾讯云开发者", "阿里云开发者",
        ],
        "zhihu": [
            "知乎程序猿", "美团技术团队", "阿里技术",
            "腾讯技术工程", "字节跳动技术团队",
        ],
        "github": [],  # GitHub Trending自动采集
        "youtube": [
            "Fireship", "ThePrimeagen", "Theo - t3.gg",
            "Web Dev Simplified", "Traversy Media",
            "Ben Eater", "Low Level Learning",
        ],
        "x": [
            "@github", "@npmjs", "@Vercel",
            "@Netlify", "@docker",
        ],
    },

    # ===== 旅游/美食/文化 =====
    "旅游美食": {
        "weibo": [
            "旅游头条", "途牛旅游", "携程旅行",
            "美食探店", "舌尖上的中国",
        ],
        "xiaohongshu": [
            "旅游攻略", "探店", "美食打卡",
            "旅行摄影", "城市漫步",
        ],
        "bilibili": [
            "日食记", "美食作家王刚", "品诺美食",
            "徐大sao", "美食圈",
        ],
        "youtube": [
            "Mark Wiens", "Strictly Dumpling", "Best Ever Food Review Show",
            "Kara and Nate", "Drew Binsky",
        ],
    },
}

# ===== 全平台关键词列表(用于搜狗搜索/搜索引擎采集) =====
ALL_KEYWORDS = [
    # AI/大模型
    "AI", "人工智能", "大模型", "ChatGPT", "OpenAI", "Claude", "Gemini",
    "DeepSeek", "LLM", "AIGC", "AI绘画", "机器学习", "深度学习",
    "Agent", "智能体", "RAG", "大模型应用", "AI开发", "AI工具",
    "AI手机", "AI PC", "AI芯片", "大模型训练", "AI评测",
    # IT/数码
    "华为", "小米", "iPhone", "三星", "OPPO", "vivo", "荣耀",
    "芯片", "骁龙", "天玑", "麒麟", "PC", "笔记本", "平板",
    "数码", "潮玩", "耳机", "智能手表", "VR", "AR",
    # 新能源汽车
    "新能源汽车", "电动汽车", "比亚迪", "特斯拉", "蔚来", "小鹏", "理想",
    "问界", "智界", "极氪", "小米汽车", "自动驾驶", "智能驾驶",
    "电池", "充电", "超充", "固态电池",
    # 汽车/机车
    "汽车", "跑车", "超跑", "机车", "摩托车", "F1", "赛车",
    "越野", "SUV", "奥迪", "宝马", "奔驰", "保时捷",
    # 军事/国际
    "军事", "战争", "航母", "战斗机", "无人机", "导弹",
    "中美", "台海", "南海", "俄罗斯", "乌克兰", "中东",
    "太空", "航天", "火箭", "卫星", "SpaceX",
    # 体育/格斗
    "篮球", "NBA", "CBA", "足球", "英超", "欧冠",
    "格斗", "UFC", "拳击", "MMA", "武术", "马拉松", "F1赛车",
    # 美女/摄影/艺术
    "美女", "写真", "模特", "摄影", "相机", "索尼", "佳能", "尼康",
    "时尚", "穿搭", "街拍", "艺术", "绘画", "设计",
    # 电影/娱乐
    "电影", "票房", "好莱坞", "国产电影", "电视剧", "综艺",
    "音乐", "MV", "演唱会", "游戏", "电竞",
    # 旅游/美食
    "旅游", "旅行", "美食", "探店", "酒店", "民宿",
    "传统文化", "非遗", "博物馆", "艺术展",
    # 开发/开源
    "GitHub", "开源", "编程", "Python", "Rust", "TypeScript",
    "开发者", "程序员", "代码", "API",
    # 社会/热点
    "热点", "热搜", "爆款", "社会新闻", "国际新闻",
]

# ===== 按分类的关键词(用于定向采集) =====
CATEGORY_KEYWORDS = {
    "AI": ["AI", "人工智能", "大模型", "ChatGPT", "OpenAI", "Claude", "Gemini", "DeepSeek", "LLM", "AIGC", "ML", "Deep Learning", "Agent"],
    "数码": ["华为", "小米", "iPhone", "三星", "手机", "芯片", "数码", "智能", "耳机", "笔记本"],
    "新能源汽车": ["新能源汽车", "电动车", "比亚迪", "特斯拉", "蔚来", "小鹏", "理想", "问界", "自动驾驶"],
    "汽车": ["汽车", "跑车", "超跑", "机车", "摩托车", "F1", "赛车", "越野"],
    "军事": ["军事", "战争", "航母", "战斗机", "无人机", "军武"],
    "国际": ["中美", "台海", "南海", "国际形势", "外交", "制裁"],
    "体育": ["篮球", "NBA", "足球", "体育", "UFC", "格斗", "拳击", "马拉松"],
    "摄影": ["摄影", "相机", "镜头", "索尼", "佳能", "尼康", "写真"],
    "美女": ["美女", "模特", "写真", "时尚", "穿搭", "街拍"],
    "游戏": ["游戏", "电竞", "Steam", "PS5", "Xbox", "原神", "黑神话"],
    "电影": ["电影", "票房", "好莱坞", "电影节", "影视"],
    "旅游": ["旅游", "旅行", "美食", "探店", "酒店", "民宿"],
    "科学": ["物理", "化学", "生物", "天文", "量子", "基因", "材料"],
    "开发": ["开源", "GitHub", "编程", "Python", "Rust", "开发", "程序员"],
    "太空": ["太空", "航天", "火箭", "卫星", "SpaceX", "NASA", "空间站"],
}

# ===== 海外平台热门英文关键词 =====
ENGLISH_KEYWORDS = [
    "AI", "OpenAI", "ChatGPT", "Claude", "Gemini", "LLM", "GPT",
    "DeepSeek", "Anthropic", "machine learning", "deep learning",
    "Tesla", "SpaceX", "iPhone", "Apple", "NVIDIA", "chip",
    "war", "military", "China", "Taiwan", "Ukraine",
    "NBA", "UFC", "F1", "photography", "camera",
    "Rust", "Python", "TypeScript", "Go", "Kubernetes",
    "game", "gaming", "movie", "film",
]

if __name__ == "__main__":
    import json
    # 统计
    total_accounts = sum(len(accounts) for cat in HOT_ACCOUNTS.values() for plat, accounts in cat.items())
    print(f"热门账号数: {total_accounts}")
    print(f"行业分类: {len(HOT_ACCOUNTS)}个")
    print(f"全平台关键词: {len(ALL_KEYWORDS)}个")
    print(f"英文关键词: {len(ENGLISH_KEYWORDS)}个")
    print("\n行业列表:")
    for cat in HOT_ACCOUNTS:
        platforms = list(HOT_ACCOUNTS[cat].keys())
        count = sum(len(v) for v in HOT_ACCOUNTS[cat].values())
        print(f"  {cat}: {count}个账号, 平台: {', '.join(platforms)}")
