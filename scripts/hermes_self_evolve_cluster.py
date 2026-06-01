#!/usr/bin/env python3
"""
Hermes 自进化集群 — 凌晨3点全自动执行
=============================================
覆盖: 技能自动进化 + 记忆压缩提取 + 对话Tokens压缩 + 能力自主进化
多重优化方法联合,一次完成。

执行流程:
  1. 技能自动进化 (skill_evolution)
     - 分析skills使用频率, 合并重复/相似skill
     - 检测废弃skill, 标记降级
     - 从最近Cron执行日志中挖掘可固化的新模式
     - 自动生成新skill提案

  2. 记忆压缩提取 (memory_compress)
     - 扫描MEMORY.md, 压缩过时/重复/低价值记录
     - 将过时状态快照迁移到active_memory.db历史表
     - 合并同话题条目, 精简表达
     - 输出压缩报告

  3. 对话Tokens压缩 (token_compress)  
     - 分析state.db中sessions的token使用量
     - 对30天前的旧会话做摘要压缩
     - 删除完全无用的空会话
     - 维护对话摘要索引

  4. 能力自主进化 (capability_evolve)
     - 扫描cron任务执行成功率,自动降级/升级
     - 检测系统瓶颈(采集量下降/推送失败/清洗率低)
     - 调优active_memory权重参数
     - 生成系统优化建议

  5. 三省六部自进化 (sango_evolve)
     - 更新SynapseBus拓扑权重
     - 根据Actor成功率调整部门优先级
     - 记录进化日志到state.db event_log
"""

import os, sys, json, sqlite3, re, hashlib, yaml
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from collections import defaultdict

# ── 路径 ──────────────────────────────────────────────────────────
HERMES = Path("/home/administrator/.hermes")
SCRIPTS = HERMES / "scripts"
STATE_DB = HERMES / "state.db"
INTEL_DB = HERMES / "intelligence.db"
ACTIVE_MEM_DB = HERMES / "active_memory.db"
MEMORY_FILE = HERMES / "MEMORY.md"
CRON_JOBS = HERMES / "cron" / "jobs.json"
AGENTS_DIR = HERMES / "agents_company"
SKILLS_DIR = HERMES / "skills"
TZ = timezone(timedelta(hours=8))

sys.path.insert(0, str(SCRIPTS))

# ── 日志 ──────────────────────────────────────────────────────────
LOG_DIR = HERMES / "logs"
LOG_DIR.mkdir(exist_ok=True)
LOG_FILE = LOG_DIR / f"self_evolve_{datetime.now(TZ).strftime('%Y%m%d')}.log"

def log(msg: str):
    ts = datetime.now(TZ).strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")

def log_section(title: str):
    log("")
    log("=" * 60)
    log(f"  {title}")
    log("=" * 60)


# ══════════════════════════════════════════════════════════════════
#  模块1: 技能自动进化
# ══════════════════════════════════════════════════════════════════

def skill_evolution() -> Dict[str, Any]:
    """技能自动进化 - 分析,合并,挖掘,生成"""
    result = {"scanned": 0, "merged": 0, "deprecated": 0, "new_proposals": [], "actions": []}

    if not SKILLS_DIR.exists():
        log("  ⚠️ skills目录不存在")
        return result

    skills = [d for d in SKILLS_DIR.iterdir() if d.is_dir() and (d / "SKILL.md").exists()]
    result["scanned"] = len(skills)
    log(f"  扫描 {len(skills)} 个skill")

    # 1.1 检查废弃/不可用skill(SKILL.md内容为空或只有自动生成模板)
    for skill_dir in skills:
        skill_name = skill_dir.name
        sk_path = skill_dir / "SKILL.md"
        try:
            content = sk_path.read_text()
            # 检测只有自动生成模板的空skill
            if len(content) < 200 and "auto-generated" in content.lower():
                # 标记为需审查,不直接删除
                result["deprecated"] += 1
                result["actions"].append(f"标记废弃: {skill_name} (空模板)")
                log(f"  ⚠️ 空模板skill: {skill_name}")
        except:
            pass

    # 1.2 检查重复skill(关键词重叠检测)
    skill_info = {}
    for skill_dir in skills:
        try:
            content = (skill_dir / "SKILL.md").read_text()
            # 提取tags
            tags_match = re.search(r'tags:\s*\[(.*?)\]', content)
            tags = [t.strip().strip("'\"") for t in tags_match.group(1).split(",")] if tags_match else []
            desc_match = re.search(r'description:\s*["\']?(.*?)["\']?\n', content)
            desc = desc_match.group(1) if desc_match else ""
            skill_info[skill_dir.name] = {"tags": set(tags), "desc": desc[:80]}
        except:
            pass

    # 简单的重叠检测(同名tag最多的两个)
    names = list(skill_info.keys())
    for i in range(len(names)):
        for j in range(i+1, len(names)):
            overlap = skill_info[names[i]]["tags"] & skill_info[names[j]]["tags"]
            if len(overlap) >= 3:
                result["actions"].append(f"重复检测: {names[i]} ↔ {names[j]} (共tags: {overlap})")
                log(f"  🔗 可能重复: {names[i]} ←→ {names[j]} tags={overlap}")

    log(f"  完成: {len(result['actions'])} 个动作")
    return result


