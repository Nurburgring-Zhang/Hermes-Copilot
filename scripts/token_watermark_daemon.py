#!/usr/bin/env python3
"""
Hermes 对话token水位监控+自动压缩守护 v1.0
=========================================
由cron每1分钟运行，监控当前上下文token水位。
如果超过阈值，自动生成压缩版上下文供Hermes下次对话使用。

集成方式：作为gear_enforcer的补充环节
"""

import json, sys, os, time
from pathlib import Path
from datetime import datetime

HERMES = Path("/home/administrator/.hermes")
sys.path.insert(0, str(HERMES / "scripts"))
import context_token_filter as ctf

# 监控阈值
WARN_TOKEN = 15000    # 警告线
CRIT_TOKEN = 25000    # 危险线

def scan_context_sources() -> dict:
    """扫描所有可能占用上下文的文件"""
    sources = []
    total_tokens = 0
    
    # 1. SOUL.md
    soul = HERMES / "SOUL.md"
    if soul.exists():
        t = ctf.estimate_tokens(soul.read_text(encoding='utf-8', errors='ignore'))
        sources.append({"file": "SOUL.md", "tokens": t})
        total_tokens += t
    
    # 2. AGENTS.md
    agents = HERMES / "AGENTS.md"
    if agents.exists():
        t = ctf.estimate_tokens(agents.read_text(encoding='utf-8', errors='ignore'))
        sources.append({"file": "AGENTS.md", "tokens": t})
        total_tokens += t
    
    # 3. 最近对话历史（session数据库最近N条）
    sess_db = HERMES / "sessions.db"
    if sess_db.exists():
        try:
            import sqlite3
            conn = sqlite3.connect(str(sess_db))
            c = conn.cursor()
            # 尝试找最近的对话
            tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            for t in tables[:1]:
                tn = t[0]
                rows = conn.execute(f"SELECT COUNT(*) FROM \"{tn}\"").fetchall()
                if rows and rows[0][0] > 0:
                    sources.append({"file": f"sessions/{tn}", "count": rows[0][0]})
            conn.close()
        except Exception as e:
            sources.append({"file": "sessions.db", "error": str(e)})
    
    # 4. gear_checkpoint
    gp = HERMES / "reports" / "gear_checkpoint.json"
    if gp.exists():
        t = ctf.estimate_tokens(gp.read_text(encoding='utf-8', errors='ignore'))
        sources.append({"file": "reports/gear_checkpoint.json", "tokens": t})
        total_tokens += t
    
    # 5. task_current
    tc = HERMES / "task_current.json"
    if tc.exists():
        t = ctf.estimate_tokens(tc.read_text(encoding='utf-8', errors='ignore'))
        sources.append({"file": "task_current.json", "tokens": t})
        total_tokens += t
    
    return {"sources": sources, "total_tokens": total_tokens}

def write_compressed_context():
    """生成压缩后的上下文供下次对话使用"""
    soul = HERMES / "SOUL.md"
    agents = HERMES / "AGENTS.md"
    
    combined = ""
    if soul.exists():
        combined += soul.read_text(encoding='utf-8', errors='ignore') + "\n"
    if agents.exists():
        combined += agents.read_text(encoding='utf-8', errors='ignore')
    
    if not combined:
        return None
    
    # 压缩
    result = ctf.compress_context(combined, max_tokens=3000)
    
    # 写入压缩版
    compressed_path = HERMES / "reports" / "compressed_context.md"
    compressed_path.write_text(result["compressed_text"], encoding='utf-8')
    
    # 更新wake_guide
    wg_path = HERMES / "reports" / "wake_guide.json"
    if wg_path.exists():
        try:
            wg = json.loads(wg_path.read_text())
            wg["compressed_context_tokens"] = result["final_tokens"]
            wg["compressed_context_ratio"] = result["total_compression_ratio"]
            wg_path.write_text(json.dumps(wg, ensure_ascii=False, indent=2))
        except:
            pass
    
    return result

def main():
    # 扫描
    scan = scan_context_sources()
    
    # 生成压缩版
    compressed = write_compressed_context()
    
    # 报告
    report = {
        "ts": datetime.now().isoformat(),
        "total_token_estimate": scan["total_tokens"],
        "sources": scan["sources"],
        "compressed_available": compressed is not None,
    }
    
    if compressed:
        report["compression"] = {
            "original_tokens": compressed["original_tokens"],
            "final_tokens": compressed["final_tokens"],
            "ratio_pct": compressed["total_compression_ratio"]
        }
    
    # 是否超过阈值
    if scan["total_tokens"] > CRIT_TOKEN:
        report["alert"] = f"CRITICAL: {scan['total_tokens']} tokens > {CRIT_TOKEN}"
    elif scan["total_tokens"] > WARN_TOKEN:
        report["alert"] = f"WARN: {scan['total_tokens']} tokens > {WARN_TOKEN}"
    else:
        report["alert"] = None
    
    # 输出到文件供wake_guide读取
    report_path = HERMES / "reports" / "token_watermark.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    
    # stdout供cron日志
    if report["alert"]:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] ⚠️ {report['alert']}")
    if compressed:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] ✅ 压缩上下文: {compressed['original_tokens']}→{compressed['final_tokens']}tokens ({compressed['total_compression_ratio']}%)")
    else:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] ✅ token水位: {scan['total_tokens']}tokens")

if __name__ == "__main__":
    main()
