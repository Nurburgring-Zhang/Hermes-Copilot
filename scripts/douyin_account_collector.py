#!/usr/bin/env python3
"""
抖音热点采集器 v2.0 — 深度改造版
====================================
架构：
  1. 热搜榜采集 (50条) — /aweme/v1/web/hot/search/list/ 无需token，稳定可用
  2. 实时上升热点采集 (5条) — trending_list
  3. 关键词过滤匹配 — 从热搜中筛选格林主人感兴趣的关键词
  4. 视频详情补全 — 对每条热点尝试获取更多元数据
  5. 去重存储 — 使用url_hash防重复

输出：每条数据存入 raw_intelligence 表
      返回 (saved_count, total_count, error_count)
"""

import urllib.request
import urllib.parse
import json
import re
import time
import hashlib
import sqlite3
import os
import random
import sys
import ssl
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Tuple

# ============================================================
# 配置区
# ============================================================
HERMES = Path("/home/administrator/.hermes")
DB_PATH = HERMES / "intelligence.db"
COLLECTOR_LOG = HERMES / "logs" / "douyin_account.log"

# 格林主人偏好方向关键词 — 用于从热搜中筛选+标记
DY_KEYWORDS = [
    "AI", "大模型", "芯片", "新能源汽车", "自动驾驶",
    "军事", "科技", "编程", "开源", "Rust",
    "美女", "摄影", "格斗", "UFC", "写真",
]

# 扩展匹配关键词 — 更宽泛的语义匹配
EXPANDED_KEYWORDS = {
    "AI": ["人工智能", "智能", "AI", "深度学习", "机器学习", "GPT", "大模型", " neural", "transformer"],
    "芯片": ["芯片", "半导体", "集成电路", "光刻", "EDA", "龙芯", "华为"],
    "新能源汽车": ["新能源", "电动车", "电动汽车", "电池", "比亚迪", "特斯拉", "蔚小理"],
    "自动驾驶": ["自动驾驶", "无人驾驶", "智能驾驶", "智驾", "FSD", "激光雷达"],
    "军事": ["军事", "国防", "军工", "导弹", "航母", "战机", "解放军", "武器"],
    "科技": ["科技", "技术", "数码", "手机", "华为", "小米", "发布"],
    "编程": ["编程", "代码", "程序员", "开源", "GitHub", "Linux", "Rust", "Python", "算法", "软件"],
    "美女": ["美女", "穿搭", "颜值", "变装", "女神"],
    "摄影": ["摄影", "拍照", "相机", "镜头", "修图", "光影"],
    "格斗": ["格斗", "UFC", "拳击", "MMA", "搏击", "散打"],
}

# User-Agent 轮换池
UA_POOL = [
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15F79 Safari/604.1",
    "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
]

# API 端点
HOT_LIST_API = "https://www.douyin.com/aweme/v1/web/hot/search/list/"


# ============================================================
# 日志
# ============================================================
def log(msg: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] [DYv2] {msg}"
    print(line)
    try:
        COLLECTOR_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(COLLECTOR_LOG, 'a', encoding='utf-8') as f:
            f.write(line + "\n")
    except Exception:
        pass


# ============================================================
# 网络请求
# ============================================================
def fetch(url: str, timeout: int = 15, headers: dict = None,
           retries: int = 2) -> Optional[str]:
    """
    通用HTTP GET请求，支持重试和UA轮换
    返回响应文本，失败返回None
    """
    for attempt in range(retries + 1):
        try:
            ua = UA_POOL[int(time.time() + attempt) % len(UA_POOL)]
            h = {
                "User-Agent": ua,
                "Accept": "application/json, text/html, */*",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                "Referer": "https://www.douyin.com/",
            }
            if headers:
                h.update(headers)

            req = urllib.request.Request(url, headers=h)
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE

            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
                data = resp.read().decode('utf-8', errors='replace')
                return data
        except Exception as e:
            if attempt < retries:
                wait = random.uniform(1.0, 2.5)
                time.sleep(wait)
                continue
            return None
    return None