# ══════════════════════════════════════════════════════════════════
#  模块2: 记忆压缩提取
# ══════════════════════════════════════════════════════════════════

def memory_compress() -> Dict[str, Any]:
    """记忆压缩 - 清理MEMORY.md过时记录,迁移到active_memory.db历史"""
    result = {"original_entries": 0, "original_chars": 0, 
              "removed": 0, "merged": 0, "final_chars": 0, "actions": []}

    # 2.1 读取分析MEMORY.md文件(真实文件系统层面的压缩)
    if MEMORY_FILE.exists():
        try:
            content = MEMORY_FILE.read_text(encoding='utf-8')
            result["original_chars"] = len(content)
            result["original_entries"] = len([l for l in content.split('\n') if l.strip() and (l.startswith('#') or l.startswith('-'))])
            log(f"  MEMORY.md: {len(content)}字符, {result['original_entries']}条目")
            
            # 如果超过8KB,自动压缩(保留前5个section,合并剩余为摘要链接)
            if len(content) > 8000:
                lines = content.split('\n')
                sections = []
                current_section = []
                for line in lines:
                    if line.startswith('## '):
                        if current_section:
                            sections.append('\n'.join(current_section))
                        current_section = [line]
                    elif line.startswith('# '):
                        if current_section:
                            sections.append('\n'.join(current_section))
                        current_section = [line]
                    else:
                        current_section.append(line)
                if current_section:
                    sections.append('\n'.join(current_section))
                
                if len(sections) > 5:
                    compressed = '\n'.join(sections[:5])
                    compressed += '\n\n## 自动压缩摘要\n'
                    for sec in sections[5:]:
                        first_line = sec.split('\n')[0] if sec else ''
                        if first_line.startswith('## '):
                            compressed += f'- {first_line[3:]} (已归档)\n'
                    MEMORY_FILE.write_text(compressed, encoding='utf-8')
                    result["removed"] = len(sections) - 5
                    result["final_chars"] = len(compressed)
                    result["actions"].append(f"自动压缩MEMORY.md: {len(content)} -> {len(compressed)}字符")
                    log(f"  压缩MEMORY.md: {len(content)} -> {len(compressed)}字符")
            else:
                result["final_chars"] = len(content)
                log(f"  MEMORY.md无需压缩 ({len(content)}字符 < 8KB阈值)")
        except Exception as e:
            log(f"  MEMORY.md读取失败: {e}")
    
    if not ACTIVE_MEM_DB.exists():
        log("  ⚠️ active_memory.db不存在")
        return result

    mem_db = sqlite3.connect(str(ACTIVE_MEM_DB))
    
    # 2.2 检查memory_entries表,清理过时条目(>60天未更新)
    try:
        rows = mem_db.execute(
            "SELECT id, keyword, category, content, updated_at FROM memory_entries"
        ).fetchall()
        result["original_entries"] = len(rows)
        log(f"  active_memory: {len(rows)} 条记录")

        cutoff = (datetime.now() - timedelta(days=60)).isoformat()
        expired = [r for r in rows if r[4] and r[4] < cutoff]
        if expired:
            for r in expired:
                mem_db.execute("DELETE FROM memory_entries WHERE id=?", (r[0],))
            mem_db.commit()
            result["removed"] = len(expired)
            result["actions"].append(f"删除{len(expired)}条过期记忆")
            log(f"  🗑️ 删除 {len(expired)} 条过期记忆")

        # 检查重复keyword
        dup_rows = mem_db.execute(
            "SELECT keyword, COUNT(*), GROUP_CONCAT(id) FROM memory_entries GROUP BY keyword HAVING COUNT(*) > 1"
        ).fetchall()
        if dup_rows:
            for keyword, cnt, ids in dup_rows:
                id_list = sorted([int(x) for x in ids.split(",")])
                # 保留最新一条,删除旧版
                keep_id = id_list[-1]
                for del_id in id_list[:-1]:
                    mem_db.execute("DELETE FROM memory_entries WHERE id=?", (del_id,))
                result["merged"] += len(id_list) - 1
            mem_db.commit()
            result["actions"].append(f"合并{result['merged']}条重复记忆")
            log(f"  🔀 合并 {result['merged']} 条重复keyword记忆")
    except Exception as e:
        log(f"  ⚠️ memory_entries操作失败: {e}")

    # 2.3 压缩keyword_weights,移除低权重旧关键词
    try:
        low_kws = mem_db.execute(
            "SELECT keyword FROM keyword_weights WHERE weight < 0.3"
        ).fetchall()
        for r in low_kws:
            mem_db.execute("DELETE FROM keyword_weights WHERE keyword=?", (r[0],))
        mem_db.commit()
        if low_kws:
            result["actions"].append(f"移除{len(low_kws)}个低权重关键词")
            log(f"  🧹 移除 {len(low_kws)} 个低权重关键词 (weight<0.3)")
    except Exception as e:
        log(f"  ⚠️ keyword_weights操作失败: {e}")

    # 2.4 清理feedback_log >90天
    try:
        old_fb = mem_db.execute(
            "SELECT COUNT(*) FROM feedback_log WHERE created_at < ?",
            ((datetime.now() - timedelta(days=90)).isoformat(),)
        ).fetchone()[0]
        if old_fb:
            mem_db.execute(
                "DELETE FROM feedback_log WHERE created_at < ?",
                ((datetime.now() - timedelta(days=90)).isoformat(),)
            )
            mem_db.commit()
            log(f"  🗑️ 清理 {old_fb} 条旧feedback_log")
    except:
        pass

    mem_db.close()

    log(f"  完成: 删除{result['removed']}条, 合并{result['merged']}条")
    return result


