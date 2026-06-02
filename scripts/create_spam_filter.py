#!/usr/bin/env python3
"""
创建垃圾过滤表 + 插入过滤词
"""
import sqlite3
from pathlib import Path

DB = Path("/home/administrator/.hermes") / "intelligence.db"
db = sqlite3.connect(str(DB))

# 1. 创建表
db.executescript("""
CREATE TABLE IF NOT EXISTS spam_filter_keywords (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    keyword TEXT NOT NULL UNIQUE,
    category TEXT DEFAULT 'low_quality',
    severity INTEGER DEFAULT 3,
    match_mode TEXT DEFAULT 'contains',
    is_active INTEGER DEFAULT 1,
    created_at TEXT DEFAULT (datetime('now','localtime')),
    note TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS spam_filter_sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_pattern TEXT NOT NULL UNIQUE,
    platform TEXT DEFAULT '',
    base_score_cap INTEGER DEFAULT 30,
    is_blocked INTEGER DEFAULT 0,
    is_active INTEGER DEFAULT 1,
    created_at TEXT DEFAULT (datetime('now','localtime')),
    note TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS spam_filter_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id INTEGER,
    title TEXT,
    matched_keyword TEXT,
    matched_source TEXT,
    action TEXT DEFAULT 'mark',
    created_at TEXT DEFAULT (datetime('now','localtime'))
);

CREATE INDEX IF NOT EXISTS idx_spam_log_item ON spam_filter_log(item_id);
CREATE INDEX IF NOT EXISTS idx_spam_keyword_active ON spam_filter_keywords(is_active);
CREATE INDEX IF NOT EXISTS idx_spam_source_active ON spam_filter_sources(is_active);
""")

print("表已创建")

# 2. 插入过滤词（从实际垃圾内容中提取）
keywords = [
    # ===== 低质泛娱乐类 =====
    ("奶龙", "low_quality", 5, "低质动画"),
    ("一拳超人", "low_quality", 5, "动漫"),
    ("原神", "low_quality", 3, "游戏-原神"),
    ("cos服", "low_quality", 3, "cosplay"),
    ("coser", "low_quality", 3, "cosplay"),
    ("vlog", "low_quality", 3, "日常vlog"),
    ("meme", "low_quality", 3, "迷因"),
    ("传说之下", "low_quality", 3, "游戏"),
    ("铠甲勇士", "low_quality", 3, "特摄"),
    ("手办", "low_quality", 3, "手办"),
    ("鸣潮", "low_quality", 3, "游戏-鸣潮"),
    ("绝区零", "low_quality", 3, "游戏-绝区零"),
    ("三角洲", "low_quality", 3, "游戏"),
    ("企鹅大战", "low_quality", 4, "低质游戏内容"),
    ("凑企鹅", "low_quality", 4, "低质游戏内容"),
    
    # ===== 震惊体标题党 =====
    ("细思极恐", "clickbait", 5, "震惊体标题党"),
    ("深度||", "clickbait", 4, "伪深度标题"),
    ("出大事了", "clickbait", 5, "震惊体"),
    ("紧急通知", "clickbait", 5, "震惊体"),
    ("快看", "clickbait", 3, "诱导点击"),
    ("惊人", "clickbait", 4, "震惊体"),
    ("彻底炸锅", "clickbait", 5, "震惊体"),
    ("万万没想到", "clickbait", 4, "震惊体"),
    ("都在看", "clickbait", 3, "诱导点击"),
    ("删前速看", "clickbait", 5, "恐吓体"),
    ("不转不是", "clickbait", 5, "道德绑架"),
    ("震惊", "clickbait", 4, "震惊体"),
    ("难以置信", "clickbait", 4, "标题党"),
    ("哭了", "low_quality", 3, "情绪标题"),
    ("看哭了", "low_quality", 3, "情绪标题"),
    ("坐不住", "low_quality", 3, "情绪标题"),
    ("彻底", "clickbait", 2, "过度修饰"),
    ("疯了", "clickbait", 3, "情绪标题"),
    
    # ===== 暴富/理财诈骗类 =====
    ("年入百万", "spam", 5, "暴富骗局"),
    ("月入5万", "spam", 5, "暴富骗局"),
    ("月入十万", "spam", 5, "暴富骗局"),
    ("闷声发大财", "spam", 5, "暴富骗局"),
    ("手中有5万", "spam", 4, "理财钓鱼"),
    ("暴富神话", "spam", 5, "暴富骗局"),
    ("躺赚", "spam", 5, "骗局"),
    ("副业赚钱", "spam", 4, "钓鱼"),
    ("零基础学", "spam", 3, "课程广告"),
    ("只要这样做", "spam", 4, "理财钓鱼"),
    
    # ===== 低质社会新闻 =====
    ("女子打赏", "low_quality", 3, "低质社会新闻"),
    ("缝裤裆", "low_quality", 5, "低质"),
    ("摆摊", "low_quality", 3, "低质"),
    ("夫妻吵架", "low_quality", 3, "低质"),
    ("离婚", "low_quality", 2, "低质社会"),
    ("太帅了", "low_quality", 3, "低质"),
    ("太美了", "low_quality", 3, "低质"),
    ("太可爱了", "low_quality", 3, "低质"),
    ("这一幕", "low_quality", 2, "低质"),
    
    # ===== 低质体育 =====
    ("赢的真硬气", "low_quality", 4, "低质体育"),
    ("永远失去了", "low_quality", 3, "情绪体育"),
    ("补时集体抗议", "low_quality", 3, "低质体育"),
    
    # ===== 低质军事/地缘（标题党类）=====
    ("顾不上", "clickbait", 3, "标题党"),
    ("突发：", "clickbait", 3, "伪突发"),
    ("亮了", "clickbait", 3, "低质"),
    ("一句话", "clickbait", 2, "过度简化"),
    ("信息量很大", "clickbait", 3, "标题党"),
]

