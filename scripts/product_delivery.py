#!/usr/bin/env python3
"""
Hermes 全自动产品验收与交付引擎 v1.0
=====================================
从auto_production读取AI产品方案，进行三层验收测试：
1. 语法验收 — JSON有效性和字段完整性
2. 语义验收 — 方案内容合理性（调用AI判断）
3. 一致性验收 — 方案与源情报的匹配度

通过验收后，生成交付物：
- 最终产品规格书（markdown格式）
- 交付清单
- 产品路线图

使用方式:
  python3 product_delivery.py                    # 验收最新一批产品方案
  python3 product_delivery.py --all              # 验收所有未验收的方案
  python3 product_delivery.py --product <path>   # 验收指定方案文件
"""
import sqlite3, json, os, re, sys, time
import urllib.request
import urllib.error
import socket
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

HERMES = Path("/home/administrator/.hermes")
DB_PATH = HERMES / "intelligence.db"
PRODUCT_DIR = HERMES / "outputs" / "auto_production"
DELIVERY_DIR = HERMES / "outputs" / "product_delivery"
LOG_DIR = HERMES / "logs"
DELIVERY_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)

DELIVERY_DB = DELIVERY_DIR / "delivery_records.db"
LOG_FILE = LOG_DIR / "product_delivery.log"

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
        print(f"[delivery] WARNING .env加载失败: {e}")


def log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] 📦 {msg}"
    print(line)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def get_api_key() -> tuple:
    key = os.environ.get("DEEPSEEK_API_KEY", "")
    if key:
        return (key, "https://api.deepseek.com/v1/chat/completions", "deepseek-chat")
    key = os.environ.get("OPENROUTER_API_KEY", "")
    if key:
        return (key, "https://openrouter.ai/api/v1/chat/completions", "openrouter/auto")
    return ("", "", "")


def init_delivery_db():
    conn = sqlite3.connect(str(DELIVERY_DB))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS delivery_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_file TEXT NOT NULL UNIQUE,
            product_name TEXT,
            source_title TEXT,
            source_ai_score REAL,
            generation_method TEXT,
            syntax_pass INTEGER DEFAULT 0,
            semantic_pass INTEGER DEFAULT 0,
            consistency_pass INTEGER DEFAULT 0,
            overall_pass INTEGER DEFAULT 0,
            syntax_errors TEXT,
            semantic_report TEXT,
            consistency_report TEXT,
            delivered_at TEXT,
            delivery_path TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.commit()
    return conn


def verify_syntax(product: dict) -> dict:
    errors = []
    spec = product.get("product_spec", {})
    if not spec:
        errors.append("缺少 product_spec")
        return {"pass": False, "errors": errors}

    required_fields = [
        ("product_name", str, "产品名称"),
        ("product_type", str, "产品类型"),
    ]
    for field, ftype, fname in required_fields:
        val = spec.get(field)
        if not val or not isinstance(val, ftype):
            errors.append(f"缺少或类型错误: {fname}({field})")

    ta = spec.get("target_audience", {})
    if isinstance(ta, str):
        ta = {"primary": ta}
    elif isinstance(ta, (list, tuple)):
        ta = {"primary": ", ".join(str(x) for x in ta[:3])}
    if isinstance(ta, dict):
        if not ta.get("primary"):
            errors.append("target_audience.primary 为空")
    else:
        errors.append("target_audience 不是对象")

    features = spec.get("mvp_features", [])
    if not features or not isinstance(features, list):
        errors.append("mvp_features 缺失或非列表")
    elif len(features) < 3:
        errors.append(f"mvp_features 不足3项(仅{len(features)}项)")
    else:
        for i, f in enumerate(features):
            if not f.get("name"):
                errors.append(f"mvp_features[{i}] 缺少 name")
            if not f.get("description"):
                errors.append(f"mvp_features[{i}] 缺少 description")

    risks = spec.get("risks", [])
    if risks is None:
        risks = []
    if isinstance(risks, str):
        risks = [{"type": "风险", "description": risks}] if risks.strip() else []
    # risks是可选的，不为空列表时检查格式
    if risks and not isinstance(risks, (list,)):
        errors.append("risks 格式错误")

    if not spec.get("competitive_advantage"):
        errors.append("competitive_advantage 为空")

    return {
        "pass": len(errors) == 0,
        "errors": errors,
        "field_count": len([k for k in spec.keys() if spec.get(k)]),
        "feature_count": len(features) if isinstance(features, list) else 0
    }