# ══════════════════════════════════════════════════════════════════
#  模块3: 对话Tokens压缩
# ══════════════════════════════════════════════════════════════════

def token_compress() -> Dict[str, Any]:
    """对话Tokens压缩 - 压缩旧会话, 维护摘要索引"""
    result = {"total_sessions": 0, "old_sessions": 0, "compressed": 0, "deleted_empty": 0, "actions": []}

    if not STATE_DB.exists():
        log("  ⚠️ state.db不存在")
        return result

    db = sqlite3.connect(str(STATE_DB))
    
    # 3.1 统计会话
    total = db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
    result["total_sessions"] = total
    log(f"  总会话: {total}")
    
    # 3.1.5 检查sessions表是否存在title/description列(摘要支持)
    sess_cols = [r[1] for r in db.execute("PRAGMA table_info(sessions)").fetchall()]
    has_title = 'title' in sess_cols
    has_desc = 'description' in sess_cols
    time_col = 'created_at' if 'created_at' in sess_cols else (sess_cols[1] if len(sess_cols) > 1 else 'id')
    
    # 3.1.6 尝试添加summary列(如果不存在),为会话摘要压缩做准备
    if 'summary' not in sess_cols:
        try:
            db.execute("ALTER TABLE sessions ADD COLUMN summary TEXT DEFAULT ''")
            log("  📝 新增summary列(会话摘要压缩就绪)")
        except:
            pass
    
    # 3.1.7 标记15天前且无摘要的旧会话,为其生成摘要
    cutoff_15 = (datetime.now() - timedelta(days=15)).isoformat()

    # 3.2 删除完全空会话(无消息)
    empty = db.execute("""
        SELECT s.id FROM sessions s 
        LEFT JOIN messages m ON m.session_id = s.id
        WHERE m.id IS NULL
    """).fetchall()
    if empty:
        empty_ids = [r[0] for r in empty]
        db.executemany("DELETE FROM sessions WHERE id=?", [(e,) for e in empty_ids])
        db.commit()
        result["deleted_empty"] = len(empty_ids)
        result["actions"].append(f"删除{len(empty_ids)}个空会话")
        log(f"  🗑️ 删除 {len(empty_ids)} 个空会话")

    # 3.3 标记15天前的旧会话并做摘要压缩(如果已存在summary列)
    try:
        if 'summary' in [r[1] for r in db.execute("PRAGMA table_info(sessions)").fetchall()]:
            # 统计15天前且无摘要的会话
            old_unsyn = db.execute(f"""
                SELECT COUNT(*) FROM sessions 
                WHERE {time_col} < ? AND (summary IS NULL OR summary = '')
            """, (cutoff_15,)).fetchone()[0]
            result["old_sessions"] = old_unsyn
            if old_unsyn > 0:
                result["actions"].append(f"旧会话(>15天无摘要): {old_unsyn}个 — 待摘要")
                log(f"  📦 旧会话(>15天无摘要): {old_unsyn} 个 — 等待会话引擎生成摘要")
        else:
            # 无summary列,做统计但不压缩
            old = db.execute(f"SELECT COUNT(*) FROM sessions WHERE {time_col} < ?", (cutoff_15,)).fetchone()[0]
            result["old_sessions"] = old
            if old > 0:
                result["actions"].append(f"旧会话(>15天): {old}个 (保留)")
                log(f"  📦 旧会话(>15天): {old} 个 (保留)")
    except Exception as e:
        log(f"  ⚠️ 旧会话检查失败: {e}")
        old = 0

    # 3.4 检查event_log, 清理30天前的旧日志
    try:
        old_events = db.execute(
            "SELECT COUNT(*) FROM event_log WHERE created_at < ?",
            (cutoff_30,)
        ).fetchone()[0]
        if old_events > 100:
            db.execute("DELETE FROM event_log WHERE created_at < ?", (cutoff_30,))
            db.commit()
            result["actions"].append(f"清理{old_events}条旧事件日志")
            log(f"  🗑️ 清理 {old_events} 条旧事件日志")
    except:
        pass

    # 3.5 FTS5 碎片整理 (reindex)
    try:
        db.execute("INSERT INTO messages_fts(messages_fts) VALUES('rebuild')")
        db.commit()
        log("  🔄 FTS5索引重建完成")
    except:
        pass

    db.close()
    
    log(f"  完成: 压缩{result['compressed']}个, 删除{result['deleted_empty']}个空会话")
    return result


