#!/usr/bin/env python3
"""
hermes_desktop_bridge.py — 从 Hermes Desktop 提取的会话/技能管理模块
原项目: https://github.com/fathah/hermes-desktop
提取自: src/main/sessions.ts + src/main/skills.ts + src/main/session-cache.ts

能力: 会话查询/管理 + 技能管理 + 会话缓存
"""

import json, sqlite3, os, re, time
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, List, Dict

HERMES = Path.home() / ".hermes"

# ============================================================
# 会话管理 (原 src/main/sessions.ts)
# ============================================================
CONTENT_JSON_PREFIX = "\x00json:"

def get_session_db() -> Optional[sqlite3.Connection]:
    """获取 Hermes state 数据库连接"""
    state_db = HERMES / "data" / "hermes_state.db"
    if not state_db.exists():
        state_db = HERMES / "state.db"
    if not state_db.exists():
        return None
    conn = sqlite3.connect(str(state_db))
    conn.row_factory = sqlite3.Row
    return conn

def list_sessions(limit: int = 20, source: str = "") -> list:
    """列出会话摘要"""
    conn = get_session_db()
    if not conn:
        return [{"error": "state.db not found"}]
    try:
        where = ""
        params = []
        if source:
            where = "WHERE source = ?"
            params.append(source)
        rows = conn.execute(f"""
            SELECT id, source, started_at, ended_at, message_count, model, title,
                   substr(content, 1, 100) as preview
            FROM sessions {where}
            ORDER BY started_at DESC LIMIT ?
        """, params + [limit]).fetchall()
        sessions = []
        for r in rows:
            sessions.append({
                "id": r["id"], "source": r["source"],
                "started_at": r["started_at"], "ended_at": r["ended_at"],
                "message_count": r["message_count"], "model": r["model"],
                "title": r["title"], "preview": r["preview"]
            })
        return sessions
    except Exception as e:
        return [{"error": str(e)}]
    finally:
        conn.close()

def get_session_messages(session_id: str, limit: int = 50) -> list:
    """获取会话消息"""
    conn = get_session_db()
    if not conn:
        return [{"error": "state.db not found"}]
    try:
        rows = conn.execute("""
            SELECT id, role, content, timestamp
            FROM messages WHERE session_id = ?
            ORDER BY id ASC LIMIT ?
        """, (session_id, limit)).fetchall()
        messages = []
        for r in rows:
            content = r["content"]
            if isinstance(content, str) and content.startswith(CONTENT_JSON_PREFIX):
                try:
                    content = json.loads(content[len(CONTENT_JSON_PREFIX):])
                except: pass
            messages.append({
                "id": r["id"], "role": r["role"],
                "content": str(content)[:500], "timestamp": r["timestamp"]
            })
        return messages
    except Exception as e:
        return [{"error": str(e)}]
    finally:
        conn.close()

def delete_session(session_id: str) -> dict:
    """删除会话"""
    conn = get_session_db()
    if not conn:
        return {"error": "state.db not found"}
    try:
        conn.execute("DELETE FROM messages WHERE session_id=?", (session_id,))
        conn.execute("DELETE FROM sessions WHERE id=?", (session_id,))
        conn.commit()
        return {"deleted": True, "session_id": session_id}
    except Exception as e:
        return {"error": str(e)}
    finally:
        conn.close()

# ============================================================
# 技能管理 (原 src/main/skills.ts)
# ============================================================
def list_skills() -> list:
    """列出所有可用技能"""
    skills_dir = HERMES / "skills"
    if not skills_dir.exists():
        return []
    skills = []
    for f in sorted(skills_dir.glob("**/SKILL.md")):
        rel = f.relative_to(skills_dir)
        skill_name = str(rel.parent)
        try:
            content = f.read_text(encoding='utf-8')
            # 提取标题
            title = ""
            for line in content.split('\n')[:5]:
                if line.startswith('# '):
                    title = line[2:].strip()
                    break
            skills.append({"name": skill_name, "title": title or skill_name})
        except:
            skills.append({"name": skill_name, "title": skill_name})
    return skills