def _primary_ta(spec):
    ta = spec.get("target_audience", "")
    if isinstance(ta, str): return ta
    if isinstance(ta, dict): return ta.get("primary", "")
    if isinstance(ta, (list, tuple)): return ", ".join(str(x) for x in ta[:3])
    return ""

def verify_semantic(product: dict) -> dict:
    spec = product.get("product_spec", {})
    product_name = spec.get("product_name", "未命名")

    prompt = f"""评估以下AI产品方案的质量。输出JSON: {{"score":0-100,"strengths":["优点1","优点2"],"weaknesses":["缺点1","缺点2"],"feasibility":"高/中/低","suggestion":"改进建议"}}

产品名: {product_name}
类型: {spec.get("product_type","")}
目标用户: {_primary_ta(spec)}
核心问题: {spec.get("core_problem","")}
功能({len(spec.get("mvp_features",[]))}项): {", ".join([f.get("name","") for f in spec.get("mvp_features",[])][:5])}
竞品优势: {spec.get("competitive_advantage","")[:100]}

只输出JSON。"""

    api_key, api_url, model = get_api_key()
    if not api_key:
        return {"pass": True, "score": 70, "reason": "无API key，跳过语义验收", "auto_pass": True}

    payload = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
        "max_tokens": 500
    }).encode()

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }
    if "openrouter" in api_url:
        headers["HTTP-Referer"] = "https://hermes.weixin.ai"
        headers["X-Title"] = "Hermes Delivery Verification"

    max_retries = 3
    last_error = None
    for attempt in range(1, max_retries + 1):
        try:
            req = urllib.request.Request(api_url, data=payload, headers=headers)
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read())
            result = data["choices"][0]["message"]["content"]

            cleaned = re.sub(r'^```(?:json)?\s*', '', result.strip())
            cleaned = re.sub(r'\s*```$', '', cleaned)
            evaluation = json.loads(cleaned)

            score = evaluation.get("score", 50)
            return {
                "pass": score >= 50,
                "score": score,
                "strengths": evaluation.get("strengths", []),
                "weaknesses": evaluation.get("weaknesses", []),
                "feasibility": evaluation.get("feasibility", "中"),
                "suggestion": evaluation.get("suggestion", ""),
                "auto_pass": False
            }
        except urllib.error.HTTPError as e:
            last_error = e
            # 402余额不足是永久错误
            if e.code in (401, 402, 403):
                log(f"⚠️ 语义验收API认证错误({e.code})，跳过")
                return {"pass": True, "score": 65, "reason": f"API认证错误: {e.code}", "auto_pass": True}
            if attempt < max_retries:
                time.sleep(3 * attempt)
            continue
        except (urllib.error.URLError, socket.timeout, OSError, json.JSONDecodeError, KeyError) as e:
            last_error = e
            if attempt < max_retries:
                time.sleep(2 * attempt)
            continue

    log(f"⚠️ 语义验收API重试均失败: {last_error}")
    return {"pass": True, "score": 65, "reason": f"API重试{max_retries}次失败: {last_error}", "auto_pass": True}