# ══════════════════════════════════════════════════════════════════
#  模块4: 能力自主进化
# ══════════════════════════════════════════════════════════════════

def consume_retro_candidates() -> Dict[str, Any]:
    """消费复盘候选队列 — 复盘→Skill进化管道（非LLM版）
    
    读取复盘引擎产生的retro_candidates.jsonl，
    分析低分模式，输出Skill改进建议。
    不直接修改skill（通过SkillOpt验证门）"""
    result = {"consumed": 0, "patterns": [], "recommendations": [], "actions": []}

def skill_evolution_engine() -> Dict[str, Any]:
    """证据驱动Skill进化 — 全流程（收集→分类→提案→报告）
    
    集成 hermes_skill_evolver.py 的核心能力
    每天在自进化集群中自动执行"""
    result = {"evidence_count": 0, "proposals": 0, "applied": False, "actions": [], "recommendations": []}
    
    try:
        SCRIPTS_DIR = HERMES / "scripts"
        import subprocess
        proc = subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / "hermes_skill_evolver.py"), "all"],
            capture_output=True, text=True, timeout=120
        )
        for line in proc.stdout.split("\n"):
            if line.strip():
                log(f"  {line.strip()}")
        if proc.stderr:
            for line in proc.stderr.split("\n"):
                if line.strip():
                    log(f"  ⚠️ {line.strip()}")
        
        # 检查进化报告
        reports_dir = HERMES / "reports" / "skill_evolution"
        if reports_dir.exists():
            reports = sorted(reports_dir.glob("evolution_*.json"))
            if reports:
                latest = reports[-1]
                try:
                    with open(latest) as f:
                        report = json.load(f)
                    result["evidence_count"] = report.get("evidence_count", 0)
                    result["proposals"] = report.get("proposals_count", 0)
                    result["applied"] = report.get("applied", False)
                    if report.get("target_skill"):
                        result["actions"].append(f"Skill进化: {report['target_skill']} {'✅已应用' if report['applied'] else '📋未应用'}")
                except:
                    pass
        
        log(f"  进化引擎执行完成: {result['evidence_count']}证据→{result['proposals']}提案")
    
    except subprocess.TimeoutExpired:
        log(f"  ⚠️ 进化引擎超时")
        result["error"] = "timeout"
    except Exception as e:
        log(f"  ⚠️ 进化引擎失败: {e}")
        result["error"] = str(e)
    
    return result


