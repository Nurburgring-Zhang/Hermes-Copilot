#!/usr/bin/env python3
"""
小红书登录Cookie获取辅助脚本
使用Playwright启动浏览器 -> 扫码登录 -> 导出cookies供采集器使用

用法:
  python3 xhs_login_helper.py              # 交互式登录
  python3 xhs_login_helper.py --headless    # 使用已有cookie尝试刷新
  python3 xhs_login_helper.py --show        # 显示当前保存的cookie状态
"""
import json
import sys
import os
import time
from pathlib import Path
from datetime import datetime

COOKIE_FILE = Path("/home/administrator/.hermes") / "xhs_cookies.json"
COOKIE_LOCK = Path("/home/administrator/.hermes") / "xhs_cookie.lock"

# 小红书域名列表
XHS_DOMAINS = [".xiaohongshu.com", "www.xiaohongshu.com", "edith.xiaohongshu.com"]


def save_cookies(cookies: list) -> bool:
    """保存cookies到文件"""
    COOKIE_FILE.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "cookies": cookies,
        "saved_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "count": len(cookies),
    }
    with open(COOKIE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"  ✅ Cookie saved: {len(cookies)} cookies -> {COOKIE_FILE}")
    return True


def load_cookies() -> list:
    """从文件加载cookies"""
    if not COOKIE_FILE.exists():
        return []
    try:
        with open(COOKIE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        cookies = data.get("cookies", [])
        saved_at = data.get("saved_at", "unknown")
        print(f"  📂 Loaded {len(cookies)} cookies (saved: {saved_at})")
        return cookies
    except Exception as e:
        print(f"  ⚠️ Cookie load error: {e}")
        return []


def check_cookie_valid(cookies: list) -> bool:
    """检查cookie是否有效（尝试访问首页）"""
    if not cookies:
        return False
    try:
        import urllib.request, ssl
        cookie_str = "; ".join([f"{c['name']}={c['value']}" for c in cookies if c.get('name') and c.get('value')])
        req = urllib.request.Request(
            "https://www.xiaohongshu.com/",
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                "Cookie": cookie_str,
            },
        )
        ctx = ssl.create_default_context()
        with urllib.request.urlopen(req, timeout=10, context=ctx) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            # 如果有登录态, __INITIAL_STATE__ 或页面内容会更丰富
            if "login" not in body.lower()[:2000]:
                print(f"  ✅ Cookie appears valid (HTTP {resp.status}, {len(body)} bytes)")
                return True
            print(f"  ⚠️ Cookie may be expired (redirect to login)")
            return False
    except Exception as e:
        print(f"  ⚠️ Cookie check error: {e}")
        return False


def browser_login(headless: bool = False) -> list:
    """
    启动Playwright浏览器进行登录
    - headless=False: 弹出浏览器窗口,用户扫码登录
    - headless=True:  使用已有cookie尝试,若无效则报错
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("  ❌ Playwright not installed. Run: pip install playwright && playwright install chromium")
        return []

    cookies = load_cookies()

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=headless,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
            ],
        )
        context = browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            locale="zh-CN",
        )

        # 反检测
        context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});
            window.chrome = {runtime: {}};
        """)

        page = context.new_page()

        if headless:
            # 无头模式: 尝试使用已有cookie
            if cookies:
                context.add_cookies(cookies)
                print("  🍪 Restored cookies, testing...")
            else:
                print("  ❌ No saved cookies. Run without --headless first to login.")
                browser.close()
                return []

        # 导航到首页
        print("  🌐 Navigating to xiaohongshu.com...")
        page.goto("https://www.xiaohongshu.com/", timeout=30000, wait_until="domcontentloaded")

        if not headless:
            print()
            print("  ════════════════════════════════════════════")
            print("  请在弹出的浏览器窗口中扫码登录小红书")
            print("  登录成功后, 按 Enter 继续...")
            print("  ════════════════════════════════════════════")
            print()
            input("  ▶ 按回车键继续 (登录后) > ")

            # 等待一下确保页面完全加载
            time.sleep(2)

        # 获取当前所有cookies
        new_cookies = context.cookies()
        print(f"  🍪 Got {len(new_cookies)} cookies from browser")

        # 如果是无头模式, 检查是否有效
        if headless:
            # 检查是否有登录态cookie (a1 / web_session 等)
            has_session = any(
                c.get("name") in ("a1", "web_session", "webId", "xhsTrackerId", "xhs_web_id")
                for c in new_cookies
            )
            if not has_session:
                print("  ⚠️ No session cookies found. Login may have expired.")
                browser.close()
                return cookies  # 返回旧的

        # 保存cookies
        save_cookies(new_cookies)

        # 验证: 试试访问搜索页面
        print("  🔍 Testing search...")
        page.goto("https://www.xiaohongshu.com/search_result?keyword=AI", timeout=20000, wait_until="domcontentloaded")
        time.sleep(3)

        # 尝试提取一些数据验证
        title = page.title()
        print(f"  📄 Page title: {title}")

        # 尝试获取笔记数据
        try:
            # 滚动加载
            for i in range(3):
                page.evaluate("window.scrollBy(0, 600)")
                time.sleep(1)

            # 检查是否有笔记卡片
            cards = page.query_selector_all(".note-item, .feeds-page .note-item, [class*='note']")
            print(f"  📊 Found ~{len(cards)} note cards on page")
        except Exception as e:
            print(f"  ⚠️ Note extraction: {e}")

        browser.close()

    return new_cookies


def show_status():
    """显示当前cookie状态"""
    if not COOKIE_FILE.exists():
        print("  ❌ No saved cookies found.")
        print(f"  💡 Run: python3 xhs_login_helper.py")
        return

    try:
        with open(COOKIE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        cookies = data.get("cookies", [])
        saved_at = data.get("saved_at", "unknown")
        print(f"  📂 Cookie file: {COOKIE_FILE}")
        print(f"  🕐 Saved at: {saved_at}")
        print(f"  📊 Total cookies: {len(cookies)}")

        # 显示关键cookie
        key_names = ["a1", "web_session", "webId", "xhsTrackerId", "xhs_web_id", "sessionid", "session"]
        for c in cookies:
            name = c.get("name", "")
            if name in key_names:
                val = c.get("value", "")
                print(f"  🍪 {name}: {val[:30]}...")
    except Exception as e:
        print(f"  ❌ Error: {e}")


def get_cookie_header() -> str:
    """获取cookie字符串,供HTTP请求使用"""
    cookies = load_cookies()
    if not cookies:
        return ""
    return "; ".join(
        [f"{c['name']}={c['value']}" for c in cookies if c.get("name") and c.get("value")]
    )


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="小红书登录Cookie助手")
    parser.add_argument("--headless", action="store_true", help="无头模式(使用已有cookie)")
    parser.add_argument("--show", action="store_true", help="显示当前cookie状态")
    args = parser.parse_args()

    print("=" * 50)
    print("  小红书 Cookie Helper")
    print(f"  Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 50)

    if args.show:
        show_status()
    elif args.headless:
        cookies = browser_login(headless=True)
        print(f"\n  Result: {len(cookies)} cookies")
        if cookies:
            print("  ✅ Ready for collection!")
        else:
            print("  ❌ Need interactive login first")
    else:
        cookies = browser_login(headless=False)
        if cookies:
            print(f"\n  ✅ Login successful! {len(cookies)} cookies saved")
            print("  💡 Now you can run the collector or use --headless to refresh")
        else:
            print(f"\n  ❌ Login failed or cancelled")