# 先清空
db.execute("DELETE FROM spam_filter_keywords")
db.execute("DELETE FROM spam_filter_sources")

for kw, cat, sev, note in keywords:
    try:
        db.execute("INSERT OR IGNORE INTO spam_filter_keywords (keyword, category, severity, note) VALUES (?, ?, ?, ?)",
                   (kw, cat, sev, note))
    except:
        pass

# 3. 插入来源过滤
sources = [
    ("toutiao_finance", "头条", 25, 0, "头条财经，暴富骗局重灾区，封顶25分"),
    ("toutiao_sports", "头条", 25, 0, "头条体育，情绪化低质，封顶25分"),
    ("toutiao_entertainment", "头条", 20, 0, "头条娱乐，封顶20分"),
    ("toutiao_world", "头条", 30, 0, "头条国际，标题党重灾区，封顶30分"),
    ("bilibili", "B站", 30, 0, "B站，低质娱乐大量，封顶30分"),
    ("B站-科技", "B站", 35, 0, "B站科技频道，但混杂大量非科技内容，封顶35分"),
    ("tieba", "贴吧", 20, 0, "贴吧，质量极低，封顶20分"),
    ("zhihu_daily", "知乎", 40, 0, "知乎日报，质量参差，封顶40分"),
]

for src, plat, cap, blocked, note in sources:
    try:
        db.execute("INSERT OR IGNORE INTO spam_filter_sources (source_pattern, platform, base_score_cap, is_blocked, note) VALUES (?, ?, ?, ?, ?)",
                   (src, plat, cap, blocked, note))
    except:
        pass

db.commit()
print(f"已插入 {len(keywords)} 条过滤关键词")
print(f"已插入 {len(sources)} 条来源过滤")

# 展示
print("\n" + "=" * 70)
print("📋 垃圾过滤词表")
print("=" * 70)
rows = db.execute("SELECT keyword, category, severity, note FROM spam_filter_keywords ORDER BY severity DESC, category").fetchall()
for r in rows:
    flag = {5: "🔴", 4: "🟠", 3: "🟡", 2: "⚪"}.get(r[2], "⚪")
    print(f"  {flag} {r[0]:20s} | [{r[1]:12s}] | 严重度{r[2]} | {r[3]}")

print("\n" + "=" * 70)
print("📋 来源过滤表")
print("=" * 70)
rows2 = db.execute("SELECT source_pattern, platform, base_score_cap, is_blocked, note FROM spam_filter_sources").fetchall()
for r in rows2:
    flag = "🔴" if r[3] else "🟡"
    print(f"  {flag} {r[0]:20s} | {r[1]:8s} | 封顶{r[2]}分 | {r[4]}")

db.close()
print("\n✅ 垃圾过滤系统已就绪")