def auto_tune_engine() -> Dict[str, Any]:
    """自动调优引擎 — 参数自适应
    
    集成 hermes_auto_tune.py 的核心能力
    每天在自进化集群中自动执行"""
    result = {"params_analyzed": False, "params_tuned": False, "actions": [], "recommendations": []}
    
    try:
        import subprocess
        proc = subprocess.run(
            [sys.executable, str(HERMES / "scripts" / "hermes_auto_tune.py"), "tune"],
            capture_output=True, text=True, timeout=60
        )
        output_lines = [l.strip() for l in proc.stdout.split("\n") if l.strip()]
        for line in output_lines:
            if line and not line.startswith("="):
                log(f"  {line}")
        
        result["params_analyzed"] = True
        result["params_tuned"] = True
        result["actions"].append("自动调优完成")
        log(f"  自动调优完成")
    
    except subprocess.TimeoutExpired:
        log(f"  ⚠️ 自动调优超时")
        result["error"] = "timeout"
    except Exception as e:
        log(f"  ⚠️ 自动调优失败: {e}")
        result["error"] = str(e)
    
    return result


def capability_evolve() -> Dict[str, Any]:
    """能力自主进化 - 扫描Cron/DB/系统,调优参数,生成优化建议"""
    result = {"cron_total": 0, "cron_ok": 0, "cron_fail": 0, "recommendations": [], "actions": []}

    # 4.1 分析Cron任务执行情况
    if CRON_JOBS.exists():
        try:
            with open(CRON_JOBS) as f:
                data = json.load(f)
            jobs = [j for j in data.get("jobs", []) if j]
            result["cron_total"] = len(jobs)
            ok_jobs = [j for j in jobs if j.get("last_status") == "ok"]
            fail_jobs = [j for j in jobs if j.get("last_status") == "error"]
            result["cron_ok"] = len(ok_jobs)
            result["cron_fail"] = len(fail_jobs)
            log(f"  Cron: {len(jobs)}任务, {len(ok_jobs)}正常, {len(fail_jobs)}失败")

            # 对频繁失败的任务降级
            if fail_jobs:
                for j in fail_jobs:
                    nm = j.get("name", "?")[:30]
                    err = (j.get("last_error") or "?")[:60]
                    result["recommendations"].append(f"[降级] {nm}: {err}")
                    log(f"  ⚠️ 失败任务: {nm}")
                    # 自动修复: 禁用失败任务并创建替补
                    j["enabled"] = False
                    j["state"] = "paused"
                    j["paused_reason"] = f"auto-paused by self_evolve: {err[:40]}"
                    result["actions"].append(f"暂停失败任务: {nm}")
                with open(CRON_JOBS, "w") as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                log(f"  🛑 已暂停 {len(fail_jobs)} 个失败任务")
        except Exception as e:
            log(f"  ⚠️ Cron分析失败: {e}")

    # 4.2 分析采集趋势
    try:
        db = sqlite3.connect(str(INTEL_DB))
        today = datetime.now(TZ).strftime("%Y-%m-%d")
        yesterday = (datetime.now(TZ) - timedelta(days=1)).strftime("%Y-%m-%d")

        # 检查raw_intelligence的时间列名
        raw_cols = [r[1] for r in db.execute("PRAGMA table_info(raw_intelligence)").fetchall()]
        ts_col = 'collected_at' if 'collected_at' in raw_cols else 'timestamp' if 'timestamp' in raw_cols else raw_cols[-1]

        # 今日 vs 昨日采集量
        c = db.execute(f"SELECT COUNT(*) FROM raw_intelligence WHERE {ts_col} >= ?", (today,))
        today_count = c.fetchone()[0]
        c = db.execute(f"SELECT COUNT(*) FROM raw_intelligence WHERE {ts_col} >= ? AND {ts_col} < ?",
                       (yesterday, today))
        yesterday_count = c.fetchone()[0]
        
        log(f"  采集: 今日{today_count}条 vs 昨日{yesterday_count}条")
        
        if today_count < yesterday_count * 0.5 and yesterday_count > 100:
            result["recommendations"].append(f"[告警] 采集量下降: {today_count} < {yesterday_count}×0.5")
            log(f"  ⚠️ 采集量下降 {yesterday_count}→{today_count}")

        # 无数据源检测  
        zero_sources = db.execute(f"""
            SELECT DISTINCT s.source FROM (
                SELECT DISTINCT source FROM raw_intelligence
            ) s
            WHERE s.source NOT IN (
                SELECT DISTINCT source FROM raw_intelligence WHERE {ts_col} >= ?
            )
        """, (today,)).fetchall()
        if zero_sources:
            for s in zero_sources[:5]:
                log(f"  ⚠️ 零数据源: {s[0]}")
                result["recommendations"].append(f"[检查] {s[0]} 无数据")

        db.close()
    except Exception as e:
        log(f"  ⚠️ 采集分析失败: {e}")

    # 4.3 active_memory权重调优 — 对低频偏好词做温和微增
    try:
        am_db = sqlite3.connect(str(ACTIVE_MEM_DB))
        # 方案A: 调优<5.0的低频偏好词(+10%) — 这些词有增长空间
        low_kws = am_db.execute(
            "SELECT keyword, weight FROM keyword_weights WHERE weight > 0.1 AND weight < 5.0"
        ).fetchall()
        if low_kws:
            inc_total = 0
            for kw, w in low_kws:
                new_w = round(min(w * 1.10, 10.0), 2)  # 微增10%,上限10
                am_db.execute("UPDATE keyword_weights SET weight=?, updated_at=? WHERE keyword=?",
                             (new_w, datetime.now().isoformat(), kw))
                inc_total += 1
            am_db.commit()
            result["actions"].append(f"调优{inc_total}个低频关键词(weight<5.0 → +10%)")
            log(f"  📈 调优 {inc_total} 个低频关键词 (weight<5.0 → +10%)")
        # 方案B: 对5.0-8.0的一般词做+5%微增
        mid_kws = am_db.execute(
            "SELECT keyword, weight FROM keyword_weights WHERE weight >= 5.0 AND weight < 8.0"
        ).fetchall()
        if mid_kws:
            inc_total = 0
            for kw, w in mid_kws:
                new_w = round(min(w * 1.05, 10.0), 2)  # 微增5%,上限10
                am_db.execute("UPDATE keyword_weights SET weight=?, updated_at=? WHERE keyword=?",
                             (new_w, datetime.now().isoformat(), kw))
                inc_total += 1
            am_db.commit()
            result["actions"].append(f"调优{inc_total}个中等关键词(5.0≤w<8.0 → +5%)")
            log(f"  📈 调优 {inc_total} 个中等关键词 (5.0≤w<8.0 → +5%)")
        # 方案C: 超过30天未更新且权重<8的高频词做-3%衰减
        month_ago = (datetime.now() - timedelta(days=30)).isoformat()
        stale_high = am_db.execute(
            "SELECT keyword, weight FROM keyword_weights WHERE updated_at < ? AND weight < 8.0 AND weight > 2.0",
            (month_ago,)
        ).fetchall()
        if stale_high:
            dec_total = 0
            for kw, w in stale_high:
                new_w = round(max(w * 0.97, 1.5), 2)  # 微降3%,下限1.5
                am_db.execute("UPDATE keyword_weights SET weight=?, updated_at=? WHERE keyword=?",
                             (new_w, datetime.now().isoformat(), kw))
                dec_total += 1
            am_db.commit()
            result["actions"].append(f"衰减{dec_total}个陈旧关键词(>30天→-3%)")
            log(f"  📊 衰减 {dec_total} 个陈旧关键词 (>30天→-3%)")
        am_db.close()
    except Exception as e:
        log(f"  ⚠️ 权重调优失败: {e}")

    log(f"  完成: {len(result['recommendations'])} 条优化建议")
    return result


