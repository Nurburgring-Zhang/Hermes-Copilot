#!/usr/bin/env python3
"""
Edge AI Daily Collector — Hermes情报管道 Edge AI内容采集器
采集源: edge-ai-vision.com RSS Feed
内容方向: Edge AI芯片/NPU/FPGA, Physical AI, 工业视觉, AI算法优化
集成: 写入cleaned_intelligence表，加入v12推送管线
"""
import sys, os, json, time, re, sqlite3, urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime
from collections import Counter
from email.utils import parsedate_to_datetime

RSS_URL = "https://www.edge-ai-vision.com/feed/"
DB_PATH = os.path.expanduser("~/.hermes/data/intelligence.db")
CLEANED_DB = os.path.expanduser("~/.hermes/data/cleaned_intelligence.db")

# 偏好词 — Edge AI方向
EDGE_AI_KEYWORDS = [
    "edge ai", "边缘AI", "NPU", "neural processing", "FPGA", "SoC",
    "physical AI", "机器人", "robotics", "humanoid", "computer vision",
    "工业视觉", "defect detection", "model optimization", "量化",
    "TinyML", "embedded ML", "sensor fusion", "3D vision", "自动驾驶",
    "AI accelerator", "semiconductor", "image sensor",
    "smart manufacturing", "AI agent", "AI safety",
]

def log(msg): print(f"[{datetime.now().strftime('%H:%M:%S')}] ⚡ {msg}")

def safe_text(elem, default=""):
    return elem.text.strip() if elem is not None and elem.text else default

def strip_html(html_text):
    clean = re.sub(r'<[^>]+>', '', html_text or '')
    return re.sub(r'\s+', ' ', clean).strip()[:500]

def calc_ai_score(title, desc, categories):
    text = f"{title} {desc}".lower()
    score = 50
    pts_map = {
        'npu': 15, 'fpga': 12, 'soc': 10, 'chip': 8,
        'edge': 10, 'robotics': 15, 'robot': 12,
        'vision': 8, 'computer vision': 10,
        'autonomous': 12, 'quantization': 10,
        'fine-tuning': 8, 'acquisition': 8,
        'funding': 10, 'industrial': 8,
        'manufacturing': 8, 'sensor': 6, 'camera': 6,
        'deep learning': 8,
    }
    for kw, pts in pts_map.items():
        if kw in text: score += pts
    return min(100, score)

def get_preference_tags(categories, title):
    tags = set()
    text = f"{title} {' '.join(categories)}"
    mapping = [
        ('芯片/半导体', ['Processor', 'NPU', 'FPGA', 'Intel', 'Synopsys', 'NXP', 'Memory', 'Efinix', 'SoC']),
        ('机器人/AI硬件', ['Robotics', 'Robot', 'Automotive', 'NVIDIA', 'Physical']),
        ('计算机视觉', ['Vision', 'Camera', 'Visual', 'Image', 'Face', '3D']),
        ('AI算法/模型', ['Algorithms', 'Model', 'Quantization', 'Fine-Tun']),
        ('工业AI', ['Industrial', 'Factory', 'Manufactur', 'Inspection', 'Defect']),
        ('AI芯片设计', ['Cadence', 'Chip Design', 'EDA', 'Semiconduc']),
        ('传感器/感知', ['Sensor']),
    ]
    for tag, kws in mapping:
        if any(kw.lower() in text.lower() for kw in kws): tags.add(tag)
    return list(tags) if tags else ['Edge AI']

def fetch_feed():
    req = urllib.request.Request(RSS_URL, headers={
        'User-Agent': 'Mozilla/5.0 (compatible; HermesBot/1.0)'
    })
    try:
        resp = urllib.request.urlopen(req, timeout=30)
        return resp.read().decode('utf-8')
    except Exception as e:
        log(f"❌ RSS获取失败: {e}")
        return None

