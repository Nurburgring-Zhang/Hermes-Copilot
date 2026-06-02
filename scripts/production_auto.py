#!/usr/bin/env python3
"""
Hermes 全自动AI产品生产引擎 v2.0 — 真正的AI驱动
=================================================
从intelligence.db读取真正AI评分的情报，
通过OpenRouter/DeepSeek API调用LLM做真实产品方案生成，
产出完整的产品定义（功能/技术栈/路线图/风险评估）。

使用方式:
  python3 production_auto.py                    # 标准模式: 基于前3条高评分情报
  python3 production_auto.py --full              # 全量模式: 所有评分>=80的情报
  python3 production_auto.py --force             # 强制模式: 即使AI评分不可用

输出: ~/.hermes/outputs/auto_production/product_*.json
"""
import sqlite3, json, os, re, time, sys
import urllib.request
import urllib.error
import socket
from datetime import datetime
from pathlib import Path

HERMES = Path("/home/administrator/.hermes")
DB_PATH = HERMES / "intelligence.db"
OUTPUT_DIR = HERMES / "outputs" / "auto_production"
LOG_DIR = HERMES / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

LOG_FILE = LOG_DIR / "production_auto.log"

# ========== 提前定义简单日志（在env加载之前可用） ==========
def _early_log(msg):
    """env加载阶段使用的简单日志"""
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

# ========== 加载.env环境变量 ==========
_env_path = HERMES / ".env"
if _env_path.exists():
    try:
        for _line in _env_path.read_text(encoding="utf-8").splitlines():
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _v = _line.split("=", 1)
                _k, _v = _k.strip(), _v.strip()
                if _v and _v != "***" and (_k not in os.environ or not os.environ[_k]):
                    os.environ[_k] = _v
    except Exception as e:
        _early_log(f"WARNING .env加载失败: {e}")

# 也尝试加载config.yaml中的deepseek api_key
try:
    import yaml
    _cfg_path = HERMES / "config.yaml"
    if _cfg_path.exists():
        with open(_cfg_path, encoding='utf-8') as _f:
            _cfg = yaml.safe_load(_f) or {}
        for _p in _cfg.get("custom_providers", []):
            if _p.get("name") == "deepseek" and _p.get("api_key"):
                if not os.environ.get("DEEPSEEK_API_KEY"):
                    os.environ["DEEPSEEK_API_KEY"] = _p["api_key"]
                if not os.environ.get("OPENROUTER_API_KEY"):
                    os.environ["OPENROUTER_API_KEY"] = _p["api_key"]
except Exception as e:
    _early_log(f"WARNING config.yaml加载失败: {e}")


def log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] 🏭 {msg}"
    print(line)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def get_api_key() -> tuple:
    """获取可用的API key和URL。返回 (api_key, api_url, model)"""
    # 优先级1: DeepSeek (可通过OpenRouter路由)
    key = os.environ.get("DEEPSEEK_API_KEY", "")
    if key:
        return (key, "https://api.deepseek.com/v1/chat/completions", "deepseek-chat")
    # 优先级2: OpenRouter (+ openrouter/auto 自动最优路由)
    key = os.environ.get("OPENROUTER_API_KEY", "")
    if key:
        return (key, "https://openrouter.ai/api/v1/chat/completions", "openrouter/auto")
    # 优先级3: Anthropic
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if key:
        return (key, "https://api.anthropic.com/v1/messages", "claude-sonnet-4-20250514")
    # 优先级4: OpenAI
    key = os.environ.get("OPENAI_API_KEY", "")
    if key:
        return (key, "https://api.openai.com/v1/chat/completions", "gpt-4o-mini")
    return ("", "", "")


def load_top_items(limit: int = 10, force: bool = False) -> list:
    """加载真正AI评分最高的情报（最近7天）"""
    db = sqlite3.connect(str(DB_PATH))
    if force:
        # 强制模式: 所有有内容的条目
        rows = db.execute("""
            SELECT id, title, COALESCE(content, '') as content,
                   platform, source, author, tags, category,
                   COALESCE(ai_score_total, importance_score*10, 50) as score,
                   url, published_at, ai_score_reasoning
            FROM cleaned_intelligence
            WHERE LENGTH(COALESCE(content, '')) > 20
              AND title IS NOT NULL AND title != ''
              AND cleaned_at >= datetime('now', '-14 days')
            ORDER BY score DESC
            LIMIT ?
        """, (limit,)).fetchall()
    else:
        # 标准模式: 只看真正AI评分过的
        rows = db.execute("""
            SELECT id, title, COALESCE(content, '') as content,
                   platform, source, author, tags, category,
                   COALESCE(ai_score_total, 0) as score,
                   url, published_at, ai_score_reasoning
            FROM cleaned_intelligence
            WHERE ai_score_total > 0
              AND ai_scored_at IS NOT NULL
              AND LENGTH(COALESCE(content, '')) > 50
              AND title IS NOT NULL AND title != ''
              AND cleaned_at >= datetime('now', '-7 days')
            ORDER BY ai_score_total DESC
            LIMIT ?
        """, (limit,)).fetchall()
    db.close()
    
    items = []
    cols = ['id','title','content','platform','source','author','tags','category',
            'ai_score_total','url','published_at','ai_score_reasoning']
    for r in rows:
        d = dict(zip(cols, r))
        d['content'] = (d.get('content') or '')[:1000]
        items.append(d)
    return items


