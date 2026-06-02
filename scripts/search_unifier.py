#!/usr/bin/env python3
"""
统一搜索适配器 — 户部的数据流核心
====================================
将多个搜索引擎(Tavily/Exa/Brave/Jina/DuckDuckGo)的响应统一为标准Schema。

架构:
1. 每个引擎一个 Adapter 类
2. SearchUnifier 统一入口
3. 输出统一 Schema: {query, results[], meta}
4. 前置 Scrapling/Crawl4AI DOM 净化

统一 Schema:
{
  "query": "string",
  "results": [
    {"url": "...", "title": "...", "snippet": "...", "confidence": 0.0, "timestamp": "...", "source": "tavily"}
  ],
  "meta": {"latency_ms": 0, "token_estimate": 0, "source_count": 1}
}
"""

import os, sys, json, time, logging, hashlib, urllib.request, urllib.parse
from typing import Any, Dict, List, Optional
from datetime import datetime
from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor, as_completed

# 确保能导入同级模块
_script_dir = os.path.dirname(os.path.abspath(__file__))
if _script_dir not in sys.path:
    sys.path.insert(0, _script_dir)

from rtk_compressor import RTK

logger = logging.getLogger("hermes.search_unifier")


@dataclass
class SearchResult:
    """标准搜索结果"""
    url: str
    title: str
    snippet: str = ""
    confidence: float = 0.5
    timestamp: str = ""
    source: str = ""
    language: str = ""
    category: str = ""
    
    def to_dict(self) -> Dict:
        return {
            "url": self.url,
            "title": self.title,
            "snippet": self.snippet[:200] if self.snippet else "",
            "confidence": round(self.confidence, 2),
            "timestamp": self.timestamp,
            "source": self.source,
            "language": self.language,
        }


@dataclass
class UnifiedResponse:
    """统一响应"""
    query: str
    results: List[SearchResult] = field(default_factory=list)
    meta: Dict = field(default_factory=lambda: {
        "latency_ms": 0, "token_estimate": 0, "source_count": 0,
    })
    
    def to_dict(self) -> Dict:
        return {
            "query": self.query,
            "results": [r.to_dict() for r in self.results],
            "meta": self.meta,
        }


