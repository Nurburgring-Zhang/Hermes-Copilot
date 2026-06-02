#!/usr/bin/env python3
"""
🔄 垃圾过滤词扩展 v2.0
基于今日真实推送数据的模式分析，生成扩展过滤词库
"""
import sqlite3
from pathlib import Path

DB = Path("/home/administrator/.hermes") / "intelligence.db"
db = sqlite3.connect(str(DB))

# ===== 先清空旧数据 =====
db.execute("DELETE FROM spam_filter_keywords")
db.execute("DELETE FROM spam_filter_sources")
db.execute("DELETE FROM spam_filter_log")

# ===== 扩展过滤词分类 =====
keywords = [
    # =====================================================================
    # 1. 🔴 严重度5 — 直接拦截（命中即阻止，不进推送候选）
    # =====================================================================
    # --- 低质动画/动漫/游戏 ---
    ("奶龙", "low_quality", 5, "低质动画角色"),
    ("一拳超人", "low_quality", 5, "二次元动漫"),
    ("铠甲勇士", "low_quality", 5, "特摄片"),
    ("奥特曼", "low_quality", 5, "特摄/低质"),
    ("奥特系列", "low_quality", 5, "特摄/低质"),
    ("传说之下", "low_quality", 5, "游戏角色"),
    ("鬼灭之刃", "low_quality", 5, "动漫"),

    # --- 震惊体/标题党 ---
    ("细思极恐", "clickbait", 5, "震惊体标题党"),
    ("出大事了", "clickbait", 5, "震惊体"),
    ("紧急通知", "clickbait", 5, "震惊体"),
    ("彻底炸锅", "clickbait", 5, "震惊体"),
    ("万万没想到", "clickbait", 5, "震惊体"),
    ("删前速看", "clickbait", 5, "恐吓体"),
    ("不转不是", "clickbait", 5, "道德绑架"),
    ("速看", "clickbait", 5, "恐吓体"),
    ("删前", "clickbait", 5, "恐吓体"),
    ("看后删", "clickbait", 5, "恐吓体"),

    # --- 暴富/理财/诈骗 ---
    ("年入百万", "spam", 5, "暴富骗局"),
    ("月入5万", "spam", 5, "暴富骗局"),
    ("月入十万", "spam", 5, "暴富骗局"),
    ("闷声发大财", "spam", 5, "暴富骗局"),
    ("暴富神话", "spam", 5, "暴富骗局"),
    ("躺赚", "spam", 5, "骗局"),
    ("副业赚钱", "spam", 5, "钓鱼"),
    ("零成本副业", "spam", 5, "骗局"),
    ("日赚", "spam", 5, "暴富骗局"),
    ("财富自由", "spam", 5, "暴富骗局"),
    ("在家就能做", "spam", 5, "副业诈骗"),
    ("带你先赚", "spam", 5, "钓鱼"),
    ("进群免费领", "spam", 5, "诈骗"),
    ("扫码进群", "spam", 5, "诈骗"),

    # --- 低质社会/狗血 ---
    ("缝裤裆", "low_quality", 5, "低质社会新闻"),
    ("夫妻吵架", "low_quality", 5, "低质家庭狗血"),
    ("女子打赏", "low_quality", 5, "低质社会"),
    ("打赏主播", "low_quality", 5, "低质社会"),

    # --- 低质游戏广告 ---
    ("企鹅大战", "low_quality", 5, "低质游戏"),
    ("凑企鹅", "low_quality", 5, "低质游戏"),
    ("王者荣耀", "low_quality", 5, "游戏"),
    ("荣耀手游", "low_quality", 5, "游戏广告"),
    ("和平精英", "low_quality", 5, "游戏"),
    ("蛋仔派对", "low_quality", 5, "低质游戏"),

    # --- 体育低质(非格林兴趣) ---
    ("赢的真硬气", "low_quality", 5, "低质体育"),
    ("补时集体抗议", "low_quality", 5, "低质体育"),
    ("丁俊晖", "low_quality", 5, "斯诺克/非格林兴趣"),

    # =====================================================================
    # 2. 🟠 严重度4 — 强降分（匹配后-40分）
    # =====================================================================
    # --- 标题党/诱导 ---
    ("震惊", "clickbait", 4, "震惊体"),
    ("惊人", "clickbait", 4, "震惊体"),
    ("难以置信", "clickbait", 4, "标题党"),
    ("深度||", "clickbait", 4, "伪深度标题"),
    ("深度：", "clickbait", 4, "伪深度标题"),
    ("内幕", "clickbait", 4, "标题党"),
    ("真相", "clickbait", 4, "标题党"),
    ("秘密", "clickbait", 4, "诱导"),
    ("竟然", "clickbait", 4, "惊讶诱导"),
    ("让人意外", "clickbait", 4, "标题党"),
    ("出人意料", "clickbait", 4, "标题党"),
    ("万万没想到", "clickbait", 4, "震惊体"),
    ("傻眼了", "clickbait", 4, "震惊体"),
    ("哭了", "clickbait", 4, "情绪标题"),
    ("看哭了", "clickbait", 4, "情绪标题"),
    ("泪目", "clickbait", 4, "情绪标题"),
    ("泪崩", "clickbait", 4, "情绪标题"),
    ("唏嘘", "clickbait", 4, "情绪标题"),
    ("破防", "clickbait", 4, "情绪标题"),
    ("坐不住了", "clickbait", 4, "情绪标题"),
    ("坐不住", "clickbait", 4, "情绪标题"),
    ("彻底坐不住", "clickbait", 4, "情绪标题"),
    ("心酸", "clickbait", 4, "情绪标题"),
    ("心疼", "clickbait", 4, "情绪标题"),
    ("看呆", "clickbait", 4, "震惊体"),
    ("无数人", "clickbait", 4, "诱导"),
    ("都在看", "clickbait", 4, "诱导点击"),
    ("不看亏了", "clickbait", 4, "诱导"),
    ("建议收藏", "clickbait", 4, "诱导"),
    ("值得收藏", "clickbait", 4, "诱导"),
    ("注意了", "clickbait", 4, "诱导"),
    ("千万别", "clickbait", 4, "诱导"),
    ("一定要看", "clickbait", 4, "诱导"),

    # --- 财经钓鱼 ---
    ("手中有5万", "spam", 4, "理财钓鱼"),
    ("手中有", "spam", 4, "理财钓鱼"),
    ("只要这样做", "spam", 4, "理财钓鱼"),
    ("两条线", "spam", 4, "理财钓鱼标题"),
    ("试试这", "spam", 4, "理财钓鱼"),
    ("还在傻傻存钱", "spam", 4, "理财钓鱼"),
    ("别再傻", "spam", 4, "钓鱼"),

    # --- 低质历史/伪深度 ---
    ("深度好文", "low_quality", 4, "伪深度"),
    ("深度揭秘", "clickbait", 4, "标题党"),
    ("不为人知", "clickbait", 4, "标题党"),
    ("隐藏", "clickbait", 4, "标题党"),
    ("严禁外传", "clickbait", 4, "恐吓体"),

    # --- 低质体育 ---
    ("NBA", "low_quality", 4, "非格林偏好"),
    ("英超", "low_quality", 4, "非格林偏好"),
    ("欧冠", "low_quality", 4, "非格林偏好"),
    ("足球", "low_quality", 4, "非格林偏好"),
    ("男篮", "low_quality", 4, "非格林偏好"),
    ("抢七", "low_quality", 4, "非格林偏好"),
    ("绝杀", "low_quality", 4, "非格林偏好"),

    # =====================================================================
    # 3. 🟡 严重度3 — 中降分（匹配后-20分）
    # =====================================================================
    # --- 头条类标题党（降低阈值） ---
    ("突发：", "clickbait", 3, "伪突发标题"),
    ("突发!", "clickbait", 3, "伪突发标题"),
    ("亮了", "clickbait", 3, "低质标题"),
    ("信息量很大", "clickbait", 3, "标题党"),
    ("一句话", "clickbait", 3, "过于简化"),
    ("疯了", "clickbait", 3, "情绪标题"),
    ("彻底疯了", "clickbait", 3, "情绪标题"),
    ("反转", "clickbait", 3, "标题党"),
    ("大反转", "clickbait", 3, "标题党"),
    ("谁也没想到", "clickbait", 3, "标题党"),
    ("没想到", "clickbait", 3, "标题党"),
    ("终于来了", "clickbait", 3, "诱导"),
    ("就在刚刚", "clickbait", 3, "伪紧急"),
    ("刚刚，", "clickbait", 3, "伪紧急"),
    ("刚刚!", "clickbait", 3, "伪紧急"),
    ("原来", "clickbait", 3, "过度好奇诱导"),
    ("这就", "clickbait", 3, "诱导"),

    # --- B站视频分类过滤 ---
    ("vlog", "low_quality", 3, "日常vlog"),
    ("日常vlog", "low_quality", 3, "日常vlog"),
    ("逛吃", "low_quality", 3, "吃播/探店"),
    ("吃播", "low_quality", 3, "吃播"),
    ("探店", "low_quality", 3, "探店"),
    ("打卡", "low_quality", 3, "打卡"),
    ("航拍", "low_quality", 3, "航拍无深度"),
    ("延时摄影", "low_quality", 3, "延时摄影/无内容"),
    ("ASMR", "low_quality", 3, "ASMR"),
    ("翻唱", "low_quality", 3, "翻唱"),
    ("舞蹈", "low_quality", 3, "舞蹈"),
    ("Cos", "low_quality", 3, "cosplay"),
    ("coser", "low_quality", 3, "cosplay"),
    ("cos服", "low_quality", 3, "cosplay"),
    ("meme", "low_quality", 3, "迷因"),
    ("表情包", "low_quality", 3, "表情包"),
    ("鬼畜", "low_quality", 3, "鬼畜"),
    ("搞笑", "low_quality", 3, "纯搞笑"),
    ("太好笑", "low_quality", 3, "搞笑"),

    # --- B站游戏 ---
    ("原神", "low_quality", 3, "游戏-原神"),
    ("鸣潮", "low_quality", 3, "游戏-鸣潮"),
    ("绝区零", "low_quality", 3, "游戏-绝区零"),
    ("三角洲", "low_quality", 3, "游戏-三角洲"),
    ("三角洲行动", "low_quality", 3, "游戏"),
    ("异环", "low_quality", 3, "游戏"),
    ("游戏实况", "low_quality", 3, "游戏实况"),
    ("游戏攻略", "low_quality", 3, "游戏攻略"),
    ("抽卡", "low_quality", 3, "抽卡"),
    ("抽到", "low_quality", 3, "抽卡"),
    ("角色展示", "low_quality", 3, "游戏角色展示"),
    ("角色演示", "low_quality", 3, "游戏角色"),
    ("PV", "low_quality", 3, "游戏预告"),
    ("技能解读", "low_quality", 3, "游戏攻略"),
    ("实战循环", "low_quality", 3, "游戏攻略"),
    ("觉醒提升", "low_quality", 3, "游戏攻略"),
    ("版本PV", "low_quality", 3, "游戏版本预告"),
    ("ssr", "low_quality", 3, "抽卡"),
    ("手办", "low_quality", 3, "手办"),
    ("周边", "low_quality", 3, "周边"),

    # --- B站日常/生活 ---
    ("试吃", "low_quality", 3, "吃播"),
    ("做菜", "low_quality", 3, "做菜"),
    ("下厨", "low_quality", 3, "下厨"),
    ("这样做", "low_quality", 3, "食谱"),
    ("巨巨巨好吃", "low_quality", 3, "吃播"),
    ("太好吃了", "low_quality", 3, "吃播"),
    ("一人食", "low_quality", 3, "吃播"),
    ("早餐", "low_quality", 3, "无价值"),
    ("晚餐", "low_quality", 3, "无价值"),
    ("午饭", "low_quality", 3, "无价值"),
    ("下午茶", "low_quality", 3, "无价值"),
    ("回家", "low_quality", 3, "无价值"),
    ("结婚", "low_quality", 3, "无价值"),
    ("婚礼", "low_quality", 3, "无价值"),
    ("生日", "low_quality", 3, "无价值"),
    ("过生日", "low_quality", 3, "无价值"),
    ("婆婆", "low_quality", 3, "家庭琐事"),
    ("公公", "low_quality", 3, "家庭琐事"),
    ("丈母娘", "low_quality", 3, "家庭琐事"),
    ("老公", "low_quality", 3, "家庭琐事"),
    ("老丈人", "low_quality", 3, "家庭琐事"),
    ("弟媳", "low_quality", 3, "家庭琐事"),
    ("嫂子", "low_quality", 3, "家庭琐事"),

    # --- B站纯娱乐/无价值 ---
    ("唱歌", "low_quality", 3, "唱歌"),
    ("跳舞", "low_quality", 3, "跳舞"),
    ("扭胯", "low_quality", 3, "低质舞蹈"),
    ("穿", "low_quality", 3, "无价值"),
    ("试穿", "low_quality", 3, "无价值"),
    ("穿搭", "low_quality", 3, "穿搭"),
    ("换装", "low_quality", 3, "换装/无价值"),
    ("化妆", "low_quality", 3, "化妆"),
    ("美妆", "low_quality", 3, "美妆"),
    ("口红", "low_quality", 3, "美妆"),
    ("护肤", "low_quality", 3, "护肤"),
    ("发型", "low_quality", 3, "发型"),
    ("显瘦", "low_quality", 3, "穿搭"),
    ("穿搭分享", "low_quality", 3, "穿搭"),

    # --- 低质体育/娱乐体育 ---
    ("王楚钦", "low_quality", 3, "乒乓球非格林兴趣"),
    ("孙颖莎", "low_quality", 3, "乒乓球非格林兴趣"),
    ("樊振东", "low_quality", 3, "乒乓球非格林兴趣"),
    ("马龙", "low_quality", 3, "乒乓球非格林兴趣"),
    ("国乒", "low_quality", 3, "乒乓球非格林兴趣"),
    ("世乒赛", "low_quality", 3, "乒乓球"),
    ("乒协", "low_quality", 3, "乒乓球"),
    ("全红婵", "low_quality", 3, "跳水娱乐八卦"),
    ("跳水", "low_quality", 3, "跳水非格林兴趣"),
    ("运动员", "low_quality", 3, "泛体育非兴趣"),
    ("退役", "low_quality", 3, "泛体育八卦"),

    # --- 低质社会/猎奇 ---
    ("监控", "low_quality", 3, "监控记录"),
    ("监控拍", "low_quality", 3, "监控低质"),
    ("摄像头", "low_quality", 3, "低质社会"),
    ("偷拍", "low_quality", 3, "低质"),
    ("悲剧", "low_quality", 3, "社会悲剧"),
    ("惨坠", "low_quality", 3, "悲剧"),
    ("惨", "low_quality", 3, "悲剧"),
    ("命陨", "low_quality", 3, "悲剧"),
    ("坠桥", "low_quality", 3, "事故"),

    # --- 低质俄乌/地缘标题党 ---
    ("顾不上", "clickbait", 3, "标题党"),
    ("奉陪到底", "clickbait", 3, "标题党"),
    ("准备拼了", "clickbait", 3, "标题党"),
    ("打2通电话", "clickbait", 3, "简化新闻"),

    # --- 低质社会争议 ---
    ("彩礼", "low_quality", 3, "社会争议"),
    ("相亲", "low_quality", 3, "社会话题"),
    ("离婚", "low_quality", 3, "家庭"),
    ("分手", "low_quality", 3, "家庭"),
    ("渣男", "low_quality", 3, "低质"),
    ("吐槽", "low_quality", 3, "低质"),
    ("被骂", "low_quality", 3, "低质"),
    ("上热搜", "low_quality", 3, "低质"),
    ("热搜", "low_quality", 3, "低质"),
    ("走红", "low_quality", 3, "低质"),
    ("爆红", "low_quality", 3, "低质"),
    ("火了", "low_quality", 3, "低质"),

    # --- 低质宠物 ---
    ("猫", "low_quality", 3, "宠物"),
    ("狗", "low_quality", 3, "宠物"),
    ("狗狗", "low_quality", 3, "宠物"),
    ("猫咪", "low_quality", 3, "宠物"),
    ("萌宠", "low_quality", 3, "宠物"),

    # --- 养生/伪科学 ---
    ("养生", "low_quality", 3, "养生"),
    ("中医", "low_quality", 3, "伪科学"),
    ("偏方", "low_quality", 3, "伪科学"),
    ("致癌", "low_quality", 3, "恐吓"),
    ("排毒", "low_quality", 3, "伪科学"),
    ("美白", "low_quality", 3, "美妆"),
    ("减肥", "low_quality", 3, "美妆/伪科学"),
    ("减脂", "low_quality", 3, "美妆"),

    # --- 低质教育 ---
    ("小学数学", "low_quality", 3, "基础教育"),
    ("初中数学", "low_quality", 3, "基础教育"),
    ("中考", "low_quality", 3, "教育"),
    ("高考", "low_quality", 3, "教育"),
    ("阅读理解", "low_quality", 3, "语文"),
    ("作文素材", "low_quality", 3, "教育"),
    ("解三角形", "low_quality", 3, "数学题"),

    # =====================================================================
    # 4. ⚪ 严重度2 — 轻降分（匹配后-10分）
    # =====================================================================
    ("彻底", "clickbait", 2, "过度修饰"),
    ("非常", "clickbait", 2, "过度修饰"),
    ("极度", "clickbait", 2, "过度修饰"),
    ("太", "clickbait", 2, "过度情绪但泛用"),
    ("这一幕", "low_quality", 2, "碎片化"),
    ("瞬间", "low_quality", 2, "碎片化"),
    ("画面", "low_quality", 2, "碎片化"),
    ("太真实", "low_quality", 2, "低质"),
    ("万万", "clickbait", 2, "过度修饰"),
    ("你敢信", "clickbait", 2, "诱导"),
    ("看傻", "clickbait", 2, "震惊"),
    ("看懵", "clickbait", 2, "震惊"),

    # =====================================================================
    # 5. 🔴 高危诈骗/恶意 — 严重度5直接拦截
    # =====================================================================
    ("中奖", "spam", 5, "诈骗"),
    ("免费领取", "spam", 5, "诈骗"),
    ("点击链接", "spam", 5, "诈骗"),
    ("验证码", "spam", 5, "诈骗"),
    ("银行卡", "spam", 5, "诈骗"),
    ("转账", "spam", 5, "诈骗"),
    ("刷单", "spam", 5, "诈骗"),
    ("佣金", "spam", 5, "诈骗"),
    ("高回报", "spam", 5, "诈骗"),
    ("稳赚", "spam", 5, "诈骗"),
    ("包赚", "spam", 5, "诈骗"),
    ("无风险", "spam", 5, "诈骗"),
    ("百分百赚钱", "spam", 5, "诈骗"),
    ("日结", "spam", 5, "诈骗/兼职"),
]