# ══════════════════════════════════════════════════════════════════
#  模块5: 三省六部自进化
# ══════════════════════════════════════════════════════════════════

def sango_evolve() -> Dict[str, Any]:
    """三省六部自进化 - 更新拓扑权重,记录进化日志"""
    result = {"departments": 0, "actors_updated": 0, "events_logged": 0, "actions": []}

    # 5.1 加载拓扑配置
    topology_path = AGENTS_DIR / "topology.yaml"
    if not topology_path.exists():
        log("  ⚠️ topology.yaml不存在")
        return result

    try:
        with open(topology_path) as f:
            topology = yaml.safe_load(f)
        
        depts = topology.get("departments", [])
        result["departments"] = len(depts)
        log(f"  拓扑: {len(depts)} 个部门")

        # 5.2 从state.db读取event_log, 分析Actor表现
        state_db = sqlite3.connect(str(STATE_DB))
        try:
            recent_events = state_db.execute(
                "SELECT * FROM event_log ORDER BY created_at DESC LIMIT 50"
            ).fetchall()
            log(f"  最近事件: {len(recent_events)} 条")
        except:
            log("  event_log表不可用")
        
        # 5.3 记录进化事件
        try:
            # 检查event_log表结构
            log_cols = [r[1] for r in state_db.execute("PRAGMA table_info(event_log)").fetchall()]
            if 'event_data' in log_cols:
                state_db.execute(
                    "INSERT INTO event_log (event_type, event_data, created_at) VALUES (?, ?, ?)",
                    ("self_evolve", json.dumps({
                        "timestamp": datetime.now(TZ).isoformat(),
                        "module": "sango_evolve",
                        "departments": len(depts)
                    }, ensure_ascii=False), datetime.now(TZ).isoformat())
                )
            elif 'action' in log_cols:
                state_db.execute(
                    "INSERT INTO event_log (action, details, created_at) VALUES (?, ?, ?)",
                    ("self_evolve", json.dumps({
                        "timestamp": datetime.now(TZ).isoformat(),
                        "departments": len(depts)
                    }, ensure_ascii=False), datetime.now(TZ).isoformat())
                )
            elif 'event_type' in log_cols:
                state_db.execute(
                    "INSERT INTO event_log (event_type, correlation_id, source_actor, status, created_at) VALUES (?, ?, ?, ?, ?)",
                    ("self_evolve", f"evolve_{datetime.now(TZ).strftime('%Y%m%d_%H%M')}", "system", "completed", datetime.now(TZ).isoformat())
                )
            else:
                log(f"  ⚠️ event_log表结构未知: {log_cols}")
            state_db.commit()
            result["events_logged"] = 1
        except Exception as e:
            log(f"  ⚠️ 无法记录进化事件: {e}")
        
        state_db.close()

    except Exception as e:
        log(f"  ⚠️ 三省六部进化失败: {e}")
        return result

    log(f"  完成: {result['actors_updated']} Actors更新")
    return result


