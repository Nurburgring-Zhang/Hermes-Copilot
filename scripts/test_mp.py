import asyncio, re
from playwright.async_api import async_playwright

async def test():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=['--disable-blink-features=AutomationControlled'])
        ctx = await browser.new_context(
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/121.0.0.0 Safari/537.36',
            locale='zh-CN',
        )
        page = await ctx.new_page()
        
        url = 'https://mp.weixin.qq.com/s/S8R7huJuSGbp-RS-o9gizA'
        resp = await page.goto(url, wait_until='domcontentloaded', timeout=8000)
        await page.wait_for_timeout(3000)
        
        content = await page.content()
        print(f'Length: {len(content)}')
        
        # Try title patterns
        title_m = re.search(r'activity-name["\s][^>]*>([^<]+)<', content)
        if title_m:
            print(f'activity-name: {title_m.group(1)[:80]}')
        
        title_m2 = re.search(r'<title>([^<]+)</title>', content)
        if title_m2:
            print(f'<title>: {title_m2.group(1)[:80]}')
        
        title_m3 = re.search(r'"title"\s*:\s*"([^"]+)"', content)
        if title_m3:
            print(f'"title": {title_m3.group(1)[:80]}')
        
        # Get body text
        try:
            text = await page.inner_text('body')
            print(f'Body (first 300): {text[:300]}')
        except:
            pass
        
        # Check verification
        if '验证' in content or '安全' in content or '投诉' in content:
            print('Needs verification')
        
        await browser.close()

asyncio.run(test())
