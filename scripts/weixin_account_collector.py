#!/usr/bin/env python3
"""
微信公众号定向采集器 (Weixin Account Collector)
================================================
从 hot_accounts_config.py 导入 HOT_ACCOUNTS，提取所有行业分类下的 wechat 账号，
对每个账号通过搜狗微信搜索采集其最新文章，写入 raw_intelligence 表。

功能:
  1. 导入 HOT_ACCOUNTS，提取所有 wechat 账号
  2. 对每个账号使用搜狗微信搜索采集最新文章
  3. 写入 raw_intelligence 表 (DDB: /home/administrator/.hermes/intelligence.db)
  4. 去重逻辑 (url_hash)

技术要点:
  - 使用 urllib.request，不支持 requests
  - User-Agent 轮换
  - 每次请求间隔 1-2 秒
  - 编码处理 (中华网等特殊编码)
  - 最多处理 5 个账号 (避免被封)
"""

import re
import json
import time
import random
import hashlib
import ssl
import html as html_module
from datetime import datetime
from urllib.request import Request, urlopen
from urllib.parse import quote
from typing import List, Dict, Optional, Tuple
from pathlib import Path

# ============================================================
# 导入 HOT_ACCOUNTS 配置
# ============================================================
import sys
sys.path.insert(0, str(Path(__file__).parent.resolve()))
from hot_accounts_config import HOT_ACCOUNTS

# ============================================================
# 配置
# ============================================================
HERMES = Path("/home/administrator/.hermes")
DB_PATH = HERMES / "intelligence.db"

# MCP 采集器可用性检查
_MCP_COLLECTOR = None  # lazy import

def _try_import_mcp():
    global _MCP_COLLECTOR
    if _MCP_COLLECTOR is not None:
        return _MCP_COLLECTOR
    try:
        from wechat_mp_mcp_collector import is_mcp_ready, MCPWechatCollector
        ready, msg = is_mcp_ready()
        if ready:
            _MCP_COLLECTOR = MCPWechatCollector
            print(f"[MCP] {msg}")
        else:
            _MCP_COLLECTOR = False
            print(f"[MCP] {msg}")
    except Exception as e:
        _MCP_COLLECTOR = False
        print(f"[MCP] 模块加载失败: {e}")
    return _MCP_COLLECTOR

# User-Agent 轮换池
UA_POOL = [
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Linux; Android 13; SM-S908E) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.144 Mobile Safari/537.36",
]

# 每次最多处理的账号数 (避免被封)
MAX_ACCOUNTS_PER_RUN = 5

# 每个账号最多采集的文章数
MAX_ARTICLES_PER_ACCOUNT = 10

# 请求超时 (秒)
REQUEST_TIMEOUT = 15

# 请求间隔范围 (秒)
SLEEP_MIN = 1.0
SLEEP_MAX = 2.0


def _get_ua(seed: int = None) -> str:
    """轮换 User-Agent"""
    if seed is None:
        seed = int(time.time() * 1000)
    return UA_POOL[seed % len(UA_POOL)]


def _url_hash(url: str) -> str:
    """生成 URL 的 SHA256 哈希 (前 32 字符)"""
    return hashlib.sha256(url.encode('utf-8')).hexdigest()[:32]


def _decode_content(raw: bytes, content_type: str = "") -> str:
    """
    智能解码内容，处理中华网等特殊编码
    先尝试 content-type 指定编码，再检测 HTML meta charset，最后用 utf-8/GBK 兜底
    """
    # 1. 从 Content-Type 获取编码
    charset = None
    if 'charset=' in content_type.lower():
        charset = content_type.split('charset=')[-1].split(';')[0].strip().lower()

    # 2. 尝试从 HTML meta 检测编码
    if not charset:
        html_sample = raw[:2048].decode('utf-8', errors='replace') if len(raw) > 10 else ""
        meta_charset = re.search(r'<meta[^>]+charset\s*=\s*["\']?([^"\'\s>]+)', html_sample, re.IGNORECASE)
        if meta_charset:
            charset = meta_charset.group(1).strip().lower()

    # 3. 按检测到的编码解码
    encoding_attempts = []
    if charset:
        encoding_attempts.append(charset)

    # 常见中文编码兜底顺序
    encoding_attempts.extend(['utf-8', 'gbk', 'gb2312', 'gb18030', 'utf-16'])

    for enc in encoding_attempts:
        try:
            return raw.decode(enc, errors='replace')
        except (UnicodeDecodeError, LookupError):
            continue

    # 最终兜底
    return raw.decode('utf-8', errors='replace')


