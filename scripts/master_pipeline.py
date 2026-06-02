#!/usr/bin/env python3
"""
Hermes 全自动化情报管线 (Master Pipeline)
==========================================
采集 → 清洗 → 评估 → 推送 一体化执行

Cron调度:
  采集: */30 * * * *  (每30分钟快速采集)
  采集: 0 */4 * * *   (每4小时全量采集)
  清洗: */15 * * * *  (每15分钟批量清洗)
  推送: 0 8,12,18,22 * * *  (每日4次推送)

用法:
  python3 master_pipeline.py --collect           # 仅采集
  python3 master_pipeline.py --collect --full    # 全量采集
  python3 master_pipeline.py --clean             # 仅清洗
  python3 master_pipeline.py --push              # 仅推送
  python3 master_pipeline.py --all               # 全流程
  python3 master_pipeline.py --daily             # 日报模式
"""

import os, sys, json, sqlite3, logging, subprocess
from pathlib import Path
from datetime import datetime, date
from typing import Dict, Any

HERMES = Path("/home/administrator/.hermes")
DB_PATH = HERMES / "intelligence.db"
LOG_DIR = HERMES / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / f"pipeline_{datetime.now().strftime('%Y%m%d')}.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger("master_pipeline")

SCRIPTS_DIR = HERMES / "scripts"