def parse_feed(xml_data):
    root = ET.fromstring(xml_data)
    items = root.findall('.//item')
    articles = []
    for item in items:
        title = safe_text(item.find('title'))
        link = safe_text(item.find('link'))
        pub_date_str = safe_text(item.find('pubDate'))
        desc_raw = safe_text(item.find('description'))
        try: pub_date = parsedate_to_datetime(pub_date_str)
        except: pub_date = datetime.now()
        categories = [safe_text(c) for c in item.findall('category') if safe_text(c)]
        content_elem = item.find('content:encoded', {'content': 'http://purl.org/rss/1.0/modules/content/'})
        content = safe_text(content_elem) if content_elem is not None else desc_raw
        description = strip_html(desc_raw) if desc_raw else strip_html(content)[:500]
        articles.append({
            'title': title, 'url': link, 'pub_date': pub_date,
            'description': description, 'content': strip_html(content)[:2000],
            'categories': categories,
        })
    return articles

def save_to_db(articles):
    conn = sqlite3.connect(CLEANED_DB)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS cleaned_intelligence (
        id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, content TEXT,
        summary TEXT, url TEXT UNIQUE, source TEXT, category TEXT,
        score REAL, preference_tags TEXT, matched_keywords TEXT,
        ai_score REAL, published_at TEXT, collected_at TEXT,
        is_pushed INTEGER DEFAULT 0)''')
    c.execute('CREATE INDEX IF NOT EXISTS idx_pushed ON cleaned_intelligence(is_pushed)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_source ON cleaned_intelligence(source)')
    saved = 0
    for art in articles:
        pref_tags = get_preference_tags(art['categories'], art['title'])
        ai_score = calc_ai_score(art['title'], art['description'], art['categories'])
        matched_kws = [kw for kw in EDGE_AI_KEYWORDS if kw.lower() in f"{art['title']} {art['description']}".lower()]
        try:
            c.execute('''INSERT OR IGNORE INTO cleaned_intelligence 
                (title, content, summary, url, source, category, score,
                 preference_tags, matched_keywords, ai_score,
                 published_at, collected_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''', (
                art['title'], art['content'], art['description'][:300],
                art['url'], 'edge_ai_vision', ','.join(art['categories']),
                ai_score, json.dumps(pref_tags, ensure_ascii=False),
                json.dumps(matched_kws[:5], ensure_ascii=False),
                ai_score,
                art['pub_date'].strftime('%Y-%m-%d %H:%M:%S'),
                datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            ))
            if c.rowcount > 0: saved += 1
        except: pass
    conn.commit()
    conn.close()
    return saved

def print_summary(articles):
    print(f"\n{'='*60}")
    print(f"📊 Edge AI Daily 采集报告")
    print(f"{'='*60}")
    print(f"总文章: {len(articles)} 条")
    date_counts = Counter(a['pub_date'].strftime('%m-%d') for a in articles)
    print(f"\n📅 日期分布:")
    for date, count in sorted(date_counts.items()):
        print(f"  {date}: {count}篇")
    scored = [(calc_ai_score(a['title'], a['description'], a['categories']), a['title']) for a in articles]
    scored.sort(reverse=True)
    print(f"\n🏆 TOP 5:")
    for score, title in scored[:5]:
        print(f"  ⭐{score:.0f} {title[:60]}")

def main():
    start = time.time()
    log("🚀 Edge AI Daily 采集器启动")
    xml_data = fetch_feed()
    if not xml_data: return 1
    articles = parse_feed(xml_data)
    log(f"📄 解析到 {len(articles)} 篇文章")
    if not articles: return 1
    saved = save_to_db(articles)
    log(f"💾 写入cleaned_intelligence: {saved}条新文章")
    print_summary(articles)
    elapsed = time.time() - start
    log(f"✅ 完成, 耗时: {elapsed:.1f}s")
    if "--push" in sys.argv:
        log("📤 触发推送...")
        os.system('cd ~/.hermes && python3 scripts/guardian.py push')
    return 0

if __name__ == "__main__":
    sys.exit(main())