def get_skill_content(name: str) -> Optional[str]:
    """读取技能内容"""
    skill_file = HERMES / "skills" / name / "SKILL.md"
    if skill_file.exists():
        return skill_file.read_text(encoding='utf-8')
    return None

# ============================================================
# 会话缓存 (原 src/main/session-cache.ts)
# ============================================================
CACHE_FILE = HERMES / "reports" / "session_cache.json"

def add_to_cache(session_id: str, title: str = "", summary: str = ""):
    """添加会话到缓存"""
    cache = {"sessions": [], "updated_at": ""}
    if CACHE_FILE.exists():
        try:
            cache = json.loads(CACHE_FILE.read_text())
        except: pass
    # 更新或添加
    found = False
    for s in cache["sessions"]:
        if s["id"] == session_id:
            s["title"] = title
            s["summary"] = summary
            s["accessed_at"] = datetime.now().isoformat()
            found = True
            break
    if not found:
        cache["sessions"].append({
            "id": session_id, "title": title, "summary": summary,
            "accessed_at": datetime.now().isoformat()
        })
    # 只保留最近100条
    if len(cache["sessions"]) > 100:
        cache["sessions"] = cache["sessions"][-100:]
    cache["updated_at"] = datetime.now().isoformat()
    CACHE_FILE.parent.mkdir(exist_ok=True)
    CACHE_FILE.write_text(json.dumps(cache, ensure_ascii=False, indent=2))

def get_cached_sessions() -> list:
    """获取缓存的会话"""
    if not CACHE_FILE.exists():
        return []
    try:
        return json.loads(CACHE_FILE.read_text()).get("sessions", [])
    except:
        return []

def remove_from_cache(session_id: str):
    """从缓存移除会话"""
    if not CACHE_FILE.exists():
        return
    try:
        cache = json.loads(CACHE_FILE.read_text())
        cache["sessions"] = [s for s in cache["sessions"] if s["id"] != session_id]
        CACHE_FILE.write_text(json.dumps(cache, ensure_ascii=False, indent=2))
    except: pass


# ============================================================
# CLI
# ============================================================
def main():
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "help"

    if cmd == "sessions":
        limit = int(sys.argv[2]) if len(sys.argv) > 2 else 20
        source = sys.argv[3] if len(sys.argv) > 3 else ""
        sessions = list_sessions(limit, source)
        print(json.dumps(sessions, ensure_ascii=False, indent=2))

    elif cmd == "messages":
        sid = sys.argv[2] if len(sys.argv) > 2 else ""
        if sid:
            msgs = get_session_messages(sid)
            print(json.dumps(msgs, ensure_ascii=False, indent=2))
        else:
            print("需要 session_id")

    elif cmd == "delete-session":
        sid = sys.argv[2] if len(sys.argv) > 2 else ""
        if sid:
            print(json.dumps(delete_session(sid)))
        else:
            print("需要 session_id")

    elif cmd == "skills":
        skills = list_skills()
        print(json.dumps(skills, ensure_ascii=False, indent=2))

    elif cmd == "skill":
        name = sys.argv[2] if len(sys.argv) > 2 else ""
        content = get_skill_content(name)
        if content:
            print(content[:2000])
        else:
            print(f"Skill not found: {name}")

    elif cmd == "cache":
        print(json.dumps(get_cached_sessions(), ensure_ascii=False, indent=2))

    else:
        print("""
Desktop Bridge — 会话/技能管理
用法:
  desktop_bridge.py sessions [limit] [source]    列出会话
  desktop_bridge.py messages <session_id>         查看会话消息
  desktop_bridge.py delete-session <session_id>   删除会话
  desktop_bridge.py skills                        列出技能
  desktop_bridge.py skill <name>                  查看技能内容
  desktop_bridge.py cache                         查看会话缓存
""")


if __name__ == "__main__":
    main()