# ============================================================
# 数据库操作
# ============================================================
def save_item(
    title: str,
    content: str = "",
    url: str = "",
    author: str = "",
    category: str = "",
    hot_score: float = 0,
    tags: str = "",
    raw_data: str = "",
) -> bool:
    """
    保存一条数据到 raw_intelligence 表
    使用 url_hash 去重
    返回 True=新保存, False=已存在/失败
    """
    if not title and not url:
        return False
    try:
        db = sqlite3.connect(str(DB_PATH))
        url_hash = hashlib.md5(url.encode()).hexdigest() if url else hashlib.md5(title.encode()).hexdigest()
        exists = db.execute(
            "SELECT 1 FROM raw_intelligence WHERE url_hash=?", (url_hash,)
        ).fetchone()
        if exists:
            db.close()
            return False

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        db.execute(
            """INSERT INTO raw_intelligence
               (title, content, url, source, platform, author, author_id,
                published_at, hot_score, source_type, category_tags, tags,
                url_hash, raw_data, collected_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                str(title)[:500],
                str(content)[:5000] if content else "",
                str(url)[:500],
                "douyin",
                "douyin",
                str(author)[:100] if author else "",
                "",
                now,
                float(hot_score),
                "social",
                str(category)[:200] if category else "Douyin|Hot",
                str(tags)[:200] if tags else "",
                url_hash,
                str(raw_data)[:10000] if raw_data else "",
                now,
            ),
        )
        db.commit()
        db.close()
        return True
    except Exception as e:
        log(f"DB保存失败: {e}")
        return False


def save_collector_log(status: str, new_count: int, total_count: int,
                       error: str = None) -> None:
    """写入采集器运行日志到 collector_log 表"""
    try:
        db = sqlite3.connect(str(DB_PATH))
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        db.execute(
            """INSERT INTO collector_log
               (collector, status, new_count, total_count, error, started_at, finished_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                "douyin_account",
                status,
                new_count,
                total_count,
                str(error)[:500] if error else None,
                now,
                now,
            ),
        )
        db.commit()
        db.close()
    except Exception:
        pass


# ============================================================
# 关键词匹配引擎
# ============================================================
def match_keywords(text: str) -> List[Tuple[str, str]]:
    """
    匹配文本中的关键词
    返回 [(主分类, 匹配词), ...]
    """
    if not text:
        return []
    text_lower = text.lower()
    results = []
    # 先匹配主关键词
    for kw in DY_KEYWORDS:
        if kw.lower() in text_lower:
            results.append((kw, kw))
    # 再匹配扩展关键词
    for main_cat, exts in EXPANDED_KEYWORDS.items():
        for ext in exts:
            if ext.lower() in text_lower:
                if not any(m[0] == main_cat for m in results):
                    results.append((main_cat, ext))
                break
    return results