# ===== 插入关键词 =====
inserted = 0
for kw, cat, sev, note in keywords:
    try:
        db.execute("INSERT INTO spam_filter_keywords (keyword, category, severity, note) VALUES (?, ?, ?, ?)",
                   (kw, cat, sev, note))
        inserted += 1
    except Exception as e:
        print(f" 跳过 {kw}: {e}")

# ===== 来源过滤（扩展版）=====
sources = [
    ("toutiao_finance", "头条", 20, 0, "头条财经，暴富骗局/理财钓鱼重灾区，封顶20分"),
    ("toutiao_sports", "头条", 20, 0, "头条体育，情绪化/低质内容充斥，封顶20分"),
    ("toutiao_entertainment", "头条", 15, 0, "头条娱乐，纯娱乐无信息价值，封顶15分"),
    ("toutiao_world", "头条", 25, 0, "头条国际，标题党/简化地缘重灾区，封顶25分"),
    ("toutiao_military", "头条", 25, 0, "头条军事，标题党泛滥，封顶25分"),
    ("bilibili", "B站", 25, 0, "B站，低质娱乐/游戏/日常大量，封顶25分"),
    ("B站-科技", "B站", 30, 0, "B站科技频道，但混入大量非科技内容，封顶30分"),
    ("B站-知识", "B站", 35, 0, "B站知识频道，质量略高但仍有标题党，封顶35分"),
    ("tieba", "贴吧", 15, 0, "贴吧，质量极低无信息价值，封顶15分"),
    ("zhihu_daily", "知乎", 35, 0, "知乎日报，部分高质量但混杂，封顶35分"),
    ("weibo", "微博", 20, 0, "微博短内容，碎片化无深度，封顶20分"),
    ("baidu", "百度", 30, 0, "百度新闻聚合，质量参差，封顶30分"),
    ("sina_tech", "新浪", 35, 0, "新浪科技，部分有价值但头条化趋势，封顶35分"),
]