def _fetch(url: str, headers: dict = None, timeout: int = REQUEST_TIMEOUT,
           post_data: str = None) -> Tuple[str, str]:
    """
    简化的 HTTP 请求函数

    Returns:
        Tuple[str, str]: (解码后的文本, URL)
    """
    ua = _get_ua()

    h = {
        "User-Agent": ua,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Connection": "keep-alive",
    }
    if headers:
        h.update(headers)

    try:
        req = Request(url, data=post_data.encode() if post_data else None, headers=h)
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        with urlopen(req, timeout=timeout, context=ctx) as resp:
            raw = resp.read()
            ct = resp.headers.get('content-type', '')
            text = _decode_content(raw, ct)
            return text, resp.geturl()
    except Exception as e:
        return "", url


def _normalize_date(date_str: str) -> str:
    """标准化搜狗日期格式 -> ISO 格式
    修复：处理 <script>document.write(timeConvert('1604152401'))</script> 残留
    """
    if not date_str or date_str.strip() == '' or date_str == 'None':
        return datetime.now().strftime('%Y-%m-%dT00:00:00')

    date_str = date_str.strip()
    now = datetime.now()

    # ============================================================
    # 修复：处理旧数据中残留的 JavaScript
    # 搜狗微信返回的日期有时是 <script>document.write(timeConvert('timestamp'))</script>
    # ============================================================
    # 匹配 document.write(timeConvert('1234567890')) 时间戳
    m_ts = re.search(r"timeConvert\s*\(\s*['\"](\d+)['\"]\s*\)", date_str)
    if m_ts:
        ts = int(m_ts.group(1))
        dt = datetime.fromtimestamp(ts)
        return dt.strftime('%Y-%m-%dT%H:%M:%S')

    # 匹配纯时间戳数字 (10位以上)
    if date_str.replace('.', '').isdigit() and len(date_str) >= 10:
        try:
            ts = int(float(date_str))
            dt = datetime.fromtimestamp(ts)
            return dt.strftime('%Y-%m-%dT%H:%M:%S')
        except (ValueError, OSError):
            pass

    if '分钟前' in date_str:
        m = re.search(r'(\d+)', date_str)
        mins = int(m.group(1)) if m else 0
        dt = datetime.fromtimestamp(time.time() - mins * 60)
        return dt.strftime('%Y-%m-%dT%H:%M:%S')

    if '小时前' in date_str:
        m = re.search(r'(\d+)', date_str)
        hours = int(m.group(1)) if m else 0
        dt = datetime.fromtimestamp(time.time() - hours * 3600)
        return dt.strftime('%Y-%m-%dT%H:%M:%S')

    if '昨天' in date_str:
        dt = datetime.fromtimestamp(time.time() - 86400)
        return dt.strftime('%Y-%m-%dT00:00:00')

    if '前天' in date_str:
        dt = datetime.fromtimestamp(time.time() - 172800)
        return dt.strftime('%Y-%m-%dT00:00:00')

    # 常见格式: 2023-12-25 或 2023/12/25
    m = re.search(r'(\d{4})[-/](\d{1,2})[-/](\d{1,2})', date_str)
    if m:
        return f"{m.group(1)}-{m.group(2).zfill(2)}-{m.group(3).zfill(2)}T00:00:00"

    # 处理 GMT/RFC 格式: Wed, 20 May 2026 23:43:41 GMT
    m_rfc = re.search(r'(\w{3}),\s+(\d{1,2})\s+(\w{3})\s+(\d{4})\s+(\d{2}:\d{2}:\d{2})', date_str)
    if m_rfc:
        try:
            from datetime import datetime as dt_lib
            month_map = {'Jan':1,'Feb':2,'Mar':3,'Apr':4,'May':5,'Jun':6,
                         'Jul':7,'Aug':8,'Sep':9,'Oct':10,'Nov':11,'Dec':12}
            month = month_map.get(m_rfc.group(3), 1)
            dt = dt_lib(int(m_rfc.group(4)), month, int(m_rfc.group(2)),
                        *[int(x) for x in m_rfc.group(5).split(':')])
            return dt.strftime('%Y-%m-%dT%H:%M:%S')
        except:
            pass

    return date_str


