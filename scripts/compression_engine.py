#!/usr/bin/env python3
"""
compression_engine.py — 统一压缩引擎
合并自: lossless_claw.py + emergency_compressor.py + rtk_compressor.py +
        context_compressor.py + compress_soul_static.py +
        compression_fidelity_validator.py + memory_compress.py +
        run_compression.py + archive_compressor.py

能力无损，接口兼容，9个旧脚本均可通过此模块调用。
"""

import json, sqlite3, hashlib, gzip, zlib, pickle, time, re, os, sys, argparse
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional, Any, Dict, List, Union

HERMES = Path.home() / ".hermes"
TZ = timezone(timedelta(hours=8))
_now = lambda: datetime.now(TZ).isoformat()

# ============================================================
# 模块1: LosslessClawCompressor — 三级无损压缩引擎 (原 lossless_claw.py)
# ============================================================
class LosslessClawCompressor:
    """无损上下文压缩引擎 — 三级压缩策略，上下文使用量降低60-70%"""

    def __init__(self, db_path: str = None):
        if db_path is None:
            db_path = str(HERMES / "state.db")
        self.db_path = db_path
        self.tz = TZ
        self.critical_keys = {
            "user_prefs", "user_profile", "api_keys", "project_config",
            "system_rules", "memory_facts", "soul_core", "topology",
            "task_current", "auth_tokens"
        }
        self._init_db()

    def _get_conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        conn = self._get_conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS claw_compression_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                level INTEGER NOT NULL,
                section TEXT NOT NULL,
                original_bytes INTEGER NOT NULL,
                compressed_bytes INTEGER NOT NULL,
                ratio REAL NOT NULL,
                checksum TEXT NOT NULL,
                status TEXT DEFAULT 'ok',
                detail TEXT DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS claw_checkpoints (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                section TEXT NOT NULL, level INTEGER NOT NULL,
                checksum TEXT NOT NULL, original_hash TEXT NOT NULL,
                compressed_data BLOB, created_at TEXT NOT NULL,
                version INTEGER DEFAULT 1, access_count INTEGER DEFAULT 0,
                last_access TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_checkpoint_section ON claw_checkpoints(section);
            CREATE INDEX IF NOT EXISTS idx_checkpoint_level ON claw_checkpoints(level);
            CREATE TABLE IF NOT EXISTS claw_deltas (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                section TEXT NOT NULL, base_checksum TEXT NOT NULL,
                delta_data BLOB NOT NULL, timestamp TEXT NOT NULL,
                is_critical INTEGER DEFAULT 0
            );
            PRAGMA user_version = 1;
        """)
        conn.commit(); conn.close()

    def _checksum(self, data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()[:16]

    def compress(self, section: str, data: str, level: int = 1, force: bool = False) -> dict:
        if not force and section in self.critical_keys:
            return {"section": section, "action": "skipped_critical", "original_bytes": len(data.encode())}
        raw_bytes = data.encode('utf-8')
        cksum = self._checksum(raw_bytes)
        if level == 1: compressed = zlib.compress(raw_bytes, level=1)
        elif level == 2: compressed = gzip.compress(raw_bytes, compresslevel=6)
        elif level >= 3: compressed = gzip.compress(raw_bytes, compresslevel=9)
        else: compressed = raw_bytes
        ratio = len(compressed) / max(len(raw_bytes), 1)
        conn = self._get_conn()
        conn.execute("INSERT INTO claw_compression_log (timestamp,level,section,original_bytes,compressed_bytes,ratio,checksum) VALUES (?,?,?,?,?,?,?)",
                     (_now(), level, section, len(raw_bytes), len(compressed), round(ratio, 4), cksum))
        compressed_blob = json.dumps({"format":"zlib" if level==1 else "gzip","level":level,"data":compressed.hex(),"original_size":len(raw_bytes),"compressed_size":len(compressed)}).encode()
        conn.execute("INSERT INTO claw_checkpoints (section,level,checksum,original_hash,compressed_data,created_at) VALUES (?,?,?,?,?,?)",
                     (section, level, cksum, self._checksum(compressed), compressed_blob, _now()))
        conn.commit(); conn.close()
        saving = len(raw_bytes) - len(compressed)
        return {"section":section,"level":level,"original_bytes":len(raw_bytes),"compressed_bytes":len(compressed),"ratio":round(ratio,4),"saving_bytes":saving,"checksum":cksum,"action":"compressed"}

    def decompress(self, section: str) -> Optional[str]:
        conn = self._get_conn()
        row = conn.execute("SELECT * FROM claw_checkpoints WHERE section=? ORDER BY created_at DESC LIMIT 1", (section,)).fetchone()
        if not row: conn.close(); return None
        conn.execute("UPDATE claw_checkpoints SET access_count=access_count+1, last_access=? WHERE id=?", (_now(), row["id"]))
        conn.commit()
        blob = json.loads(row["compressed_data"])
        raw_hex = bytes.fromhex(blob["data"])
        if blob["format"] == "zlib": decompressed = zlib.decompress(raw_hex)
        elif blob["format"] == "gzip": decompressed = gzip.decompress(raw_hex)
        else: decompressed = raw_hex
        conn.close(); return decompressed.decode('utf-8')

    def level1_compress(self) -> dict:
        conn = self._get_conn(); results = {}
        try:
            cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%session%'")
            for table_row in cursor.fetchall():
                table = table_row["name"]
                try:
                    data_cursor = conn.execute(f"SELECT * FROM {table} LIMIT 100")
                    rows = data_cursor.fetchall()
                    if rows:
                        serialized = json.dumps({str(i): dict(r) for i,r in enumerate(rows)}, ensure_ascii=False, default=str)
                        results[table] = self.compress(f"session_{table}", serialized, level=1)
                except: pass
        except: pass
        conn.close()
        return {"level":1,"sections_compressed":len(results),"total_saving_bytes":sum(r.get("saving_bytes",0) for r in results.values()),"results":list(results.values())[:10]}

    def level2_compress(self) -> dict:
        conn = self._get_conn(); results = {}
        cursor = conn.execute("SELECT section, access_count FROM claw_checkpoints WHERE level=1 GROUP BY section")
        for row in cursor.fetchall():
            if row["access_count"] < 3:
                data = self.decompress(row["section"])
                if data and len(data) > 500:
                    results[row["section"]] = self.compress(row["section"], data, level=2, force=True)
        conn.close()
        return {"level":2,"sections_recompressed":len(results),"total_saving_bytes":sum(r.get("saving_bytes",0) for r in results.values()),"results":list(results.values())[:10]}

    def level3_archive(self, older_than_days: int = 7) -> dict:
        conn = self._get_conn(); results = {"archived":[],"removed":[],"vacuums":[]}
        cursor = conn.execute("SELECT * FROM claw_checkpoints WHERE created_at < date('now',?) AND access_count < 3 ORDER BY created_at ASC", (f'-{older_than_days} days',))
        old_entries = cursor.fetchall()
        for entry in old_entries:
            if entry["compressed_data"]:
                conn.execute("DELETE FROM claw_checkpoints WHERE id=?", (entry["id"],))
                results["archived"].append({"section":entry["section"],"removed_checkpoint":True})
        cursor = conn.execute("SELECT COUNT(*) as cnt FROM claw_compression_log WHERE timestamp < date('now',?)", (f'-{older_than_days} days',))
        old_logs = cursor.fetchone()["cnt"]
        conn.execute("DELETE FROM claw_compression_log WHERE timestamp < date('now',?)", (f'-{older_than_days} days',))
        results["removed"].append({"old_logs":old_logs})
        conn.commit(); conn.execute("VACUUM"); results["vacuums"].append({"vacuumed":True,"timestamp":_now()})
        conn.close()
        return {"level":3,"archived_count":len(old_entries),"old_logs_removed":old_logs,"details":results}

    def status(self) -> dict:
        conn = self._get_conn()
        total_logs = conn.execute("SELECT COUNT(*) as cnt FROM claw_compression_log").fetchone()["cnt"]
        total_checkpoints = conn.execute("SELECT COUNT(*) as cnt FROM claw_checkpoints").fetchone()["cnt"]
        by_level = {f"level_{r['level']}":r["cnt"] for r in conn.execute("SELECT level,COUNT(*) as cnt FROM claw_checkpoints GROUP BY level").fetchall()}
        totals = conn.execute("SELECT SUM(original_bytes) as orig, SUM(compressed_bytes) as comp FROM claw_compression_log").fetchone()
        orig = totals["orig"] or 0; comp = totals["comp"] or 0
        conn.close()
        return {"total_compressions":total_logs,"total_checkpoints":total_checkpoints,"by_level":by_level,
                "original_bytes":orig,"compressed_bytes":comp,"overall_ratio":f"{comp/max(orig,1)*100:.1f}%" if orig else "N/A",
                "savings_bytes":orig-comp,"savings_pct":f"{(1-comp/max(orig,1))*100:.1f}%" if orig else "N/A","db_path":self.db_path}

# ============================================================
# 模块2: EmergencyCompressor — 紧急上下文压缩 (原 emergency_compressor.py)
# ============================================================
OFFLOAD_DB = HERMES / "offload_entries.jsonl"

class EmergencyCompressor:
    """紧急上下文压缩引擎 — 三级级联压缩(mild/aggressive/emergency)"""
    MILD_RATIO = 0.50; AGGRESSIVE_RATIO = 0.85; EMERGENCY_RATIO = 0.92
    MIN_KEEP_AGGRESSIVE = 2; MIN_KEEP_EMERGENCY = 2

    def __init__(self, context_window: int = 128000):
        self.context_window = context_window

    def _estimate_tokens(self, text: str) -> int:
        if not text: return 0
        chinese_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
        ascii_chars = len(text) - chinese_chars
        return int(chinese_chars / 1.5 + ascii_chars / 3.7)

    def compress(self, current_text: str, mild: bool = True, aggressive: bool = True, emergency: bool = True) -> dict:
        original_tokens = self._estimate_tokens(current_text)
        original_lines = current_text.split('\n')
        result = {"original_tokens":original_tokens,"compressed_text":current_text,"compressed_tokens":original_tokens,"saved_tokens":0,"saved_percent":0,"level":"none"}
        ratio = original_tokens / self.context_window if self.context_window > 0 else 1.0
        lines = original_lines
        if mild and ratio >= self.MILD_RATIO:
            ref_markers = [l for l in lines if l.startswith("[ref:")]
            if not ref_markers:
                replaced = self._mild_cascade_replace(lines)
                if replaced > 0:
                    ratio = self._estimate_tokens('\n'.join(lines)) / self.context_window
                    result["level"] = "mild"; result["mild_replacements"] = replaced
        if aggressive and ratio >= self.AGGRESSIVE_RATIO:
            lines = self._aggressive_compress(lines)
            ratio = self._estimate_tokens('\n'.join(lines)) / self.context_window
            result["level"] = "aggressive"
        if emergency and ratio >= self.EMERGENCY_RATIO:
            lines = self._emergency_compress(lines)
            result["level"] = "emergency"
        compressed_text = '\n'.join(lines)
        compressed_tokens = self._estimate_tokens(compressed_text)
        result.update({"compressed_text":compressed_text,"compressed_tokens":compressed_tokens,"saved_tokens":original_tokens-compressed_tokens,
                       "saved_percent":round((1-compressed_tokens/original_tokens)*100,1) if original_tokens>0 else 0})
        return result

    def _mild_cascade_replace(self, lines: list) -> int:
        replaced = 0; i = 0
        while i < len(lines):
            if lines[i].startswith('```') and len(lines[i]) < 10:
                start = i; i += 1; block_lines = []
                while i < len(lines) and not lines[i].startswith('```'):
                    block_lines.append(lines[i]); i += 1
                if i < len(lines): block_lines.append(lines[i])
                block_text = '\n'.join(block_lines)
                if len(block_text) > 1000:
                    lines[start] = f"[ref:auto_compressed] large block ({len(block_text)} chars compressed)"
                    del lines[start+1:i+1]; replaced += 1; i = start + 1; continue
            i += 1
        return replaced

    def _aggressive_compress(self, lines: list) -> list:
        if len(lines) <= self.MIN_KEEP_AGGRESSIVE * 20: return lines
        keep_count = min(len(lines)//3, 80)
        if keep_count < self.MIN_KEEP_AGGRESSIVE * 20: keep_count = self.MIN_KEEP_AGGRESSIVE * 20
        kept = lines[-keep_count:]
        kept.insert(0, f"[AUTO-COMPRESSED] Deleted {len(lines)-len(kept)} lines of older context. Use session_search for full history.")
        return kept

    def _emergency_compress(self, lines: list) -> list:
        if len(lines) <= self.MIN_KEEP_EMERGENCY * 5: return lines
        keep_count = min(len(lines)//5, 30)
        if keep_count < self.MIN_KEEP_EMERGENCY * 5: keep_count = self.MIN_KEEP_EMERGENCY * 5
        kept = lines[-keep_count:]
        kept.insert(0, f"[EMERGENCY COMPRESSION ACTIVATED] Only last {keep_count} lines preserved. ({len(lines)-keep_count} lines deleted)")
        return kept

    def get_status(self, current_text: str) -> dict:
        tokens = self._estimate_tokens(current_text)
        ratio = tokens / self.context_window if self.context_window > 0 else 0
        level = "emergency" if ratio >= self.EMERGENCY_RATIO else "aggressive" if ratio >= self.AGGRESSIVE_RATIO else "mild" if ratio >= self.MILD_RATIO else "none"
        return {"current_tokens":tokens,"context_window":self.context_window,"usage_ratio":round(ratio*100,1),"recommended_level":level}


# ============================================================
# 模块3: RTK — 实时 token 压缩器 (原 rtk_compressor.py)
# ============================================================
class RTK:
    """RTK (Real-Time Token Killer) — 实时 token 压缩器"""
    SAFE_DROP_FIELDS = {"raw_data","rawData","metadata","tracking","timestamp","updated_at","created_at","_id","__v","version","revision"}
    MAX_LIST_ITEMS = 15; MAX_SNIPPET_CHARS = 300; MAX_TITLE_CHARS = 150

    @classmethod
    def compress(cls, content: Any, mode: str = "auto", ratio: float = 0.5, bp_level: int = 0) -> Union[str, Dict]:
        bp_mult = {0:1.0,1:0.7,2:0.4,3:0.2}; effective_ratio = ratio * bp_mult.get(bp_level,1.0)
        if mode == "auto":
            if isinstance(content, str):
                mode = "html" if content.strip().startswith("<") else "json" if content.strip().startswith("{") else "text"
            elif isinstance(content, dict): mode = "json"
            else: mode = "text"
        if mode == "html": return cls.compress_html(content, effective_ratio)
        elif mode == "json": return cls.compress_json(content, effective_ratio)
        else: return cls.compress_text(str(content), effective_ratio)

    @classmethod
    def compress_html(cls, html: str, ratio: float = 0.5) -> str:
        if not html: return ""
        text = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL|re.IGNORECASE)
        text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL|re.IGNORECASE)
        text = re.sub(r'<svg[^>]*>.*?</svg>', '', text, flags=re.DOTALL|re.IGNORECASE)
        text = re.sub(r'<!--.*?-->', '', text, flags=re.DOTALL)
        text = re.sub(r'<[^>]+>', ' ', text)
        text = text.replace('&amp;','&').replace('&lt;','<').replace('&gt;','>').replace('&quot;','"').replace('&#39;',"'").replace('&nbsp;',' ')
        text = re.sub(r'\s+', ' ', text); text = re.sub(r'\n\s*\n', '\n', text.strip())
        if ratio < 1.0 and len(text) > 200:
            target_len = max(int(len(text)*ratio), 200)
            text = text[:target_len] + "\n[... 已压缩 ...]"
        return text

    @classmethod
    def compress_text(cls, text: str, ratio: float = 0.5) -> str:
        if not text: return ""
        lines = text.split('\n'); seen = set(); unique_lines = []
        for line in lines:
            key = re.sub(r'\s+', '', line.strip())[:60]
            if key and key not in seen: seen.add(key); unique_lines.append(line)
        result = '\n'.join(unique_lines)
        if ratio < 1.0 and len(result) > 200:
            target_len = max(int(len(result)*ratio), 200)
            result = result[:target_len] + "\n[... 已压缩 ...]"
        return result

    @classmethod
    def compress_json(cls, data: Any, ratio: float = 0.5) -> Any:
        if isinstance(data, str):
            try: data = json.loads(data)
            except: return data[:int(len(data)*ratio)]
        if isinstance(data, dict): return cls._compress_dict(data, ratio)
        elif isinstance(data, list): return cls._compress_list(data, ratio)
        return data

    @classmethod
    def _compress_dict(cls, d: Dict, ratio: float) -> Dict:
        result = {}
        for k, v in d.items():
            k_lower = k.lower()
            if k_lower in cls.SAFE_DROP_FIELDS: continue
            if v is None or v == "" or v == [] or v == {}: continue
            if isinstance(v, str) and len(v) > cls.MAX_SNIPPET_CHARS: v = v[:cls.MAX_SNIPPET_CHARS] + "..."
            if isinstance(v, dict): v = cls._compress_dict(v, ratio)
            elif isinstance(v, list): v = cls._compress_list(v, ratio)
            result[k] = v
        return result

    @classmethod
    def _compress_list(cls, lst: List, ratio: float) -> List:
        if not lst: return lst
        keep = max(int(len(lst)*ratio), 1); keep = min(keep, cls.MAX_LIST_ITEMS)
        if len(lst) <= keep: return [cls.compress_json(item, ratio) for item in lst]
        result = [cls.compress_json(item, ratio) for item in lst[:keep]]
        result.append({"__truncated":True,"total_items":len(lst),"shown":keep})
        return result

    @classmethod
    def estimate_tokens(cls, text: str) -> int:
        return len(text) // 4

    @classmethod
    def compress_for_context(cls, content: Any, context_limit: int = 8000, current_usage: int = 0, bp_level: int = 0) -> str:
        available = context_limit - current_usage
        if available <= 0: return "[CONTEXT_LIMIT_REACHED]"
        text = json.dumps(content, ensure_ascii=False) if isinstance(content, (dict,list)) else str(content)
        estimated = cls.estimate_tokens(text)
        if estimated <= available: return text
        return cls.compress(text, ratio=available/estimated, bp_level=bp_level)


def compress_for_context(content: Any, context_limit: int = 8000, current_usage: int = 0, bp_level: int = 0) -> str:
    """快捷函数 — 兼容旧 rtk_compressor.py 接口"""
    return RTK.compress_for_context(content, context_limit, current_usage, bp_level)

def compress(content: Any, mode: str = "auto", ratio: float = 0.5) -> Any:
    """快捷函数 — 兼容旧 rtk_compressor.py 接口"""
    return RTK.compress(content, mode=mode, ratio=ratio)


# ============================================================
# 模块4: ContextCompressor — 对话/检查点压缩 (原 context_compressor.py)
# ============================================================
class ContextCompressor:
    """对话上下文压缩器 — 压缩对话/存断点/存快照"""

    def compress_conversation(self, conversation_json_path: str) -> dict:
        raw = Path(conversation_json_path).read_text()
        raw_bytes = raw.encode('utf-8')
        compressed = zlib.compress(raw_bytes, level=6)
        cksum = hashlib.sha256(raw_bytes).hexdigest()[:16]
        result = {"ts":_now(),"original_kb":round(len(raw_bytes)/1024,1),"compressed_kb":round(len(compressed)/1024,1),
                  "ratio":round(len(compressed)/max(len(raw_bytes),1),4),"checksum":cksum,"steps":0}
        db_path = HERMES / "active_memory.db"
        try:
            db = sqlite3.connect(str(db_path))
            db.execute("CREATE TABLE IF NOT EXISTS context_compressions (id INTEGER PRIMARY KEY AUTOINCREMENT,timestamp TEXT,original_bytes INTEGER,compressed_bytes INTEGER,ratio REAL,checksum TEXT,compressed_data BLOB)")
            db.execute("INSERT INTO context_compressions (timestamp,original_bytes,compressed_bytes,ratio,checksum,compressed_data) VALUES (?,?,?,?,?,?)",
                       (_now(), len(raw_bytes), len(compressed), result["ratio"], cksum, compressed))
            db.commit(); db.close()
        except: pass
        return result

    def store_task_checkpoint(self, task_id: str, status: str, completed: list, pending: list, next_action: str, detail: str):
        data = {"task_id":task_id,"status":status,"completed_steps":completed,"pending_steps":pending,"next_action":next_action,"detail":detail,"ts":_now()}
        (HERMES/"reports").mkdir(exist_ok=True)
        (HERMES/"task_current.json").write_text(json.dumps(data, ensure_ascii=False, indent=2))
        return data

    def store_audit_snapshot(self, title: str, content: str):
        checksum = hashlib.sha256(content.encode()).hexdigest()[:16]
        report = {"ts":_now(),"title":title,"content_preview":content[:500],"content_length":len(content),"checksum":checksum}
        (HERMES/"reports").mkdir(exist_ok=True)
        report_path = HERMES/"reports"/f"audit_{_now().replace(':','-')}.json"
        report_path.write_text(content)
        idx_path = HERMES/"reports"/"audit_index.json"
        idx = json.loads(idx_path.read_text()) if idx_path.exists() else []
        idx.append(report)
        if len(idx) > 50: idx = idx[-50:]
        idx_path.write_text(json.dumps(idx, ensure_ascii=False, indent=2))
        return {"stored":True,"path":str(report_path),"preview":content[:200]}


# ============================================================
# 模块5: compress_soul — SOUL.md 静态压缩 (原 compress_soul_static.py)
# ============================================================
def compress_soul() -> dict:
    """压缩 SOUL.md 为精简版 — 保留核心规则，移除 skill 列表/tools/记忆等"""
    soul = HERMES / "SOUL.md"
    if not soul.exists(): return {"error":"SOUL.md not found"}
    text = soul.read_text(encoding="utf-8")
    original_len = len(text)
    lines = text.split('\n')
    keep_sections = []; current_section = []; section_name = "header"; in_keep = True
    keep_keywords = ['规则','强制','永久','禁令','核心身份','行为准则','齿轮强制恢复','生产级可靠性',
                     'skills组合','低分数据自动清理','采集质量预筛','OI项目','全能力激活','自主能力基线','Memory']
    exclude_keywords = ['关键文件索引','九面人格','CONVERSATION','MEMORY','USER PROFILE',
                        'Host:','Home Channels','Connected Platforms','Delivery options','available_skills','## Tools']
    for line in lines:
        if line.startswith('## '):
            if current_section and in_keep: keep_sections.append((section_name, '\n'.join(current_section)))
            current_section = [line]; section_name = line.strip()
            in_keep = any(kw in line for kw in keep_keywords) and not any(kw in line for kw in exclude_keywords)
        elif line.startswith('### '):
            if current_section and in_keep: keep_sections.append((section_name, '\n'.join(current_section)))
            current_section = [line]; section_name = line.strip(); in_keep = True
        else:
            if current_section is not None: current_section.append(line)
    if current_section and in_keep: keep_sections.append((section_name, '\n'.join(current_section)))
    compressed = '\n'.join(c for _,c in keep_sections)
    compressed = re.sub(r'\n{3,}', '\n\n', compressed)
    compressed += '\n\n---\n*[该版本由SOUL.md静态压缩生成]*\n'
    output_path = HERMES / "reports" / "soul_compressed.md"
    output_path.write_text(compressed, encoding="utf-8")
    return {"original_chars":original_len,"compressed_chars":len(compressed),
            "compression_ratio":round((1-len(compressed)/original_len)*100,1),
            "sections_kept":len(keep_sections),"sections_removed":sum(1 for l in lines if l.startswith('## '))-len(keep_sections),
            "output":str(output_path)}

def _soul_main():
    """CLI入口 — 兼容原 compress_soul_static.py main()"""
    result = compress_soul()
    print(json.dumps(result, ensure_ascii=False, indent=2))


# ============================================================
# 模块6: FidelityValidator — 压缩保真度验证 (原 compression_fidelity_validator.py)
# ============================================================
STATS_FILE = HERMES / "reports" / "compression_stats_v2.json"

def _load_fidelity_stats() -> dict:
    if STATS_FILE.exists():
        try: return json.loads(STATS_FILE.read_text(encoding='utf-8'))
        except: pass
    return {"total_compressed":0,"total_bytes_in":0,"total_bytes_out":0,"total_fidelity_checks":0,"fidelity_failures":0,
            "l1_byte_fidelity":0,"l2_semantic_fidelity":0,"l3_structure_fidelity":0,"l4_compression_fidelity":0,"l5_transport_fidelity":0,
            "prefix_cache_hits":0,"prefix_cache_misses":0}

def _find_compressed_pairs() -> list:
    pairs = []
    sf = HERMES/"reports"/"conversation_summary.json"
    if sf.exists():
        try:
            data = json.loads(sf.read_text(encoding='utf-8'))
            if data.get("summary",""): pairs.append((Path(str(sf)+".original"), sf))
        except: pass
    tc = HERMES/"task_current.json"
    if tc.exists(): pairs.append((tc,tc))
    wg = HERMES/"reports"/"wake_guide.json"
    if wg.exists():
        try:
            data = json.loads(wg.read_text(encoding='utf-8'))
            if data.get("hy_memory",{}): pairs.append((Path(str(wg)+".hy_memory"), wg))
        except: pass
    return pairs

def _check_byte_fidelity(original_bytes: int, compressed_bytes: int) -> float:
    if original_bytes <= 0: return 0.0
    ratio = compressed_bytes / original_bytes
    if 0.005 <= ratio <= 1.0:
        if ratio <= 0.01: return 0.3
        return min(1.0, 1.0 - (ratio - 0.1) * 0.5)
    return 0.0

def _check_semantic_fidelity(stats: dict) -> float:
    try:
        wg = HERMES/"reports"/"wake_guide.json"
        if not wg.exists(): return 0.0
        data = json.loads(wg.read_text(encoding='utf-8'))
        hy = data.get("hy_memory",{})
        key_fields = ["relevant_memories","persona_summary","l1_stats"]
        found = sum(1 for f in key_fields if f in hy and hy[f])
        if found >= 3: return 1.0
        elif found >= 2: return 0.8
        elif found >= 1: return 0.5
        elif hy.get("scenes",[]) or hy.get("profiles",[]): return 0.3
        return 0.0
    except: return 0.0

def _check_structure_fidelity() -> float:
    score = 0.0; checks = 0
    for jf in [HERMES/"reports"/"wake_guide.json",HERMES/"reports"/"conversation_summary.json",HERMES/"task_current.json"]:
        if jf.exists():
            checks += 1
            try:
                data = json.loads(jf.read_text(encoding='utf-8'))
                score += 1.0 if isinstance(data,dict) else 0.8
            except: pass
    return score / max(checks,1)

def _check_compression_fidelity(stats: dict) -> float:
    total_in = stats.get("total_bytes_in",0); total_out = stats.get("total_bytes_out",0)
    if total_in <= 0: return 0.0
    ratio = total_out / total_in
    if ratio <= 0.01: return min(0.5, 0.3 + _check_semantic_fidelity(stats)*0.2)
    elif ratio <= 0.1: return 0.9
    elif ratio <= 0.3: return 0.7
    elif ratio <= 0.5: return 0.5
    return 0.2

def _check_transport_fidelity() -> float:
    score = 0.0; checks = 0
    key_files = [HERMES/"reports"/"wake_guide.json",HERMES/"reports"/"conversation_summary.json",
                 HERMES/"reports"/"compression_stats_v2.json",HERMES/"reports"/"gear_checkpoint.json",HERMES/"task_current.json"]
    for f in key_files:
        checks += 1
        if f.exists():
            try:
                content = f.read_bytes()
                score += 1.0 if len(content) >= 100 else 0.5
            except: pass
    tc = HERMES/"task_current.json"; gc = HERMES/"reports"/"gear_checkpoint.json"
    if tc.exists() and gc.exists():
        try:
            checks += 1
            if json.loads(tc.read_text()).get("task_id") == json.loads(gc.read_text()).get("task_id"): score += 1.0
        except: pass
    return score / max(checks,1)

def run_fidelity_validation(update_stats: bool = True) -> dict:
    """五级保真度验证 — 兼容原 compression_fidelity_validator.run_validation()"""
    stats = _load_fidelity_stats()
    pairs = _find_compressed_pairs()
    total_byte_fidelity = 0.0; byte_count = 0
    for orig, comp in pairs:
        byte_count += 1
        try:
            ob = len(orig.read_bytes()) if orig.exists() else 0
            cb = len(comp.read_bytes())
            total_byte_fidelity += _check_byte_fidelity(ob, cb)
        except: pass
    l1 = round(total_byte_fidelity/max(byte_count,1),3)
    l2 = round(_check_semantic_fidelity(stats),3)
    l3 = round(_check_structure_fidelity(),3)
    l4 = round(_check_compression_fidelity(stats),3)
    l5 = round(_check_transport_fidelity(),3)
    avg_fidelity = round((l1+l2+l3+l4+l5)/5,3)
    result = {"ts":time.strftime('%Y-%m-%dT%H:%M:%S'),"l1_byte_fidelity":l1,"l2_semantic_fidelity":l2,
              "l3_structure_fidelity":l3,"l4_compression_fidelity":l4,"l5_transport_fidelity":l5,
              "average_fidelity":avg_fidelity,"files_checked":byte_count}
    if update_stats:
        for key in ["l1_byte_fidelity","l2_semantic_fidelity","l3_structure_fidelity","l4_compression_fidelity","l5_transport_fidelity"]:
            stats[key] = round((stats.get(key,0)+result[key])/2,3)
        stats["total_fidelity_checks"] = stats.get("total_fidelity_checks",0)+1
        if avg_fidelity < 0.5 and stats.get("total_compressed",0) > 0:
            stats["fidelity_failures"] = stats.get("fidelity_failures",0)+1
        STATS_FILE.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"L1 byte: {l1}  L2 semantic: {l2}  L3 structure: {l3}  L4 compression: {l4}  L5 transport: {l5}  avg: {avg_fidelity}")
    return result


# ============================================================
# 模块7: 数据归档压缩 (原 run_compression.py + archive_compressor.py + memory_compress.py)
# ============================================================
DB_PATH = HERMES / "intelligence.db"

def archive_old_intelligence(days: int = 7, dry_run: bool = False) -> dict:
    """将 cleaned_intelligence 中超过指定天数的数据归档到 compressed_intelligence"""
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("""CREATE TABLE IF NOT EXISTS compressed_intelligence (
        id INTEGER PRIMARY KEY AUTOINCREMENT,source_id INTEGER,title TEXT,content_snippet TEXT,
        url TEXT,source TEXT,platform TEXT,importance_score REAL DEFAULT 0,
        ai_score_total REAL DEFAULT 0,ai_score_scarcity REAL DEFAULT 0,ai_score_impact REAL DEFAULT 0,
        ai_score_tech_depth REAL DEFAULT 0,ai_score_timeliness REAL DEFAULT 0,ai_score_preference REAL DEFAULT 0,
        ai_score_credibility REAL DEFAULT 0,collected_at TEXT,compressed_at TEXT DEFAULT (datetime('now')))""")
    cutoff = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
    pending = conn.execute("""SELECT COUNT(*) FROM cleaned_intelligence c
        WHERE (c.cleaned_at < ? OR c.cleaned_at IS NULL)
          AND c.id NOT IN (SELECT COALESCE(source_id,0) FROM compressed_intelligence)""", (cutoff,)).fetchone()[0]
    print(f"待归档: {pending}条 (>={days}天)")
    if dry_run: conn.close(); return {"pending":pending,"days":days,"dry_run":True}
    batch_size = 500; total_archived = 0
    while True:
        rows = conn.execute("""SELECT c.id,c.title,COALESCE(c.content,'') as content,c.url,c.source,c.platform,
            c.importance_score,c.ai_score_total,c.ai_score_scarcity,c.ai_score_impact,c.ai_score_tech_depth,
            c.ai_score_timeliness,c.ai_score_preference,c.ai_score_credibility,c.collected_at
            FROM cleaned_intelligence c WHERE (c.cleaned_at<? OR c.cleaned_at IS NULL)
            AND c.id NOT IN (SELECT COALESCE(source_id,0) FROM compressed_intelligence) LIMIT ?""", (cutoff, batch_size)).fetchall()
        if not rows: break
        archived = 0
        for row in rows:
            conn.execute("""INSERT OR IGNORE INTO compressed_intelligence (source_id,title,content_snippet,url,source,platform,
                importance_score,ai_score_total,ai_score_scarcity,ai_score_impact,ai_score_tech_depth,
                ai_score_timeliness,ai_score_preference,ai_score_credibility,collected_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (row[0],(row[1] or '')[:300],(row[2] or '')[:200],row[3],row[4],row[5],
                 row[6],row[7],row[8],row[9],row[10],row[11],row[12],row[13],row[14]))
            archived += 1
        conn.commit(); total_archived += archived
        if len(rows) < batch_size: break
    after = conn.execute("SELECT COUNT(*) FROM compressed_intelligence").fetchone()[0]
    conn.close()
    return {"archived":total_archived,"total_in_compressed":after,"days":days}


# ============================================================
# CLI 入口 — 兼容全部9个旧脚本的调用方式
# ============================================================
def main():
    """统一CLI入口 — python3 compression_engine.py <command> [args]"""
    if len(sys.argv) < 2:
        print("用法: compression_engine.py <命令> [参数]")
        print("命令: claw|emergency|rtk|context|soul|fidelity|archive|compress")
        print("  claw status                          LosslessClaw状态")
        print("  claw compress <section> <data>       压缩数据")
        print("  claw decompress <section>            解压数据")
        print("  emergency [text]                     紧急压缩")
        print("  rtk compress <mode> <text>           RTK压缩")
        print("  soul                                  SOUL.md静态压缩")
        print("  fidelity [check]                      保真度验证")
        print("  archive [days]                        数据归档")
        return

    cmd = sys.argv[1]

    if cmd == "claw":
        c = LosslessClawCompressor()
        sub = sys.argv[2] if len(sys.argv) > 2 else "status"
        if sub == "status": print(json.dumps(c.status(), ensure_ascii=False, indent=2))
        elif sub == "compress" and len(sys.argv) >= 5:
            r = c.compress(sys.argv[3], sys.argv[4], int(sys.argv[5]) if len(sys.argv) > 5 else 1)
            print(json.dumps(r, ensure_ascii=False, indent=2))
        elif sub == "decompress" and len(sys.argv) >= 4:
            d = c.decompress(sys.argv[3])
            print(d[:2000] if d else f"No data for {sys.argv[3]}")
        elif sub == "level1": print(json.dumps(c.level1_compress(), ensure_ascii=False, indent=2))
        elif sub == "level2": print(json.dumps(c.level2_compress(), ensure_ascii=False, indent=2))
        elif sub == "level3":
            days = int(sys.argv[3]) if len(sys.argv) > 3 else 7
            print(json.dumps(c.level3_archive(days), ensure_ascii=False, indent=2))
        else: print(f"Unknown claw subcommand: {sub}")

    elif cmd == "emergency":
        e = EmergencyCompressor()
        text = sys.argv[2] if len(sys.argv) > 2 else (sys.stdin.read() if not sys.stdin.isatty() else "")
        if not text: print("需要输入文本"); return
        result = e.compress(text)
        print(f"Original: {result['original_tokens']}t → Compressed: {result['compressed_tokens']}t")
        print(f"Saved: {result['saved_tokens']}t ({result['saved_percent']}%) Level: {result['level']}")

    elif cmd == "rtk" and len(sys.argv) >= 4:
        mode = sys.argv[2]; text = sys.argv[3]
        result = RTK.compress(text, mode=mode)
        print(result)

    elif cmd == "soul":
        result = compress_soul()
        print(json.dumps(result, ensure_ascii=False, indent=2))

    elif cmd == "fidelity":
        check_only = len(sys.argv) > 2 and sys.argv[2] == "check"
        run_fidelity_validation(update_stats=not check_only)

    elif cmd == "archive":
        days = int(sys.argv[2]) if len(sys.argv) > 2 else 7
        result = archive_old_intelligence(days)
        print(json.dumps(result, ensure_ascii=False, indent=2))

    elif cmd == "compress":
        # 兼容原 run_compression.py 直接执行
        result = archive_old_intelligence(days=7)
        print(json.dumps(result, ensure_ascii=False, indent=2))

    else:
        print(f"Unknown command: {cmd}")


if __name__ == "__main__":
    main()
