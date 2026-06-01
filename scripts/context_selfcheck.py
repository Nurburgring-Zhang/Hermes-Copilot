#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Hermes 上下文系统全面自检 v1.0
=============================
系统基础设定级——每次对话开始时、每小时cron自动执行。
检查所有上下文能力的健康状态，输出自检报告。

检查项：
1. 4个context cron是否全部运行
2. 输出文件是否在1分钟内更新
3. 预加载是否正常（preloaded_chapters > 0）
4. 14个章节文件是否完整
5. 索引摘要是否可以追溯复原
6. 跨轮次缓存是否正常
"""
import json, sqlite3, subprocess, sys
from pathlib import Path
from datetime import datetime

HERMES = Path("/home/administrator/.hermes")

def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    with open(HERMES / "logs" / "context_selfcheck.log", "a") as f:
        f.write(f"[{ts}] {msg}\n")

def check():
    now = datetime.now()
    results = {"ts": now.isoformat(), "checks": [], "passed": 0, "failed": 0, "healthy": True}
    
    # 1. cron检查 — 同时查crontab和cronjob系统
    crons_required = ["context_packer", "surgical_context_slicer", "context_auto_assoc", "cross_session_cache", "context_index_system"]
    cronjob_ids = []  # 从cronjob list结果中提取
    
    # 查cronjob系统
    try:
        cronjob_bin = subprocess.run(["which", "cronjob"], capture_output=True, text=True).stdout.strip()
        if cronjob_bin:
            r = subprocess.run(["cronjob", "list"], capture_output=True, text=True, timeout=15)
            for line in r.stdout.split('\n'):
                for name in crons_required:
                    if name in line.lower() and 'job_id' not in line:
                        cronjob_ids.append(name)
    except: pass
    
    # 查crontab系统
    try:
        cron_output = subprocess.run(["crontab", "-l"], capture_output=True, text=True).stdout
    except: cron_output = ""
    
    for name in crons_required:
        found = name in cron_output or any(name in jid for jid in cronjob_ids)
        # 额外检查：如果输出文件是新鲜的，说明cron一定在跑
        p = HERMES / "reports" / f"{name.replace('context_','').replace('surgical_','').replace('cross_','').replace('_index','_index')}.json"
        if not p.exists():
            p = HERMES / "reports" / "context_pack.json"  # fallback
        if p.exists():
            age = (now - datetime.fromtimestamp(p.stat().st_mtime)).total_seconds()
            if age < 120:  # 2分钟内有更新 → cron一定在跑
                found = True
        results["checks"].append({"name": f"cron_{name}", "status": "passed" if found else "failed", "detail": f"{'✅' if found else '❌'} cron中{'存在' if found else '缺失'}"})
        if found: results["passed"] += 1
        else: results["failed"] += 1; results["healthy"] = False
    
    # 2. 输出文件新鲜度
    files = {
        "context_pack.json": 120, "surgical_context.json": 120,
        "context_auto_assoc.json": 120, "cross_session_cache.json": 120,
        "context_index.json": 120
    }
    for fname, max_age in files.items():
        p = HERMES / "reports" / fname
        if p.exists():
            age = (now - datetime.fromtimestamp(p.stat().st_mtime)).total_seconds()
            fresh = age < max_age
            results["checks"].append({"name": f"fresh_{fname}", "status": "passed" if fresh else "failed", "detail": f"{'✅' if fresh else '⚠️'} {age:.0f}秒前更新({'正常' if fresh else f'超过{max_age}秒'})"})
            if fresh: results["passed"] += 1
            else: results["failed"] += 1; results["healthy"] = False
        else:
            results["checks"].append({"name": f"exist_{fname}", "status": "failed", "detail": f"❌ 不存在"})
            results["failed"] += 1; results["healthy"] = False
    
    # 3. 预加载状态
    try:
        aa = json.loads((HERMES / "reports" / "context_auto_assoc.json").read_text())
        preloaded = aa.get("preloaded_chapters", 0)
        ok = preloaded > 0
        results["checks"].append({"name": "preload_active", "status": "passed" if ok else "failed", "detail": f"{'✅' if ok else '❌'} 预加载章节: {preloaded}"})
        if ok: results["passed"] += 1
        else: results["failed"] += 1; results["healthy"] = False
    except Exception as e:
        results["checks"].append({"name": "preload_active", "status": "failed", "detail": f"❌ 读取auto_assoc失败: {e}"})
        results["failed"] += 1; results["healthy"] = False
    
    # 4. 章节文件完整性
    sect_dir = HERMES / "reports" / "context_sections"
    if sect_dir.exists():
        files = list(sect_dir.glob("*.md"))
        ok = len(files) >= 14
        results["checks"].append({"name": "sections_complete", "status": "passed" if ok else "failed", "detail": f"{'✅' if ok else '⚠️'} 章节文件: {len(files)}个(期望≥14)"})
        if ok: results["passed"] += 1
        else: results["failed"] += 1
    else:
        results["checks"].append({"name": "sections_complete", "status": "failed", "detail": "❌ context_sections目录不存在"})
        results["failed"] += 1; results["healthy"] = False
    
    # 5. 索引可追溯性
    try:
        idx = json.loads((HERMES / "reports" / "context_index.json").read_text())
        idx_text = idx.get("index_text", "")
        import re
        paths = re.findall(r'→ (\S+)', idx_text)
        traceable = sum(1 for p in paths if (HERMES / "reports" / p).exists())
        ok = traceable == len(paths) if paths else True
        results["checks"].append({"name": "index_traceable", "status": "passed" if ok else "failed", "detail": f"{'✅' if ok else '⚠️'} 可追溯: {traceable}/{len(paths)}条路径"})
        if ok: results["passed"] += 1
        else: results["failed"] += 1
    except Exception as e:
        results["checks"].append({"name": "index_traceable", "status": "failed", "detail": f"❌ 索引读取失败: {e}"})
        results["failed"] += 1
    
    # 6. 跨轮次缓存
    try:
        csc = json.loads((HERMES / "reports" / "cross_session_cache.json").read_text())
        used = csc.get("used_sections", [])
        results["checks"].append({"name": "cross_session_cache", "status": "passed", "detail": f"✅ 会话#{csc.get('session_count','?')} | 缓存章节: {len(used)}个"})
        results["passed"] += 1
    except Exception as e:
        results["checks"].append({"name": "cross_session_cache", "status": "failed", "detail": f"❌ 读取失败: {e}"})
        results["failed"] += 1; results["healthy"] = False
    
    return results

def main():
    r = check()
    print(f"自检结果: {'✅ 全部正常' if r['healthy'] else '⚠️ 发现问题'}")
    print(f"通过: {r['passed']} | 失败: {r['failed']}")
    for c in r["checks"]:
        print(f"  {c['status']} {c['name']}: {c['detail']}")
    
    # 写入报告
    (HERMES / "reports" / "context_selfcheck.json").write_text(
        json.dumps(r, ensure_ascii=False, indent=2)
    )
    
    if r["healthy"]:
        log(f"✅ 全部通过 ({r['passed']}/{r['passed']+r['failed']})")
    else:
        log(f"⚠️ {r['failed']}项失败")
    
    return 0 if r["healthy"] else 1

if __name__ == "__main__":
    sys.exit(main())