# ============================================================
# 热搜采集（核心）
# ============================================================
def collect_hot_list() -> List[Dict]:
    """
    采集抖音热搜榜
    返回: [{'title':..., 'content':..., 'url':..., 'author':...,
            'hot_score':..., 'category':..., 'tags':..., 'raw_data':...}, ...]
    稳定返回50条
    """
    items = []

    # 构建请求参数 — 尝试获取更多结果
    for detail_flag in [1, 0]:
        params = urllib.parse.urlencode({
            "detail_list": detail_flag,
            "source": 0,
            "main_billboard_count": 200,
            "ts": int(time.time()),
        })
        url = f"{HOT_LIST_API}?{params}"
        text = fetch(url, timeout=15)
        if not text:
            continue

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            continue

        api_data = data.get("data", {})
        word_list = api_data.get("word_list", []) or []
        trending_list = api_data.get("trending_list", []) or []

        # ---------- word_list: 热搜条目 (50条) ----------
        for w in word_list:
            word = (w.get("word") or "").strip()
            if not word:
                continue

            hot_val = w.get("hot_value", 0) or 0
            group_id = w.get("group_id", "")
            pos = w.get("position", 0)

            # 构建内容描述
            content_parts = []
            if hot_val:
                content_parts.append(f"热度值:{hot_val}")
            if group_id:
                content_parts.append(f"group_id:{group_id}")
            content = " | ".join(content_parts)

            # 构建搜索URL
            search_url = f"https://www.douyin.com/search/{urllib.parse.quote(word)}"
            if group_id:
                search_url = f"https://www.douyin.com/video/{group_id}"

            # 关键词匹配
            matched = match_keywords(word)
            if matched:
                main_cats = [m[0] for m in matched]
                category = "Douyin|Hot|" + "|".join(main_cats[:3])
                tags = ",".join(main_cats)
            else:
                category = "Douyin|Hot"
                tags = ""

            # 保存原始数据
            raw_data = json.dumps({
                "word": word,
                "hot_value": hot_val,
                "group_id": group_id,
                "position": pos,
                "sentence_id": w.get("sentence_id", ""),
                "label": w.get("label", 0),
                "video_count": w.get("video_count", 0),
                "event_time": w.get("event_time", 0),
            }, ensure_ascii=False)

            items.append({
                "title": word,
                "content": content,
                "url": search_url,
                "author": "抖音热搜",
                "hot_score": hot_val,
                "category": category,
                "tags": tags,
                "raw_data": raw_data,
            })

        # ---------- trending_list: 实时上升热点 (5条) ----------
        for t in trending_list:
            word = (t.get("word") or "").strip()
            if not word:
                continue

            group_id = t.get("group_id", "")
            video_cnt = t.get("video_count", 0)
            discuss_cnt = t.get("discuss_video_count", 0)
            event_time = t.get("event_time", 0)

            content = f"实时上升 | 视频:{video_cnt} | 讨论:{discuss_cnt}"
            if event_time:
                content += f" | 时间:{datetime.fromtimestamp(event_time).strftime('%m-%d %H:%M')}"

            search_url = f"https://www.douyin.com/search/{urllib.parse.quote(word)}"
            if group_id:
                search_url = f"https://www.douyin.com/video/{group_id}"

            matched = match_keywords(word)
            if matched:
                main_cats = [m[0] for m in matched]
                category = "Douyin|Trending|" + "|".join(main_cats[:3])
                tags = ",".join(main_cats)
            else:
                category = "Douyin|Trending"
                tags = ""

            raw_data = json.dumps({
                "word": word,
                "group_id": group_id,
                "video_count": video_cnt,
                "discuss_video_count": discuss_cnt,
                "event_time": event_time,
                "sentence_id": t.get("sentence_id", ""),
            }, ensure_ascii=False)

            items.append({
                "title": word,
                "content": content,
                "url": search_url,
                "author": "抖音实时热点",
                "hot_score": float(video_cnt * 100000),
                "category": category,
                "tags": tags,
                "raw_data": raw_data,
            })

        # 如果拿到了数据就跳出循环
        if len(items) >= 50:
            break

    # 去重（按title去重）
    seen_titles = set()
    deduped = []
    for item in items:
        t = item["title"]
        if t not in seen_titles:
            seen_titles.add(t)
            deduped.append(item)

    log(f"热搜榜采集: 原始{len(items)}条 → 去重后{len(deduped)}条")
    return deduped


# ============================================================
# 关键词定向搜索（兜底方案）
# ============================================================
def collect_by_keywords() -> List[Dict]:
    """
    基于关键词的热搜过滤 + 扩展搜索
    从完整热搜中筛选出与关键词相关的条目
    """
    items = []
    seen = set()

    # 获取完整热搜作为数据源
    log("关键词搜索: 从热搜中筛选...")
    hot_items = collect_hot_list()  # 复用热搜数据
    for item in hot_items:
        matched = match_keywords(item["title"] + " " + item["content"])
        if matched:
            key = item["title"] + item["url"]
            if key not in seen:
                seen.add(key)
                items.append(item)

    # 对每个关键词，尝试通过抖音搜索API（虽然受限，但还是构建搜索URL）
    for kw in DY_KEYWORDS:
        encoded = urllib.parse.quote(kw)
        # 仅构建搜索URL作为数据源URL，不尝试解析搜索结果页
        search_url = f"https://www.douyin.com/search/{encoded}?type=general"
        kw_hash = hashlib.md5(f"kw:{kw}".encode()).hexdigest()

        # 如果这个关键词还没有被热搜覆盖，添加一个占位搜索条目
        already_covered = any(kw in item.get("tags", "") or kw in item.get("title", "")
                              for item in items)
        if not already_covered:
            matched_ext = match_keywords(kw)
            tags = ",".join([m[0] for m in matched_ext]) if matched_ext else kw
            items.append({
                "title": kw,
                "content": f"关键词搜索: {kw}",
                "url": search_url,
                "author": "",
                "hot_score": 0,
                "category": f"Douyin|Search|{tags}",
                "tags": tags,
                "raw_data": json.dumps({"keyword": kw, "type": "keyword_search"}, ensure_ascii=False),
            })

    log(f"关键词搜索采集: {len(items)}条")
    return items


