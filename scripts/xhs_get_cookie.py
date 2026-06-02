#!/usr/bin/env python3
"""
小红书Cookie获取器 — 通过Playwright浏览器扫码登录获取真实Cookie
=============================================================
格林主人说：采高质量数据需要真实的cookie。

使用方式:
  1. 在你有显示器的电脑上运行: python3 xhs_get_cookie.py
  2. 浏览器打开小红书，手动登录
  3. Cookie自动保存到 xhs_cookies.json
  4. 采集器自动使用保存的cookie
"""

import json, sys, time
from datetime import datetime, timezone, timedelta
from pathlib import Path

HERMES = Path("/home/administrator/.hermes")
COOKIE_FILE = HERMES / "scripts" / "xhs_cookies.json"
TZ = timezone(timedelta(hours=8))

def get_cookies_playwright():
    """用Playwright打开小红书网页，让用户手动登录后获取cookie"""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("❌ 需要Playwright: pip install playwright && playwright install chromium")
        return None

    print("=" * 60)
    print("  小红书Cookie获取器")
    print("=" * 60)
    print()
    print("📱 将要打开小红书网页版，请按以下步骤：")
    print("  1. 在弹出的浏览器中打开 https://www.xiaohongshu.com")
    print("  2. 如果已登录，刷新一次确保cookie有效")
    print("  3. 如果未登录，请手动登录（扫码/手机号）")
    print("  4. 登录后等待5秒，脚本自动保存cookie")
    print("⏳ 10秒后自动打开浏览器...")
    time.sleep(10)

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
            locale="zh-CN",
        )
        page = context.new_page()
        page.goto("https://www.xiaohongshu.com/explore", timeout=30000)
        
        print()
        print("⏳ 请在浏览器中完成登录，然后等待60秒...")
        print("   如果已经登录，等待60秒自动保存")
        
        # 等待用户手动操作
        for i in range(60, 0, -1):
            print(f"\r  倒计时 {i}秒后自动保存cookie...", end="", flush=True)
            time.sleep(1)
        
        print()
        
        # 获取cookies
        cookies = context.cookies()
        cookie_dict = {}
        for c in cookies:
            cookie_dict[c['name']] = c['value']
        
        # 获取localStorage（可能含token）
        tokens = page.evaluate("""() => {
            const keys = Object.keys(localStorage);
            const result = {};
            for (const k of keys) {
                if (k.includes('token') || k.includes('session') || k.includes('auth')) {
                    try {
                        result[k] = JSON.parse(localStorage.getItem(k));
                    } catch {
                        result[k] = localStorage.getItem(k);
                    }
                }
            }
            return result;
        }""")
        
        page.close()
        browser.close()
        
        # 保存
        result = {
            "timestamp": datetime.now(TZ).isoformat(),
            "cookies": cookie_dict,
            "cookie_str": "; ".join([f"{k}={v}" for k, v in cookie_dict.items()]),
            "tokens": tokens,
        }
        
        COOKIE_FILE.parent.mkdir(parents=True, exist_ok=True)
        COOKIE_FILE.write_text(json.dumps(result, ensure_ascii=False, indent=2))
        
        print(f"\n✅ Cookie已保存到 {COOKIE_FILE}")
        print(f"   Cookie数: {len(cookie_dict)}")
        if tokens:
            print(f"   发现tokens: {list(tokens.keys())}")
        
        return result


if __name__ == "__main__":
    get_cookies_playwright()
