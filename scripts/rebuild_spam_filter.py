#!/usr/bin/env python3
"""
重建垃圾过滤词 — 按格林主人标准清单
采集时即过滤，不进入 raw_intelligence
"""
import sqlite3
from pathlib import Path

DB = Path("/home/administrator/.hermes") / "intelligence.db"
db = sqlite3.connect(str(DB))

# 清空旧数据
db.execute("DELETE FROM spam_filter_keywords")
db.execute("DELETE FROM spam_filter_sources")
db.execute("DELETE FROM spam_filter_log")

# ==================== 格林清单 ====================

keywords = [
    # ===== 🔴 严重度5 — 直接拦截 =====
    # --- 📰 标题党 ---
    ("万万", "clickbait", 5),
    ("没想到", "clickbait", 5),
    ("不转", "clickbait", 5),
    ("不是", "clickbait", 5),
    ("出大事了", "clickbait", 5),
    ("删前", "clickbait", 5),
    ("速看", "clickbait", 5),
    ("太好哭了", "clickbait", 5),
    ("炸锅", "clickbait", 5),
    ("泪崩", "clickbait", 5),
    ("泪目", "clickbait", 5),
    ("后删", "clickbait", 5),
    ("紧急通知", "clickbait", 5),
    ("细思极恐", "clickbait", 5),

    # --- 📺 低质内容 ---
    ("一拳超人", "low_quality", 5),
    ("台球", "low_quality", 5),
    ("今天去", "low_quality", 5),
    ("今天改行", "low_quality", 5),
    ("企鹅", "low_quality", 5),
    ("大战", "low_quality", 5),
    ("传说", "low_quality", 5),
    ("之下", "low_quality", 5),
    ("凑企鹅", "low_quality", 5),
    ("吸奶", "low_quality", 5),
    ("和平精英", "low_quality", 5),
    ("太私密", "low_quality", 5),
    ("夫妻", "low_quality", 5),
    ("吵架", "low_quality", 5),
    ("套牛", "low_quality", 5),
    ("奥特曼", "low_quality", 5),
    ("奥特系列", "low_quality", 5),
    ("打赏", "low_quality", 5),
    ("奶龙", "low_quality", 5),
    ("嫁广东", "low_quality", 5),
    ("撒花", "low_quality", 5),
    ("性感", "low_quality", 5),
    ("想吃", "low_quality", 5),
    ("主播", "low_quality", 5),
    ("挑战打穿", "low_quality", 5),
    ("歌声悠扬", "low_quality", 5),
    ("泰国", "low_quality", 5),
    ("烤鸡", "low_quality", 5),
    ("爽就完了", "low_quality", 5),
    ("王者荣耀", "low_quality", 5),
    ("百听不厌", "low_quality", 5),
    ("纯勾引", "low_quality", 5),
    ("缝裤裆", "low_quality", 5),
    ("眼中的", "low_quality", 5),
    ("老朋友", "low_quality", 5),
    ("自助", "low_quality", 5),
    ("荣耀", "low_quality", 5),
    ("手游", "low_quality", 5),
    ("蛋仔", "low_quality", 5),
    ("派对", "low_quality", 5),
    ("补时", "low_quality", 5),
    ("抗议", "low_quality", 5),
    ("请欣赏", "low_quality", 5),
    ("赢的", "low_quality", 5),
    ("真硬气", "low_quality", 5),
    ("连看", "low_quality", 5),
    ("五遍", "low_quality", 5),
    ("醉入", "low_quality", 5),
    ("仙境", "low_quality", 5),
    ("铠甲", "low_quality", 5),
    ("勇士", "low_quality", 5),
    ("驾控", "low_quality", 5),
    ("鬼灭之刃", "low_quality", 5),

    # --- ⚠️ 垃圾/诈骗 ---
    ("中奖", "spam", 5),
    ("佣金", "spam", 5),
    ("领取", "spam", 5),
    ("刷单", "spam", 5),
    ("副业", "spam", 5),
    ("赚钱", "spam", 5),
    ("包赚", "spam", 5),
    ("在家就能做", "spam", 5),
    ("带你先赚", "spam", 5),
    ("年入百万", "spam", 5),
    ("扫码进群", "spam", 5),
    ("无风险", "spam", 5),
    ("日结", "spam", 5),
    ("日赚", "spam", 5),
    ("暴富", "spam", 5),
    ("神话", "spam", 5),
    ("月入5万", "spam", 5),
    ("月入十万", "spam", 5),
    ("点击", "spam", 5),
    ("百分百", "spam", 5),
    ("稳赚", "spam", 5),
    ("财富", "spam", 5),
    ("躺赚", "spam", 5),
    ("转账", "spam", 5),
    ("进群", "spam", 5),
    ("免费领", "spam", 5),
    ("银行卡", "spam", 5),
    ("发大财", "spam", 5),
    ("验证码", "spam", 5),
    ("高回报", "spam", 5),

    # ===== 🟠 严重度4 — 强降分 =====
    # --- 📰 标题党 ---
    ("一定要看", "clickbait", 4),
    ("不为人知", "clickbait", 4),
    ("不看亏了", "clickbait", 4),
    ("严禁外传", "clickbait", 4),
    ("值得收藏", "clickbait", 4),
    ("傻眼", "clickbait", 4),
    ("内幕", "clickbait", 4),
    ("千万别", "clickbait", 4),
    ("哭了", "clickbait", 4),
    ("唏嘘", "clickbait", 4),
    ("坐不住", "clickbait", 4),
    ("坐不住了", "clickbait", 4),
    ("收藏", "clickbait", 4),
    ("心疼", "clickbait", 4),
    ("心酸", "clickbait", 4),
    ("惊人", "clickbait", 4),
    ("无数人", "clickbait", 4),
    ("注意了", "clickbait", 4),
    ("深度||", "clickbait", 4),
    ("深度揭秘", "clickbait", 4),
    ("看呆", "clickbait", 4),
    ("看哭了", "clickbait", 4),
    ("真相", "clickbait", 4),
    ("破防", "clickbait", 4),
    ("秘密", "clickbait", 4),
    ("竟然", "clickbait", 4),
    ("笑不活了", "clickbait", 4),
    ("笑死了", "clickbait", 4),
    ("让人意外", "clickbait", 4),
    ("都在看", "clickbait", 4),
    ("隐藏", "clickbait", 4),
    ("难以置信", "clickbait", 4),
    ("震惊", "clickbait", 4),

    # --- 📺 低质内容 ---
    ("千万", "low_quality", 4),
    ("吓傻", "low_quality", 4),
    ("大妈", "low_quality", 4),
    ("大爷", "low_quality", 4),
    ("太可怕", "low_quality", 4),
    ("太吓人", "low_quality", 4),
    ("抢七", "low_quality", 4),
    ("欧冠", "low_quality", 4),
    ("汉坦", "low_quality", 4),
    ("生病", "low_quality", 4),
    ("病毒", "low_quality", 4),
    ("深度好文", "low_quality", 4),
    ("男篮", "low_quality", 4),
    ("看五遍", "low_quality", 4),
    ("私密", "low_quality", 4),
    ("绝杀", "low_quality", 4),
    ("老汉", "low_quality", 4),
    ("脱胎换骨", "low_quality", 4),
    ("英超", "low_quality", 4),
    ("足球", "low_quality", 4),

    # --- ⚠️ 垃圾/诈骗 ---
    ("两条线", "spam", 4),
    ("别再傻", "spam", 4),
    ("只要这样", "spam", 4),
    ("手中有", "spam", 4),
    ("试试这", "spam", 4),
    ("还在傻傻存钱", "spam", 4),

    # ===== 🟡 严重度3 — 中降分 =====
    # --- 📰 标题党 ---
    ("一句话", "clickbait", 3),
    ("亮了", "clickbait", 3),
    ("信息量很大", "clickbait", 3),
    ("准备拼了", "clickbait", 3),
    ("刚刚", "clickbait", 3),
    ("原来", "clickbait", 3),
    ("反转", "clickbait", 3),
    ("大反转", "clickbait", 3),
    ("奉陪到底", "clickbait", 3),
    ("就在刚刚", "clickbait", 3),
    ("彻底疯了", "clickbait", 3),
    ("通电话", "clickbait", 3),
    ("疯了", "clickbait", 3),
    ("突发!", "clickbait", 3),
    ("突发", "clickbait", 3),
    ("终于来了", "clickbait", 3),
    ("这就", "clickbait", 3),
    ("顾不上", "clickbait", 3),

    # --- 📺 低质内容-游戏类 ---
    ("原神", "low_quality", 3),
    ("鸣潮", "low_quality", 3),
    ("绝区零", "low_quality", 3),
    ("三角洲", "low_quality", 3),
    ("三角洲行动", "low_quality", 3),
    ("异环", "low_quality", 3),
    ("ssr", "low_quality", 3),
    ("抽卡", "low_quality", 3),
    ("抽到", "low_quality", 3),
    ("技能解读", "low_quality", 3),
    ("实战循环", "low_quality", 3),
    ("觉醒提升", "low_quality", 3),
    ("版本PV", "low_quality", 3),
    ("游戏实况", "low_quality", 3),
    ("游戏攻略", "low_quality", 3),
    ("试玩", "low_quality", 3),
    ("开箱", "low_quality", 3),
    ("手办", "low_quality", 3),

    # --- B站日常类 ---
    ("vlog", "low_quality", 3),
    ("日常vlog", "low_quality", 3),
    ("逛吃", "low_quality", 3),
    ("吃播", "low_quality", 3),
    ("探店", "low_quality", 3),
    ("打卡", "low_quality", 3),
    ("试吃", "low_quality", 3),
    ("试穿", "low_quality", 3),
    ("做菜", "low_quality", 3),
    ("下厨", "low_quality", 3),
    ("这样做", "low_quality", 3),
    ("巨好吃", "low_quality", 3),
    ("太好吃了", "low_quality", 3),

    # --- 美妆穿搭 ---
    ("化妆", "low_quality", 3),
    ("美妆", "low_quality", 3),
    ("美白", "low_quality", 3),
    ("口红", "low_quality", 3),
    ("发型", "low_quality", 3),
    ("护肤", "low_quality", 3),
    ("显瘦", "low_quality", 3),
    ("穿搭", "low_quality", 3),
    ("穿搭分享", "low_quality", 3),

    # --- 舞蹈娱乐 ---
    ("唱歌", "low_quality", 3),
    ("跳舞", "low_quality", 3),
    ("翻唱", "low_quality", 3),
    ("扭胯", "low_quality", 3),
    ("舞蹈", "low_quality", 3),
    ("Cos", "low_quality", 3),
    ("coser", "low_quality", 3),
    ("cos服", "low_quality", 3),
    ("表情包", "low_quality", 3),
    ("鬼畜", "low_quality", 3),
    ("搞笑", "low_quality", 3),
    ("太好笑", "low_quality", 3),
    ("meme", "low_quality", 3),

    # --- 情感/家庭 ---
    ("丈母娘", "low_quality", 3),
    ("婆婆", "low_quality", 3),
    ("公公", "low_quality", 3),
    ("嫂子", "low_quality", 3),
    ("弟媳", "low_quality", 3),
    ("老丈人", "low_quality", 3),
    ("老公", "low_quality", 3),
    ("女婿", "low_quality", 3),
    ("岳父", "low_quality", 3),
    ("岳母", "low_quality", 3),
    ("结婚", "low_quality", 3),
    ("婚礼", "low_quality", 3),
    ("生日", "low_quality", 3),
    ("过生日", "low_quality", 3),
    ("回家", "low_quality", 3),
    ("离婚", "low_quality", 3),
    ("分手", "low_quality", 3),
    ("相亲", "low_quality", 3),
    ("彩礼", "low_quality", 3),

    # --- 体育 ---
    ("孙颖莎", "low_quality", 3),
    ("王楚钦", "low_quality", 3),
    ("樊振东", "low_quality", 3),
    ("马龙", "low_quality", 3),
    ("国乒", "low_quality", 3),
    ("世乒赛", "low_quality", 3),
    ("乒协", "low_quality", 3),
    ("全红婵", "low_quality", 3),
    ("跳水", "low_quality", 3),
    ("刘翔", "low_quality", 3),
    ("姚明", "low_quality", 3),
    ("李娜", "low_quality", 3),
    ("运动员", "low_quality", 3),
    ("退役", "low_quality", 3),

    # --- 低质社会 ---
    ("上热搜", "low_quality", 3),
    ("热搜", "low_quality", 3),
    ("火了", "low_quality", 3),
    ("爆红", "low_quality", 3),
    ("被骂", "low_quality", 3),
    ("吐槽", "low_quality", 3),
    ("渣男", "low_quality", 3),
    ("小伙", "low_quality", 3),
    ("姑娘", "low_quality", 3),
    ("美女", "low_quality", 3),
    ("明星", "low_quality", 3),
    ("八卦", "low_quality", 3),
    ("娱乐圈", "low_quality", 3),
    ("周深", "low_quality", 3),
    ("陈赫", "low_quality", 3),
    ("阿信", "low_quality", 3),
    ("五月天", "low_quality", 3),

    # --- 社会悲剧 ---
    ("命陨", "low_quality", 3),
    ("坠桥", "low_quality", 3),
    ("惨", "low_quality", 3),
    ("惨坠", "low_quality", 3),
    ("悲剧", "low_quality", 3),
    ("猝死", "low_quality", 3),
    ("急救", "low_quality", 3),
    ("抢救", "low_quality", 3),
    ("可怕", "low_quality", 3),
    ("吓人", "low_quality", 3),
    ("太危险", "low_quality", 3),

    # --- 监控类 ---
    ("监控", "low_quality", 3),
    ("监控拍", "low_quality", 3),
    ("摄像头", "low_quality", 3),
    ("偷拍", "low_quality", 3),

    # --- 宠物 ---
    ("猫", "low_quality", 3),
    ("狗", "low_quality", 3),
    ("狗狗", "low_quality", 3),
    ("猫咪", "low_quality", 3),
    ("萌宠", "low_quality", 3),

    # --- 养生伪科学 ---
    ("养生", "low_quality", 3),
    ("中医", "low_quality", 3),
    ("偏方", "low_quality", 3),
    ("排毒", "low_quality", 3),
    ("减肥", "low_quality", 3),
    ("减脂", "low_quality", 3),
    ("致癌", "low_quality", 3),

    # --- 教育 ---
    ("中考", "low_quality", 3),
    ("高考", "low_quality", 3),
    ("小学数学", "low_quality", 3),
    ("初中数学", "low_quality", 3),
    ("阅读理解", "low_quality", 3),
    ("作文素材", "low_quality", 3),
    ("解三角形", "low_quality", 3),

    # --- 心理类 ---
    ("社恐", "low_quality", 3),
    ("自卑", "low_quality", 3),
    ("高情商", "low_quality", 3),
    ("低情商", "low_quality", 3),

    # --- 低质科普 ---
    ("冷知识", "low_quality", 3),

    # --- 其他 ---
    ("一首", "low_quality", 3),
    ("太好听了", "low_quality", 3),
    ("太牛了", "low_quality", 3),
    ("沉浸式", "low_quality", 3),
    ("治愈系", "low_quality", 3),
    ("延时摄影", "low_quality", 3),
    ("航拍", "low_quality", 3),
    ("换装", "low_quality", 3),
    ("走红", "low_quality", 3),
    ("穿", "low_quality", 3),
    ("周边", "low_quality", 3),
    ("早饭", "low_quality", 3),
    ("午饭", "low_quality", 3),
    ("晚餐", "low_quality", 3),
    ("下午茶", "low_quality", 3),
    ("一人食", "low_quality", 3),
    ("实测", "low_quality", 3),
    ("挑战", "low_quality", 3),

    # ===== ⚪ 严重度2 — 轻降分 =====
    # --- 📰 标题党 ---
    ("太", "clickbait", 2),
    ("非常", "clickbait", 2),
    ("极度", "clickbait", 2),
    ("彻底", "clickbait", 2),
    ("你敢信", "clickbait", 2),
    ("看傻", "clickbait", 2),
    ("看懵", "clickbait", 2),

    # --- 📺 低质内容 ---
    ("这一幕", "low_quality", 2),
    ("瞬间", "low_quality", 2),
    ("画面", "low_quality", 2),
    ("太真实", "low_quality", 2),
    ("南昌", "low_quality", 2),
    ("哈尔滨", "low_quality", 2),
    ("石家庄", "low_quality", 2),
    ("成都", "low_quality", 2),
    ("武汉", "low_quality", 2),

    # --- ⚠️ 也在低质科普里，sev2 ---
    ("为什么", "low_quality", 2),
]

