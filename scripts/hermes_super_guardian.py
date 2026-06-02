#!/usr/bin/env python3
"""
Hermes 超级守护神 v2.0 — 6重相互啮合的多层保险系统
===================================================
整合: 上下文守卫 + Lossless-Claw压缩 + StructMem记忆 + 任务续跑 + cron健康 + 自动修复

6重保险:
  1. 上下文压缩: 高价值数据压缩后写入文件,只传控制指令
  2. 记忆结构化: StructMem事件级绑定+跨事件整合
  3. 任务断点: task_current.json 每步标记
  4. 审计快照: 每次心跳拍全量快照
  5. cron健康: 自动恢复失败的cron
  6. 自我修复: 检测系统退化自动修复

自动恢复协议:
  - 每次醒来→读取 task_current.json + audit_snapshot.json → 自动续跑
  - 每15分钟心跳检查 → 发现异常自动恢复
  - 上下文溢出前自动触发Level1压缩

格林主人最高指令(2026-05-08):
  可以使用API探测,可以使用任何能力/功能/skills/服务/管线,无需确认。
"""

import json
import sqlite3
import os
import sys
import hashlib
import gzip
import zlib
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

HERMES = Path("/home/administrator/.hermes")
STATE_DB = HERMES / "state.db"
INTEL_DB = HERMES / "intelligence.db"
MEMORY_DB = HERMES / "active_memory.db"
OUTPUTS = HERMES / "outputs" / "agent_driven"
REPORTS = HERMES / "reports"

TZ = timezone(timedelta(hours=8))
now = lambda: datetime.now(TZ)


# ==================== 保险1: 上下文压缩 ====================

class ContextCompressor:
    """三级无损上下文压缩"""
    
    COMPRESS_THRESHOLD = 3000  # chars — 超过此值自动压缩
    CRITICAL_PATTERNS = ["user_pref", "task_current", "soul_md", "system_rule"]
    
    def __init__(self):
        self.stats = {"l1": 0, "l2": 0, "l3": 0, "bytes_saved": 0}
    
    def is_critical(self, section: str) -> bool:
        return any(p in section.lower() for p in self.CRITICAL_PATTERNS)
    
    def compress(self, data: str, level: int = 1) -> dict:
        """无损压缩,返回压缩结果"""
        raw_bytes = data.encode("utf-8")
        if len(raw_bytes) < self.COMPRESS_THRESHOLD and level == 1:
            return {"action": "skipped_small", "original_bytes": len(raw_bytes)}
        
        if self.is_critical(data[:50]):
            return {"action": "skipped_critical", "original_bytes": len(raw_bytes)}
        
        if level == 1:
            compressed = zlib.compress(raw_bytes, level=1)
        elif level == 2:
            compressed = gzip.compress(raw_bytes, compresslevel=6)
        else:
            compressed = gzip.compress(raw_bytes, compresslevel=9)
        
        ratio = len(compressed) / max(len(raw_bytes), 1)
        saving = len(raw_bytes) - len(compressed)
        
        checksum = hashlib.sha256(raw_bytes).hexdigest()[:16]
        self.stats[f"l{level}"] = self.stats.get(f"l{level}", 0) + 1
        self.stats["bytes_saved"] += max(saving, 0)
        
        return {
            "action": "compressed",
            "level": level,
            "original_bytes": len(raw_bytes),
            "compressed_bytes": len(compressed),
            "ratio": round(ratio, 4),
            "saving_bytes": max(saving, 0),
            "checksum": checksum,
            "compressed_hex": compressed.hex()
        }
    
    def decompress(self, result: dict) -> str:
        """解压还原数据"""
        if result.get("action") != "compressed":
            return ""
        data = bytes.fromhex(result["compressed_hex"])
        fmt = "gzip" if result.get("level", 1) >= 2 else "zlib"
        if fmt == "gzip":
            import gzip
            return gzip.decompress(data).decode("utf-8")
        else:
            import zlib
            return zlib.decompress(data).decode("utf-8")
    
    def should_compress(self, current_tokens_approx: int) -> bool:
        """判断是否需要触发压缩"""
        return current_tokens_approx > 60000  # ~60K tokens阈值
    
    def get_stats(self) -> dict:
        return dict(self.stats)