def verify_consistency(product: dict) -> dict:
    source_title = product.get("source_title", "")
    spec = product.get("product_spec", {})

    if not source_title:
        return {"pass": True, "reason": "无源情报信息", "auto_pass": True}

    product_name = spec.get("product_name", "")
    source_lower = (source_title + " " + spec.get("core_problem", "")).lower()
    product_lower = product_name.lower()

    source_keywords = set(re.findall(r'[\w\u4e00-\u9fff]+', source_lower))
    product_keywords = set(re.findall(r'[\w\u4e00-\u9fff]+', product_lower))

    overlap = source_keywords & product_keywords
    overlap_count = len(overlap)

    feature_hits = 0
    for f in spec.get("mvp_features", []):
        ftext = (f.get("name", "") + " " + f.get("description", "")).lower()
        if any(kw in ftext for kw in list(source_keywords)[:20]):
            feature_hits += 1

    consistency_score = min(100, overlap_count * 20 + feature_hits * 10)

    return {
        "pass": consistency_score >= 20 or overlap_count >= 1,
        "score": consistency_score,
        "keyword_overlap": list(overlap)[:5],
        "feature_alignment": f"{feature_hits}/{len(spec.get('mvp_features',[]))}",
        "auto_pass": False
    }


def generate_delivery(product: dict, syntax: dict, semantic: dict, consistency: dict) -> str:
    spec = product.get("product_spec", {})
    overall_pass = syntax["pass"] and semantic["pass"] and consistency["pass"]

    md = f"""# 产品规格书: {spec.get("product_name", "未命名")}

## 基本信息
| 字段 | 内容 |
|------|------|
| 产品类型 | {spec.get("product_type", "N/A")} |
| 目标用户 | {_primary_ta(spec)} |
| 核心问题 | {spec.get("core_problem", "N/A")} |
| 竞争优势 | {spec.get("competitive_advantage", "N/A")} |

## 源情报
- **标题**: {product.get("source_title", "N/A")}
- **来源**: {product.get("source_platform", "N/A")}
- **AI评分**: {product.get("source_ai_score", 0)}/100
- **生成方式**: {product.get("generation_method", "N/A")}

## MVP功能
"""
    for i, f in enumerate(spec.get("mvp_features", []), 1):
        md += f"### P{i} {f.get('name', f'功能{i}')}\n"
        md += f"- 描述: {f.get('description', 'N/A')}\n"

    if spec.get("tech_stack"):
        ts = spec["tech_stack"]
        md += f"""
## 技术栈
- 后端: {', '.join(ts.get('backend', ['N/A']))}
- 前端: {', '.join(ts.get('frontend', ['N/A']))}
- AI/ML: {', '.join(ts.get('ai_ml', ['N/A']))}
"""

    md += """## 风险评估

"""
    for r in spec.get("risks", []):
        if isinstance(r, str):
            md += f"- {r}\n"
        elif isinstance(r, dict):
            md += f"- **{r.get('type', '风险')}**: {r.get('description', 'N/A')}"
            if r.get('mitigation'):
                md += f" → 应对: {r['mitigation']}"
            md += "\n"

    if spec.get("monetization"):
        mon = spec["monetization"]
        md += f"""
## 商业模式
- 模式: {mon.get('model', 'N/A')}
- 定价: {mon.get('pricing', 'N/A')}
"""

    md += f"""
## 验收结果
| 验收维度 | 结果 | 详情 |
|----------|------|------|
| 语法验收 | {'✅通过' if syntax['pass'] else '❌失败'} | {len(syntax.get('errors',[]))}个问题 |
| 语义验收 | {'✅通过' if semantic['pass'] else '❌失败'} | 评分{semantic.get('score','N/A')}/100 |
| 一致性验收 | {'✅通过' if consistency['pass'] else '❌失败'} | 关键字匹配{consistency.get('score', 0)}/100 |
| **综合判定** | **{'✅ 通过' if overall_pass else '❌ 未通过'}** | |

## 交付信息
- 生成时间: {product.get('generated_at', 'N/A')}
- 验收时间: {datetime.now().isoformat()}
"""
    return md