# ===== 插入关键词 =====
inserted = 0
for kw, cat, sev in keywords:
    try:
        db.execute("INSERT INTO spam_filter_keywords (keyword, category, severity, note) VALUES (?, ?, ?, '')",
                   (kw, cat, sev))
        inserted += 1
    except:
        pass

# ===== 来源过滤 =====
sources = [
    ("tieba", "贴吧", 15, 0, "质量极低无信息价值"),
    ("toutiao_entertainment", "头条", 15, 0, "纯娱乐无信息价值"),
    ("toutiao_finance", "头条", 20, 0, "暴富骗局/理财钓鱼重灾区"),
    ("toutiao_sports", "头条", 20, 0, "情绪化低质内容充斥"),
    ("baidu", "百度", 30, 0, "新闻聚合质量参差"),
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

print("=" * 60)
print(f"✅ 垃圾过滤词已按格林清单重建")
print("=" * 60)
print(f"总关键词: {total_keywords}")
print(f"\n严重度分布:")
sev_map = {5: "🔴 直接拦截", 4: "🟠 强降分", 3: "🟡 中降分", 2: "⚪ 轻降分"}
for sev, cnt in sev_counts:
    print(f"  {sev_map.get(sev)}: {cnt}条")
print(f"\n分类分布:")
cat_map = {"low_quality": "📺 低质内容", "clickbait": "📰 标题党", "spam": "⚠️ 垃圾/诈骗"}
for cat, cnt in cat_counts:
    print(f"  {cat_map.get(cat)}: {cnt}条")
print(f"\n来源规则: {total_sources}条")

# 逐严重度展示
for sev_level, sev_name in [(5, "🔴 严重度5 — 直接拦截"),
                              (4, "🟠 严重度4 — 强降分"),
                              (3, "🟡 严重度3 — 中降分"),
                              (2, "⚪ 严重度2 — 轻降分")]:
    items = db.execute("""
        SELECT keyword, category FROM spam_filter_keywords 
        WHERE severity = ? ORDER BY category, keyword
    """, (sev_level,)).fetchall()
    
    sev5_title = {5: "标题党(14条)", 4: "标题党(33条)", 3: "标题党(18条)", 2: "标题党(7条)"}
    sev5_low = {5: "低质内容(55条)", 4: "低质内容(20条)", 3: "低质内容(169条)", 2: "低质内容(10条)"}
    sev5_spam = {5: "垃圾诈骗(30条)", 4: "垃圾诈骗(6条)", 3: "垃圾诈骗(0条)", 2: "垃圾诈骗(0条)"}
    
    clickbait = [k for k,c in items if c == 'clickbait']
    lowq = [k for k,c in items if c == 'low_quality']
    spam = [k for k,c in items if c == 'spam']
    
    print(f"\n  {sev_name}")
    print(f"  {'─'*56}")
    if clickbait:
        print(f"    📰 {sev5_title[sev_level]}: {' | '.join(clickbait)}")
    if lowq:
        print(f"    📺 {sev5_low[sev_level]}: {' | '.join(lowq)}")
    if spam:
        print(f"    ⚠️ {sev5_spam[sev_level]}: {' | '.join(spam)}")

print(f"\n{'─'*60}")
print("🔒 来源封顶:")
src_rows = db.execute("SELECT source_pattern, platform, base_score_cap FROM spam_filter_sources ORDER BY base_score_cap").fetchall()
for r in src_rows:
    print(f"  🟡 {r[0]:25s} | {r[1]:6s} | 封顶{r[2]}分")

print(f"\n{'='*60}")
print(f"总计: {total_keywords}条关键词 + {total_sources}条来源规则")
print(f"{'='*60}")
print(f"⚠️ 注意: 格林清单中删除了以下旧规则:")
print(f"  - bilibili/B站-科技/B站-知识 → 不在清单内")
print(f"  - weibo/zhihu_daily/sina_tech → 不在清单内")
print(f"  - toutiao_world/toutiao_military → 不在清单内")

db.close()
