#!/usr/bin/env python3
"""
微信公众号MCP采集模块
======================
通过 mp.weixin.qq.com 订阅号接口采集公众号文章。
依赖 MCP 方案的 WeixinClient 实现扫码登录 + API 调用。

使用流程:
  1. 首次使用需运行 wechat-mp-mcp-login-auto 扫码登录
  2. 登录后 auth 保存在 ~/.config/wechat-mp-mcp/auth.json
  3. 本模块自动复用该会话

优势:
  - 不受搜狗微信反爬影响
  - 直接调用微信公众号后台API，数据可靠
  - 可稳定获取50+条/次
  - published_at 为准确时间戳

用法:
  from wechat_mp_mcp_collector import MCPWechatCollector
  collector = MCPWechatCollector()
  articles = collector.collect_account_articles("机器之心", "AI", max_articles=50)
"""

import sys
import time
import random
import re
import hashlib
import json
from datetime import datetime, timezone
from typing import List, Dict, Optional, Tuple
from pathlib import Path

# ============================================================
# 导入 MCP 方案的 WeixinClient
# ============================================================
MCP_PATH = Path(__file__).parent.resolve() / "collectors" / "wechat-mp-mcp"
sys.path.insert(0, str(MCP_PATH / "src"))

# 导入 hot_accounts_config
sys.path.insert(0, str(Path(__file__).parent.resolve()))
from hot_accounts_config import HOT_ACCOUNTS

try:
    from wechat_mp_mcp.client import WeixinClient, WeixinApiError
    from wechat_mp_mcp.auth import AuthError, load_auth
    from wechat_mp_mcp.storage import get_today_quota, increment_today_quota
    MCP_AVAILABLE = True
except ImportError as e:
    MCP_AVAILABLE = False
    print(f"[MCP-Warning] wechat_mp_mcp 模块未安装: {e}")
    WeixinClient = None


# ============================================================
# 配置
# ============================================================
HERMES = Path("/home/administrator/.hermes")
DB_PATH = HERMES / "intelligence.db"

# 每个账号最多采集的文章数
MAX_ARTICLES_PER_ACCOUNT = 50

# MCP 每日限额
MCP_DAILY_LIMIT = 150

# 请求间隔 (MCP 自己有 jitter, 这里额外加一层)
SLEEP_MIN = 0.5
SLEEP_MAX = 1.5


def _url_hash(url: str) -> str:
    """生成 URL 的 SHA256 哈希 (前 32 字符)"""
    return hashlib.sha256(url.encode('utf-8')).hexdigest()[:32]


def _extract_timestamp_from_script(date_str: str) -> Optional[str]:
    """
    从搜狗返回的 <script>document.write(timeConvert('1604152401'))</script> 中提取时间戳
    返回 ISO 格式日期字符串
    """
    if not date_str:
        return None
    
    # 匹配 document.write(timeConvert('1234567890'))
    m = re.search(r"timeConvert\s*['\"](\d+)['\"]", date_str)
    if m:
        ts = int(m.group(1))
        dt = datetime.fromtimestamp(ts)
        return dt.strftime('%Y-%m-%dT%H:%M:%S')
    
    # 匹配纯时间戳
    if date_str.strip().isdigit() and len(date_str.strip()) >= 10:
        ts = int(date_str.strip())
        dt = datetime.fromtimestamp(ts)
        return dt.strftime('%Y-%m-%dT%H:%M:%S')
    
    return None


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


def is_mcp_ready() -> Tuple[bool, str]:
    """
    检查 MCP 登录状态
    
    Returns:
        Tuple[bool, str]: (是否可用, 状态描述)
    """
    if not MCP_AVAILABLE:
        return False, "MCP 模块未安装"
    
    auth_path = Path.home() / ".config" / "wechat-mp-mcp" / "auth.json"
    if not auth_path.exists():
        return False, f"未登录, 请先运行: wechat-mp-mcp-login-auto (扫码登录)"
    
    try:
        auth = load_auth()
        if not auth.token or not auth.cookies:
            return False, "登录信息不完整"
        
        # 检查 cookie 过期 (典型 1-2h, 但放宽检查)
        age = time.time() - auth.saved_at
        if age > 7200:  # 超过 2 小时
            return True, "登录可能已过期(>2h)，建议重新扫码"
        
        return True, f"已登录 (token有效, {len(auth.cookies)} cookies, 已保存{int(age/60)}分钟)"
    except Exception as e:
        return False, f"登录检查失败: {e}"