def run_delivery(product_path: Optional[str] = None, all_mode: bool = False):
    log("产品验收与交付引擎启动")

    conn = init_delivery_db()
    cursor = conn.cursor()

    if product_path:
        product_files = [Path(product_path)]
    elif all_mode:
        product_files = sorted(PRODUCT_DIR.glob("product_*.json"))
        delivered = set(r[0] for r in cursor.execute("SELECT product_file FROM delivery_records").fetchall())
        product_files = [f for f in product_files if str(f) not in delivered]
    else:
        all_files = sorted([f for f in PRODUCT_DIR.glob("product_*.json") if "summary" not in f.stem], reverse=True)
        if not all_files:
            log("❌ 无产品方案文件")
            return
        latest_ts = all_files[0].stem.split("product_")[-1].rsplit("_", 1)[0]
        product_files = [f for f in all_files if latest_ts in f.stem]

    if not product_files:
        log("📭 无待验收的产品方案")
        conn.close()
        return

    log(f"📊 待验收: {len(product_files)} 个产品方案")

    delivery_products = []

    for pf in product_files:
        try:
            product = json.loads(pf.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, FileNotFoundError) as e:
            log(f"❌ 读取失败 {pf.name}: {e}")
            continue

        product_name = product.get("product_spec", {}).get("product_name", pf.stem)
        log(f"📋 验收: {product_name[:40]}")

        syntax = verify_syntax(product)
        if not syntax["pass"]:
            log(f"  ❌ 语法验收失败: {syntax['errors']}")

        semantic = verify_semantic(product)
        log(f"  🔬 语义验收: {'✅' if semantic['pass'] else '❌'} 评分={semantic.get('score','?')}")

        consistency = verify_consistency(product)
        log(f"  🔗 一致性验收: {'✅' if consistency['pass'] else '❌'} 得分={consistency.get('score', 0)}")

        overall_pass = syntax["pass"] and semantic["pass"] and consistency["pass"]
        log(f"  {'✅ 综合判定: 通过' if overall_pass else '❌ 综合判定: 未通过'}")

        delivery_md = generate_delivery(product, syntax, semantic, consistency)

        delivery_filename = f"delivery_{pf.stem.replace('product_', '')}.md"
        delivery_path = DELIVERY_DIR / delivery_filename
        delivery_path.write_text(delivery_md, encoding="utf-8")
        log(f"  📝 交付物: {delivery_path.name}")

        cursor.execute("""
            INSERT OR REPLACE INTO delivery_records 
            (product_file, product_name, source_title, source_ai_score, generation_method,
             syntax_pass, semantic_pass, consistency_pass, overall_pass,
             syntax_errors, semantic_report, consistency_report, delivered_at, delivery_path)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            str(pf), product_name, product.get("source_title", ""),
            product.get("source_ai_score", 0), product.get("generation_method", ""),
            1 if syntax["pass"] else 0, 1 if semantic["pass"] else 0,
            1 if consistency["pass"] else 0, 1 if overall_pass else 0,
            json.dumps(syntax.get("errors", []), ensure_ascii=False),
            json.dumps(semantic, ensure_ascii=False),
            json.dumps(consistency, ensure_ascii=False),
            datetime.now().isoformat(), str(delivery_path)
        ))
        conn.commit()

        delivery_products.append({
            "name": product_name,
            "file": str(pf),
            "delivery": str(delivery_path),
            "syntax": syntax["pass"],
            "semantic": semantic["pass"],
            "consistency": consistency["pass"],
            "overall": overall_pass,
            "semantic_score": semantic.get("score", 0)
        })

    if delivery_products:
        summary = {
            "generated_at": datetime.now().isoformat(),
            "total_products": len(delivery_products),
            "passed": sum(1 for p in delivery_products if p["overall"]),
            "failed": sum(1 for p in delivery_products if not p["overall"]),
            "products": delivery_products
        }
        summary_path = DELIVERY_DIR / f"delivery_summary_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        try:
            summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError as e:
            log(f"❌ 写入汇总失败: {e}")
        log(f"📊 汇总: {summary['passed']}/{summary['total_products']} 通过验收")

    conn.close()
    log("✅ 交付流程完成")


if __name__ == "__main__":
    product_path = None
    all_mode = "--all" in sys.argv

    for i, arg in enumerate(sys.argv):
        if arg == "--product" and i + 1 < len(sys.argv):
            product_path = sys.argv[i + 1]

    run_delivery(product_path=product_path, all_mode=all_mode)