def _extract_category(account_name: str) -> str:
    """根据账号名所属行业分类确定分类"""
    for cat, accounts in HOT_ACCOUNTS.items():
        wechat_list = accounts.get("wechat", [])
        if account_name in wechat_list:
            return cat
    return "General"


def _extract_tags_from_category(category: str) -> str:
    """根据分类生成标签"""
    tag_map = {
        "AI": "AI|科技",
        "IT数码": "数码|科技",
        "新能源汽车": "汽车|新能源",
        "军事": "军事|国际",
        "体育格斗": "体育",
        "美女摄影": "摄影|艺术",
        "游戏": "游戏|电竞",
        "科技": "科技|科学",
        "电影娱乐": "电影|娱乐",
        "开发": "开发|编程",
        "旅游美食": "旅游|美食",
    }
    return tag_map.get(category, "微信|综合")


def extract_wechat_accounts() -> List[Dict[str, str]]:
    """
    从 HOT_ACCOUNTS 提取所有微信账号

    Returns:
        List[Dict]: [{'name': '机器之心', 'category': 'AI'}, ...]
    """
    accounts = []
    for cat, platforms in HOT_ACCOUNTS.items():
        wechat_list = platforms.get("wechat", [])
        for name in wechat_list:
            accounts.append({
                'name': name,
                'category': cat,
            })
    return accounts