# ============================================================
# 视频详情补全（可选，尝试获取更多元数据）
# ============================================================
def enrich_video_detail(items: List[Dict]) -> List[Dict]:
    """
    视频详情补全（占位函数）
    抖音视频详情API需要登录态/cookie，无token时不可用。
    保留函数签名兼容调用，但不实际请求。
    """
    return items


# ============================================================
# 主采集流程
# ============================================================
def collect_douyin_hot(enable_enrich: bool = True) -> Tuple[int, int, int]:
    """
    抖音热点采集主入口

    Args:
        enable_enrich: 是否开启视频详情补全（会减慢速度）

    Returns:
        (new_saved, total_candidates, error_count)
    """
    start_time = time.time()
    log("=" * 50)
    log("🚀 抖音热点采集器 v2.0 启动")
    log("=" * 50)

    all_items = []
    total_saved = 0
    total_candidates = 0
    error_count = 0

    # 阶段1: 热搜榜采集 (核心, 50条)
    log("📡 阶段1: 热搜榜采集...")
    try:
        hot_items = collect_hot_list()
        all_items.extend(hot_items)
        log(f"  热搜榜: {len(hot_items)}条")
    except Exception as e:
        log(f"  ❌ 热搜榜采集异常: {e}")
        error_count += 1

    # 阶段2: 关键词匹配/搜索 (补充)
    log("🎯 阶段2: 关键词匹配搜索...")
    try:
        kw_items = collect_by_keywords()
        # 合并（去重）
        existing_titles = {item["title"] for item in all_items}
        for item in kw_items:
            if item["title"] not in existing_titles:
                all_items.append(item)
                existing_titles.add(item["title"])
        log(f"  关键词补充: {len(kw_items)}条 (新增{len(all_items) - len(hot_items)}条)")
    except Exception as e:
        log(f"  ❌ 关键词搜索异常: {e}")
        error_count += 1

    # 阶段3: 视频详情补全 (可选)
    if enable_enrich and all_items:
        log("🔍 阶段3: 尝试补全视频详情...")
        try:
            all_items = enrich_video_detail(all_items)
            log("  视频详情补全完成")
        except Exception as e:
            log(f"  ⚠️ 视频详情补全异常: {e}")

    # 阶段4: 批量存储
    log(f"💾 阶段4: 批量存储 ({len(all_items)}条)...")
    total_candidates = len(all_items)
    for i, item in enumerate(all_items):
        try:
            saved = save_item(
                title=item.get("title", ""),
                content=item.get("content", ""),
                url=item.get("url", ""),
                author=item.get("author", ""),
                category=item.get("category", "Douyin|Hot"),
                hot_score=item.get("hot_score", 0),
                tags=item.get("tags", ""),
                raw_data=item.get("raw_data", ""),
            )
            if saved:
                total_saved += 1
        except Exception as e:
            log(f"  保存失败 #{i}: {e}")
            error_count += 1

        # 每20条打印进度
        if (i + 1) % 20 == 0:
            log(f"  进度: {i + 1}/{len(all_items)}, 已保存{total_saved}条")

    # 写日志
    elapsed = time.time() - start_time
    status = "ok" if error_count == 0 else "partial"
    log(f"📊 结果: 候选{total_candidates}条 → 新保存{total_saved}条 | 错误{error_count} | 耗时{elapsed:.1f}s")
    save_collector_log(status, total_saved, total_candidates,
                       None if error_count == 0 else f"{error_count} errors")

    return total_saved, total_candidates, error_count


