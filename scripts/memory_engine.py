#!/usr/bin/env python3
"""
memory_engine.py — 统一记忆引擎
合并自: hermes_memory_engine.py + hermes_memory_engine_v2.py + unified_memory_core.py +
        hierarchical_memory.py + active_memory.py + memory_highway.py + init_active_memory_db.py

能力无损，接口兼容，7个旧脚本均可通过此模块调用。

核心模块:
  1. MemoryCore — 语义/事件/程序/反射记忆 (V1+V2)
  2. CompressionEngine — 三级压缩引擎 (zlib/gzip检查点+delta)
  3. MemPalace — 记忆宫殿(四层堆栈+知识图谱+BM25搜索)
  4. DualExtractor — 双视角提取+跨事件整合
  5. HierarchicalMemory — 三层事件整合(L1事件→L2知识→L3归档)
  6. ActiveMemory — 关键词权重进化(反馈循环+偏好评分)
  7. MemoryHighway — 系统状态备份+记忆注入
  8. UnifiedMemoryEngine — 统一入口
"""

import json, sqlite3, hashlib, re, math, zlib, gzip, logging, time, os, sys, uuid, argparse
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional, Any, Dict, List, Tuple, Union
from dataclasses import dataclass, field

TZ = timezone(timedelta(hours=8))
HERMES = Path.home() / ".hermes"
LOG = HERMES / "logs" / "memory_engine.log"
_now = lambda: datetime.now(TZ).isoformat()
_logger = logging.getLogger("memory-engine")


def log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def estimate_tokens(text: str) -> int:
    if not text: return 0
    cn = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    en = len(text) - cn
    return int(cn * 1.5 + en * 1.3)


def uid():
    return uuid.uuid4().hex[:12]


# ============================================================
# 模块0: 数据库初始化 (原 init_active_memory_db.py)
# ============================================================
def init_memory_db(db_path: str = None) -> list:
    """初始化所有记忆系统所需的表"""
    if db_path is None:
        db_path = str(HERMES / "active_memory.db")
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.executescript("""
        -- ActiveMemory
        CREATE TABLE IF NOT EXISTS keyword_weights (keyword TEXT PRIMARY KEY, weight REAL DEFAULT 1.0, category TEXT DEFAULT '', updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS preference_feedback (keyword TEXT PRIMARY KEY, hit_count INTEGER DEFAULT 0, miss_count INTEGER DEFAULT 0, last_hit TIMESTAMP, last_miss TIMESTAMP);
        CREATE TABLE IF NOT EXISTS platform_feedback (platform TEXT PRIMARY KEY, hit_count INTEGER DEFAULT 0, total_score REAL DEFAULT 0, last_hit TIMESTAMP);
        CREATE TABLE IF NOT EXISTS preference_config (key TEXT PRIMARY KEY, value TEXT);
        -- MemoryCore (V1/V2)
        CREATE TABLE IF NOT EXISTS memory_semantic (id TEXT PRIMARY KEY, fact TEXT UNIQUE, cat TEXT, confidence REAL DEFAULT 0.8, src_count INTEGER DEFAULT 1, created_at TEXT, confirmed_at TEXT, keywords TEXT, ehash TEXT, active INTEGER DEFAULT 1);
        CREATE TABLE IF NOT EXISTS memory_episodic (id TEXT PRIMARY KEY, timestamp TEXT DEFAULT (datetime('now')), source TEXT DEFAULT 'system', content TEXT, context TEXT DEFAULT '', importance INTEGER DEFAULT 5, ttl_hours INTEGER DEFAULT 48, compressed INTEGER DEFAULT 0, tags TEXT DEFAULT '');
        CREATE TABLE IF NOT EXISTS memory_procedural (id TEXT PRIMARY KEY, name TEXT UNIQUE, trigger_desc TEXT, steps TEXT, tools TEXT, success_rate REAL DEFAULT 0.0, runs INTEGER DEFAULT 0, last_used TEXT, created_at TEXT, active INTEGER DEFAULT 1);
        CREATE TABLE IF NOT EXISTS memory_reflexive (id TEXT PRIMARY KEY, pattern TEXT UNIQUE, trigger_regex TEXT, response TEXT, frequency INTEGER DEFAULT 0, last_triggered TEXT, effectiveness REAL DEFAULT 0.8, created_at TEXT, is_active INTEGER DEFAULT 1);
        CREATE TABLE IF NOT EXISTS memory_entries (id INTEGER PRIMARY KEY AUTOINCREMENT, category TEXT, keyword TEXT, content TEXT, weight REAL DEFAULT 1.0, created_at TEXT, updated_at TEXT);
        -- HierarchicalMemory
        CREATE TABLE IF NOT EXISTS layer1_events (event_id TEXT PRIMARY KEY, timestamp TEXT NOT NULL, session_id TEXT DEFAULT '', fact_summary TEXT DEFAULT '', relation_summary TEXT DEFAULT '', entities TEXT DEFAULT '[]', importance REAL DEFAULT 1.0, access_count INTEGER DEFAULT 0, last_access TEXT, expires_at TEXT DEFAULT '');
        CREATE TABLE IF NOT EXISTS layer2_knowledge (knowledge_id TEXT PRIMARY KEY, timestamp TEXT NOT NULL, domain TEXT DEFAULT 'general', pattern_type TEXT DEFAULT 'trend', summary TEXT DEFAULT '', source_event_ids TEXT DEFAULT '[]', confidence REAL DEFAULT 0.5, reaffirm_count INTEGER DEFAULT 1, last_updated TEXT);
        CREATE TABLE IF NOT EXISTS layer3_archive (archive_id TEXT PRIMARY KEY, timestamp TEXT NOT NULL, original_event_id TEXT DEFAULT '', compressed_summary TEXT DEFAULT '', original_importance REAL DEFAULT 0.0, archived_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS access_patterns (entity TEXT PRIMARY KEY, access_count INTEGER DEFAULT 0, last_access TEXT, domain TEXT DEFAULT 'general');
        -- MemPalace
        CREATE TABLE IF NOT EXISTS mp_wings (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE NOT NULL, wing_type TEXT DEFAULT 'project', created_at TEXT NOT NULL, summary TEXT DEFAULT '');
        CREATE TABLE IF NOT EXISTS mp_rooms (id INTEGER PRIMARY KEY AUTOINCREMENT, wing_id INTEGER NOT NULL, name TEXT NOT NULL, description TEXT DEFAULT '', FOREIGN KEY(wing_id) REFERENCES mp_wings(id));
        CREATE TABLE IF NOT EXISTS mp_closets (id INTEGER PRIMARY KEY AUTOINCREMENT, room_id INTEGER NOT NULL, aak_summary TEXT NOT NULL, created_at TEXT NOT NULL, version INTEGER DEFAULT 1, FOREIGN KEY(room_id) REFERENCES mp_rooms(id));
        CREATE TABLE IF NOT EXISTS mp_drawers (id INTEGER PRIMARY KEY AUTOINCREMENT, closet_id INTEGER NOT NULL, text_chunk TEXT NOT NULL, token_count INTEGER DEFAULT 0, chunk_hash TEXT, FOREIGN KEY(closet_id) REFERENCES mp_closets(id));
        CREATE TABLE IF NOT EXISTS mp_layer0_identity (id INTEGER PRIMARY KEY AUTOINCREMENT, key TEXT UNIQUE NOT NULL, value TEXT NOT NULL, updated_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS mp_layer1_essential (id INTEGER PRIMARY KEY AUTOINCREMENT, wing_id INTEGER, content TEXT NOT NULL, priority INTEGER DEFAULT 0, expires_at TEXT, FOREIGN KEY(wing_id) REFERENCES mp_wings(id));
        CREATE TABLE IF NOT EXISTS mp_layer2_ondemand (id INTEGER PRIMARY KEY AUTOINCREMENT, room_id INTEGER, content TEXT NOT NULL, access_count INTEGER DEFAULT 0, last_access TEXT, FOREIGN KEY(room_id) REFERENCES mp_rooms(id));
        CREATE VIRTUAL TABLE IF NOT EXISTS mp_fts USING fts5(content, source, wing_name, tokenize='unicode61');
        CREATE TABLE IF NOT EXISTS mp_entities (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE NOT NULL, entity_type TEXT DEFAULT 'concept', created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS mp_relations (id INTEGER PRIMARY KEY AUTOINCREMENT, source_entity_id INTEGER NOT NULL, target_entity_id INTEGER NOT NULL, relation_type TEXT NOT NULL, valid_from TEXT, valid_to TEXT, confidence REAL DEFAULT 0.8, FOREIGN KEY(source_entity_id) REFERENCES mp_entities(id), FOREIGN KEY(target_entity_id) REFERENCES mp_entities(id));
        -- StructMem
        CREATE TABLE IF NOT EXISTS structmem_events (id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT NOT NULL, session_id TEXT NOT NULL, facts TEXT NOT NULL DEFAULT '[]', relations TEXT NOT NULL DEFAULT '[]', context_hash TEXT, source_preview TEXT DEFAULT '', integrated INTEGER DEFAULT 0, mem_quality REAL DEFAULT 1.0);
        -- Claw compression
        CREATE TABLE IF NOT EXISTS claw_compression_log (id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT NOT NULL, level INTEGER NOT NULL, section TEXT NOT NULL, original_bytes INTEGER NOT NULL, compressed_bytes INTEGER NOT NULL, ratio REAL NOT NULL, checksum TEXT NOT NULL, status TEXT DEFAULT 'ok', detail TEXT DEFAULT '');
        CREATE TABLE IF NOT EXISTS claw_checkpoints (id INTEGER PRIMARY KEY AUTOINCREMENT, section TEXT NOT NULL, level INTEGER NOT NULL, checksum TEXT NOT NULL, original_hash TEXT NOT NULL, compressed_data BLOB, created_at TEXT NOT NULL, version INTEGER DEFAULT 1, access_count INTEGER DEFAULT 0, last_access TEXT);
        CREATE TABLE IF NOT EXISTS claw_deltas (id INTEGER PRIMARY KEY AUTOINCREMENT, section TEXT NOT NULL, base_checksum TEXT NOT NULL, delta_data BLOB NOT NULL, timestamp TEXT NOT NULL, is_critical INTEGER DEFAULT 0);
        -- Push system
        CREATE TABLE IF NOT EXISTS push_config (key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE IF NOT EXISTS preference_matching_tags (id INTEGER PRIMARY KEY AUTOINCREMENT, tag TEXT NOT NULL, weight REAL DEFAULT 1.0, tier TEXT DEFAULT 'P2', category TEXT, enabled INTEGER DEFAULT 1, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
    """)
    conn.commit()

    # Verify
    c.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    tables = c.fetchall()
    conn.close()

    log(f"✅ 数据库初始化: {len(tables)}个表")
    return tables


