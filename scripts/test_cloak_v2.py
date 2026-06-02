#!/usr/bin/env python3
"""测试CloakBrowser v0.3.30 采小红书"""
from cloakbrowser import launch
import json, time

print("=" * 60)
print("🧪 CloakBrowser v0.3.30 (Chromium 146)")
print("=" * 60)

browser = launch(
    headless=True,
    humanize=True,
    args=["--no-sandbox", "--disable-setuid-sandbox"],
)

page = browser.new_page()
page.goto("https://www.xiaohongshu.com/explore", timeout=30000, wait_until="domcontentloaded")
time.sleep(4)

# 提取笔记
notes = page.evaluate("""
    () => {
        const items = document.querySelectorAll('.note-item');
        return Array.from(items).slice(0, 10).map(item => {
            const link = item.querySelector('a');
            const img = item.querySelector('img');
            const titleEl = item.querySelector('.title, .note-title, [class*=title]');
            const authorEl = item.querySelector('.author, .name, [class*=author]');
            const likeEl = item.querySelector('.like, .count, [class*=like]');
            const href = link ? link.href : '';
            const match = href.match(/explore\\/([a-f0-9]+)/);
            return {
                href: href,
                img: img ? img.src : '',
                title: titleEl ? titleEl.textContent.trim() : '',
                author: authorEl ? authorEl.textContent.trim() : '',
                like: likeEl ? likeEl.textContent.trim() : '0',
                noteId: match ? match[1] : '',
            };
        });
    }
""")

print(f"\n📝 笔记: {len(notes)}条")
for n in notes[:5]:
    print(f"  [{n['author'][:15]}] {n['title'][:50]} | 👍{n['like']}")

# 测试能否拿__INITIAL_STATE__
state = page.evaluate("() => window.__INITIAL_STATE__")
if state:
    print(f"\n✅ __INITIAL_STATE__: keys={list(state.keys())[:10]}")
else:
    print(f"\n❌ __INITIAL_STATE__ = None (但DOM数据拿到了)")

browser.close()
print("\n✅ CloakBrowser测试完成!")
