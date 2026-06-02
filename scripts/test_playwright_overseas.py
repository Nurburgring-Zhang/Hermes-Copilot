#!/usr/bin/env python3
"""Test Playwright connectivity to overseas platforms"""
import json, time, sys
from playwright.sync_api import sync_playwright

results = {}

with sync_playwright() as p:
    browser = p.chromium.launch(
        headless=True,
        args=['--no-sandbox', '--disable-dev-shm-usage', '--disable-blink-features=AutomationControlled']
    )
    context = browser.new_context(
        user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
        viewport={'width': 1280, 'height': 720},
    )

    # === HackerNews ===
    print("\n=== Testing HackerNews ===")
    try:
        page = context.new_page()
        page.goto('https://news.ycombinator.com', timeout=20000, wait_until='domcontentloaded')
        time.sleep(2)
        print(f"  Title: {page.title()}")
        items = page.evaluate("""
            () => {
                const rows = document.querySelectorAll('.athing');
                return Array.from(rows).slice(0,10).map(row => {
                    const titleEl = row.querySelector('.titleline a');
                    return {
                        title: titleEl ? titleEl.textContent.trim() : '',
                        url: titleEl ? titleEl.href : ''
                    };
                });
            }
        """)
        results['hackernews'] = {'status': 'OK', 'count': len(items), 'items': items}
        print(f"  Got {len(items)} stories")
        for i, item in enumerate(items[:5], 1):
            print(f"    {i}. {item['title'][:70]}")
        page.close()
    except Exception as e:
        results['hackernews'] = {'status': 'FAILED', 'error': str(e)}
        print(f"  FAILED: {e}")

    # === Reddit ===
    print("\n=== Testing Reddit ===")
    try:
        page = context.new_page()
        page.goto('https://www.reddit.com/r/programming/hot/?limit=15', timeout=20000, wait_until='domcontentloaded')
        time.sleep(3)
        print(f"  Title: {page.title()}")
        # Try extracting via JS
        items = page.evaluate("""
            () => {
                const articles = document.querySelectorAll('article');
                return Array.from(articles).slice(0,10).map(a => {
                    const link = a.querySelector('a[data-testid="post-title"]');
                    return {
                        title: link ? link.textContent.trim() : '',
                        url: link ? link.href : ''
                    };
                });
            }
        """)
        if items and items[0]['title']:
            results['reddit'] = {'status': 'OK', 'count': len(items), 'items': items}
            print(f"  Got {len(items)} posts")
            for i, item in enumerate(items[:5], 1):
                print(f"    {i}. {item['title'][:70]}")
        else:
            # Fallback: use snapshot text
            from bs4 import BeautifulSoup
            html = page.content()
            soup = BeautifulSoup(html, 'html.parser')
            links = soup.select('a[data-testid="post-title"]')
            items = [{'title': l.get_text(strip=True)[:100], 'url': l.get('href','')} for l in links[:10]]
            if items:
                results['reddit'] = {'status': 'OK', 'count': len(items), 'items': items}
                print(f"  Got {len(items)} posts (bs4 fallback)")
                for i, item in enumerate(items[:5], 1):
                    print(f"    {i}. {item['title'][:70]}")
            else:
                results['reddit'] = {'status': 'OK', 'count': 0, 'note': 'page loaded but no items found'}
                print(f"  Page loaded but no items extracted")
        page.close()
    except Exception as e:
        results['reddit'] = {'status': 'FAILED', 'error': str(e)}
        print(f"  FAILED: {e}")

    # === HuggingFace ===
    print("\n=== Testing HuggingFace ===")
    try:
        page = context.new_page()
        page.goto('https://huggingface.co/papers', timeout=20000, wait_until='domcontentloaded')
        time.sleep(3)
        print(f"  Title: {page.title()}")
        items = page.evaluate("""
            () => {
                const links = document.querySelectorAll('a[href*="/papers/"]');
                const seen = new Set();
                return Array.from(links).filter(l => {
                    const text = l.textContent.trim();
                    if (text.length > 10 && !seen.has(text)) {
                        seen.add(text);
                        return true;
                    }
                    return false;
                }).slice(0,10).map(l => ({
                    title: l.textContent.trim().substring(0, 100),
                    url: l.href
                }));
            }
        """)
        if items:
            results['huggingface'] = {'status': 'OK', 'count': len(items), 'items': items}
            print(f"  Got {len(items)} papers")
            for i, item in enumerate(items[:5], 1):
                print(f"    {i}. {item['title'][:70]}")
        else:
            results['huggingface'] = {'status': 'OK', 'count': 0, 'note': 'page loaded, no paper links'}
            print(f"  Page loaded but no papers extracted")
        page.close()
    except Exception as e:
        results['huggingface'] = {'status': 'FAILED', 'error': str(e)}
        print(f"  FAILED: {e}")

    browser.close()

print("\n\n" + "="*60)
print("OVERSEAS PLATFORM TEST RESULTS")
print("="*60)
for plat, data in results.items():
    status = data.get('status', 'UNKNOWN')
    count = data.get('count', 0)
    print(f"  {plat}: {status} ({count} items)")
    if 'error' in data:
        print(f"    Error: {data['error']}")

# Save results
with open('/home/administrator/.hermes/scripts/overseas_test_results.json', 'w') as f:
    json.dump(results, f, ensure_ascii=False, indent=2)
print(f"\nResults saved to overseas_test_results.json")