# ============================================================
# 模块1: MemoryCore — V1/V2 记忆引擎核心 (原 hermes_memory_engine.py/v2)
# ============================================================
PROCEDURAL_TEMPLATES = [
    {"name": "情报采集全流程", "trigger_desc": "cron触发: 每2小时自动采集",
     "steps": json.dumps(["1. guardian.py cycle 启动采集器", "2. 多平台并行采集", "3. 智能清洗: 去重+去噪+格式化", "4. AI六维评分", "5. 存储到cleaned_intelligence表"], ensure_ascii=False),
     "tools": json.dumps(["guardian.py", "hermes_collector_v4.py", "delegate_task"], ensure_ascii=False)},
    {"name": "推送执行流程", "trigger_desc": "cron触发: 每日8/14/20/22点",
     "steps": json.dumps(["1. 候选获取: 各平台TOP20", "2. 偏好评分排序", "3. 垃圾过滤", "4. 多样性强制", "5. HTML构建+PushPlus推送"], ensure_ascii=False),
     "tools": json.dumps(["hermes_v12_push.py", "pushplus"], ensure_ascii=False)},
    {"name": "记忆引擎保存", "trigger_desc": "cron触发: 每4小时",
     "steps": json.dumps(["1. 保存语义事实", "2. 保存重要事件", "3. 更新keyword_weights"], ensure_ascii=False),
     "tools": json.dumps(["memory_engine.py --save"], ensure_ascii=False)},
    {"name": "记忆引擎压缩", "trigger_desc": "cron触发: 每12小时",
     "steps": json.dumps(["1. 清理过期事件记忆", "2. 合并重复语义记忆", "3. 压缩旧系统快照"], ensure_ascii=False),
     "tools": json.dumps(["memory_engine.py --compress"], ensure_ascii=False)},
    {"name": "自进化集群", "trigger_desc": "cron触发: 每天03:00",
     "steps": json.dumps(["1. 技能自动进化", "2. 记忆压缩", "3. Token压缩", "4. 能力进化"], ensure_ascii=False),
     "tools": json.dumps(["hermes_self_evolve_cluster.py"], ensure_ascii=False)},
    {"name": "三省六部Actor执行", "trigger_desc": "system触发: 每小时",
     "steps": json.dumps(["1. 吏部: 记忆搜索", "2. 户部: 搜索调度", "3. 工部: 快照生成", "4. 刑部: 任务记录"], ensure_ascii=False),
     "tools": json.dumps(["phase4_actors.py"], ensure_ascii=False)},
    {"name": "守护神自愈", "trigger_desc": "cron触发: 每15分钟",
     "steps": json.dumps(["1. 数据库健康检查", "2. 磁盘空间检查", "3. 日志轮转"], ensure_ascii=False),
     "tools": json.dumps(["guardian.py"], ensure_ascii=False)},
    {"name": "全系统审计", "trigger_desc": "格林主人要求时触发",
     "steps": json.dumps(["1. 检查cron状态", "2. 检查核心DB", "3. 检查推送历史", "4. 检查记忆系统", "5. 检查磁盘"], ensure_ascii=False),
     "tools": json.dumps(["crontab", "sqlite3", "df"], ensure_ascii=False)},
]

REFLEXIVE_TEMPLATES = [
    {"pattern": "pua_self_check", "trigger_regex": "(检查状态|汇报进度|系统健康|audit|审计)",
     "response": "执行全系统审计: cron→db→推送→记忆→六部, 输出结构化报告", "frequency": 0, "effectiveness": 0.9},
    {"pattern": "push_quality_check", "trigger_regex": "(推送|内容|垃圾|质量|过滤)",
     "response": "检查最近20条推送, 用垃圾关键词库验证, 输出垃圾比例", "frequency": 0, "effectiveness": 0.85},
    {"pattern": "memory_backup", "trigger_regex": "(记忆|保存|持久化)",
     "response": "执行memory_engine.py --save 保存语义/事件/程序记忆", "frequency": 0, "effectiveness": 0.95},
]