class MCPWechatCollector:
    """
    通过 mp.weixin.qq.com 订阅号接口采集公众号文章
    
    支持:
    - 搜索公众号获取 fakeid
    - 拉取文章列表 (最新50+条)
    - 解析发布时间 (准确时间戳)
    - 写入 raw_intelligence 表
    """
    
    def __init__(self):
        if not MCP_AVAILABLE:
            raise ImportError("wechat_mp_mcp 模块未安装，无法使用 MCP 采集器")
        
        ready, msg = is_mcp_ready()
        if not ready:
            raise RuntimeError(f"MCP 未就绪: {msg}")
        
        self._client = None
        self._daily_quota_check()
    
    def _daily_quota_check(self):
        """检查当日配额"""
        try:
            used = get_today_quota()
            if used >= MCP_DAILY_LIMIT:
                print(f"[MCP-Warning] 今日 API 配额已用 {used}/{MCP_DAILY_LIMIT}")
        except Exception:
            pass  # quota check 失败不阻塞
    
    def _get_client(self) -> WeixinClient:
        """获取或创建 WeixinClient (带重连)"""
        if self._client is None:
            try:
                self._client = WeixinClient()
            except AuthError as e:
                print(f"[MCP-Error] 认证失败，请重新扫码: {e}")
                raise
        return self._client
    
    def close(self):
        """关闭客户端连接"""
        if self._client:
            try:
                self._client.close()
            except Exception:
                pass
            self._client = None
    
    def __enter__(self):
        return self
    
    def __exit__(self, *args):
        self.close()
    
    def search_account(self, account_name: str) -> Optional[Dict]:
        """
        搜索公众号，返回 fakeid 等信息
        
        Args:
            account_name: 公众号名称
            
        Returns:
            Optional[Dict]: {fakeid, nickname, alias, ...} 或 None
        """
        try:
            client = self._get_client()
            accounts = client.search_account(query=account_name, begin=0, count=5)
            
            if not accounts:
                print(f"    [MCP-Search] 未找到公众号: {account_name}")
                return None
            
            # 尝试精确匹配
            for acc in accounts:
                if acc.nickname == account_name:
                    print(f"    [MCP-Search] 找到: {acc.nickname} (fakeid={acc.fakeid})")
                    return {
                        'fakeid': acc.fakeid,
                        'nickname': acc.nickname,
                        'alias': acc.alias,
                    }
            
            # 模糊匹配：返回第一个
            acc = accounts[0]
            print(f"    [MCP-Search] 模糊匹配: '{account_name}' -> {acc.nickname} (fakeid={acc.fakeid})")
            return {
                'fakeid': acc.fakeid,
                'nickname': acc.nickname,
                'alias': acc.alias,
            }
            
        except AuthError as e:
            print(f"    [MCP-Error] 认证过期: {e}")
            return None
        except WeixinApiError as e:
            print(f"    [MCP-Error] API 错误 [{e.code}]: {e.message}")
            return None
        except Exception as e:
            print(f"    [MCP-Error] 搜索失败: {e}")
            return None
    
    def list_articles(self, fakeid: str, max_articles: int = 50) -> List[Dict]:
        """
        拉取公众号文章列表
        
        使用分页方式采集，每页 5 条，可稳定获取 50+ 条/次
        
        Args:
            fakeid: 公众号 fakeid
            max_articles: 最多采集文章数
            
        Returns:
            List[Dict]: 文章元数据列表
        """
        articles = []
        seen_links = set()
        begin = 0
        page_size = 5  # 固定每页5条，MCP有jitter但此处用固定值更可控
        max_pages = (max_articles // page_size) + 3  # 多取几页确保足够
        page_count = 0
        
        print(f"    [MCP-Articles] 开始采集 (fakeid={fakeid[:8]}..., max={max_articles})")
        
        try:
            client = self._get_client()
            
            for page in range(max_pages):
                if len(articles) >= max_articles:
                    break
                
                page_count += 1
                
                # 计算本次请求的数量（最后几页可能不足）
                remaining = max_articles - len(articles)
                count = min(page_size, remaining)
                
                try:
                    page_articles, total = client.list_articles(
                        fakeid=fakeid, begin=begin, count=count
                    )
                except AuthError:
                    print(f"    [MCP-Error] 认证过期，停止采集")
                    break
                except WeixinApiError as e:
                    print(f"    [MCP-Error] API 错误 [{e.code}]: {e.message}")
                    break
                except Exception as e:
                    print(f"    [MCP-Error] 分页请求失败: {e}")
                    time.sleep(2)
                    continue
                
                if not page_articles:
                    print(f"    [MCP-Articles] 第{page+1}页无更多文章，结束")
                    break
                
                new_count = 0
                for a in page_articles:
                    if a.link in seen_links:
                        continue
                    seen_links.add(a.link)
                    
                    # 转换更新时间
                    pub_at = datetime.fromtimestamp(a.update_time).strftime('%Y-%m-%dT%H:%M:%S')
                    
                    articles.append({
                        'title': a.title,
                        'link': a.link,
                        'update_time': a.update_time,
                        'update_time_iso': pub_at,
                        'digest': a.digest,
                        'cover': a.cover,
                        'aid': a.aid,
                    })
                    new_count += 1
                
                print(f"    [MCP-Articles] 第{page+1}页: {new_count} 篇新文章 (累计 {len(articles)}/{total})")
                
                begin += len(page_articles)
                
                # 如果返回的文章数少于请求数，说明已到末尾
                if len(page_articles) < count:
                    print(f"    [MCP-Articles] 已到列表末尾")
                    break
                
                # 请求间隔 (1-2 秒随机)
                if page < max_pages - 1 and len(articles) < max_articles:
                    delay = SLEEP_MIN + random.random() * (SLEEP_MAX - SLEEP_MIN)
                    time.sleep(delay)
            
            print(f"    [MCP-Articles] 完成: 共获取 {len(articles)} 篇 (分 {page_count} 页)")
            return articles
            
        except Exception as e:
            print(f"    [MCP-Articles] 采集异常: {e}")
            return articles
    
    def collect_account_articles(
        self, 
        account_name: str, 
        category: str = "General",
        max_articles: int = MAX_ARTICLES_PER_ACCOUNT
    ) -> List[dict]:
        """
        采集指定公众号文章，返回 raw_intelligence 格式
        
        Args:
            account_name: 公众号名称
            category: 行业分类
            max_articles: 最多采集文章数
            
        Returns:
            List[dict]: raw_intelligence 格式记录列表
        """
        items = []
        now_iso = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        tags = _extract_tags_from_category(category)
        
        print(f"    [MCP] 处理公众号: {account_name}")
        
        # 1. 搜索公众号获取 fakeid
        account_info = self.search_account(account_name)
        if not account_info:
            print(f"    [MCP] 找不到公众号 '{account_name}'")
            return items
        
        fakeid = account_info['fakeid']
        
        # 2. 拉取文章列表
        articles = self.list_articles(fakeid, max_articles)
        if not articles:
            print(f"    [MCP] 未获取到文章")
            return items
        
        # 3. 转换为 raw_intelligence 格式
        seen_urls = set()
        seen_titles = set()
        count = 0
        
        for art in articles:
            if count >= max_articles:
                break
            
            title = art['title'].strip()
            if len(title) < 4 or title in seen_titles:
                continue
            seen_titles.add(title)
            
            link = art['link']
            if link in seen_urls:
                continue
            seen_urls.add(link)
            
            pub_at = art['update_time_iso']
            
            # 时效过滤：跳过超过7天的旧文章
            try:
                pub_dt = datetime.fromisoformat(pub_at) if 'T' in pub_at else None
                if pub_dt and (datetime.now() - pub_dt).days > 7:
                    continue
            except:
                pass
            
            # 摘要
            summary = art.get('digest', '').strip()
            content = summary or f"来自微信公众号 [{account_name}] 的文章"
            
            item = {
                'title': title[:500],
                'content': content[:3000],
                'url': link,
                'source': 'mcp_wechat',
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
                'published_at': pub_at,
                'collected_at': now_iso,
                'raw_data': json.dumps(art, ensure_ascii=False),
                'url_hash': _url_hash(link),
                'source_type': 'mp_api',
            }
            items.append(item)
            count += 1
        
        print(f"    [MCP] 完成: 采集到 {len(items)} 篇文章 (来自 {account_name})")
        return items


# ============================================================
# 独立运行入口
# ============================================================

def extract_wechat_accounts() -> List[Dict[str, str]]:
    """从 HOT_ACCOUNTS 提取所有微信账号"""
    accounts = []
    for cat, platforms in HOT_ACCOUNTS.items():
        wechat_list = platforms.get("wechat", [])
        for name in wechat_list:
            accounts.append({'name': name, 'category': cat})
    return accounts


def collect_weixin_accounts_mcp(
    max_accounts: int = 5,
    max_articles_per_account: int = MAX_ARTICLES_PER_ACCOUNT
) -> List[dict]:
    """
    全流程：提取账号 -> MCP 采集 -> 返回结果
    
    Args:
        max_accounts: 最多处理账号数
        max_articles_per_account: 每个账号最多采集文章数
        
    Returns:
        List[dict]: 采集结果
    """
    print("=" * 60)
    print("  微信公众号 MCP 采集器")
    print(f"  时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    
    # 检查 MCP 就绪
    ready, msg = is_mcp_ready()
    if not ready:
        print(f"\n  [MCP] {msg}")
        print("  [MCP] 请运行以下命令扫码登录:")
        print("    cd /home/administrator/.hermes/scripts/collectors/wechat-mp-mcp")
        print("    .venv/bin/wechat-mp-mcp-login-auto")
        return []
    
    print(f"\n  [MCP] {msg}")
    
    # 提取账号
    all_accounts = extract_wechat_accounts()
    print(f"\n  共发现 {len(all_accounts)} 个微信账号")
    
    # 随机选取
    if len(all_accounts) > max_accounts:
        random.seed(int(time.time()))
        selected = random.sample(all_accounts, max_accounts)
    else:
        selected = all_accounts
    
    print(f"\n  本次处理: {len(selected)} 个账号")
    for acc in selected:
        print(f"    [{acc['category']}] {acc['name']}")
    
    # 采集
    all_items = []
    errors = []
    random.shuffle(selected)
    
    try:
        collector = MCPWechatCollector()
        
        for idx, acc in enumerate(selected):
            print(f"\n  [{idx+1}/{len(selected)}] 采集: {acc['name']} ({acc['category']})")
            
            try:
                items = collector.collect_account_articles(
                    acc['name'], acc['category'], max_articles_per_account
                )
                if items:
                    all_items.extend(items)
                    print(f"    -> 采集到 {len(items)} 篇文章")
                else:
                    print(f"    -> 未采集到文章")
                    errors.append(acc['name'])
            except Exception as e:
                print(f"    -> 采集失败: {e}")
                errors.append(acc['name'])
            
            # 请求间隔
            if idx < len(selected) - 1:
                delay = SLEEP_MIN + random.random() * (SLEEP_MAX - SLEEP_MIN)
                print(f"    等待 {delay:.1f} 秒...")
                time.sleep(delay)
        
        collector.close()
    
    except RuntimeError as e:
        print(f"\n  [MCP] 初始化失败: {e}")
        return []
    
    # 汇总
    print(f"\n{'=' * 60}")
    print(f"  采集完成!")
    print(f"  总采集: {len(all_items)} 条")
    if errors:
        print(f"  失败: {len(errors)} 个账号: {', '.join(errors[:5])}")
    print(f"{'=' * 60}")
    
    return all_items


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
    """批量写入 raw_intelligence 表 (含去重)"""
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
                    item.get('source', 'mcp_wechat'),
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
                    item.get('source_type', 'mp_api'),
                ))
                db.commit()
                new_count += 1
                
            except sqlite3.IntegrityError:
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


def main():
    """主入口: MCP 采集并写入数据库"""
    items = collect_weixin_accounts_mcp()
    
    if items:
        new_count = _insert_batch(items)
        print(f"\n  数据库写入: 共 {len(items)} 条, 新写入 {new_count} 条")
    else:
        print("\n  未采集到任何内容")
    
    print("=" * 60)
    return len(items)


if __name__ == "__main__":
    main()