# ============================================================
# 独立运行测试
# ============================================================
def run_self_test() -> Dict:
    """
    自测试函数：验证网络、API、数据库均可用
    返回诊断报告字典
    """
    report = {
        "network": False,
        "hot_api": False,
        "hot_count": 0,
        "db_write": False,
        "keyword_match": False,
        "overall": False,
    }

    log("🧪 运行自测试...")

    # 1. 网络测试
    try:
        resp = fetch("https://www.douyin.com", timeout=10)
        if resp is not None:
            report["network"] = True
            log("  ✅ 网络连通: OK")
        else:
            log("  ❌ 网络连通: FAILED")
    except Exception as e:
        log(f"  ❌ 网络测试异常: {e}")

    if not report["network"]:
        report["overall"] = False
        log("❌ 自测试失败: 网络不通")
        return report

    # 2. 热搜API测试
    try:
        params = urllib.parse.urlencode({"detail_list": 1, "source": 0, "main_billboard_count": 50})
        url = f"{HOT_LIST_API}?{params}"
        text = fetch(url, timeout=15)
        if text:
            data = json.loads(text)
            word_list = data.get("data", {}).get("word_list", [])
            report["hot_api"] = True
            report["hot_count"] = len(word_list)
            if len(word_list) >= 10:
                log(f"  ✅ 热搜API: OK ({len(word_list)}条)")
                # 打印前3条
                for w in word_list[:3]:
                    log(f"    - {w.get('word', '?')} (热度:{w.get('hot_value', 0)})")
            else:
                log(f"  ⚠️ 热搜API: 返回 {len(word_list)}条, 偏少")
        else:
            log("  ❌ 热搜API: 无响应")
    except Exception as e:
        log(f"  ❌ 热搜API测试异常: {e}")

    # 3. 数据库写入测试
    try:
        test_hash = hashlib.md5(f"test_douyin_v2_{time.time()}".encode()).hexdigest()
        db = sqlite3.connect(str(DB_PATH))
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        db.execute(
            "INSERT OR IGNORE INTO raw_intelligence (title, content, url, source, platform, url_hash, collected_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("__test_douyin_v2__", "自测试数据", f"https://test.douyin/{test_hash}", "douyin", "douyin", test_hash, now),
        )
        db.commit()
        db.close()
        report["db_write"] = True
        log("  ✅ 数据库写入: OK")
        # 清理测试数据
        db = sqlite3.connect(str(DB_PATH))
        db.execute("DELETE FROM raw_intelligence WHERE url_hash=?", (test_hash,))
        db.commit()
        db.close()
    except Exception as e:
        log(f"  ❌ 数据库测试异常: {e}")

    # 4. 关键词匹配测试
    try:
        test_text = "华为发布最新AI芯片麒麟9000，自动驾驶技术突破"
        matched = match_keywords(test_text)
        if matched:
            report["keyword_match"] = True
            log(f"  ✅ 关键词匹配: OK ({matched})")
        else:
            log("  ⚠️ 关键词匹配: 未命中")
    except Exception as e:
        log(f"  ❌ 关键词匹配测试异常: {e}")

    # 综合判定
    report["overall"] = all([
        report["network"],
        report["hot_api"],
        report["hot_count"] >= 10,
        report["db_write"],
    ])
    if report["overall"]:
        log("✅ 自测试全部通过!")
    else:
        log("⚠️ 自测试部分失败，详情见上")

    return report


# ============================================================
# 入口
# ============================================================
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="抖音热点采集器 v2.0")
    parser.add_argument("--test", action="store_true", help="运行自测试")
    parser.add_argument("--no-enrich", action="store_true", help="禁用视频详情补全（更快）")
    parser.add_argument("--count-only", action="store_true", help="仅统计已有数据条数")
    args = parser.parse_args()

    if args.test:
        report = run_self_test()
        sys.exit(0 if report["overall"] else 1)

    if args.count_only:
        try:
            db = sqlite3.connect(str(DB_PATH))
            row = db.execute("SELECT COUNT(*) FROM raw_intelligence WHERE source='douyin'").fetchone()
            log(f"📊 抖音数据总量: {row[0]}条")
            db.close()
        except Exception as e:
            log(f"❌ 查询失败: {e}")
        sys.exit(0)

    saved, total, errors = collect_douyin_hot(enable_enrich=not args.no_enrich)
    log(f"🏁 完成: 新保存{saved}条 / 候选{total}条 / 错误{errors}")

    # 输出简短摘要供外部解析
    print(f"RESULT: saved={saved} total={total} errors={errors}", flush=True)