class MemoryCore:
    """语义+事件+程序+反射记忆核心 — 合并V1/V2全部能力"""

    def __init__(self, db_path: str = None):
        if db_path is None:
            db_path = str(HERMES / "active_memory.db")
        self.db_path = db_path
        self.tz = TZ
        init_memory_db(db_path)

    def _get_conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    # ---- 语义记忆 ----
    def save_semantic_fact(self, fact: str, cat: str = "general", confidence: float = 0.8) -> bool:
        conn = self._get_conn()
        try:
            existing = conn.execute("SELECT id, confidence, src_count FROM memory_semantic WHERE fact=?", (fact,)).fetchone()
            if existing:
                new_conf = min(1.0, existing["confidence"] + 0.05)
                conn.execute("UPDATE memory_semantic SET confidence=?, src_count=src_count+1, confirmed_at=datetime('now') WHERE id=?", (new_conf, existing["id"]))
                log(f"  [语义更新] conf={new_conf:.2f}: {fact[:60]}")
            else:
                ehash = fact.encode("utf-8").hex()[:32]
                conn.execute("INSERT INTO memory_semantic (id, fact, cat, confidence, src_count, created_at, confirmed_at, keywords, ehash, active) VALUES (?,?,?,?,1,datetime('now'),datetime('now'),?,?,1)",
                             (f"sem_{_now()}_{uid()}", fact, cat, confidence, f'["{cat}"]', ehash))
                log(f"  [语义新增] cat={cat}: {fact[:60]}")
            conn.commit(); return True
        except Exception as e:
            log(f"  [语义FAIL] {e}"); return False
        finally:
            conn.close()

    # ---- 事件记忆 ----
    def save_episodic_event(self, content: str, source: str = "system", importance: int = 5) -> bool:
        conn = self._get_conn()
        try:
            ttl = 72 if importance >= 8 else (48 if importance >= 5 else 24)
            eid = f"ep_{_now()}_{uid()}"
            conn.execute("INSERT OR REPLACE INTO memory_episodic (id, timestamp, source, content, context, importance, ttl_hours, compressed, tags) VALUES (?,datetime('now'),?,?,?,?,?,0,?)",
                         (eid, source, content[:500], f"importance={importance}", importance, ttl, source))
            conn.commit(); return True
        except Exception as e:
            log(f"  [事件FAIL] {e}"); return False
        finally:
            conn.close()

    # ---- 程序记忆 ----
    def init_procedural(self) -> int:
        conn = self._get_conn(); count = 0
        for tpl in PROCEDURAL_TEMPLATES:
            try:
                existing = conn.execute("SELECT id FROM memory_procedural WHERE name=?", (tpl["name"],)).fetchone()
                if existing:
                    conn.execute("UPDATE memory_procedural SET trigger_desc=?, steps=?, tools=?, success_rate=0.0, active=1, last_used=datetime('now') WHERE id=?", (tpl["trigger_desc"], tpl["steps"], tpl["tools"], existing["id"]))
                    log(f"  [程序更新] {tpl['name']}")
                else:
                    pid = f"pro_{_now()}_{uid()}"
                    conn.execute("INSERT INTO memory_procedural (id, name, trigger_desc, steps, tools, success_rate, runs, last_used, created_at, active) VALUES (?,?,?,?,?,0.0,0,datetime('now'),datetime('now'),1)",
                                 (pid, tpl["name"], tpl["trigger_desc"], tpl["steps"], tpl["tools"]))
                    log(f"  [程序新增] {tpl['name']}")
                count += 1
            except Exception as e:
                log(f"  [程序FAIL] {tpl['name']}: {e}")
        conn.commit(); conn.close(); return count

    def init_reflexive(self) -> int:
        conn = self._get_conn(); count = 0
        for tpl in REFLEXIVE_TEMPLATES:
            try:
                existing = conn.execute("SELECT id FROM memory_reflexive WHERE pattern=?", (tpl["pattern"],)).fetchone()
                if existing:
                    conn.execute("UPDATE memory_reflexive SET trigger_regex=?, response=?, effectiveness=?, last_triggered=datetime('now') WHERE id=?", (tpl["trigger_regex"], tpl["response"], tpl["effectiveness"], existing["id"]))
                    log(f"  [反射更新] {tpl['pattern']}")
                else:
                    rid = f"ref_{_now()}_{uid()}"
                    conn.execute("INSERT INTO memory_reflexive (id, pattern, trigger_regex, response, frequency, last_triggered, effectiveness, created_at, is_active) VALUES (?,?,?,?,0,datetime('now'),?,datetime('now'),1)",
                                 (rid, tpl["pattern"], tpl["trigger_regex"], tpl["response"], tpl["effectiveness"]))
                    log(f"  [反射新增] {tpl['pattern']}")
                count += 1
            except Exception as e:
                log(f"  [反射FAIL] {tpl['pattern']}: {e}")
        conn.commit(); conn.close(); return count

    def track_procedural(self, name: str, success: bool = True) -> bool:
        conn = self._get_conn()
        try:
            existing = conn.execute("SELECT id, runs, success_rate FROM memory_procedural WHERE name=?", (name,)).fetchone()
            if existing:
                new_runs = existing["runs"] + 1
                new_rate = (existing["success_rate"] * existing["runs"] + (1.0 if success else 0.0)) / new_runs
                conn.execute("UPDATE memory_procedural SET runs=?, success_rate=?, last_used=datetime('now') WHERE id=?", (new_runs, new_rate, existing["id"]))
                log(f"  [轨迹] {name}: run#{new_runs} {'✅' if success else '❌'} rate={new_rate:.2f}")
            conn.commit(); return True
        except Exception as e:
            log(f"  [轨迹FAIL] {name}: {e}"); return False
        finally:
            conn.close()

    # ---- 报告 ----
    def report(self) -> dict:
        conn = self._get_conn()
        r = {}
        for table, label in [("memory_entries","系统快照"),("memory_episodic","事件记忆"),("memory_semantic","语义记忆"),
                             ("memory_procedural","程序记忆"),("memory_reflexive","反射记忆"),("keyword_weights","关键词权重"),("preference_feedback","偏好反馈")]:
            try: ct = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]; r[table] = {"label":label,"count":ct}
            except: r[table] = {"label":label,"count":"ERR"}
        try: r["semantic_categories"] = {c["cat"]:c["cnt"] for c in conn.execute("SELECT cat,COUNT(*) as cnt FROM memory_semantic GROUP BY cat ORDER BY cnt DESC").fetchall()}
        except: r["semantic_categories"] = {}
        try: r["episodic_7d"] = conn.execute("SELECT COUNT(*) FROM memory_episodic WHERE timestamp >= datetime('now','-7 days')").fetchone()[0]
        except: r["episodic_7d"] = 0
        conn.close(); return r

    def create_checkpoint(self) -> Optional[str]:
        cp_dir = HERMES / "checkpoints"; cp_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S"); cp_file = cp_dir / f"memory_pre_compress_{ts}.db"
        try:
            import shutil; shutil.copy2(self.db_path, str(cp_file))
            for old in sorted(cp_dir.glob("memory_pre_compress_*.db"))[:-5]: old.unlink()
            log(f"  💾 Checkpoint: {cp_file.name}"); return str(cp_file)
        except Exception as e:
            log(f"  ❌ Checkpoint失败: {e}"); return None

    def restore_checkpoint(self, cp_path: str) -> bool:
        try:
            import shutil; shutil.copy2(cp_path, self.db_path)
            log(f"  🔄 已从checkpoint恢复: {cp_path}"); return True
        except Exception as e:
            log(f"  ❌ 恢复失败: {e}"); return False

    def compress_memory(self) -> list:
        cp = self.create_checkpoint()
        conn = self._get_conn(); actions = []
        try:
            expired = conn.execute("DELETE FROM memory_episodic WHERE timestamp < datetime('now', '-' || ttl_hours || ' hours')").rowcount
            if expired: actions.append(f"清理{expired}条过期事件记忆")
        except: pass
        try:
            dups = conn.execute("SELECT fact,COUNT(*) as cnt,GROUP_CONCAT(id) as ids FROM memory_semantic GROUP BY fact HAVING cnt>1").fetchall()
            for d in dups:
                ids = [x for x in d["ids"].split(",")]
                for rid in ids[1:]: conn.execute("DELETE FROM memory_semantic WHERE id=?", (rid,))
                actions.append(f"合并语义: '{str(d['fact'])[:40]}' {len(ids)}→1")
        except: pass
        try:
            snapshot_ids = conn.execute("SELECT id FROM memory_entries WHERE category='system_snapshot' ORDER BY id DESC LIMIT 20").fetchall()
            keep_ids = [s["id"] for s in snapshot_ids]
            if keep_ids:
                ph = ",".join("?"*len(keep_ids))
                deleted = conn.execute(f"DELETE FROM memory_entries WHERE category='system_snapshot' AND id NOT IN ({ph})", keep_ids).rowcount
                if deleted: actions.append(f"压缩快照: 删除{deleted}条")
        except: pass
        conn.commit(); conn.close()
        return actions

    def save_default_facts(self):
        """保存当前系统状态的默认语义事实"""
        log("=== 保存会话记忆 ===")
        self.save_semantic_fact("v12推送使用HTML模板+平台颜色+可点击链接", "system_config", 0.95)
        self.save_semantic_fact("垃圾过滤60+关键词含体育/政治/低俗/网文", "system_config", 0.9)
        self.save_semantic_fact("memory_engine.py统一记忆引擎管理语义/事件/程序/反射记忆", "system_config", 1.0)
        log("=== 保存完成 ===")