for src, plat, cap, blocked, note in sources:
    db.execute("INSERT OR IGNORE INTO spam_filter_sources (source_pattern, platform, base_score_cap, is_blocked, note) VALUES (?, ?, ?, ?, ?)",
               (src, plat, cap, blocked, note))

db.commit()

# ===== 统计 =====
total_keywords = db.execute("SELECT COUNT(*) FROM spam_filter_keywords").fetchone()[0]
sev_counts = db.execute("SELECT severity, COUNT(*) FROM spam_filter_keywords GROUP BY severity ORDER BY severity DESC").fetchall()
cat_counts = db.execute("SELECT category, COUNT(*) FROM spam_filter_keywords GROUP BY category ORDER BY COUNT(*) DESC").fetchall()
total_sources = db.execute("SELECT COUNT(*) FROM spam_filter_sources").fetchone()[0]

print("=" * 70)
print(f"📋 垃圾过滤词库扩展完成")
print("=" * 70)
print(f"总关键词数: {total_keywords}")
print(f"\n严重度分布:")
sev_map = {5: "🔴 直接拦截", 4: "🟠 强降分", 3: "🟡 中降分", 2: "⚪ 轻降分"}
for sev, cnt in sev_counts:
    print(f"  {sev_map.get(sev, f'sev{sev}')}: {cnt}条")