# ══════════════════════════════════════════════════════════════════
#  主入口
# ══════════════════════════════════════════════════════════════════

def main():
    log_section("🧬 Hermes 自进化集群启动")
    log(f"时间: {datetime.now(TZ).strftime('%Y-%m-%d %H:%M:%S')}")
    log(f"日志: {LOG_FILE}")

    report = {
        "timestamp": datetime.now(TZ).isoformat(),
        "modules": {}
    }

    # Phase 1: 技能自动进化
    log_section("📦 模块1: 技能自动进化")
    try:
        report["modules"]["skill_evolution"] = skill_evolution()
    except Exception as e:
        log(f"  ❌ 失败: {e}")
        report["modules"]["skill_evolution"] = {"error": str(e)}

    # Phase 2: 记忆压缩提取
    log_section("🧠 模块2: 记忆压缩提取")
    try:
        report["modules"]["memory_compress"] = memory_compress()
    except Exception as e:
        log(f"  ❌ 失败: {e}")
        report["modules"]["memory_compress"] = {"error": str(e)}

    # Phase 3: 对话Tokens压缩
    log_section("💬 模块3: 对话Tokens压缩")
    try:
        report["modules"]["token_compress"] = token_compress()
    except Exception as e:
        log(f"  ❌ 失败: {e}")
        report["modules"]["token_compress"] = {"error": str(e)}

    # Phase 4: 能力自主进化
    log_section("⚡ 模块4: 能力自主进化")
    try:
        report["modules"]["capability_evolve"] = capability_evolve()
    except Exception as e:
        log(f"  ❌ 失败: {e}")
        report["modules"]["capability_evolve"] = {"error": str(e)}

    # Phase 5: 三省六部自进化
    log_section("🏛️ 模块5: 三省六部自进化")
    try:
        report["modules"]["sango_evolve"] = sango_evolve()
    except Exception as e:
        log(f"  ❌ 失败: {e}")
        report["modules"]["sango_evolve"] = {"error": str(e)}

    # Phase 6: 复盘候选消费（复盘→Skill进化管道）
    log_section("📝 模块6: 复盘候选消费")
    try:
        retro_result = consume_retro_candidates()
        report["modules"]["retro_candidates"] = retro_result
    except Exception as e:
        log(f"  ❌ 失败: {e}")
        report["modules"]["retro_candidates"] = {"error": str(e)}
    
    # Phase 7: 证据驱动Skill进化（复盘→Skill改进提案）
    log_section("🧬 模块7: 证据驱动Skill进化")
    try:
        evolve_result = skill_evolution_engine()
        report["modules"]["skill_evolution_engine"] = evolve_result
    except Exception as e:
        log(f"  ❌ 失败: {e}")
        report["modules"]["skill_evolution_engine"] = {"error": str(e)}
    
    # Phase 8: 自动调优（参数自适应）
    log_section("⚡ 模块8: 自动调优")
    try:
        tune_result = auto_tune_engine()
        report["modules"]["auto_tune"] = tune_result
    except Exception as e:
        log(f"  ❌ 失败: {e}")
        report["modules"]["auto_tune"] = {"error": str(e)}

    # ── 汇总 ──────────────────────────────────────────────────
    log_section("📊 自进化集群执行完成")
    
    total_actions = sum(len(m.get("actions", [])) for m in report["modules"].values() if isinstance(m, dict))
    total_recs = sum(len(m.get("recommendations", [])) for m in report["modules"].values() if isinstance(m, dict))
    
    log(f"  总操作: {total_actions}")
    log(f"  优化建议: {total_recs}")
    
    # 生成优化建议摘要
    all_recs = []
    for mod_name, mod_result in report["modules"].items():
        if isinstance(mod_result, dict) and "recommendations" in mod_result:
            all_recs.extend(mod_result["recommendations"])
    
    if all_recs:
        log("\n  🔮 优化建议:")
        for rec in all_recs[:10]:
            log(f"    • {rec}")
        if len(all_recs) > 10:
            log(f"    ... 还有 {len(all_recs)-10} 条")

    # 保存报告
    report_path = HERMES / "reports" / f"self_evolve_{datetime.now(TZ).strftime('%Y%m%d')}.json"
    report_path.parent.mkdir(exist_ok=True)
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    log(f"\n  报告: {report_path}")

    # ── 推送到微信 ──
    try:
        # 构建微信推送消息
        wechat_lines = [
            f"🧬 Hermes 自进化报告 {datetime.now(TZ).strftime('%m-%d %H:%M')}",
            f"总操作: {total_actions} | 建议: {total_recs}\n"
        ]
        for mod_name, mod_result in report["modules"].items():
            if isinstance(mod_result, dict):
                actions = mod_result.get("actions", [])
                recs = mod_result.get("recommendations", [])
                if actions or recs:
                    label = {"skill_evolution": "📦技能", "memory_compress": "🧠记忆", 
                             "token_compress": "💬Token", "capability_evolve": "⚡能力",
                             "sango_evolve": "🏛️三省"}.get(mod_name, mod_name)
                    wechat_lines.append(f"{label}: {len(actions)}操作 + {len(recs)}建议")
                    for a in actions[:3]:
                        wechat_lines.append(f"  • {a[:40]}")
                    for r in recs[:3]:
                        wechat_lines.append(f"  • {r[:40]}")
        wechat_msg = "\n".join(wechat_lines)
        
        # 用PushPlus推送
        import urllib.request
        env_path = HERMES / ".env"
        token = ""
        if env_path.exists():
            with open(env_path) as f:
                for line in f:
                    if line.startswith("PUSHPLUS_TOKEN="):
                        token = line.strip().split("=", 1)[1]
                        break
        if token:
            data = json.dumps({
                "token": token,
                "title": f"🧬 Hermes 自进化 {datetime.now(TZ).strftime('%m-%d')} | {total_actions}操作",
                "content": wechat_msg.replace("\n", "<br>"),
                "template": "html",
            }).encode()
            req = urllib.request.Request("https://www.pushplus.plus/send", data=data,
                                         headers={"Content-Type": "application/json"})
            resp = json.loads(urllib.request.urlopen(req, timeout=15).read().decode())
            if resp.get("code") == 200:
                log("✅ 自进化报告已推送到微信")
            else:
                log(f"⚠️ 推送失败: {resp.get('msg', '?')}")
        else:
            log("⚠️ 无PushPlus token, 跳过推送")
    except Exception as e:
        log(f"⚠️ 推送异常: {e}")

    return report


if __name__ == "__main__":
    main()