def collect_account_articles_sogou(account_name: str, category: str,
                                    max_articles: int = MAX_ARTICLES_PER_ACCOUNT) -> List[dict]:
    """
    通过搜狗微信搜索采集指定账号的最新文章

    Args:
        account_name: 微信公众号名称
        category: 行业分类
        max_articles: 最多采集文章数

    Returns:
        List[dict]: 符合 raw_intelligence 表结构的记录列表
    """
    items = []
    seen_urls = set()
    seen_titles = set()
    now_iso = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    tags = _extract_tags_from_category(category)

    try:
        # 搜狗微信搜索文章
        # type=2 搜索文章, query 为公众号名称
        search_url = f"https://weixin.sogou.com/weixin?type=2&query={quote(account_name)}&ie=utf8"

        headers = {
            "Referer": "https://weixin.sogou.com/",
            "User-Agent": _get_ua(),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }

        print(f"    [Sogou] Searching: {account_name}")
        text, final_url = _fetch(search_url, headers)

        # 检查是否被反爬
        if not text or len(text) < 200:
            print(f"    [Sogou] Empty response for {account_name}, trying Baidu backup...")
            return collect_account_articles_baidu(account_name, category, max_articles)

        if 'antispider' in text[:500] or '请输入验证码' in text[:2000] or '验证' in text[:1000]:
            print(f"    [Sogou] Anti-spider detected for {account_name}, trying Baidu backup...")
            return collect_account_articles_baidu(account_name, category, max_articles)

        # --- 解析搜索结果 ---
        # 提取标题 (在 <h3> 标签内的 <a> 链接文本)
        titles = re.findall(r'<h3[^>]*>.*?<a[^>]*>(.*?)</a>', text, re.DOTALL)

        # 提取链接
        link_blocks = re.findall(r'<h3[^>]*>.*?<a[^>]*href="([^"]+)"', text, re.DOTALL)
        links = []
        for lb in link_blocks:
            if lb.startswith('//'):
                lb = 'https:' + lb
            elif lb.startswith('/'):
                lb = 'https://weixin.sogou.com' + lb
            # 过滤图片/图标等链接
            if any(skip in lb for skip in ['.ico', '.png', '.gif', '.svg', '.jpg',
                                           'sogou.com/images', 'sogou.com/index']):
                continue
            links.append(lb)

        if not links:
            # 方法2: 直接匹配 mp.weixin.qq.com 链接
            links = re.findall(r'href="(https?://mp\.weixin\.qq\.com[^"]*)"', text)

        if not links:
            # 方法3: 匹配搜狗跳转链接
            links_sogou = re.findall(r'href="(/link\?[^"]*)"', text)
            links = [f"https://weixin.sogou.com{l}" for l in links_sogou]

        # 提取日期
        dates = re.findall(r'<span[^>]*class="s2"[^>]*>(.*?)</span>', text, re.DOTALL)
        if not dates:
            dates = re.findall(r'<span[^>]*class="[^"]*time[^"]*"[^>]*>(.*?)</span>', text, re.DOTALL)
        
        # 清理日期中的 script 标签 (搜狗有时返回 <script>document.write(...)</script>)
        cleaned_dates = []
        for d in dates:
            d_clean = re.sub(r'<script[^>]*>.*?</script>', '', d, flags=re.DOTALL).strip()
            cleaned_dates.append(d_clean)
        dates = cleaned_dates

        # 提取公众号名称 (作者)
        authors = re.findall(r'<span[^>]*class="s3"[^>]*>(.*?)</span>', text, re.DOTALL)
        if not authors:
            authors = re.findall(r'account_name_([^"\']+)', text)

        # 提取摘要
        summaries = re.findall(r'<p[^>]*class="txt-info"[^>]*>(.*?)</p>', text, re.DOTALL)

        # 逐条处理
        count = 0
        for i in range(min(len(titles), len(links) if links else 0)):
            if count >= max_articles:
                break

            # 清理标题
            title = re.sub(r'<[^>]+>', '', titles[i]).strip()
            title = html_module.unescape(title)
            title = re.sub(r'\s+', ' ', title)
            if len(title) < 4:
                continue
            if title in seen_titles:
                continue
            seen_titles.add(title)

            # 链接
            link = links[i] if i < len(links) else ''
            if not link:
                continue

            # 规范 URL
            if link.startswith('//'):
                link = 'https:' + link
            elif link.startswith('/'):
                link = 'https://weixin.sogou.com' + link

            if link in seen_urls:
                continue
            seen_urls.add(link)

            # 日期
            date = dates[i].strip() if i < len(dates) else ''
            pub_at = _normalize_date(date)
            
            # ⏰ 时效过滤：跳过超过7天的旧文章
            try:
                pub_dt = datetime.fromisoformat(pub_at) if 'T' in pub_at else None
                if pub_dt and (datetime.now() - pub_dt).days > 7:
                    count += 0  # 不计入成功计数
                    continue
            except:
                pass  # 日期解析失败不过滤，留给推送层处理

            # 作者 (公众号名称)
            author = authors[i].strip() if i < len(authors) else account_name
            author = re.sub(r'<[^>]+>', '', author).strip()
            author = html_module.unescape(author)

            # 内容摘要
            summary = summaries[i].strip() if i < len(summaries) else ''
            summary = re.sub(r'<[^>]+>', '', summary).strip()
            summary = html_module.unescape(summary)
            content = summary or f"来自微信公众号 [{account_name}] 的文章"

            # 构建记录
            item = {
                'title': title[:500],
                'content': content[:3000],
                'url': link,
                'source': 'sogou_wechat',
                'platform': 'weixin',
                'author': author[:100],
                'author_id': account_name[:100],
                'category': category,
                'tags': tags,
                'hot_score': 0.0,
                'view_count': 0,
                'like_count': 0,
                'collect_count': 0,
                'comment_count': 0,
                'share_count': 0,
                'published_at': pub_at,
                'collected_at': now_iso,
                'raw_data': '',
                'url_hash': _url_hash(link),
                'source_type': 'search',
            }
            items.append(item)
            count += 1

        print(f"    [Sogou] Found {count} articles for {account_name}")

    except Exception as e:
        print(f"    [Sogou] Error for {account_name}: {e}")
        # 搜狗失败时尝试百度备份
        if not items:
            return collect_account_articles_baidu(account_name, category, max_articles)

    return items