# ============================================================
# 模块2: CompressionEngine — 三级压缩引擎 (来自 unified_memory_core.py)
# ============================================================
class CompressionEngine:
    """三级压缩引擎 — zlib/gzip检查点+delta+老化归档"""

    def __init__(self, db_path: str = None):
        if db_path is None:
            db_path = str(HERMES / "active_memory.db")
        self.db_path = db_path
        self.critical_keys = {"user_prefs","user_profile","api_keys","project_config","system_rules","memory_facts","soul_core","topology","task_current","auth_tokens"}

    def _get_conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row; conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _checksum(self, data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()[:16]

    def compress(self, section: str, data: str, level: int = 1, force: bool = False) -> dict:
        if not force and section in self.critical_keys:
            return {"section":section,"action":"skipped_critical","original_bytes":len(data.encode())}
        raw_bytes = data.encode('utf-8'); cksum = self._checksum(raw_bytes)
        compressed = zlib.compress(raw_bytes, level=1) if level == 1 else gzip.compress(raw_bytes, compresslevel=6 if level==2 else 9)
        ratio = len(compressed)/max(len(raw_bytes),1)
        conn = self._get_conn()
        conn.execute("INSERT INTO claw_compression_log (timestamp,level,section,original_bytes,compressed_bytes,ratio,checksum) VALUES (?,?,?,?,?,?,?)",
                     (_now(),level,section,len(raw_bytes),len(compressed),round(ratio,4),cksum))
        blob = json.dumps({"format":"zlib" if level==1 else "gzip","level":level,"data":compressed.hex(),"original_size":len(raw_bytes),"compressed_size":len(compressed)}).encode()
        conn.execute("INSERT INTO claw_checkpoints (section,level,checksum,original_hash,compressed_data,created_at) VALUES (?,?,?,?,?,?)",
                     (section,level,cksum,self._checksum(compressed),blob,_now()))
        conn.commit(); conn.close()
        return {"section":section,"level":level,"original_bytes":len(raw_bytes),"compressed_bytes":len(compressed),"ratio":round(ratio,4),"saving_bytes":len(raw_bytes)-len(compressed),"checksum":cksum,"action":"compressed"}

    def decompress(self, section: str) -> Optional[str]:
        conn = self._get_conn()
        row = conn.execute("SELECT * FROM claw_checkpoints WHERE section=? ORDER BY created_at DESC LIMIT 1",(section,)).fetchone()
        if not row: conn.close(); return None
        conn.execute("UPDATE claw_checkpoints SET access_count=access_count+1,last_access=? WHERE id=?",(_now(),row["id"])); conn.commit()
        blob = json.loads(row["compressed_data"]); raw_hex = bytes.fromhex(blob["data"])
        data = zlib.decompress(raw_hex) if blob["format"]=="zlib" else gzip.decompress(raw_hex)
        conn.close(); return data.decode('utf-8')

    def level3_archive(self, older_than_days: int = 7) -> dict:
        conn = self._get_conn(); archived = 0
        for entry in conn.execute("SELECT * FROM claw_checkpoints WHERE created_at<date('now',?) AND access_count<3",(f'-{older_than_days} days',)).fetchall():
            if entry["compressed_data"]: conn.execute("DELETE FROM claw_checkpoints WHERE id=?",(entry["id"],)); archived += 1
        old_logs = conn.execute("SELECT COUNT(*) as cnt FROM claw_compression_log WHERE timestamp<date('now',?)",(f'-{older_than_days} days',)).fetchone()["cnt"]
        conn.execute("DELETE FROM claw_compression_log WHERE timestamp<date('now',?)",(f'-{older_than_days} days',))
        conn.commit(); conn.execute("VACUUM"); conn.close()
        return {"level":3,"archived_count":archived,"old_logs_removed":old_logs}

    def status(self) -> dict:
        conn = self._get_conn()
        total_logs = conn.execute("SELECT COUNT(*) as cnt FROM claw_compression_log").fetchone()["cnt"]
        total_ckpt = conn.execute("SELECT COUNT(*) as cnt FROM claw_checkpoints").fetchone()["cnt"]
        t = conn.execute("SELECT SUM(original_bytes) as orig,SUM(compressed_bytes) as comp FROM claw_compression_log").fetchone()
        orig=t["orig"] or 0; comp=t["comp"] or 0
        conn.close()
        return {"total_logs":total_logs,"total_checkpoints":total_ckpt,
                "total_original_bytes":orig,"total_compressed_bytes":comp,"overall_ratio":round(comp/orig,4) if orig>0 else 0}


# ============================================================
# 模块3: MemPalace — 记忆宫殿 (来自 unified_memory_core.py)
# ============================================================
class MemPalace:
    """记忆宫殿架构 — 四层堆栈 + 时序知识图谱 + BM25搜索"""

    def __init__(self, db_path: str = None):
        if db_path is None: db_path = str(HERMES / "active_memory.db")
        self.db_path = db_path

    def _get_conn(self):
        conn = sqlite3.connect(self.db_path); conn.row_factory = sqlite3.Row; conn.execute("PRAGMA journal_mode=WAL"); return conn

    def set_identity(self, key: str, value: str):
        conn = self._get_conn()
        conn.execute("INSERT OR REPLACE INTO mp_layer0_identity (key,value,updated_at) VALUES (?,?,?)",(key,value,_now()))
        conn.commit(); conn.close()

    def get_layer0(self) -> str:
        conn = self._get_conn()
        items = {r["key"]:r["value"] for r in conn.execute("SELECT key,value FROM mp_layer0_identity ORDER BY key")}
        conn.close(); return json.dumps(items,ensure_ascii=False)

    def set_essential(self, content: str, priority: int = 0):
        conn = self._get_conn()
        conn.execute("INSERT INTO mp_layer1_essential (content,priority) VALUES (?,?)",(content,priority))
        conn.commit(); conn.close()

    def get_layer1(self, limit: int = 5) -> str:
        conn = self._get_conn()
        rows = conn.execute("SELECT content FROM mp_layer1_essential ORDER BY priority DESC,id DESC LIMIT ?",(limit,)).fetchall()
        conn.close(); return "\n---\n".join([r["content"] for r in rows])

    def ensure_wing(self, name: str, wing_type: str = "project", summary: str = "") -> int:
        conn = self._get_conn()
        row = conn.execute("SELECT id FROM mp_wings WHERE name=?",(name,)).fetchone()
        if row: conn.close(); return row["id"]
        conn.execute("INSERT INTO mp_wings (name,wing_type,created_at,summary) VALUES (?,?,?,?)",(name,wing_type,_now(),summary))
        wid = conn.execute("SELECT last_insert_rowid() as id").fetchone()["id"]; conn.commit(); conn.close(); return wid

    def ensure_room(self, wing_id: int, name: str, desc: str = "") -> int:
        conn = self._get_conn()
        row = conn.execute("SELECT id FROM mp_rooms WHERE wing_id=? AND name=?",(wing_id,name)).fetchone()
        if row: conn.close(); return row["id"]
        conn.execute("INSERT INTO mp_rooms (wing_id,name,description) VALUES (?,?,?)",(wing_id,name,desc))
        rid = conn.execute("SELECT last_insert_rowid() as id").fetchone()["id"]; conn.commit(); conn.close(); return rid

    def store_closet(self, room_id: int, summary: str) -> int:
        conn = self._get_conn()
        conn.execute("INSERT INTO mp_closets (room_id,aak_summary,created_at) VALUES (?,?,?)",(room_id,summary,_now()))
        cid = conn.execute("SELECT last_insert_rowid() as id").fetchone()["id"]; conn.commit(); conn.close(); return cid

    def store_drawer(self, closet_id: int, text: str):
        conn = self._get_conn()
        h = hashlib.sha256(text.encode()).hexdigest()[:16]
        conn.execute("INSERT INTO mp_drawers (closet_id,text_chunk,token_count,chunk_hash) VALUES (?,?,?,?)",(closet_id,text,estimate_tokens(text),h))
        conn.commit(); conn.close()

    def add_entity(self, name: str, entity_type: str = "concept") -> int:
        conn = self._get_conn()
        row = conn.execute("SELECT id FROM mp_entities WHERE name=?",(name,)).fetchone()
        if row: conn.close(); return row["id"]
        conn.execute("INSERT INTO mp_entities (name,entity_type,created_at) VALUES (?,?,?)",(name,entity_type,_now()))
        eid = conn.execute("SELECT last_insert_rowid() as id").fetchone()["id"]; conn.commit(); conn.close(); return eid

    def add_relation(self, source: str, target: str, rtype: str, confidence: float = 0.8):
        conn = self._get_conn(); s_id = self.add_entity(source); t_id = self.add_entity(target)
        conn.execute("INSERT INTO mp_relations (source_entity_id,target_entity_id,relation_type,valid_from,confidence) VALUES (?,?,?,?,?)",(s_id,t_id,rtype,_now(),confidence))
        conn.commit(); conn.close()

    def search(self, query: str, limit: int = 5) -> list:
        conn = self._get_conn(); results = []
        try:
            for r in conn.execute("SELECT content,source FROM mp_fts WHERE mp_fts MATCH ? LIMIT ?",(query,limit)):
                results.append({"source":r["source"],"content":r["content"][:300],"method":"fts5","score":1.0})
        except: pass
        docs = [r["content"] for r in conn.execute("SELECT content FROM mp_layer1_essential ORDER BY priority DESC LIMIT 20")]
        if docs:
            avg_len = sum(len(d.split()) for d in docs)/len(docs); import math
            for doc in docs:
                q_terms = re.findall(r'\w+', query.lower()); d_terms = Counter(re.findall(r'\w+', doc.lower()))
                score = sum(math.log((1+1)/1.5)*(d_terms.get(qt,0)*2.5)/(d_terms.get(qt,0)+1.5*(1-0.75+0.75*len(d_terms)/avg_len)) for qt in set(q_terms) if qt in d_terms)
                if score > 0: results.append({"content":doc[:300],"method":"bm25","score":round(score,2)})
        conn.close(); return sorted(results, key=lambda x:-x["score"])[:limit]


# ============================================================
# 模块4: DualExtractor — 双视角提取+跨事件整合 (来自 unified_memory_core.py)
# ============================================================
class DualExtractor:
    """双视角提取器 — 事实视角 + 关系视角 + 跨事件整合"""

    def __init__(self, db_path: str = None):
        if db_path is None: db_path = str(HERMES / "active_memory.db")
        self.db_path = db_path

    def _get_conn(self):
        conn = sqlite3.connect(self.db_path); conn.row_factory = sqlite3.Row; conn.execute("PRAGMA journal_mode=WAL"); return conn

    def dual_extract(self, text: str) -> dict:
        facts, relations = [], []
        lines = text.strip().split('\n')
        for line in lines:
            line = line.strip()
            if not line: continue
            for pat,ftype in [(r'(?:用户|我|我们)(?:说|提到|问|要求|希望|想要|需要|喜欢|讨厌|觉得|认为|决定|选择|完成|做了|创建了|修改了|删除了|修复了|部署了|配置了|安装了|升级了|迁移了|测试了|发布了|优化了|重构了|添加了|实现了)(.+?)(?:[。!?\\n]|$)','action'),
                              (r'(?:是|使用|用|基于|采用|依赖|包含|包括|支持|提供|拥有|具备)(.+?)(?:[。!?\\n]|$)','state'),
                              (r'(?:偏好|喜欢|偏爱|倾向|更[喜倾]).+?(?:[。!?\\n]|$)','preference'),
                              (r'(?:计划|打算|准备|下一步|接下来|将要|即将).+?(?:[。!?\\n]|$)','plan')]:
                m = re.search(pat,line)
                if m and len(m.group(0).strip())>5: facts.append({"type":ftype,"content":m.group(0).strip()})
            for pat,rtype in [(r'(?:同意|赞同|支持|认可|确认).+?(?:[。!?\\n]|$)','support'),
                              (r'(?:反对|拒绝|不同意|不认可|怀疑|质疑).+?(?:[。!?\\n]|$)','oppose'),
                              (r'(?:因为|由于|导致|使得|造成|引发|促进|推动|阻碍|限制).+?(?:[。!?\\n]|$)','causal')]:
                m = re.search(pat,line)
                if m and len(m.group(0).strip())>8: relations.append({"type":rtype,"content":m.group(0).strip()})
        seen=set()
        return {"facts":[f for f in facts if not (h:=hashlib.md5(f['content'].encode()).hexdigest()) in seen and not seen.add(h)][:10],
                "relations":[r for r in relations if not (h:=hashlib.md5(r['content'].encode()).hexdigest()) in seen and not seen.add(h) if r not in relations[:relations.index(r)]][:5]}

    def process_turn(self, session_id: str, conversation_text: str) -> int:
        extraction = self.dual_extract(conversation_text)
        conn = self._get_conn()
        cursor = conn.execute("INSERT INTO structmem_events (timestamp,session_id,facts,relations,context_hash,source_preview) VALUES (?,?,?,?,?,?)",
                              (_now(),session_id,json.dumps(extraction["facts"],ensure_ascii=False),json.dumps(extraction["relations"],ensure_ascii=False),
                               hashlib.sha256(conversation_text.encode()).hexdigest()[:16],conversation_text[:120].replace('\n',' ')))
        eid = cursor.lastrowid; conn.commit()
        if conn.execute("SELECT COUNT(*) as cnt FROM structmem_events WHERE session_id=? AND integrated=0",(session_id,)).fetchone()["cnt"] >= 3:
            for r in conn.execute("SELECT facts,relations FROM structmem_events WHERE session_id=? AND integrated=0 ORDER BY timestamp",(session_id,)):
                extraction["facts"].extend(json.loads(r["facts"])); extraction["relations"].extend(json.loads(r["relations"]))
            conn.execute("UPDATE structmem_events SET integrated=1 WHERE session_id=? AND integrated=0",(session_id,))
            for f in extraction["facts"][:3]:
                try: conn.execute("INSERT OR IGNORE INTO memory_semantic (id,fact,cat,confidence,created_at,confirmed_at,keywords,ehash,active) VALUES (?,?,?,?,datetime('now'),datetime('now'),?,?,1)",
                                  (f"sem_{_now()}_{hashlib.md5(f['content'].encode()).hexdigest()[:8]}",f['content'],f['type'],0.7,f'["{f["type"]}"]',hashlib.sha256(f['content'].encode()).hexdigest()[:32]))
                except: pass
            conn.commit()
        conn.close(); return eid


# ============================================================
# 模块5: HierarchicalMemory — 三层事件整合 (原 hierarchical_memory.py)
# ============================================================
@dataclass
class EventEntry:
    event_id: str; timestamp: str; session_id: str = ""; fact_summary: str = ""
    relation_summary: str = ""; entities: List[str] = field(default_factory=list)
    importance: float = 1.0; access_count: int = 0; expires_at: str = ""

@dataclass
class ConsolidatedKnowledge:
    knowledge_id: str; timestamp: str; domain: str = "general"; pattern_type: str = "trend"
    summary: str = ""; source_event_ids: List[str] = field(default_factory=list)
    confidence: float = 0.5; reaffirm_count: int = 1


class HierarchicalMemory:
    """三层记忆 — L1事件→L2知识→L3归档 + 自动整合"""

    def __init__(self, db_path: Path = None):
        self.db_path = db_path or (HERMES / "active_memory.db")

    def _get_conn(self):
        conn = sqlite3.connect(str(self.db_path)); conn.row_factory = sqlite3.Row; conn.execute("PRAGMA journal_mode=WAL"); return conn

    def store_event(self, event: EventEntry) -> bool:
        conn = self._get_conn()
        try:
            conn.execute("INSERT OR REPLACE INTO layer1_events (event_id,timestamp,session_id,fact_summary,relation_summary,entities,importance,access_count,last_access,expires_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                         (event.event_id,event.timestamp,event.session_id,event.fact_summary[:300],event.relation_summary[:300],json.dumps(event.entities),event.importance,event.access_count,event.timestamp,event.expires_at))
            for entity in event.entities:
                conn.execute("INSERT INTO access_patterns (entity,access_count,last_access,domain) VALUES (?,1,?,?) ON CONFLICT(entity) DO UPDATE SET access_count=access_count+1,last_access=excluded.last_access",(entity,event.timestamp,"general"))
            conn.commit(); return True
        except Exception as e: _logger.error(f"store_event: {e}"); return False
        finally: conn.close()

    def create_event(self, fact: str, relations: str = "", entities: List[str] = None, importance: float = 1.0) -> EventEntry:
        now = datetime.now().isoformat()
        return EventEntry(event_id=hashlib.md5(f"{now}:{fact[:50]}".encode()).hexdigest()[:16],timestamp=now,fact_summary=fact[:300],relation_summary=relations[:300],entities=entities or [],importance=importance)

    def retrieve_events(self, query: str = "", entity: str = "", limit: int = 20, min_importance: float = 0.0, hours_lookback: int = 168) -> List[EventEntry]:
        conn = self._get_conn()
        if entity: rows = conn.execute("SELECT * FROM layer1_events WHERE entities LIKE ? AND importance>=? AND timestamp>=datetime('now',?) ORDER BY importance DESC,timestamp DESC LIMIT ?",(f'%{entity}%',min_importance,f'-{hours_lookback} hours',limit)).fetchall()
        elif query: rows = conn.execute("SELECT * FROM layer1_events WHERE (fact_summary LIKE ? OR relation_summary LIKE ?) AND importance>=? AND timestamp>=datetime('now',?) ORDER BY importance DESC,timestamp DESC LIMIT ?",(f'%{query}%',f'%{query}%',min_importance,f'-{hours_lookback} hours',limit)).fetchall()
        else: rows = conn.execute("SELECT * FROM layer1_events WHERE importance>=? AND timestamp>=datetime('now',?) ORDER BY importance DESC,timestamp DESC LIMIT ?",(min_importance,f'-{hours_lookback} hours',limit)).fetchall()
        for r in rows: conn.execute("UPDATE layer1_events SET access_count=access_count+1,last_access=datetime('now') WHERE event_id=?",(r['event_id'],))
        conn.commit(); conn.close(); return [EventEntry(**dict(r)) for r in rows]

    def consolidate(self, batch_events: List[EventEntry]) -> List[ConsolidatedKnowledge]:
        conn = self._get_conn(); consolidated = []; now_dt = datetime.now().isoformat()
        entity_groups: Dict[str, list] = {}
        for ev in batch_events:
            for entity in ev.entities:
                entity_groups.setdefault(entity,[]).append(ev)
        for entity, events in entity_groups.items():
            if len(events) < 2: continue
            facts = [e.fact_summary for e in events if e.fact_summary]
            if len(facts) > 2:
                knowledge = ConsolidatedKnowledge(
                    knowledge_id=hashlib.md5(f"trend:{entity}:{now_dt}".encode()).hexdigest()[:16],timestamp=now_dt,
                    domain="general",pattern_type="trend",summary=f"Entity '{entity}' appeared {len(events)} times: {facts[0][:80]}...",
                    source_event_ids=[e.event_id for e in events],confidence=min(1.0,len(events)/10.0),reaffirm_count=len(events))
                conn.execute("INSERT OR REPLACE INTO layer2_knowledge (knowledge_id,timestamp,domain,pattern_type,summary,source_event_ids,confidence,reaffirm_count,last_updated) VALUES (?,?,?,?,?,?,?,?,?)",
                             (knowledge.knowledge_id,knowledge.timestamp,knowledge.domain,knowledge.pattern_type,knowledge.summary,json.dumps(knowledge.source_event_ids),knowledge.confidence,knowledge.reaffirm_count,knowledge.timestamp))
                consolidated.append(knowledge)
        conn.commit(); conn.close(); return consolidated

    def retrieve_knowledge(self, domain: str = "", pattern_type: str = "", min_confidence: float = 0.3) -> List[ConsolidatedKnowledge]:
        conn = self._get_conn()
        where = []; params = []
        if domain: where.append("domain LIKE ?"); params.append(f'%{domain}%')
        if pattern_type: where.append("pattern_type=?"); params.append(pattern_type)
        where.append("confidence>=?"); params.append(min_confidence)
        rows = conn.execute(f"SELECT * FROM layer2_knowledge WHERE {' AND '.join(where) if where else '1=1'} ORDER BY confidence DESC,reaffirm_count DESC LIMIT 30",params).fetchall()
        conn.close(); return [ConsolidatedKnowledge(**dict(r)) for r in rows]

    def archive_old_events(self, older_than_days: int = 14) -> int:
        conn = self._get_conn(); archived = 0
        rows = conn.execute("SELECT * FROM layer1_events WHERE timestamp<datetime('now',?) AND importance<3.0 ORDER BY importance ASC LIMIT 200",(f'-{older_than_days} days',))
        for row in rows.fetchall():
            conn.execute("INSERT OR REPLACE INTO layer3_archive (archive_id,timestamp,original_event_id,compressed_summary,original_importance) VALUES (?,?,?,?,?)",
                         (f"arch_{row['event_id']}",row['timestamp'],row['event_id'],row['fact_summary'][:150],row['importance']))
            conn.execute("DELETE FROM layer1_events WHERE event_id=?",(row['event_id'],)); archived += 1
        conn.commit(); conn.close(); return archived

    def prune_expired(self) -> int:
        conn = self._get_conn()
        count = conn.execute("DELETE FROM layer1_events WHERE expires_at!='' AND expires_at<datetime('now')").rowcount
        conn.commit(); conn.close(); return count

    def get_stats(self) -> dict:
        conn = self._get_conn()
        stats = {"l1_events":conn.execute("SELECT COUNT(*) FROM layer1_events").fetchone()[0],
                 "l2_knowledge":conn.execute("SELECT COUNT(*) FROM layer2_knowledge").fetchone()[0],
                 "l3_archives":conn.execute("SELECT COUNT(*) FROM layer3_archive").fetchone()[0],
                 "entities":conn.execute("SELECT COUNT(*) FROM access_patterns").fetchone()[0]}
        conn.close(); return stats


# ============================================================
# 模块6: ActiveMemory — 关键词权重进化 (原 active_memory.py)
# ============================================================
class ActiveMemory:
    """关键词权重进化引擎 — 反馈循环 + 偏好评分"""
    _instance = None; _initialized = False

    def __new__(cls):
        if cls._instance is None: cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if self._initialized: return
        self._initialized = True; self.cfg = {"kw_weight_adjust_rate":0.02,"kw_min_weight":0.5,"kw_max_weight":10.0,"kw_decay_days":30,"auto_evolve":True}
        self.keywords = {}
        self._load_config(); self._load_preference_keywords()

    def _load_config(self):
        try:
            conn = sqlite3.connect(str(HERMES/"state.db"))
            for k,v in conn.execute("SELECT key,value FROM preference_config"):
                if k == 'kw_weight_adjust_rate': self.cfg['kw_weight_adjust_rate'] = float(v)
                elif k == 'kw_min_weight': self.cfg['kw_min_weight'] = float(v)
                elif k == 'kw_max_weight': self.cfg['kw_max_weight'] = float(v)
                elif k == 'kw_decay_days': self.cfg['kw_decay_days'] = int(v)
                elif k == 'auto_evolve': self.cfg['auto_evolve'] = v.lower() == 'true'
            conn.close()
        except: pass

    def _load_preference_keywords(self):
        try:
            conn = sqlite3.connect(str(HERMES/"active_memory.db"))
            self.keywords = {r[0]:{"weight":r[1],"category":r[2]} for r in conn.execute("SELECT keyword,weight,category FROM keyword_weights")}
            conn.close()
        except: self.keywords = {}

    def record_feedback(self, keyword: str, hit: bool = True):
        conn = sqlite3.connect(str(HERMES/"active_memory.db")); now = datetime.now().isoformat()
        try:
            col, opp = ("hit_count","last_hit") if hit else ("miss_count","last_miss")
            conn.execute(f"INSERT INTO preference_feedback (keyword,{col},{opp}) VALUES (?,1,?) ON CONFLICT(keyword) DO UPDATE SET {col}={col}+1,{opp}=excluded.{opp}",(keyword,now))
            conn.commit()
        except: pass
        finally: conn.close()

    def auto_evolve(self, dry_run: bool = False) -> dict:
        if not self.cfg['auto_evolve'] and not dry_run: return {"status":"disabled","changes":[]}
        conn = sqlite3.connect(str(HERMES/"active_memory.db")); changes = []
        try:
            for keyword,hit_count,miss_count,last_hit_str,_ in conn.execute("SELECT keyword,hit_count,miss_count,last_hit,last_miss FROM preference_feedback"):
                total = hit_count + miss_count
                if total == 0: continue
                old_weight = self.keywords.get(keyword,{}).get("weight",1.0); new_weight = old_weight; hit_rate = hit_count/total
                if last_hit_str:
                    days_since = (datetime.now() - datetime.fromisoformat(last_hit_str)).days
                    if days_since > self.cfg['kw_decay_days'] and hit_rate <= 0.5:
                        new_weight = max(self.cfg['kw_min_weight'], new_weight * (1.0 - self.cfg['kw_weight_adjust_rate']*2))
                        changes.append({"keyword":keyword,"reason":f'decay ({days_since}d)',"old_weight":round(old_weight,2),"new_weight":round(new_weight,2)})
                if hit_rate > 0.7: new_weight = min(self.cfg['kw_max_weight'], old_weight + self.cfg['kw_weight_adjust_rate'])
                elif hit_rate < 0.3: new_weight = max(self.cfg['kw_min_weight'], old_weight - self.cfg['kw_weight_adjust_rate'])
                if abs(new_weight-old_weight) > 0.001 and not dry_run:
                    conn.execute("INSERT INTO keyword_weights (keyword,weight,updated_at) VALUES (?,?,datetime('now')) ON CONFLICT(keyword) DO UPDATE SET weight=excluded.weight,updated_at=datetime('now')",(keyword,new_weight))
                    self.keywords[keyword] = {"weight":new_weight,"category":self.keywords.get(keyword,{}).get("category")}
                    if not any(c['keyword']==keyword and 'boost' in c['reason'] for c in changes): changes.append({"keyword":keyword,"reason":"boost" if hit_rate>0.7 else "penalty","old_weight":round(old_weight,2),"new_weight":round(new_weight,2)})
            conn.commit()
        except: pass
        finally: conn.close()
        return {"status":"completed","dry_run":dry_run,"changes_count":len(changes),"changes":changes}

    def score_item(self, item: dict) -> dict:
        text = f"{item.get('title','')} {item.get('content','')}".lower()
        matched = [kw for kw in self.keywords if kw.lower() in text]
        if not matched: return {"score":0,"matched_keywords":[],"total_weight":0}
        tw = sum(self.keywords[kw]["weight"] for kw in matched)
        return {"score":min(100,tw*20),"matched_keywords":matched,"total_weight":round(tw,2)}


def auto_evolve(dry_run: bool = False) -> dict:
    """快捷函数 — 兼容原 active_memory.py"""
    return ActiveMemory().auto_evolve(dry_run=dry_run)


# ============================================================
# 模块7: MemoryHighway — 系统状态备份+记忆注入 (原 memory_highway.py)
# ============================================================
class MemoryHighway:
    """记忆高速公路 — 系统状态备份 + memory注入 + 跨系统持久化"""

    def get_intel_stats(self) -> dict:
        try:
            db = sqlite3.connect(str(HERMES/"intelligence.db"))
            c = db.cursor()
            stats = {"total":c.execute("SELECT COUNT(*) FROM cleaned_intelligence").fetchone()[0],
                     "high_value":c.execute("SELECT COUNT(*) FROM cleaned_intelligence WHERE ai_score_total>=60").fetchone()[0],
                     "excellent":c.execute("SELECT COUNT(*) FROM cleaned_intelligence WHERE ai_score_total>=80").fetchone()[0],
                     "unscored":c.execute("SELECT COUNT(*) FROM cleaned_intelligence WHERE ai_score_total IS NULL OR ai_score_total=0").fetchone()[0],
                     "last_update":(c.execute("SELECT MAX(cleaned_at) FROM cleaned_intelligence").fetchone()[0] or ""),
                     "top_platforms":{r[0]:r[1] for r in c.execute("SELECT platform,COUNT(*) FROM cleaned_intelligence GROUP BY platform ORDER BY COUNT(*) DESC LIMIT 8")}}
            db.close(); return stats
        except: return {"total":0,"high_value":0,"excellent":0,"unscored":0}

    def backup_to_active_db(self, state: dict) -> bool:
        try:
            am = sqlite3.connect(str(HERMES/"active_memory.db"))
            am.execute("INSERT OR REPLACE INTO memory_entries (category,keyword,content,weight,created_at,updated_at) VALUES (?,?,?,?,?,?)",
                       ("system_snapshot",f'snapshot_{datetime.now().strftime("%H%M")}',json.dumps({**state,"timestamp":_now()},ensure_ascii=False),1.0,_now(),_now()))
            deleted = am.execute("DELETE FROM memory_entries WHERE category='system_snapshot' AND updated_at<datetime('now','-48 hours')").rowcount
            am.commit(); am.close()
            log(f"📸 active_memory.db备份: {state['total']}条DB, 清理{deleted}条旧快照"); return True
        except: return False

    def write_memory_injection(self, state: dict) -> bool:
        try:
            now = datetime.now()
            summary = f"Hermes系统状态 @ {now.strftime('%H:%M')}: 数据库{state['total']}条情报, {state['high_value']}条高价值(>=60). 前3平台: {', '.join(list(state.get('top_platforms',{}).keys())[:3])}."
            (HERMES/"memory_inject.json").write_text(json.dumps({"injected_at":now.isoformat(),"source":"memory_highway","actions":[{"action":"add","target":"memory","content":summary[:500]}]},ensure_ascii=False),encoding="utf-8")
            log(f"📝 memory_inject.json已写入"); return True
        except: return False

    def compress_old_entries(self) -> int:
        try:
            am = sqlite3.connect(str(HERMES/"active_memory.db"))
            d1 = am.execute("DELETE FROM memory_entries WHERE category IN ('hermes_memory','system_snapshot') AND updated_at<datetime('now','-7 days')").rowcount
            d2 = am.execute("DELETE FROM feedback_log WHERE created_at<datetime('now','-30 days')").rowcount if self._table_exists(am,"feedback_log") else 0
            am.commit(); am.close()
            if d1+d2 > 0: log(f"🧹 清理memory_entries:{d1} feedback_log:{d2}")
            return d1+d2
        except: return 0

    def _table_exists(self, conn, name: str) -> bool:
        return bool(conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?",(name,)).fetchone())

    def run_full_cycle(self):
        log("🧠 记忆高速公路启动")
        state = self.get_intel_stats()
        self.backup_to_active_db(state)
        self.write_memory_injection(state)
        self.compress_old_entries()
        try:
            am = sqlite3.connect(str(HERMES/"active_memory.db"))
            log(f"📊 active_memory: {am.execute('SELECT COUNT(*) FROM memory_entries').fetchone()[0]}条entries, {am.execute('SELECT COUNT(*) FROM keyword_weights').fetchone()[0]}条weights")
            am.close()
        except: pass
        log("✅ 记忆高速公路完成")
        return True


# ============================================================
# 模块8: UnifiedMemoryEngine — 统一入口
# ============================================================
class UnifiedMemoryEngine:
    """统一记忆引擎入口 — 整合全部7个模块"""

    def __init__(self, db_path: str = None):
        if db_path is None: db_path = str(HERMES / "active_memory.db")
        self.db_path = db_path
        self.core = MemoryCore(db_path)
        self.compressor = CompressionEngine(db_path)
        self.palace = MemPalace(db_path)
        self.extractor = DualExtractor(db_path)
        self.hierarchical = HierarchicalMemory(Path(db_path))
        self.active = ActiveMemory()
        self.highway = MemoryHighway()

    def status(self) -> dict:
        r = self.core.report()
        hier = self.hierarchical.get_stats()
        r.update(hier)
        comp = self.compressor.status()
        r["compression_logs"] = comp["total_logs"]
        return r

    def save_event(self, session_id: str, text: str) -> int:
        return self.extractor.process_turn(session_id, text)

    def search(self, query: str, limit: int = 5) -> list:
        return self.palace.search(query, limit)

    def wakeup(self) -> str:
        layer0 = self.palace.get_layer0(); layer1 = self.palace.get_layer1(3)
        combined = f"## 记忆唤醒\n## Layer0 (身份)\n{layer0}\n\n## Layer1 (关键)\n{layer1}"
        log(f"记忆唤醒: {estimate_tokens(combined)}tokens")
        return combined


# ============================================================
# CLI 入口
# ============================================================
CLI_COMMANDS = {
    "--report": "显示记忆系统报告",
    "--save": "保存默认语义事实",
    "--compress": "压缩记忆(清理过期/合并重复)",
    "--procedural-init": "初始化程序记忆",
    "--reflexive-init": "初始化反射记忆",
    "--full-init": "全量初始化(程序+反射)",
    "--track": "记录程序记忆执行轨迹 --track '名称' [success|fail]",
    "--status": "统一引擎状态",
    "--wakeup": "记忆唤醒(Layer0+Layer1)",
    "--search": "搜索记忆 --search <query>",
    "--highway": "运行记忆高速公路",
    "--evolve": "关键词权重进化 [--dry-run]",
    "--init-db": "初始化/修复数据库",
}


def main():
    action = sys.argv[1] if len(sys.argv) > 1 else "--help"

    if action == "--help" or action == "-h":
        print("用法: python3 memory_engine.py <命令> [参数]")
        for cmd, desc in CLI_COMMANDS.items():
            print(f"  {cmd:20s} {desc}")
        return

    engine = UnifiedMemoryEngine()

    if action == "--report":
        r = engine.core.report()
        print("=== 记忆系统健康报告 ===")
        for k, v in r.items():
            print(f"  {k}: {json.dumps(v, ensure_ascii=False)}")

    elif action == "--save":
        engine.core.save_default_facts()

    elif action == "--compress":
        log("=== 压缩历史记忆 ===")
        actions = engine.core.compress_memory()
        for a in actions:
            print(f"  ✅ {a}")
        if not actions:
            print("  📭 无需压缩")
        log("=== 压缩完成 ===")

    elif action == "--procedural-init":
        n = engine.core.init_procedural()
        print(f"  ✅ 初始化 {n} 条程序记忆")

    elif action == "--reflexive-init":
        n = engine.core.init_reflexive()
        print(f"  ✅ 初始化 {n} 条反射记忆")

    elif action == "--full-init":
        n1 = engine.core.init_procedural()
        n2 = engine.core.init_reflexive()
        print(f"  ✅ 程序记忆: {n1}条, 反射记忆: {n2}条")

    elif action == "--track":
        name = sys.argv[2] if len(sys.argv) > 2 else ""
        success = sys.argv[3] != "fail" if len(sys.argv) > 3 else True
        if name:
            engine.core.track_procedural(name, success)
        else:
            print("请指定程序记忆名称")

    elif action == "--status":
        s = engine.status()
        print("📊 统一记忆引擎状态:")
        for k, v in s.items():
            print(f"  {k}: {v}")

    elif action == "--wakeup":
        print(engine.wakeup())

    elif action == "--search":
        query = sys.argv[2] if len(sys.argv) > 2 else ""
        results = engine.search(query)
        for r in results:
            print(f"  [{r.get('method','?')}] {r.get('content','')[:100]} (score={r.get('score','?')})")

    elif action == "--highway":
        engine.highway.run_full_cycle()

    elif action == "--evolve":
        dry_run = "--dry-run" in sys.argv or "-n" in sys.argv
        result = engine.active.auto_evolve(dry_run=dry_run)
        print(json.dumps(result, ensure_ascii=False, indent=2))

    elif action == "--init-db":
        tables = init_memory_db()
        print(f"✅ 数据库初始化: {len(tables)}个表")

    else:
        print(f"未知命令: {action}")
        print(f"可用命令: {', '.join(CLI_COMMANDS.keys())}")


if __name__ == "__main__":
    main()


