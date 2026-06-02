#!/usr/bin/env python3
"""
页面快照API — 工部的浏览器自动化核心
======================================
统一接口: navigate(url) → render(mode) → extract(selector_map)

三层 fallback:
1. Playwright (完整浏览器)
2. HTTP 直接请求 (无JS)
3. Jina Reader API

输出经 RTK 压缩后注入主池。
"""

import os, sys, json, re, time, logging, urllib.request, urllib.parse
from typing import Any, Dict, List, Optional, Callable
from datetime import datetime
from dataclasses import dataclass, field

# 确保能导入同级模块
_script_dir = os.path.dirname(os.path.abspath(__file__))
if _script_dir not in sys.path:
    sys.path.insert(0, _script_dir)

from rtk_compressor import RTK

logger = logging.getLogger("hermes.page_snapshot")


@dataclass
class SnapshotResult:
    """页面快照结果"""
    url: str
    title: str = ""
    status: str = "ok"
    mode: str = "compact"
    content: str = ""
    structured: Dict = field(default_factory=dict)
    size_bytes: int = 0
    tokens_estimated: int = 0
    source: str = ""  # playwright/http/jina
    
    def compress(self, ratio: float = 0.5, bp_level: int = 0):
        """压缩内容"""
        if self.content:
            self.content = RTK.compress(self.content, "html", ratio, bp_level)
            self.tokens_estimated = len(self.content) // 4
            self.size_bytes = len(self.content.encode())