def collect_account_articles_baidu(account_name: str, category: str,
                                    max_articles: int = MAX_ARTICLES_PER_ACCOUNT) -> List[dict]:
    """
    备用方案: 通过百度搜索采集微信公众号文章
    搜索 site:mp.weixin.qq.com {账号名}

    Args:
        account_name: 微信公众号名称
        category: 行业分类
        max_articles: 最多采集文章数

    Returns:
        List[dict]: 符合 raw_intelligence 表结构的记录列表
    """
    items = []
    seen_urls = set()
    seen_titles = set()
    now_iso = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    tags = _extract_tags_from_category(category)

    try:
        # 百度搜索: site:mp.weixin.qq.com {账号名}
        query = f"site:mp.weixin.qq.com {account_name}"
        search_url = f"https://www.baidu.com/s?wd={quote(query)}&ie=utf-8"

        headers = {
            "Referer": "https://www.baidu.com/",
            "User-Agent": _get_ua(int(time.time())),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }

        print(f"    [Baidu] Searching: {account_name}")
        text, final_url = _fetch(search_url, headers)

        if not text or len(text) < 200:
            print(f"    [Baidu] Empty response for {account_name}")
            return items

        # 检查是否被反爬
        if 'antispider' in text[:500] or '验证码' in text[:1000]:
            print(f"    [Baidu] Anti-spider detected for {account_name}")
            return items

        # --- 解析百度搜索结果 ---
        # 提取标题和链接
        result_blocks = re.findall(
            r'<div[^>]*class="[^"]*result[^"]*"[^>]*>.*?</div>\s*</div>',
            text, re.DOTALL
        )

        if not result_blocks:
            # 方法2: 更通用的提取方式
            result_blocks = re.findall(
                r'<div[^>]*class="[^"]*c-container[^"]*"[^>]*>.*?</div>\s*</div>',
                text, re.DOTALL
            )

        if not result_blocks:
            # 方法3: 直接从页面提取标题+链接对
            titles = re.findall(r'<h3[^>]*>.*?<a[^>]*>(.*?)</a>', text, re.DOTALL)
            links = re.findall(r'<h3[^>]*>.*?<a[^>]*href="([^"]+)"', text, re.DOTALL)
            abstracts = re.findall(r'<div[^>]*class="[^"]*c-abstract[^"]*"[^>]*>(.*?)</div>', text, re.DOTALL)

            count = 0
            for i in range(min(len(titles), len(links))):
                if count >= max_articles:
                    break

                title = re.sub(r'<[^>]+>', '', titles[i]).strip()
                title = html_module.unescape(title)
                title = re.sub(r'\s+', ' ', title)
                if len(title) < 4 or title in seen_titles:
                    continue
                seen_titles.add(title)

                link = links[i]
                if link.startswith('//'):
                    link = 'https:' + link
                elif link.startswith('/'):
                    link = 'https://www.baidu.com' + link

                # 过滤非微信公众号链接
                if 'mp.weixin.qq.com' not in link and 'weixin.sogou.com' not in link:
                    continue

                if link in seen_urls:
                    continue
                seen_urls.add(link)

                abstract = abstracts[i].strip() if i < len(abstracts) else ''
                abstract = re.sub(r'<[^>]+>', '', abstract).strip()
                abstract = html_module.unescape(abstract)

                content = abstract or f"来自微信公众号 [{account_name}] 的文章"

                item = {
                    'title': title[:500],
                    'content': content[:3000],
                    'url': link,
                    'source': 'baidu_search_wechat',
                    'platform': 'weixin',
                    'author': account_name[:100],
                    'author_id': account_name[:100],
                    'category': category,
                    'tags': tags,
                    'hot_score': 0.0,
                    'view_count': 0,
                    'like_count': 0,
                    'collect_count': 0,
                    'comment_count': 0,
                    'share_count': 0,
                    'published_at': now_iso,
                    'collected_at': now_iso,
                    'raw_data': '',
                    'url_hash': _url_hash(link),
                    'source_type': 'search',
                }
                items.append(item)
                count += 1

            print(f"    [Baidu] Found {count} articles for {account_name}")
            return items

        # 逐块解析
        count = 0
        for block in result_blocks:
            if count >= max_articles:
                break

            # 提取标题
            title_match = re.search(r'<h3[^>]*>.*?<a[^>]*>(.*?)</a>', block, re.DOTALL)
            if not title_match:
                continue
            title = re.sub(r'<[^>]+>', '', title_match.group(1)).strip()
            title = html_module.unescape(title)
            title = re.sub(r'\s+', ' ', title)
            if len(title) < 4 or title in seen_titles:
                continue
            seen_titles.add(title)

            # 提取链接
            link_match = re.search(r'<a[^>]*href="([^"]+)"', block, re.DOTALL)
            if not link_match:
                continue
            link = link_match.group(1)
            if link.startswith('//'):
                link = 'https:' + link
            elif link.startswith('/'):
                link = 'https://www.baidu.com' + link

            # 过滤非微信公众号链接
            if 'mp.weixin.qq.com' not in link and 'weixin.sogou.com' not in link:
                continue

            if link in seen_urls:
                continue
            seen_urls.add(link)

            # 提取摘要
            abstract_match = re.search(r'<div[^>]*class="[^"]*c-abstract[^"]*"[^>]*>(.*?)</div>', block, re.DOTALL)
            abstract = ''
            if abstract_match:
                abstract = re.sub(r'<[^>]+>', '', abstract_match.group(1)).strip()
                abstract = html_module.unescape(abstract)

            content = abstract or f"来自微信公众号 [{account_name}] 的文章"

            item = {
                'title': title[:500],
                'content': content[:3000],
                'url': link,
                'source': 'baidu_search_wechat',
                'platform': 'weixin',
                'author': account_name[:100],
                'author_id': account_name[:100],
                'category': category,
                'tags': tags,
                'hot_score': 0.0,
                'view_count': 0,
                'like_count': 0,
                'collect_count': 0,
                'comment_count': 0,
                'share_count': 0,
                'published_at': now_iso,
                'collected_at': now_iso,
                'raw_data': '',
                'url_hash': _url_hash(link),
                'source_type': 'search',
            }
            items.append(item)
            count += 1

        print(f"    [Baidu] Found {count} articles for {account_name}")

    except Exception as e:
        print(f"    [Baidu] Error for {account_name}: {e}")

    return items