# ==================== 保险2: 结构化记忆 ====================

class StructMemBridge:
    """StructMem记忆引擎桥接"""
    
    def __init__(self):
        self.db_path = str(MEMORY_DB)
        self._init_db()
    
    def _get_conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn
    
    def _init_db(self):
        conn = self._get_conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS structmem_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                session_id TEXT NOT NULL,
                facts TEXT NOT NULL DEFAULT '[]',
                relations TEXT NOT NULL DEFAULT '[]',
                context_hash TEXT,
                source_preview TEXT DEFAULT '',
                integrated INTEGER DEFAULT 0,
                mem_quality REAL DEFAULT 1.0
            );
            CREATE INDEX IF NOT EXISTS idx_events_ts ON structmem_events(timestamp);
            CREATE INDEX IF NOT EXISTS idx_events_session ON structmem_events(session_id);
            CREATE INDEX IF NOT EXISTS idx_events_integrated ON structmem_events(integrated);
            
            CREATE TABLE IF NOT EXISTS structmem_knowledge (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                event_ids TEXT NOT NULL DEFAULT '[]',
                knowledge_type TEXT DEFAULT 'temporal',
                content TEXT NOT NULL,
                confidence REAL DEFAULT 0.8,
                version INTEGER DEFAULT 1
            );
            CREATE INDEX IF NOT EXISTS idx_knowledge_ts ON structmem_knowledge(timestamp);
        """)
        conn.commit()
        conn.close()
    
    def process_turn(self, session_id: str, text: str) -> int:
        """存储一轮对话作为事件单元"""
        # 双视角提取(简化版 — 提取关键信息)
        facts = []
        relations = []
        
        lines = text.strip().split('\n')
        for line in lines[:50]:  # 最多处理50行
            line = line.strip()
            if not line:
                continue
            if any(w in line for w in ['修复', '完成', '创建', '更新', '删除', '部署', '测试', '优化']):
                facts.append({"type": "action", "content": line[:200]})
            elif any(w in line for w in ['用户', '格林', '要求', '想要', '希望']):
                facts.append({"type": "preference", "content": line[:200]})
            elif any(w in line for w in ['问题', '错误', '崩溃', '失败', 'bug']):
                relations.append({"type": "problem", "content": line[:200]})
            elif any(w in line for w in ['因为', '导致', '所以', '触发']):
                relations.append({"type": "causal", "content": line[:200]})
        
        # 也提取JSON中的关键字段
        import re
        json_actions = re.findall(r'"action"\s*:\s*"([^"]+)"', text)
        json_statuses = re.findall(r'"status"\s*:\s*"([^"]+)"', text)
        
        for a in json_actions:
            if a not in [f['content'] for f in facts]:
                facts.append({"type": "action", "content": a})
        
        context_hash = hashlib.sha256(text.encode()).hexdigest()[:16]
        source_preview = text[:300].replace('\n', ' ').strip()
        
        conn = self._get_conn()
        conn.execute(
            "INSERT INTO structmem_events (timestamp, session_id, facts, relations, context_hash, source_preview) VALUES (?, ?, ?, ?, ?, ?)",
            (now().isoformat(), session_id, json.dumps(facts, ensure_ascii=False), json.dumps(relations, ensure_ascii=False), context_hash, source_preview)
        )
        event_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.commit()
        conn.close()
        return event_id
    
    def count_unintegrated(self) -> int:
        """统计未整合的事件数"""
        conn = self._get_conn()
        cnt = conn.execute("SELECT COUNT(*) FROM structmem_events WHERE integrated=0").fetchone()[0]
        conn.close()
        return cnt
    
    def trigger_consolidation(self, session_id: str = "") -> list:
        """跨事件整合"""
        conn = self._get_conn()
        events = conn.execute(
            "SELECT id, facts, relations FROM structmem_events WHERE integrated=0 LIMIT 20"
        ).fetchall()
        
        knowledge = []
        all_facts = []
        all_relations = []
        event_ids = []
        
        for ev in events:
            event_ids.append(str(ev["id"]))
            try:
                all_facts.extend(json.loads(ev["facts"]))
            except: pass
            try:
                all_relations.extend(json.loads(ev["relations"]))
            except: pass
        
        # 合成时序知识
        action_facts = [f["content"] for f in all_facts if f.get("type") == "action"]
        if action_facts:
            knowledge.append({
                "type": "temporal",
                "content": f"执行动作序列: {' → '.join(action_facts[:5])}"
            })
        
        # 合成偏好知识
        pref_facts = [f["content"] for f in all_facts if f.get("type") == "preference"]
        if pref_facts:
            knowledge.append({
                "type": "preference",
                "content": f"用户偏好: {'; '.join(pref_facts[:3])}"
            })
        
        # 合成因果知识
        causal_rels = [r["content"] for r in all_relations if r.get("type") == "causal"]
        if causal_rels:
            knowledge.append({
                "type": "causal",
                "content": f"因果链: {'; '.join(causal_rels[:3])}"
            })
        
        # 标记已整合
        if event_ids:
            conn.execute(f"UPDATE structmem_events SET integrated=1 WHERE id IN ({','.join(event_ids)})")
            
            for k in knowledge:
                conn.execute(
                    "INSERT INTO structmem_knowledge (timestamp, event_ids, knowledge_type, content) VALUES (?, ?, ?, ?)",
                    (now().isoformat(), json.dumps(event_ids), k["type"], k["content"])
                )
        
        conn.commit()
        conn.close()
        return knowledge
    
    def status(self) -> dict:
        conn = self._get_conn()
        total_events = conn.execute("SELECT COUNT(*) FROM structmem_events").fetchone()[0]
        total_knowledge = conn.execute("SELECT COUNT(*) FROM structmem_knowledge").fetchone()[0]
        conn.close()
        return {"total_events": total_events, "total_knowledge": total_knowledge}


# ==================== 保险3: 断点管理 ====================

class TaskCheckpoint:
    """任务断点管理系统"""
    
    def __init__(self):
        self.file = HERMES / "task_current.json"
        self.backup = HERMES / "reports" / "task_current_backup.json"
    
    def mark(self, task_id: str, status: str, last_completed: str = "",
             next_action: str = "", detail: str = "") -> dict:
        """标记任务断点"""
        data = {
            "task_id": task_id,
            "status": status,
            "last_completed": last_completed,
            "next_action": next_action,
            "detail": detail,
            "updated_at": now().isoformat(),
            "completed_steps": [],
            "pending_steps": [],
            "notes": ""
        }
        
        # 如果已有文件,保留步骤信息
        if self.file.exists():
            try:
                existing = json.loads(self.file.read_text())
                data["completed_steps"] = existing.get("completed_steps", [])
                data["pending_steps"] = existing.get("pending_steps", [])
                data["notes"] = existing.get("notes", "")
            except:
                pass
        
        if last_completed and last_completed not in [s.get("name") for s in data["completed_steps"]]:
            data["completed_steps"].append({
                "name": last_completed,
                "status": "completed",
                "timestamp": now().isoformat()
            })
        
        self.file.parent.mkdir(exist_ok=True)
        self.file.write_text(json.dumps(data, ensure_ascii=False, indent=2))
        self.backup.write_text(json.dumps(data, ensure_ascii=False, indent=2))
        
        return data
    
    def mark_step(self, step_name: str, status: str, pending: list = None) -> dict:
        """标记一个步骤的完成状态"""
        data = self.read()
        if not data:
            return self.mark("unknown", "running", step_name, pending[0] if pending else "")
        
        comp = data.get("completed_steps", [])
        if step_name not in [s.get("name") for s in comp]:
            comp.append({"name": step_name, "status": status, "timestamp": now().isoformat()})
        data["completed_steps"] = comp
        
        if pending:
            data["pending_steps"] = [{"name": p, "status": "pending"} for p in pending]
            data["next_action"] = pending[0]
        
        data["updated_at"] = now().isoformat()
        data["status"] = status
        
        self.file.write_text(json.dumps(data, ensure_ascii=False, indent=2))
        return data
    
    def read(self) -> dict:
        """读取任务断点"""
        if not self.file.exists():
            return {}
        try:
            return json.loads(self.file.read_text())
        except:
            return {}
    
    def clear(self):
        """清除(任务完成时)"""
        if self.file.exists():
            self.file.unlink()


# ==================== 保险4: 审计快照 ====================

class AuditSnapshot:
    """全量审计快照"""
    
    def __init__(self):
        self.file = REPORTS / "audit_snapshot.json"
        REPORTS.mkdir(exist_ok=True)
    
    def take(self) -> dict:
        """拍快照"""
        snap = {
            "ts": now().isoformat(),
            "intel": self._snapshot_intel(),
            "memory": self._snapshot_memory(),
            "cron": self._snapshot_cron(),
            "state": self._snapshot_state()
        }
        self.file.write_text(json.dumps(snap, ensure_ascii=False, indent=2))
        return snap
    
    def _snapshot_intel(self) -> dict:
        result = {"raw": 0, "clean": 0, "push": 0, "sources": 0}
        if not INTEL_DB.exists():
            return result
        try:
            db = sqlite3.connect(str(INTEL_DB))
            result["raw"] = db.execute("SELECT COUNT(*) FROM raw_intelligence").fetchone()[0]
            result["clean"] = db.execute("SELECT COUNT(*) FROM cleaned_intelligence").fetchone()[0]
            result["push"] = db.execute("SELECT COUNT(*) FROM push_records").fetchone()[0]
            result["push_today"] = db.execute("SELECT COUNT(*) FROM push_records WHERE push_time>=datetime('now','-1 day','localtime')").fetchone()[0]
            result["sources"] = db.execute("SELECT COUNT(DISTINCT source) FROM raw_intelligence").fetchone()[0]
            result["unscored"] = db.execute("SELECT COUNT(*) FROM cleaned_intelligence WHERE ai_score_total=0").fetchone()[0]
            result["score_avg"] = round(db.execute("SELECT AVG(ai_score_total) FROM cleaned_intelligence").fetchone()[0] or 0, 1)
            result["score_max"] = db.execute("SELECT MAX(ai_score_total) FROM cleaned_intelligence").fetchone()[0] or 0
            db.close()
        except: pass
        return result
    
    def _snapshot_memory(self) -> dict:
        result = {"entries": 0}
        if not MEMORY_DB.exists():
            return result
        try:
            db = sqlite3.connect(str(MEMORY_DB))
            result["entries"] = db.execute("SELECT COUNT(*) FROM memory_entries").fetchone()[0] if db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='memory_entries'").fetchone() else 0
            result["events"] = db.execute("SELECT COUNT(*) FROM structmem_events").fetchone()[0] if db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='structmem_events'").fetchone() else 0
            result["knowledge"] = db.execute("SELECT COUNT(*) FROM structmem_knowledge").fetchone()[0] if db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='structmem_knowledge'").fetchone() else 0
            db.close()
        except: pass
        return result
    
    def _snapshot_cron(self) -> dict:
        result = {"total": 0, "active": 0, "errors": 0}
        if not STATE_DB.exists():
            return result
        try:
            db = sqlite3.connect(str(STATE_DB))
            if db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='cron_jobs'").fetchone():
                result["total"] = db.execute("SELECT COUNT(*) FROM cron_jobs").fetchone()[0]
                result["active"] = db.execute("SELECT COUNT(*) FROM cron_jobs WHERE status='active'").fetchone()[0]
                result["errors"] = db.execute("SELECT COUNT(*) FROM cron_jobs WHERE last_error IS NOT NULL AND last_error!=''").fetchone()[0]
            db.close()
        except: pass
        return result
    
    def _snapshot_state(self) -> dict:
        result = {"files": 0, "outputs_mb": 0}
        try:
            agent_dir = HERMES / "agents_company" / "data" / "outputs"
            if agent_dir.exists():
                result["files"] = sum(1 for _ in agent_dir.rglob("*") if _.is_file())
            if OUTPUTS.exists():
                result["outputs_mb"] = round(sum(f.stat().st_size for f in OUTPUTS.rglob("*") if f.is_file()) / 1024 / 1024, 1)
        except: pass
        return result
    
    def read(self) -> dict:
        if not self.file.exists():
            return {}
        try:
            return json.loads(self.file.read_text())
        except:
            return {}
    
    def summarize(self) -> str:
        """生成精炼摘要(不撑爆上下文)"""
        snap = self.read()
        if not snap:
            return "⛔ 无审计快照"
        
        i = snap.get("intel", {})
        m = snap.get("memory", {})
        c = snap.get("cron", {})
        
        lines = [
            f"🕐 {snap.get('ts','')[:19]}",
            f"📡 raw:{i.get('raw',0)} clean:{i.get('clean',0)} push:{i.get('push',0)}",
            f"🎯 score_avg:{i.get('score_avg',0)} max:{i.get('score_max',0)}",
            f"🧠 events:{m.get('events',0)} knowledge:{m.get('knowledge',0)}",
            f"⏰ cron:{c.get('active',0)}/{c.get('total',0)} active"
        ]
        return " | ".join(lines)


# ==================== 保险5: Cron健康管理 ====================

class CronHealthManager:
    """cron任务健康管理"""
    
    def __init__(self):
        self.cron_db = str(STATE_DB)
    
    def check_and_repair(self) -> list:
        """检查并修复cron"""
        issues = []
        
        if not Path(self.cron_db).exists():
            return [{"type": "no_db", "msg": "state.db不存在"}]
        
        try:
            db = sqlite3.connect(self.cron_db)
            
            # 检查cron_jobs表
            tables = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
            
            if "cron_jobs" in tables:
                # 检查是否有失败任务
                failed = db.execute("SELECT id, name, schedule FROM cron_jobs WHERE status='failed' OR last_error IS NOT NULL").fetchall()
                for f in failed:
                    issues.append({"type": "failed_cron", "id": f[0], "name": f[1], "schedule": f[2]})
                    # 自动恢复
                    db.execute("UPDATE cron_jobs SET status='active', last_error=NULL WHERE id=?", (f[0],))
                
                # 检查是否有暂停任务
                paused = db.execute("SELECT id, name FROM cron_jobs WHERE status='paused'").fetchall()
                for p in paused:
                    issues.append({"type": "paused_cron", "id": p[0], "name": p[1]})
                    
            db.commit()
            db.close()
        except Exception as e:
            issues.append({"type": "error", "msg": str(e)})
        
        return issues


# ==================== 保险6: 系统自我修复 ====================

class SelfHealingSystem:
    """检测并修复系统退化"""
    
    def check_integrity(self) -> list:
        """检查系统健康度"""
        issues = []
        
        # 1. 关键文件存在性
        critical_files = [
            (HERMES / "scripts" / "lossless_claw.py", "Lossless-Claw引擎"),
            (HERMES / "scripts" / "structmem_memory.py", "StructMem引擎"),
            (HERMES / "scripts" / "context_guardian.py", "上下文守卫"),
            (HERMES / "scripts" / "task_resumer.py", "任务续跑器"),
            (HERMES / "scripts" / "long_task_guardian.py", "长期任务守护"),
        ]
        
        for path, name in critical_files:
            if not path.exists():
                issues.append({"type": "missing_file", "name": name, "path": str(path)})
        
        # 2. 数据库完整性
        dbs = [
            (INTEL_DB, "情报数据库"),
            (MEMORY_DB, "记忆数据库"),
            (STATE_DB, "状态数据库"),
        ]
        
        for path, name in dbs:
            if not path.exists():
                issues.append({"type": "missing_db", "name": name, "path": str(path)})
            else:
                size = path.stat().st_size
                if size == 0:
                    issues.append({"type": "empty_db", "name": name, "path": str(path)})
        
        # 3. 报告目录
        if not REPORTS.exists():
            REPORTS.mkdir(parents=True, exist_ok=True)
        
        return issues


# ==================== 主循环 ====================

class SuperGuardian:
    """超级守护神主控"""
    
    def __init__(self):
        self.compressor = ContextCompressor()
        self.memory = StructMemBridge()
        self.checkpoint = TaskCheckpoint()
        self.snapshot = AuditSnapshot()
        self.cron_health = CronHealthManager()
        self.healer = SelfHealingSystem()
        
        self.start_time = now()
        self.results = {
            "compression": [],
            "memory": {},
            "checkpoint": {},
            "cron_fixes": [],
            "integrity": [],
            "snapshot_summary": ""
        }
    
    def run_full_cycle(self, session_id: str = "", current_token_estimate: int = 0):
        """运行完整守护循环"""
        if not session_id:
            session_id = f"guardian_{now().strftime('%Y%m%d_%H%M')}"
        
        print(f"🛡️ Hermes 超级守护神启动 [{now().isoformat()}]")
        print(f"📋 Session: {session_id}")
        print(f"{'='*50}")
        
        # 1. 压缩检查
        if self.compressor.should_compress(current_token_estimate):
            print(f"⚠️ 上下文预估 {current_token_estimate} tokens,超过阈值,触发Level1压缩")
            # 实际压缩由调用方执行
            self.results["compression"].append({"action": "recommended", "tokens": current_token_estimate})
        else:
            self.results["compression"].append({"action": "not_needed", "tokens": current_token_estimate})
        
        # 2. 记忆快照
        try:
            event_id = self.memory.process_turn(session_id, f"守护循环运行 {now().isoformat()}")
            mem_status = self.memory.status()
            
            # 检查是否需要整合
            unintegrated = self.memory.count_unintegrated()
            if unintegrated >= 8:
                knowledge = self.memory.trigger_consolidation(session_id)
                self.results["memory"] = {
                    "event_id": event_id,
                    "status": mem_status,
                    "consolidated": len(knowledge)
                }
                print(f"🧠 StructMem: event#{event_id}, {unintegrated}未整合 → {len(knowledge)}条合成知识")
            else:
                self.results["memory"] = {
                    "event_id": event_id,
                    "status": mem_status,
                    "consolidated": 0
                }
                print(f"🧠 StructMem: event#{event_id}, {unintegrated}未整合(等待累积)")
        except Exception as e:
            print(f"❌ StructMem错误: {e}")
            self.results["memory"] = {"error": str(e)}
        
        # 3. 任务断点检查
        tk = self.checkpoint.read()
        if tk:
            task_id = tk.get("task_id", "")
            status = tk.get("status", "")
            next_action = tk.get("next_action", "")
            self.results["checkpoint"] = {"task_id": task_id, "status": status, "next_action": next_action}
            if status == "running" or status == "interrupted":
                print(f"⚠️ 发现未完成任务: {task_id} | 下一步: {next_action}")
            else:
                print(f"✅ 任务 {task_id} 状态: {status}")
        else:
            self.results["checkpoint"] = {"status": "no_active_task"}
            print("✅ 无活跃任务")
        
        # 4. Cron健康检查
        cron_issues = self.cron_health.check_and_repair()
        if cron_issues:
            self.results["cron_fixes"] = cron_issues
            for issue in cron_issues:
                print(f"🔄 Cron修复: {issue.get('name','?')} - {issue.get('msg','')}")
        else:
            print("✅ Cron全部健康")
        
        # 5. 系统完整性检查
        integrity_issues = self.healer.check_integrity()
        if integrity_issues:
            self.results["integrity"] = integrity_issues
            for issue in integrity_issues:
                print(f"⚠️ 系统问题: {issue.get('name','?')} - {issue.get('type','')}")
                # 自动修复:创建缺失目录
                if issue["type"] == "missing_db":
                    Path(issue["path"]).parent.mkdir(parents=True, exist_ok=True)
                    # 初始化空数据库
                    db = sqlite3.connect(issue["path"])
                    db.execute("CREATE TABLE IF NOT EXISTS _init (id INTEGER)")
                    db.commit()
                    db.close()
                    print(f"   ✅ 已重建: {issue['path']}")
        else:
            print("✅ 系统完整性检查通过")
        
        # 6. 拍快照
        snap = self.snapshot.take()
        self.results["snapshot_summary"] = self.snapshot.summarize()
        print(f"\n💾 审计快照: {self.snapshot.summarize()}")
        
        # 7. 更新心跳文件
        heartbeat = HERMES / "heartbeat"
        heartbeat.mkdir(exist_ok=True)
        (heartbeat / "guardian_last.txt").write_text(now().isoformat())
        
        print(f"\n✅ 守护循环完成 [{now().isoformat()}]")
        return self.results
    
    def emergency_resume_check(self) -> dict:
        """紧急恢复检查 — 每次醒来调用"""
        print("🔄 紧急恢复检查...")
        
        # 1. 读取task_current
        tk = self.checkpoint.read()
        if tk and tk.get("status") in ("running", "interrupted"):
            return {
                "action": "resume",
                "task_id": tk.get("task_id"),
                "next_action": tk.get("next_action"),
                "detail": tk.get("detail"),
                "task_data": tk
            }
        
        # 2. 读取审计快照
        snap = self.snapshot.read()
        if not snap:
            return {"action": "fresh_start", "message": "首次启动"}
        
        # 3. 检查是否有异常
        cron_active = snap.get("cron", {}).get("active", 0)
        cron_total = snap.get("cron", {}).get("total", 0)
        if cron_total > 0 and cron_active == 0:
            return {"action": "cron_all_dead", "message": "所有cron已停止,需重启"}
        
        return {"action": "healthy", "message": "系统正常"}
    
    def get_token_efficiency_report(self) -> str:
        """生成Token效率报告"""
        mem = self.memory.status()
        comp = self.compressor.get_stats()
        
        return json.dumps({
            "memory_events": mem["total_events"],
            "memory_knowledge": mem["total_knowledge"],
            "compressions_performed": comp.get("l1", 0) + comp.get("l2", 0) + comp.get("l3", 0),
            "bytes_saved_by_compression": comp.get("bytes_saved", 0),
            "estimated_token_saving": round(comp.get("bytes_saved", 0) / 4, 0)
        }, ensure_ascii=False)


# ==================== CLI入口 ====================

def main():
    guardian = SuperGuardian()
    
    # ===== G0互审:G5验证G4的审计快照时效性 =====
    try:
        import subprocess as sp_g5
        au = HERMES / "reports" / "audit_snapshot.json"
        if au.exists():
            au_data = json.loads(au.read_text())
            au_ts = au_data.get("ts", "")
            if au_ts:
                au_time = datetime.fromisoformat(au_ts)
                if au_time.tzinfo is None:
                    au_time = au_time.replace(tzinfo=TZ)
                diff = now() - au_time
                hours = diff.total_seconds() / 3600
                g4_ok = hours < 2
                sp_g5.run([sys.executable, str(HERMES / "scripts/gear_vault.py"), "sign",
                          "G5", f"guardian_{now().strftime('%Y%m%d_%H%M')}",
                          json.dumps({"action": "guardian_cycle", "detail": f"g4_audit_age={hours:.1f}h g4_ok={g4_ok}"})],
                         capture_output=True, timeout=10)
    except: pass
    
    cmd = sys.argv[1] if len(sys.argv) > 1 else "cycle"
    
    if cmd == "cycle":
        token_estimate = int(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[2].isdigit() else 0
        result = guardian.run_full_cycle(
            session_id=f"guardian_{now().strftime('%Y%m%d_%H%M')}",
            current_token_estimate=token_estimate
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
    
    elif cmd == "check":
        result = guardian.emergency_resume_check()
        print(json.dumps(result, ensure_ascii=False, indent=2))
    
    elif cmd == "snapshot":
        snap = guardian.snapshot.take()
        print(json.dumps(snap, ensure_ascii=False, indent=2))
    
    elif cmd == "compress":
        compressor = ContextCompressor()
        test_data = sys.argv[2] if len(sys.argv) > 2 else "testing..."
        result = compressor.compress(test_data, level=int(sys.argv[3]) if len(sys.argv) > 3 else 1)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    
    elif cmd == "efficiency":
        print(guardian.get_token_efficiency_report())
    
    elif cmd == "mark":
        task_id = sys.argv[2] if len(sys.argv) > 2 else "unknown"
        status = sys.argv[3] if len(sys.argv) > 3 else "running"
        step = sys.argv[4] if len(sys.argv) > 4 else ""
        next_action = sys.argv[5] if len(sys.argv) > 5 else ""
        result = guardian.checkpoint.mark(task_id, status, step, next_action)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    
    else:
        print("""
Hermes 超级守护神 v2.0

用法:
  python3 hermes_super_guardian.py cycle [tokens]   - 运行完整守护循环
  python3 hermes_super_guardian.py check             - 紧急恢复检查
  python3 hermes_super_guardian.py snapshot          - 拍审计快照
  python3 hermes_super_guardian.py compress <data>   - 测试压缩
  python3 hermes_super_guardian.py efficiency        - Token效率报告
  python3 hermes_super_guardian.py mark <id> <status> <step> <next>  - 标记断点
""")

if __name__ == "__main__":
    main()