print(f"\n分类分布:")
cat_map = {"low_quality": "低质内容", "clickbait": "标题党", "spam": "垃圾/诈骗"}
for cat, cnt in cat_counts:
    print(f"  {cat_map.get(cat, cat)}: {cnt}条")
print(f"\n来源规则: {total_sources}条")

# ===== 按严重度展示 =====
print(f"\n{'='*70}")
print(f"📋 完整过滤词表")
print(f"{'='*70}\n")

for sev_level, sev_name in [(5, "🔴 严重度5 — 直接拦截（命中即屏蔽不进推送）"),
                              (4, "🟠 严重度4 — 强降分（匹配后-40分或更多）"),
                              (3, "🟡 严重度3 — 中降分（匹配后-20分）"),
                              (2, "⚪ 严重度2 — 轻降分（匹配后-10分）")]:
    items = db.execute("""
        SELECT keyword, category, note FROM spam_filter_keywords 
        WHERE severity = ? ORDER BY category, keyword
    """, (sev_level,)).fetchall()
    
    print(f"  {sev_name}")
    print(f"  {'-'*60}")
    current_cat = ""
    for kw, cat, note in items:
        if cat != current_cat:
            cat_name = {"low_quality": "📺 低质内容", "clickbait": "📰 标题党", "spam": "⚠️ 垃圾/诈骗"}.get(cat, cat)
            print(f"\n    [{cat_name}]")
            current_cat = cat
        print(f"    · {kw:24s} — {note}")
    print()

# ===== 来源规则展示 =====
print(f"{'='*70}")
print(f"📋 来源封顶规则")
print(f"{'='*70}")
sources_rows = db.execute("""
    SELECT source_pattern, platform, base_score_cap, is_blocked, note 
    FROM spam_filter_sources ORDER BY base_score_cap
""").fetchall()
for r in sources_rows:
    flag = "🔴" if r[3] else "🟡"
    cap_type = "🔒 完全封锁" if r[3] else f"封顶{r[2]}分"
    print(f"  {flag} {r[0]:25s} | {r[1]:6s} | {cap_type:12s} | {r[4]}")

print(f"\n{'='*70}")
print(f"总计: {total_keywords}条关键词 + {total_sources}条来源规则")
print(f"{'='*70}")

db.close()