def _ensure_table(db) -> None:
    """确保 raw_intelligence 表存在"""
    db.execute("""
        CREATE TABLE IF NOT EXISTS raw_intelligence (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            content TEXT,
            url TEXT,
            source TEXT,
            platform TEXT,
            author TEXT,
            author_id TEXT,
            category TEXT,
            tags TEXT,
            hot_score REAL DEFAULT 0.0,
            view_count INTEGER DEFAULT 0,
            like_count INTEGER DEFAULT 0,
            collect_count INTEGER DEFAULT 0,
            comment_count INTEGER DEFAULT 0,
            share_count INTEGER DEFAULT 0,
            published_at TEXT,
            collected_at TEXT,
            raw_data TEXT,
            url_hash TEXT UNIQUE,
            source_type TEXT
        )
    """)


def _insert_batch(items: List[dict]) -> int:
    """
    批量写入 raw_intelligence 表 (含去重)

    Args:
        items: 采集到的记录列表

    Returns:
        int: 新写入的记录数
    """
    import sqlite3

    if not items:
        return 0

    new_count = 0
    skip_count = 0
    now_iso = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    try:
        db = sqlite3.connect(str(DB_PATH), timeout=30)
        _ensure_table(db)

        for item in items:
            try:
                url_h = item.get('url_hash') or _url_hash(item.get('url', ''))

                # 先检查是否已存在 (url_hash 去重)
                existing = db.execute(
                    "SELECT id FROM raw_intelligence WHERE url_hash = ?", (url_h,)
                ).fetchone()

                if existing:
                    skip_count += 1
                    continue

                db.execute("""
                    INSERT INTO raw_intelligence
                    (title, content, url, source, platform, author, author_id,
                     category, tags, hot_score, view_count, like_count,
                     collect_count, comment_count, share_count,
                     published_at, collected_at, raw_data, url_hash, source_type)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    item.get('title', '')[:500],
                    item.get('content', '')[:3000],
                    item.get('url', ''),
                    item.get('source', 'weixin_account_collector'),
                    item.get('platform', 'weixin'),
                    item.get('author', '')[:100],
                    item.get('author_id', '')[:100],
                    item.get('category', 'General'),
                    item.get('tags', '微信|综合'),
                    float(item.get('hot_score', 0.0)),
                    int(item.get('view_count', 0)),
                    int(item.get('like_count', 0)),
                    int(item.get('collect_count', 0)),
                    int(item.get('comment_count', 0)),
                    int(item.get('share_count', 0)),
                    item.get('published_at', now_iso),
                    item.get('collected_at', now_iso),
                    item.get('raw_data', ''),
                    url_h,
                    item.get('source_type', 'search'),
                ))
                db.commit()
                new_count += 1

            except sqlite3.IntegrityError:
                # url_hash 唯一约束冲突
                skip_count += 1
                continue
            except Exception as e:
                continue

        db.close()

    except Exception as e:
        print(f"  [DB] Error: {e}")

    if skip_count > 0:
        print(f"  [DB] Skipped {skip_count} duplicates (url_hash)")
    return new_count


# ============================================================
# 主入口函数
# ============================================================

def collect_weixin_accounts() -> List[dict]:
    """
    微信公众号定向采集主函数

    从 HOT_ACCOUNTS 提取所有 wechat 账号，对每个账号通过
    搜狗微信搜索 (备用: 百度搜索) 采集其最新文章。

    Returns:
        List[dict]: 采集到的记录列表
    """
    print("=" * 60)
    print("  微信公众号定向采集器 (Weixin Account Collector)")
    print(f"  时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    # 1. 提取所有微信账号
    all_accounts = extract_wechat_accounts()
    print(f"\n  共发现 {len(all_accounts)} 个微信账号 (来自 {len(HOT_ACCOUNTS)} 个行业分类)")

    # 显示按行业分布
    cat_counts = {}
    for acc in all_accounts:
        cat_counts[acc['category']] = cat_counts.get(acc['category'], 0) + 1
    for cat, cnt in cat_counts.items():
        print(f"    {cat}: {cnt} 个账号")

    # 2. 限制本次处理的账号数 (随机选取, 分散采样)
    if len(all_accounts) > MAX_ACCOUNTS_PER_RUN:
        random.seed(int(time.time()))
        selected = random.sample(all_accounts, MAX_ACCOUNTS_PER_RUN)
        print(f"\n  本次处理: {MAX_ACCOUNTS_PER_RUN}/{len(all_accounts)} 个账号 (随机选取)")
    else:
        selected = all_accounts
        print(f"\n  本次处理: {len(selected)}/{len(all_accounts)} 个账号")

    print(f"\n  选定账号:")
    for acc in selected:
        print(f"    [{acc['category']}] {acc['name']}")

    # 3. 逐账号采集
    all_items = []
    errors = []

    # 打乱顺序, 降低被检测风险
    random.shuffle(selected)

    # 先尝试 MCP 采集 (如果可用)
    mcp_available = _try_import_mcp()
    mcp_collector = None
    
    if mcp_available:
        try:
            mcp_collector = mcp_available()
            print(f"\n  [主模式] 使用 MCP (mp.weixin.qq.com API) 采集")
        except Exception as e:
            print(f"\n  [MCP] 初始化失败, 降级到搜狗微信: {e}")
            mcp_collector = None

    for idx, acc in enumerate(selected):
        print(f"\n  [{idx+1}/{len(selected)}] 采集: {acc['name']} ({acc['category']})")

        items = []

        # 策略1: MCP 采集 (稳定、准确、不受反爬影响)
        if mcp_collector:
            try:
                items = mcp_collector.collect_account_articles(
                    acc['name'], acc['category'], MAX_ARTICLES_PER_ACCOUNT
                )
            except Exception as e:
                print(f"    [MCP] 失败: {e}")
                items = []

        # 策略2: 搜狗微信搜索 (备用)
        if not items:
            print(f"    -> MCP 无结果, 尝试搜狗微信搜索...")
            items = collect_account_articles_sogou(acc['name'], acc['category'])

        # 策略3: 百度搜索 (最后备用)
        if not items:
            print(f"    -> 搜狗无结果, 尝试百度搜索...")
            items = collect_account_articles_baidu(acc['name'], acc['category'])

        if items:
            all_items.extend(items)
            print(f"    -> 采集到 {len(items)} 篇文章")
        else:
            print(f"    -> 未采集到文章")
            errors.append(acc['name'])

        # 请求间隔 1-2 秒
        if idx < len(selected) - 1:
            sleep_time = SLEEP_MIN + random.random() * (SLEEP_MAX - SLEEP_MIN)
            print(f"    等待 {sleep_time:.1f} 秒...")
            time.sleep(sleep_time)

    # 4. 汇总
    print(f"\n{'=' * 60}")
    print(f"  采集完成!")
    print(f"  总采集: {len(all_items)} 条")
    if errors:
        print(f"  失败: {len(errors)} 个账号: {', '.join(errors[:5])}")
    print(f"{'=' * 60}")

    return all_items


def main():
    """主入口: 采集并写入数据库"""
    items = collect_weixin_accounts()

    if items:
        new_count = _insert_batch(items)
        print(f"\n  数据库写入: 共 {len(items)} 条, 新写入 {new_count} 条 (去重跳过 {len(items) - new_count} 条)")
    else:
        print("\n  未采集到任何内容")

    print("=" * 60)
    return len(items)


if __name__ == "__main__":
    main()