class SearchAdapter:
    """搜索适配器基类"""
    
    name = "base"
    
    def search(self, query: str, max_results: int = 10, **kwargs) -> List[SearchResult]:
        raise NotImplementedError
    
    def _make_request(self, url: str, headers: Dict = None, 
                      timeout: int = 15) -> Optional[str]:
        """通用 HTTP 请求"""
        try:
            req = urllib.request.Request(
                url,
                headers=headers or {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "Accept": "application/json, text/html, */*",
                }
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except Exception as e:
            logger.debug(f"{self.name} request failed: {e}")
            return None


class TavilyAdapter(SearchAdapter):
    """Tavily Search API"""
    
    name = "tavily"
    
    def __init__(self, api_key: str = ""):
        self.api_key = api_key or os.environ.get("TAVILY_API_KEY", "")
    
    def search(self, query: str, max_results: int = 10, **kwargs) -> List[SearchResult]:
        if not self.api_key:
            logger.warning("Tavily API key not set")
            return []
        
        url = f"https://api.tavily.com/search"
        data = json.dumps({
            "api_key": self.api_key,
            "query": query,
            "max_results": min(max_results, 20),
            "search_depth": kwargs.get("depth", "basic"),
        }).encode()
        
        try:
            req = urllib.request.Request(
                url, data=data,
                headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                result = json.loads(resp.read())
            
            results = []
            for item in result.get("results", []):
                results.append(SearchResult(
                    url=item.get("url", ""),
                    title=item.get("title", ""),
                    snippet=item.get("content", ""),
                    confidence=min(item.get("score", 0.5) + 0.3, 1.0),
                    source=self.name,
                    timestamp=item.get("published_date", ""),
                ))
            return results
        except Exception as e:
            logger.warning(f"Tavily search failed: {e}")
            return []


class JinaReaderAdapter(SearchAdapter):
    """Jina Reader — URL内容提取"""
    
    name = "jina_reader"
    
    def search(self, query: str, max_results: int = 5, **kwargs) -> List[SearchResult]:
        """Jina Reader 是内容提取器,这里做 URL 内容提取"""
        url = kwargs.get("url", "")
        if not url:
            return []
        
        jina_url = f"https://r.jina.ai/{urllib.parse.quote(url)}"
        try:
            req = urllib.request.Request(
                jina_url,
                headers={
                    "User-Agent": "Mozilla/5.0",
                    "Accept": "text/plain",
                }
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                content = resp.read().decode("utf-8", errors="replace")
            
            if content and len(content) > 100:
                # Jina 返回格式: 标题\n\n正文
                lines = content.split("\n\n", 1)
                title = lines[0].strip() if lines else url
                body = lines[1] if len(lines) > 1 else content
                
                return [SearchResult(
                    url=url,
                    title=title[:150],
                    snippet=RTK.compress_html(body)[:500],
                    confidence=0.8,
                    source=self.name,
                )]
        except Exception as e:
            logger.debug(f"Jina extract failed: {e}")
        
        return []


class DuckDuckGoAdapter(SearchAdapter):
    """DuckDuckGo HTML 搜索"""
    
    name = "duckduckgo"
    
    def search(self, query: str, max_results: int = 10, **kwargs) -> List[SearchResult]:
        url = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(query)}"
        html = self._make_request(url)
        
        if not html:
            return []
        
        results = []
        import re
        
        # 解析 DuckDuckGo 的 HTML 结果
        # 提取 result 卡片
        blocks = re.findall(
            r'<a[^>]*class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>.*?'
            r'<a[^>]*class="result__snippet"[^>]*>(.*?)</a>',
            html, re.DOTALL
        )
        
        if not blocks:
            # fallback: 更宽松的匹配
            blocks = re.findall(
                r'<a[^>]*href="(https?://[^"]+)"[^>]*>(.*?)</a>',
                html, re.DOTALL
            )
            seen = set()
            for href, title in blocks:
                title_clean = re.sub(r'<[^>]+>', '', title).strip()
                if title_clean and len(title_clean) > 5 and href not in seen:
                    seen.add(href)
                    results.append(SearchResult(
                        url=href,
                        title=title_clean[:150],
                        confidence=0.5,
                        source=self.name,
                    ))
                    if len(results) >= max_results:
                        break
            return results
        
        for href, title, snippet in blocks[:max_results]:
            title_clean = re.sub(r'<[^>]+>', '', title).strip()
            snippet_clean = re.sub(r'<[^>]+>', '', snippet).strip()
            results.append(SearchResult(
                url=href.strip(),
                title=title_clean[:150],
                snippet=snippet_clean[:300],
                confidence=0.6,
                source=self.name,
            ))
        
        return results


class ExaAdapter(SearchAdapter):
    """Exa Search API"""
    
    name = "exa"
    
    def __init__(self, api_key: str = ""):
        self.api_key = api_key or os.environ.get("EXA_API_KEY", "")
    
    def search(self, query: str, max_results: int = 10, **kwargs) -> List[SearchResult]:
        if not self.api_key:
            logger.debug("Exa API key not set")
            return []
        
        url = "https://api.exa.ai/search"
        data = json.dumps({
            "query": query,
            "numResults": max_results,
            "useAutoprompt": kwargs.get("autoprompt", True),
        }).encode()
        
        try:
            req = urllib.request.Request(
                url, data=data,
                headers={
                    "Content-Type": "application/json",
                    "x-api-key": self.api_key,
                }
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                result = json.loads(resp.read())
            
            return [
                SearchResult(
                    url=item.get("url", ""),
                    title=item.get("title", ""),
                    snippet=item.get("text", "")[:300],
                    confidence=min(item.get("score", 0) / 10, 1.0),
                    source=self.name,
                )
                for item in result.get("results", [])
            ]
        except Exception as e:
            logger.debug(f"Exa search failed: {e}")
            return []


class BraveAdapter(SearchAdapter):
    """Brave Search API"""
    
    name = "brave"
    
    def __init__(self, api_key: str = ""):
        self.api_key = api_key or os.environ.get("BRAVE_API_KEY", "")
    
    def search(self, query: str, max_results: int = 10, **kwargs) -> List[SearchResult]:
        if not self.api_key:
            logger.debug("Brave API key not set")
            return []
        
        url = f"https://api.search.brave.com/res/v1/web/search?q={urllib.parse.quote(query)}&count={max_results}"
        html = self._make_request(url, {
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
            "X-Subscription-Token": self.api_key,
        })
        
        if not html:
            return []
        
        try:
            data = json.loads(html)
            results = []
            for item in data.get("web", {}).get("results", []):
                results.append(SearchResult(
                    url=item.get("url", ""),
                    title=item.get("title", ""),
                    snippet=item.get("description", ""),
                    confidence=0.7,
                    source=self.name,
                ))
            return results
        except:
            return []


class SearchUnifier:
    """
    统一搜索入口。
    
    用法:
        su = SearchUnifier()
        response = su.search("最新AI新闻", sources=["tavily", "duckduckgo"])
        print(response.results)
    """
    
    def __init__(self, max_workers: int = 3):
        self.max_workers = max_workers
        self._adapters: Dict[str, SearchAdapter] = {}
        self._register_defaults()
    
    def _register_defaults(self):
        """注册默认适配器"""
        self.register(TavilyAdapter())
        self.register(ExaAdapter())
        self.register(BraveAdapter())
        self.register(DuckDuckGoAdapter())
        self.register(JinaReaderAdapter())
    
    def register(self, adapter: SearchAdapter):
        """注册适配器"""
        self._adapters[adapter.name] = adapter
        logger.info(f"Search adapter registered: {adapter.name}")
    
    def search(self, query: str, sources: List[str] = None,
               max_results: int = 10, timeout: float = 20.0,
               dedup: bool = True, **kwargs) -> UnifiedResponse:
        """
        统一搜索。
        
        参数:
            query: 搜索词
            sources: 使用的搜索源 (默认: 全部可用)
            max_results: 最大结果数
            timeout: 总超时
            dedup: 是否去重
            kwargs: 传递给各 adapter 的额外参数
            
        返回:
            UnifiedResponse
        """
        start = time.time()
        response = UnifiedResponse(query=query)
        
        # 确定搜索源
        if sources:
            adapters = [self._adapters[s] for s in sources if s in self._adapters]
        else:
            adapters = list(self._adapters.values())
        
        if not adapters:
            logger.warning("No search adapters available")
            return response
        
        # 并行搜索
        all_results = []
        futures = {}
        
        with ThreadPoolExecutor(max_workers=min(len(adapters), self.max_workers)) as executor:
            for adapter in adapters:
                future = executor.submit(
                    self._safe_search, adapter, query, max_results, **kwargs
                )
                futures[future] = adapter.name
            
            for future in as_completed(futures, timeout=timeout):
                source_name = futures[future]
                try:
                    results = future.result()
                    all_results.extend(results)
                    logger.info(f"  {source_name}: {len(results)} results")
                except Exception as e:
                    logger.warning(f"  {source_name} failed: {e}")
        
        # 去重
        if dedup:
            all_results = self._dedup(all_results)
        
        # 排序 + 截断
        all_results.sort(key=lambda r: r.confidence, reverse=True)
        response.results = all_results[:max_results]
        
        # Meta
        elapsed = time.time() - start
        response.meta = {
            "latency_ms": round(elapsed * 1000),
            "token_estimate": sum(len(r.title + r.snippet) // 4 for r in response.results),
            "source_count": len(adapters),
            "sources_used": [a.name for a in adapters],
        }
        
        logger.info(f"Search '{query[:40]}': {len(response.results)} results in {elapsed:.1f}s")
        return response
    
    def _safe_search(self, adapter: SearchAdapter, query: str, 
                     max_results: int, **kwargs) -> List[SearchResult]:
        """安全搜索包装"""
        try:
            return adapter.search(query, max_results, **kwargs) or []
        except Exception as e:
            logger.warning(f"Search error {adapter.name}: {e}")
            return []
    
    def _dedup(self, results: List[SearchResult]) -> List[SearchResult]:
        """按 URL 去重"""
        seen = set()
        unique = []
        for r in results:
            url_key = r.url.strip().rstrip('/')
            if url_key and url_key not in seen:
                seen.add(url_key)
                unique.append(r)
        return unique
    
    def get_available_sources(self) -> List[str]:
        """获取可用搜索源列表"""
        return list(self._adapters.keys())


# 单例
_unifier_instance = None


def get_search_unifier() -> SearchUnifier:
    """获取全局搜索统一器"""
    global _unifier_instance
    if _unifier_instance is None:
        _unifier_instance = SearchUnifier()
    return _unifier_instance


def search(query: str, **kwargs) -> Dict:
    """快捷搜索"""
    return get_search_unifier().search(query, **kwargs).to_dict()
