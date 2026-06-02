#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Hermes 底层对话层压缩钩子 v1.0
================================
在每次Hermes对话开始时作为"步骤0"自动执行。

职责：
1. 检测当前是否首轮对话（通过cross_session_cache的session_count判断）
2. 首轮 → 不做特殊处理（SOUL.md全量已在system prompt中）
3. 非首轮 → 检查当前上下文是否已加载压缩版（检查context_pack版本标记）
4. 如果上下文过大 → 触发压缩

使用方式：
  python3 scripts/dialogue_context_init.py
"""

import json, sys, os
from pathlib import Path
from datetime import datetime

HERMES = Path(os.environ.get("HERMES_PATH", "/home/administrator/.hermes"))

# ── 阈值常量 ──────────────────────────────────────────────
TOKEN_LIMIT_HIGH = 8000       # tokens超过此值触发压缩警告
COMPRESSION_VERSION_FILE = "reports/compression_version.json"

def estimate_tokens(text: str) -> int:
    """估算文本token数（中文*1.5，英文*1.3）"""
    cn = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    en = len(text) - cn
    return int(cn * 1.5 + en * 1.3)

def get_compression_version() -> dict:
    """读取当前压缩版本标记"""
    path = HERMES / COMPRESSION_VERSION_FILE
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            pass
    return {"version": "unknown", "compressed": False, "last_update": None}

def update_compression_version(compressed: bool = True, version: str = None):
    """更新压缩版本标记"""
    path = HERMES / COMPRESSION_VERSION_FILE
    data = get_compression_version()
    data["version"] = version or datetime.now().strftime("%Y%m%d_%H%M%S")
    data["compressed"] = compressed
    data["last_update"] = datetime.now().isoformat()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False))

def is_first_round() -> bool:
    """检测是否为首次对话"""
    cache = HERMES / "reports" / "cross_session_cache.json"
    if not cache.exists():
        return True  # 无缓存 = 首次
    try:
        data = json.loads(cache.read_text())
        sc = data.get("session_count", 0)
        return sc == 0
    except Exception:
        return True

def check_context_overload() -> dict:
    """
    检查当前上下文是否过大。
    读取context_pack.json判断压缩版本和token量。
    """
    result = {
        "status": "ok",
        "first_round": False,
        "compressed": False,
        "tokens": 0,
        "diagnostic": ""
    }

    first = is_first_round()
    result["first_round"] = first

    if first:
        result["status"] = "skip_first_round"
        result["diagnostic"] = "首轮对话：SOUL.md全量已在system prompt中，跳过压缩检查"
        return result

    # 非首轮：检查压缩版本
    cv = get_compression_version()
    result["compressed"] = cv.get("compressed", False)

    # 检查context_pack.json的token量
    pack = HERMES / "reports" / "context_pack.json"
    if pack.exists():
        tokens = estimate_tokens(pack.read_text())
        result["tokens"] = tokens

        if tokens > TOKEN_LIMIT_HIGH and not result["compressed"]:
            result["status"] = "overload_warning"
            result["diagnostic"] = (
                f"上下文过大：{tokens}tokens > 阈值{TOKEN_LIMIT_HIGH}tokens，"
                f"且未标记为压缩版。建议触发context_packer压缩。"
            )
        elif not result["compressed"]:
            result["status"] = "not_compressed"
            result["diagnostic"] = (
                f"context_pack.json {tokens}tokens，未压缩标记。"
                f"建议运行context_packer确保使用压缩版。"
            )
        else:
            result["status"] = "compressed_ok"
            result["diagnostic"] = (
                f"压缩版已加载（v{cv.get('version', '?')}），{tokens}tokens，状态健康"
            )
    else:
        result["status"] = "no_pack"
        result["diagnostic"] = "context_pack.json不存在，跳过上下文大小检查"

    return result

def ensure_compression():
    """确保上下文已压缩。如果未压缩则触发context_packer。"""
    result = check_context_overload()

    # 输出诊断信息（这些会出现在agent的上下文中）
    print(f"[对话层压缩钩子] session状态: {'首轮' if result['first_round'] else '非首轮'}")
    print(f"  压缩标记: {'是(v' + get_compression_version().get('version', '?') + ')' if result['compressed'] else '否'}")
    print(f"  context_pack tokens: {result['tokens']}")
    print(f"  诊断: {result['diagnostic']}")

    # ── 武器库注入v2.0: 先问LLM, 再系统执行 ──
    try:
        sys.path.insert(0, str(HERMES))
        from scripts.engine_core import ArsenalRegistry
        
        registry = ArsenalRegistry()
        summary = registry.summary()
        
        # 获取wake_guide中的当前任务
        task = "通用"
        wg = HERMES / "reports" / "wake_guide.json"
        if wg.exists():
            try:
                wg_data = json.loads(wg.read_text())
                interrupted = str(wg_data.get("interrupted_task", ""))
                if interrupted:
                    task = interrupted
            except:
                pass
        
        # ════════════════════════════════════════════════════════════
        # v3.0 系统级强制: 强制多武器+深度分解
        # ════════════════════════════════════════════════════════════
        # 流程:
        #   1. 告诉LLM: "这个任务可以同时使用哪些武器? 至少选3个!"
        #   2. 告诉LLM: "这个任务可以拆成几个阶段? 至少3个!"
        #   3. LLM输出JSON方案(武器+分段+并行)
        #   4. 系统自动执行全部武器
        #   5. LLM基于结果做总结
        forced_context = ""
        if task != "通用" and len(str(task)) > 5:
            try:
                from scripts.forced_executor import LLMForcedExecutorV3
                executor = LLMForcedExecutorV3()
                
                # 先尝试用LLM获取方案
                llm_response = executor.query_llm(executor.build_weapon_query(str(task)))
                
                if llm_response:
                    plan = executor.parse_llm_plan(llm_response)
                    # 检查是否少于3个武器/阶段
                    if plan.get("total_weapons_selected", 0) < 3 or plan.get("total_segments", 0) < 3:
                        # 再问一次强制分解
                        llm_response2 = executor.query_llm(executor.build_decomposition_query(str(task)))
                        if llm_response2:
                            plan2 = executor.parse_llm_plan(llm_response2)
                            if plan2.get("total_segments", 0) > plan.get("total_segments", 0):
                                plan = plan2
                else:
                    plan = executor._fallback_plan(str(task))
                
                tw = plan.get("total_weapons_selected", 0)
                ts = plan.get("total_segments", 0)
                print(f"\n  [强制执行] 方案: {tw}个武器 × {ts}个阶段")
                
                # 系统自动执行
                exec_results = executor.execute_plan(plan, str(task))
                forced_context = executor.build_force_context(plan, exec_results)
                
                print(forced_context)
                
            except Exception as fe:
                forced_context = f"\n[强制执行] 加载失败: {fe}\n"
                import traceback
                print(f"\n[强制执行] 异常详情: {traceback.format_exc()[:500]}\n")
        
        # 输出武器库摘要
        print(f"\n⚔️ 武器库: {summary['total']}件 (scripts {summary['scripts']} / skills {summary['skills']} / 员工 {summary['employees']} / 专家 {summary['experts']})")
        print()
        
    except Exception as e:
        print(f"  [武器库] 加载异常: {e}")
    # ── 武器库注入结束 ──
    
    # 原压缩逻辑
    if result["status"] in ("overload_warning", "not_compressed"):
        # 触发压缩 — 直接调用context_packer
        print("  → 触发context_packer压缩...")
        import subprocess
        try:
            r = subprocess.run(
                [sys.executable, str(HERMES / "scripts" / "context_packer.py"), "general"],
                capture_output=True, text=True, timeout=30,
                cwd=str(HERMES)
            )
            if r.returncode == 0:
                # 标记为已压缩
                update_compression_version(True)
                print(f"  ✅ 压缩完成: {r.stdout.strip()[:200]}")
            else:
                print(f"  ⚠️ 压缩失败: {r.stderr.strip()[:200]}")
        except Exception as e:
            print(f"  ⚠️ 压缩异常: {e}")

        # 触发索引更新
        try:
            r = subprocess.run(
                [sys.executable, str(HERMES / "scripts" / "context_index_system.py"), "auto"],
                capture_output=True, text=True, timeout=30,
                cwd=str(HERMES)
            )
            if r.returncode == 0:
                print(f"  ✅ 索引已更新")
            else:
                print(f"  ⚠️ 索引更新失败: {r.stderr.strip()[:200]}")
        except Exception as e:
            print(f"  ⚠️ 索引异常: {e}")

    elif result["status"] == "compressed_ok":
        print("  ✅ 压缩版已就绪，无需额外操作")

    return result

# ── 主入口 ────────────────────────────────────────────────
if __name__ == "__main__":
    ensure_compression()