def run_script(name: str, args: list = [], timeout: int = 120) -> Dict[str, Any]:
    """执行子脚本并返回结果"""
    script_path = SCRIPTS_DIR / name
    if not script_path.exists():
        return {"success": False, "error": f"Script not found: {name}"}
    
    cmd = [sys.executable, str(script_path)] + args
    log.info(f"执行: {' '.join(cmd[-3:])}")
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(HERMES)
        )
        output = result.stdout + result.stderr
        
        return {
            "success": result.returncode == 0,
            "returncode": result.returncode,
            "stdout": result.stdout[:1000],
            "stderr": result.stderr[:500],
            "output": output[:2000],
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "error": f"Timeout after {timeout}s"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def step_collect(full: bool = False) -> Dict[str, Any]:
    """步骤1: 采集"""
    log.info("=" * 40)
    log.info("STEP 1: 情报采集")
    log.info("=" * 40)
    
    args = []
    if not full:
        args.append("--quick")
    
    result = run_script("unified_collector.py", args, timeout=180)
    
    if result["success"]:
        # 解析输出获取统计
        try:
            stats = json.loads(result["stdout"].split("采集统计:")[-1].strip())
        except:
            stats = {"raw": "unknown"}
        log.info(f"采集完成: {stats}")
        return {"success": True, "stats": stats}
    else:
        log.error(f"采集失败: {result.get('error', '')}")
        return {"success": False, "error": result.get("error", "")}


def step_clean(batch_size: int = 200) -> Dict[str, Any]:
    """步骤2: 清洗"""
    log.info("=" * 40)
    log.info("STEP 2: 情报清洗")
    log.info("=" * 40)
    
    result = run_script("unified_cleaning_pipeline.py", ["--batch", str(batch_size)], timeout=120)
    
    if result["success"]:
        try:
            stats = json.loads(result["stdout"].strip())
        except:
            stats = result
        log.info(f"清洗完成: {stats}")
        return {"success": True, "stats": stats}
    else:
        log.error(f"清洗失败: {result.get('error', '')}")
        return {"success": False, "error": result.get("error", "")}


def step_push(mode: str = "normal") -> Dict[str, Any]:
    """步骤3: 推送"""
    log.info("=" * 40)
    log.info(f"STEP 3: 情报推送 ({mode})")
    log.info("=" * 40)
    
    import yaml
    cfg = {}
    cfg_path = HERMES / "config.yaml"
    if cfg_path.exists():
        with open(cfg_path) as f:
            cfg = yaml.safe_load(f) or {}
    
    token = cfg.get("pushplus", {}).get("token", "")
    if not token:
        token = os.environ.get("PUSHPLUS_TOKEN", "")
    
    if not token:
        log.warning("PushPlus token未配置,跳过推送")
        return {"success": False, "error": "PushPlus token not configured"}
    
    args = []
    if mode == "daily":
        args = ["--daily"]
    elif mode == "urgent":
        args = ["--urgent"]
    elif mode == "preview":
        args = ["--preview"]
    
    result = run_script("unified_pusher.py", args, timeout=60)
    
    if result["success"]:
        log.info(f"推送完成")
        return {"success": True}
    else:
        # 可能是内容为空,不是错误
        if "no_data" in result.get("output", ""):
            log.info("无可推送内容")
            return {"success": True, "skipped": True}
        log.warning(f"推送: {result.get('error', '')}")
        return {"success": False, "error": result.get("error", "")}


def get_pipeline_stats() -> Dict[str, Any]:
    """获取管线状态"""
    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.cursor()
    
    stats = {}
    
    try:
        cur.execute("SELECT COUNT(*) FROM raw_intelligence")
        stats["raw_total"] = cur.fetchone()[0]
        
        cur.execute("SELECT COUNT(*) FROM cleaned_intelligence")
        stats["cleaned_total"] = cur.fetchone()[0]
        
        cur.execute("SELECT COUNT(*) FROM cleaned_intelligence WHERE is_processed=1")
        stats["processed_total"] = cur.fetchone()[0]
        
        cur.execute("SELECT COUNT(*) FROM raw_intelligence WHERE collected_at >= datetime('now', '-1 day')")
        stats["raw_today"] = cur.fetchone()[0]
        
        cur.execute("SELECT COUNT(*) FROM cleaned_intelligence WHERE cleaned_at >= datetime('now', '-1 day')")
        stats["cleaned_today"] = cur.fetchone()[0]
        
        cur.execute("SELECT COUNT(*) FROM push_records WHERE created_at >= datetime('now', '-1 day')")
        stats["pushed_today"] = cur.fetchone()[0]
        
        cur.execute("SELECT platform, COUNT(*) FROM raw_intelligence WHERE collected_at >= datetime('now', '-1 day') GROUP BY platform")
        stats["sources_active"] = dict(cur.fetchall())
        
    except Exception as e:
        stats["error"] = str(e)
    
    conn.close()
    return stats


def run_full_pipeline(full: bool = False, push: bool = True) -> Dict[str, Any]:
    """执行完整管线"""
    results = {
        "started_at": datetime.now().isoformat(),
        "steps": {},
    }
    
    # 采集
    c_result = step_collect(full=full)
    results["steps"]["collect"] = c_result
    
    # 清洗
    cl_result = step_clean(batch_size=300 if full else 150)
    results["steps"]["clean"] = cl_result
    
    # 推送
    if push:
        p_result = step_push()
        results["steps"]["push"] = p_result
    
    results["finished_at"] = datetime.now().isoformat()
    results["stats"] = get_pipeline_stats()
    
    log.info("=" * 40)
    log.info("管线执行完成")
    log.info(f"统计: {json.dumps(results['stats'], ensure_ascii=False)}")
    log.info("=" * 40)
    
    return results


def run_daily_report() -> Dict[str, Any]:
    """日报模式"""
    results = {"started_at": datetime.now().isoformat()}
    
    # 先清洗最新数据
    step_clean(batch_size=500)
    
    # 执行日报推送
    p_result = step_push(mode="daily")
    results["push"] = p_result
    
    results["finished_at"] = datetime.now().isoformat()
    results["stats"] = get_pipeline_stats()
    
    return results


# ── CLI ────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Hermes 全自动化情报管线")
    parser.add_argument("--collect", action="store_true", help="仅采集")
    parser.add_argument("--clean", action="store_true", help="仅清洗")
    parser.add_argument("--push", action="store_true", help="仅推送")
    parser.add_argument("--all", action="store_true", help="全流程")
    parser.add_argument("--daily", action="store_true", help="日报模式")
    parser.add_argument("--full", action="store_true", help="全量采集(非快速)")
    parser.add_argument("--status", action="store_true", help="查看管线状态")
    args = parser.parse_args()
    
    if args.status:
        stats = get_pipeline_stats()
        print(f"\n{'='*50}")
        print(f"Hermes 情报管线状态")
        print(f"{'='*50}")
        print(f"原始情报总数:    {stats.get('raw_total', 0):,}")
        print(f"清洗后情报总数:  {stats.get('cleaned_total', 0):,}")
        print(f"今日新增原始:    {stats.get('raw_today', 0):,}")
        print(f"今日新增清洗:    {stats.get('cleaned_today', 0):,}")
        print(f"今日已推送:      {stats.get('pushed_today', 0):,}")
        print(f"今日活跃数据源:  {len(stats.get('sources_active', {}))}")
        print(f"各源统计: {stats.get('sources_active', {})}")
    elif args.collect:
        result = step_collect(full=args.full)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.clean:
        result = step_clean()
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.push:
        result = step_push()
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.daily:
        result = run_daily_report()
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.all:
        result = run_full_pipeline(full=args.full)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        # 默认:全流程
        result = run_full_pipeline()
        print(json.dumps(result, ensure_ascii=False, indent=2))