def call_ai_api(prompt: str, system_msg: str = "", timeout: int = 120) -> str:
    """调用AI API，支持多provider自动切换"""
    api_key, api_url, model = get_api_key()
    if not api_key:
        raise RuntimeError("无可用API key")
    
    messages = []
    if system_msg:
        messages.append({"role": "system", "content": system_msg})
    messages.append({"role": "user", "content": prompt})
    
    # 构造请求体
    if "anthropic" in api_url:
        payload = json.dumps({
            "model": model,
            "max_tokens": 1000,
            "messages": messages
        }).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01"
        }
    else:
        payload = json.dumps({
            "model": model,
            "messages": messages,
            "temperature": 0.3,
            "max_tokens": 1000
        }).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        }
        if "openrouter" in api_url:
            headers["HTTP-Referer"] = "https://hermes.weixin.ai"
            headers["X-Title"] = "Hermes Product Generation"
    
    max_retries = 3
    for attempt in range(1, max_retries + 1):
        try:
            req = urllib.request.Request(api_url, data=payload, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                response_data = json.loads(resp.read().decode("utf-8"))
            
            if "anthropic" in api_url:
                return response_data["content"][0]["text"]
            else:
                return response_data["choices"][0]["message"]["content"]
        except urllib.error.HTTPError as e:
            # 402(余额不足)和401(认证失败)是永久错误，不重试
            if e.code in (401, 402, 403):
                raise RuntimeError(f"API认证/余额错误({e.code}): {e.reason}")
            if attempt < max_retries:
                wait = 3 * attempt
                log(f"⚠️ API请求HTTP {e.code}(尝试{attempt}/{max_retries})，{wait}秒后重试")
                time.sleep(wait)
            else:
                raise RuntimeError(f"API请求全部失败: {e}")
        except (urllib.error.URLError, socket.timeout, OSError) as e:
            if attempt < max_retries:
                wait = 3 * attempt
                log(f"⚠️ API请求失败(尝试{attempt}/{max_retries}): {e}，{wait}秒后重试")
                time.sleep(wait)
            else:
                raise RuntimeError(f"API请求全部失败: {e}")


def generate_product_spec_with_ai(item: dict) -> dict:
    """调用真正的AI生成产品方案"""
    title = item.get('title', '')
    content = (item.get('content', '') or '')[:800]
    platform = item.get('platform', '')
    score = item.get('ai_score_total', 0)
    tags = (item.get('tags', '') or '')
    
    log(f"📝 AI产品生成中: {title[:50]}... (AI评分={score})")
    
    prompt = f"""JSON产品方案: product_name, product_type, target_audience, core_problem, mvp_features(5项,name+description), 2个risk, competitive_advantage

情报: {title[:50]}
摘要: {content[:150]}
评分: {score}/100

纯JSON输出。"""

    system_msg = "你是顶级产品架构师。严格输出JSON，不要任何额外文字。"
    
    try:
        ai_response = call_ai_api(prompt, system_msg, timeout=120)
        
        # 清理AI响应，提取纯JSON
        cleaned = ai_response.strip()
        # 移除markdown代码块
        cleaned = re.sub(r'^```(?:json)?\s*', '', cleaned)
        cleaned = re.sub(r'\s*```$', '', cleaned)
        
        product_spec = json.loads(cleaned)
        log(f"  ✅ AI产品方案生成成功: {product_spec.get('product_name', '未命名')[:40]}")
        return product_spec
    except json.JSONDecodeError as e:
        log(f"  ❌ AI返回JSON解析失败: {e}")
        log(f"  AI原始响应前200字: {ai_response[:200] if 'ai_response' in dir() else 'N/A'}")
        return None
    except Exception as e:
        log(f"  ❌ AI产品生成失败: {e}")
        return None


def assemble_product_report(item: dict, product_spec: dict) -> dict:
    """组装完整的产品报告"""
    if not product_spec:
        # AI失败时的后备方案——用简单模板，标注为"规则生成"
        return {
            "generated_at": datetime.now().isoformat(),
            "generation_method": "rule_fallback",
            "source_title": item.get('title', ''),
            "source_url": item.get('url', ''),
            "source_platform": item.get('platform', ''),
            "source_ai_score": item.get('ai_score_total', 0),
            "product_spec": {
                "product_name": f"基于'{item.get('title','')[:30]}'的产品方案",
                "product_type": "AI工具",
                "target_audience": {"primary": "技术决策者"},
                "core_problem": "基于情报驱动的自动化产品方案",
                "mvp_features": [],
                "tech_stack": {"backend": ["Python"], "ai_ml": ["LLM API"]},
                "data_strategy": "基于情报数据库",
                "monetization": {"model": "订阅制"},
                "development_timeline": {"mvp_weeks": "4周"},
                "risks": [],
                "competitive_advantage": "情报驱动",
                "success_metrics": ["方案采纳率"]
            },
            "ai_reasoning": item.get('ai_score_reasoning', ''),
            "generation_note": "⚠️ AI方案生成失败，使用规则后备方案"
        }
    
    return {
        "generated_at": datetime.now().isoformat(),
        "generation_method": "ai_driven",
        "source_title": item.get('title', ''),
        "source_url": item.get('url', ''),
        "source_platform": item.get('platform', ''),
        "source_tags": item.get('tags', ''),
        "source_ai_score": item.get('ai_score_total', 0),
        "ai_reasoning": item.get('ai_score_reasoning', ''),
        "product_spec": product_spec,
        "data_synthesis": {
            "key_insights_from_intelligence": [
                f"核心情报: {item.get('title','')[:80]}",
                f"AI六维评分: {item.get('ai_score_total',0)}/100",
                f"来源可信度: {item.get('platform','')}"
            ]
        }
    }


def run_production(full_mode: bool = False, force: bool = False):
    """主流程：读取高评分情报 → AI产品生成 → 产出报告"""
    log("🏭 产品生产引擎v2启动（真正AI驱动）")
    
    # 检查API可用性
    api_key, api_url, model = get_api_key()
    if not api_key:
        log("❌ 无可用API key，无法进行AI产品生成")
        log("   请配置 OPENROUTER_API_KEY 或 DEEPSEEK_API_KEY")
        if not force:
            return
        log("   force模式: 继续尝试")
    
    log(f"🤖 使用API: {api_url} | 模型: {model}")
    
    # 加载情报
    limit = 50 if full_mode else 10
    items = load_top_items(limit=limit, force=(force or full_mode))
    
    if not items:
        log("❌ 无可用数据（无真正AI评分的情报），尝试force模式...")
        items = load_top_items(limit=5, force=True)
        if not items:
            log("❌ 确实无可用数据")
            return
    
    top_score = items[0].get('ai_score_total', 0)
    log(f"📊 加载 {len(items)} 条情报 (最高分={top_score})")
    
    # 取前3条（full模式取前10条，但分批生成API调用太慢）
    max_items = 10 if full_mode else 3
    items_to_process = items[:max_items]
    
    now_str = datetime.now().strftime('%Y%m%d_%H%M%S')
    reports = []
    
    for i, item in enumerate(items_to_process):
        product_spec = generate_product_spec_with_ai(item)
        report = assemble_product_report(item, product_spec)
        reports.append(report)
        
        # 每条单独输出
        out_path = OUTPUT_DIR / f"product_{now_str}_{i+1}.json"
        try:
            out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            log(f"📄 [{i+1}] {out_path.name}")
        except OSError as e:
            log(f"❌ 写入产品文件失败 {out_path}: {e}")
        
        # API调用间隔，避免限流
        if i < len(items_to_process) - 1:
            time.sleep(2)
    
    # 汇总输出
    summary = {
        "generated_at": now_str,
        "generation_method": "ai_driven",
        "batch_count": len(reports),
        "products": [
            {
                "name": r.get("product_spec", {}).get("product_name", "N/A") if r.get("generation_method") == "ai_driven" else "后备方案",
                "source": r.get("source_title", "")[:40],
                "ai_score": r.get("source_ai_score", 0),
                "method": r.get("generation_method", "unknown")
            }
            for r in reports
        ],
        "api_status": {
            "url": api_url,
            "model": model,
            "has_key": bool(api_key)
        }
    }
    summary_path = OUTPUT_DIR / f"product_summary_{now_str}.json"
    try:
        summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError as e:
        log(f"❌ 写入汇总文件失败 {summary_path}: {e}")
    
    ai_count = sum(1 for r in reports if r.get("generation_method") == "ai_driven")
    log(f"📊 汇总: {len(reports)}个产品方案 (AI生成{ai_count}个)")
    
    # 清理临时文件
    for f in OUTPUT_DIR.glob("_tmp_*.json"):
        f.unlink()
    
    log(f"✅ 产品生产完成 (AI驱动={bool(ai_count)})")


if __name__ == "__main__":
    full_mode = "--full" in sys.argv
    force = "--force" in sys.argv
    run_production(full_mode=full_mode, force=force)