class PageSnapshot:
    """
    页面快照 — 统一浏览器接口。
    
    三层 fallback:
    1. Playwright (完全浏览器,可执行JS)
    2. HTTP 直接请求 (无JS,速度快)
    3. Jina Reader (内容提取API)
    
    用法:
        ps = PageSnapshot()
        
        # 导航
        result = ps.navigate("https://example.com")
        
        # 渲染
        html = ps.render("html")
        structured = ps.render("json")
        summary = ps.render("compact")
        
        # 提取
        data = ps.extract({"title": "h1", "links": "a[href]"})
    """
    
    def __init__(self, use_playwright: bool = False):
        self.use_playwright = use_playwright
        self._current_url: str = ""
        self._current_html: str = ""
        self._current_title: str = ""
        self._source: str = ""
        
        # 缓存
        self._cache: Dict[str, SnapshotResult] = {}
        self._cache_ttl = 300  # 5分钟
        
        # 尝试导入 Playwright
        self._playwright_available = False
        if use_playwright:
            try:
                import playwright
                self._playwright_available = True
            except ImportError:
                logger.warning("Playwright not installed, using HTTP fallback")
    
    def navigate(self, url: str, timeout: int = 15) -> SnapshotResult:
        """
        导航到 URL。
        
        策略:
        1. 检查缓存
        2. Playwright (如果可用)
        3. HTTP 直接请求
        4. Jina Reader (内容提取)
        """
        # 缓存检查
        cache_key = url.strip().rstrip('/')
        if cache_key in self._cache:
            cached = self._cache[cache_key]
            if (datetime.now().timestamp() - self._cache_time(cache_key)) < self._cache_ttl:
                logger.info(f"Cache hit: {url[:60]}")
                return cached
        
        result = SnapshotResult(url=url)
        
        # 策略1: Playwright
        if self._playwright_available:
            try:
                result = self._navigate_playwright(url, timeout)
                if result.status == "ok":
                    self._cache_result(url, result)
                    return result
            except Exception as e:
                logger.debug(f"Playwright failed: {e}")
        
        # 策略2: HTTP 直接
        try:
            result = self._navigate_http(url, timeout)
            if result.status == "ok":
                self._cache_result(url, result)
                return result
        except Exception as e:
            logger.debug(f"HTTP failed: {e}")
        
        # 策略3: Jina Reader
        try:
            result = self._navigate_jina(url, timeout)
            if result.status == "ok":
                self._cache_result(url, result)
                return result
        except Exception as e:
            logger.debug(f"Jina failed: {e}")
        
        result.status = "error"
        result.content = f"All fetch strategies failed for {url}"
        return result
    
    def _navigate_http(self, url: str, timeout: int) -> SnapshotResult:
        """HTTP 直接请求"""
        result = SnapshotResult(url=url, source="http")
        
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "text/html,application/xhtml+xml,*/*",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            }
        )
        
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            html_bytes = resp.read()
            encoding = resp.headers.get_content_charset() or "utf-8"
            html = html_bytes.decode(encoding, errors="replace")
        
        # 提取 title
        title_match = re.search(r'<title[^>]*>(.*?)</title>', html, re.DOTALL | re.IGNORECASE)
        result.title = title_match.group(1).strip() if title_match else ""
        
        # 净化为文本
        text = RTK.compress_html(html)
        
        result.content = text
        result.size_bytes = len(html.encode())
        result.tokens_estimated = len(text) // 4
        result.mode = "compact"
        
        # 结构化数据
        result.structured = self._extract_structured(html)
        
        # 缓存当前
        self._current_url = url
        self._current_html = html
        self._current_title = result.title
        self._source = "http"
        
        logger.info(f"HTTP fetched: {url[:50]} ({result.size_bytes // 1024}KB)")
        return result
    
    def _navigate_jina(self, url: str, timeout: int) -> SnapshotResult:
        """Jina Reader 内容提取"""
        result = SnapshotResult(url=url, source="jina")
        
        jina_url = f"https://r.jina.ai/{urllib.parse.quote(url)}"
        req = urllib.request.Request(
            jina_url,
            headers={"User-Agent": "Mozilla/5.0", "Accept": "text/plain"}
        )
        
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            content = resp.read().decode("utf-8", errors="replace")
        
        if content and len(content) > 50:
            # Jina 格式: 标题\n\n正文
            parts = content.split("\n\n", 1)
            result.title = parts[0].strip() if parts else ""
            result.content = parts[1] if len(parts) > 1 else content
            result.content = result.content[:2000]  # 截断
            result.size_bytes = len(content.encode())
            result.tokens_estimated = len(result.content) // 4
            
            self._current_url = url
            self._current_title = result.title
            self._source = "jina"
            
            logger.info(f"Jina extracted: {url[:50]}")
            return result
        
        result.status = "error"
        result.content = "Jina returned empty content"
        return result
    
    def _navigate_playwright(self, url: str, timeout: int) -> SnapshotResult:
        """Playwright 浏览器渲染"""
        result = SnapshotResult(url=url, source="playwright")
        # Playwright 集成留空,环境无浏览器
        result.status = "unavailable"
        result.content = "Playwright not available in this environment"
        return result
    
    def _extract_structured(self, html: str) -> Dict:
        """从 HTML 提取结构化数据"""
        structured = {}
        
        # 提取标题
        title_m = re.search(r'<title[^>]*>(.*?)</title>', html, re.DOTALL | re.IGNORECASE)
        if title_m:
            structured["title"] = title_m.group(1).strip()
        
        # 提取 meta description
        desc_m = re.search(r'<meta[^>]*name=["\']description["\'][^>]*content=["\']([^"\']+)["\']', html, re.IGNORECASE)
        if desc_m:
            structured["description"] = desc_m.group(1)
        
        # 提取所有链接
        links = re.findall(r'<a[^>]*href=["\'](https?://[^"\']+)["\'][^>]*>(.*?)</a>', html, re.DOTALL | re.IGNORECASE)
        if links:
            structured["links"] = [
                {"url": u, "text": re.sub(r'<[^>]+>', '', t).strip()[:50]}
                for u, t in links[:20]
            ]
        
        # 提取所有标题 (h1-h3)
        headings = []
        for tag in ['h1', 'h2', 'h3']:
            hs = re.findall(f'<{tag}[^>]*>(.*?)</{tag}>', html, re.DOTALL | re.IGNORECASE)
            headings.extend([re.sub(r'<[^>]+>', '', h).strip() for h in hs[:10]])
        if headings:
            structured["headings"] = headings
        
        # 提取图片
        imgs = re.findall(r'<img[^>]*src=["\']([^"\']+)["\'][^>]*alt=["\']([^"\']*)["\']', html, re.IGNORECASE)
        if imgs:
            structured["images"] = [
                {"src": s, "alt": a[:50]} for s, a in imgs[:10]
            ]
        
        return structured
    
    def render(self, mode: str = "compact") -> Any:
        """
        渲染当前页面。
        
        参数:
            mode: html/json/compact
            
        html — 原始 HTML(已压缩)
        json — 结构化数据 {title, text, links, images, headings}
        compact — 净文本摘要
        """
        if not self._current_html and not self._current_url:
            return {"error": "No page loaded, call navigate() first"}
        
        if mode == "html":
            return {
                "content": RTK.compress_html(self._current_html)[:5000],
                "size": len(self._current_html),
                "mode": "html",
            }
        
        elif mode == "json":
            return {
                "title": self._current_title,
                "structured": self._extract_structured(self._current_html),
                "mode": "json",
            }
        
        else:  # compact
            text = RTK.compress_html(self._current_html)[:2000]
            return {
                "summary": text[:500],
                "key_points": self._extract_structured(self._current_html).get("headings", []),
                "link_count": len(self._extract_structured(self._current_html).get("links", [])),
                "mode": "compact",
            }
    
    def extract(self, selector_map: Dict[str, str]) -> Dict:
        """
        从当前页面提取指定选择器的内容。
        
        参数:
            selector_map: {"字段名": "CSS选择器"}
            
        返回:
            {"字段名": ["匹配内容列表"], ...}
        """
        if not self._current_html:
            return {"error": "No page loaded"}
        
        results = {}
        html = self._current_html
        
        for field, selector in selector_map.items():
            if selector.startswith("."):
                # class 选择器
                cls = selector[1:]
                matches = re.findall(
                    f'<[^>]*class=["\'][^"\']*{cls}[^"\']*["\'][^>]*>(.*?)</[^>]+>',
                    html, re.DOTALL | re.IGNORECASE
                )
            elif selector.startswith("#"):
                # id 选择器
                id_ = selector[1:]
                matches = re.findall(
                    f'<[^>]*id=["\']{id_}["\'][^>]*>(.*?)</[^>]+>',
                    html, re.DOTALL | re.IGNORECASE
                )
            elif selector == "a" or selector.startswith("a["):
                # 链接
                matches = re.findall(r'<a[^>]*href="([^"]+)"', html, re.IGNORECASE)
            elif selector.startswith("h") and len(selector) == 2:
                # h1-h6
                matches = re.findall(
                    f'<{selector}[^>]*>(.*?)</{selector}>',
                    html, re.DOTALL | re.IGNORECASE
                )
                matches = [re.sub(r'<[^>]+>', '', m).strip() for m in matches]
            elif selector == "img":
                matches = re.findall(r'<img[^>]*src="([^"]+)"', html, re.IGNORECASE)
            else:
                # 通用标签
                matches = re.findall(
                    f'<{selector}[^>]*>(.*?)</{selector}>',
                    html, re.DOTALL | re.IGNORECASE
                )
            
            results[field] = [m[:200] for m in matches[:10]]
        
        return {"results": results, "matched_selectors": list(selector_map.keys())}
    
    def _cache_result(self, url: str, result: SnapshotResult):
        """缓存结果"""
        key = url.strip().rstrip('/')
        self._cache[key] = result
        # 限制缓存大小
        if len(self._cache) > 50:
            oldest = min(self._cache.keys(), key=lambda k: self._cache[k].tokens_estimated or 0)
            del self._cache[oldest]
    
    def _cache_time(self, key: str) -> float:
        """获取缓存时间戳"""
        return datetime.now().timestamp()
    
    def clear_cache(self):
        """清空缓存"""
        self._cache.clear()
    
    def get_stats(self) -> Dict:
        return {
            "cache_size": len(self._cache),
            "current_url": self._current_url[:50] if self._current_url else None,
            "source": self._source,
            "playwright_available": self._playwright_available,
        }


# 单例
_snapshot_instance = None


def get_page_snapshot() -> PageSnapshot:
    """获取全局页面快照实例"""
    global _snapshot_instance
    if _snapshot_instance is None:
        _snapshot_instance = PageSnapshot()
    return _snapshot_instance


def navigate(url: str, timeout: int = 15) -> Dict:
    """快捷导航"""
    return get_page_snapshot().navigate(url, timeout).__dict__
