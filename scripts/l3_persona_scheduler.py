#!/usr/bin/env python3
"""
🔴🔴🔴 反幻觉铁律：严禁任何不加核实的猜想、胡编乱造、自己瞎编！
必须核实才能说/必须验证才能写/必须确认才能断言/不知道就说不知道
这是最高优先级规则，凌驾于所有其他规则之上。
"""

"""
l3_persona_scheduler.py — L3 画像自动生成调度器 (LLM驱动)
======================================================================
对应 Hy-Memory: src/core/persona/persona-generator.ts (9KB) + persona-trigger.ts

核心逻辑:
  1. 从 memory_scene + memory_semantic 读取最新数据
  2. 通过 delegate_task 调用 Hermes LLM 综合生成用户画像
  3. 写入 memory_profile 表
  4. 更新 wake_injector 的画像注入

触发条件:
  - L2场景变化 >= 3个 (对应 Hy-Memory triggerEveryN=50)
  - 或每天凌晨5点 cron 自动执行
  - 或手动 --force

用法:
  python3 scripts/l3_persona_scheduler.py
  python3 scripts/l3_persona_scheduler.py --force
  python3 scripts/l3_persona_scheduler.py stats
"""

import sqlite3
import json
import time
import hashlib
import sys
from pathlib import Path
from typing import Optional

ACTIVE_MEMORY_DB = Path.home() / ".hermes" / "active_memory.db"
PERSONA_TRIGGER_SCENE_CHANGES = 3  # 3个场景变化触发一次画像更新


class L3PersonaScheduler:
    """
    L3 画像生成调度器
    
    对标 Hy-Memory 的:
      - PersonaTrigger — 检测画像更新条件
      - PersonaGenerator — 调用LLM生成/更新persona.md
      - 四层深度扫描: Layer1基础 → Layer2兴趣 → Layer3交互 → Layer4认知
    """
    
    def __init__(self):
        pass
    
    def _get_db(self):
        conn = sqlite3.connect(str(ACTIVE_MEMORY_DB))
        conn.row_factory = sqlite3.Row
        return conn
    
    def get_current_persona(self) -> Optional[dict]:
        """获取当前用户画像"""
        conn = self._get_db()
        cur = conn.cursor()
        cur.execute("""
            SELECT name, profile_type, dimensions, summary, updated_at 
            FROM memory_profile 
            WHERE profile_type = 'user'
            ORDER BY updated_at DESC 
            LIMIT 1
        """)
        row = cur.fetchone()
        conn.close()
        if row:
            dims = json.loads(row[3]) if isinstance(row[3], str) else {}
            return {
                "name": row[0],
                "type": row[1],
                "dimensions": row[2],
                "summary": dims,
                "updated_at": row[4],
            }
        return None
    
    def check_trigger(self) -> tuple[bool, dict]:
        """检查L3触发条件"""
        conn = self._get_db()
        cur = conn.cursor()
        
        # 获取上次画像更新时间
        cur.execute("SELECT MAX(updated_at) FROM memory_profile WHERE profile_type='user'")
        last_persona = cur.fetchone()[0]
        
        # 获取上次L2场景后变更的场景数
        if last_persona:
            cur.execute("""
                SELECT COUNT(*) FROM memory_scene 
                WHERE last_activated > ?
            """, (last_persona,))
        else:
            cur.execute("SELECT COUNT(*) FROM memory_scene")
        
        changed_scenes = cur.fetchone()[0]
        
        # 获取统计数据
        cur.execute("SELECT COUNT(*) FROM memory_semantic WHERE active=1")
        total_facts = cur.fetchone()[0]
        
        cur.execute("SELECT COUNT(*) FROM memory_scene")
        total_scenes = cur.fetchone()[0]
        
        should_run = changed_scenes >= PERSONA_TRIGGER_SCENE_CHANGES
        info = {
            "changed_scenes_since_last_persona": changed_scenes,
            "threshold": PERSONA_TRIGGER_SCENE_CHANGES,
            "total_facts": total_facts,
            "total_scenes": total_scenes,
            "last_persona_at": last_persona,
            "should_run": should_run,
        }
        
        conn.close()
        return should_run, info
    
    def build_persona_prompt(self) -> str:
        """
        构建画像生成提示词
        对应 Hy-Memory: prompts/persona-generation.ts 四层深度扫描
        """
        conn = self._get_db()
        cur = conn.cursor()
        
        # 获取所有场景
        cur.execute("""
            SELECT name, description, tags, frequency, confidence 
            FROM memory_scene 
            ORDER BY frequency DESC 
            LIMIT 15
        """)
        scenes = cur.fetchall()
        
        # 获取按类别分组的事实
        cur.execute("""
            SELECT cat, COUNT(*) as cnt, 
                   GROUP_CONCAT(fact, '\n---\n') as samples
            FROM memory_semantic 
            WHERE active = 1 AND confidence >= 0.4
            GROUP BY cat 
            ORDER BY cnt DESC
            LIMIT 15
        """)
        cat_facts = {}
        for r in cur.fetchall():
            cat_facts[r[0]] = {
                "count": r[1],
                "samples": r[2][:3000] if r[2] else "",
            }
        
        # 现有画像
        cur.execute("""
            SELECT summary FROM memory_profile 
            WHERE profile_type='user' 
            ORDER BY updated_at DESC LIMIT 1
        """)
        existing = cur.fetchone()
        
        conn.close()
        
        # 构建提示词
        scenes_text = "\n".join(
            f"- {s[0]}: {s[1][:100] if s[1] else '无描述'} (热度:{s[3]}, 置信度:{s[4]})"
            for s in scenes
        ) if scenes else "无"
        
        facts_text = "\n".join(
            f"### {cat}\n({info['count']}条)\n{info['samples'][:500]}"
            for cat, info in cat_facts.items()
        ) if cat_facts else "无"
        
        existing_text = existing[0] if existing else "无"
        
        return f"""# 🔴 L3 用户画像生成任务

## 现有画像（供参考和增量更新）
{existing_text}

## 当前场景数据
{scenes_text}

## 提取的事实（按类别分组）
{facts_text}

## 四层深度扫描要求

### 🟢 Layer 1: 基础锚点
- 确凿的事实、用户特征、当前状态
- 提取用户的基本信息、角色、工作模式

### 🔵 Layer 2: 兴趣图谱
- 用户投入时间/精力的领域
- 区分活跃/被动兴趣

### 🟡 Layer 3: 交互协议
- 用户的沟通习惯、工作流偏好、交付标准
- 如何和这个用户高效协作

### 🔴 Layer 4: 认知内核
- 决策逻辑、驱动力、价值观
- 让Agent能真正理解用户的思维模式

## 输出JSON格式
{{"archetype": "核心原型一句话", "basic_info": {{"role": "角色", "domain": "领域", "mode": "工作模式"}}, "interests": ["兴趣1", "兴趣2"], "protocol": {{"comm_style": "沟通风格", "quality_standard": "质量标准", "workflow_pref": "工作流偏好"}}, "core": {{"decision_logic": "决策逻辑", "driving_force": "驱动力", "values": ["价值1", "价值2"]}}, "summary": "综合画像描述（100字内）"}}"""

    def consume_llm_result(self, llm_result: str) -> Optional[dict]:
        """解析LLM输出的画像"""
        raw = llm_result.strip()
        if raw.startswith("```"):
            raw = re.sub(r'^```(?:json)?\s*\n?', '', raw)
            raw = re.sub(r'\n?```\s*$', '', raw)
        
        try:
            start = raw.find('{')
            end = raw.rfind('}')
            if start >= 0 and end > start:
                return json.loads(raw[start:end+1])
            return json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            print(f"  [L3] JSON解析失败")
            return None
    
    def write_persona(self, persona: dict) -> dict:
        """写入画像到数据库"""
        if not persona:
            return {"written": 0}
        
        conn = self._get_db()
        cur = conn.cursor()
        now = time.strftime('%Y-%m-%d %H:%M:%S')
        
        archetype = persona.get("archetype", "")
        basic_info = persona.get("basic_info", {})
        interests = persona.get("interests", [])
        protocol = persona.get("protocol", {})
        core = persona.get("core", {})
        summary = persona.get("summary", "")
        
        dimensions = json.dumps({
            "archetype": archetype,
            "basic_info": basic_info,
            "interests": interests,
            "protocol": protocol,
            "core": core,
        }, ensure_ascii=False)
        
        profile_id = f"profile_{int(time.time())}"
        
        # 检查是否已存在
        cur.execute(
            "SELECT id FROM memory_profile WHERE profile_type='user' ORDER BY updated_at DESC LIMIT 1"
        )
        existing = cur.fetchone()
        
        if existing:
            cur.execute("""
                UPDATE memory_profile SET 
                    dimensions = ?, summary = ?, updated_at = ?
                WHERE id = ?
            """, (dimensions, json.dumps(persona, ensure_ascii=False), now, existing[0]))
            result = {"written": 0, "updated": 1}
        else:
            cur.execute("""
                INSERT INTO memory_profile (id, name, profile_type, dimensions, summary, updated_at)
                VALUES (?, ?, 'user', ?, ?, ?)
            """, (profile_id, "格林主人", dimensions, json.dumps(persona, ensure_ascii=False), now))
            result = {"written": 1, "updated": 0}
        
        conn.commit()
        conn.close()
        return result
    
    def run(self, force: bool = False) -> dict:
        """
        执行 L3 画像生成
        使用 LLM 四层深度分析生成用户画像
        
        🔴 注意: 这里生成的画像只作为基础数据
        最终、最精确、最语义化的L3画像由
        当前对话中的LLM（Hermes自己）实时生成并写入 memory_profile
        """
        should_run, info = self.check_trigger()
        
        if not should_run and not force:
            return {
                "triggered": False,
                "changed_scenes": info["changed_scenes_since_last_persona"],
                "threshold": PERSONA_TRIGGER_SCENE_CHANGES,
                "message": f"未达触发条件 (变化{info['changed_scenes_since_last_persona']}个 < 阈值{PERSONA_TRIGGER_SCENE_CHANGES})",
            }
        
        print(f"  [L3] 触发画像生成: {info['total_facts']} 条事实, {info['total_scenes']} 个场景")
        
        # 构建提示词
        prompt = self.build_persona_prompt()
        
        # 尝试LLM调用
        llm_result = self._call_local_llm(prompt)
        
        if llm_result:
            persona = self.consume_llm_result(llm_result)
        else:
            print("  [L3] LLM不可用，使用规则引擎降级生成画像")
            persona = self._rule_based_persona(info)
            if not persona:
                return {
                    "triggered": True,
                    "success": False,
                    "message": "LLM不可用且规则降级失败，画像生成需要LLM能力",
                }
        
        if not persona:
            return {"triggered": True, "success": False, "message": "画像解析失败"}
        
        write_result = self.write_persona(persona)
        
        return {
            "triggered": True,
            "success": True,
            "archetype": persona.get("archetype", ""),
            "summary": persona.get("summary", ""),
            "written": write_result["written"],
            "updated": write_result["updated"],
        }
    
    def _call_local_llm(self, prompt: str) -> Optional[str]:
        """调用本地LLM — 通过llm_bridge统一入口"""
        try:
            from scripts.llm_bridge import llm_call
            # 用Hermes自身模型(对话态), 不可用时自动降级LM Studio和Ollama
            result = llm_call(
                system_prompt="你是画像架构师。分析用户数据,生成四层画像,输出JSON。",
                user_prompt=prompt,
                temperature=0.3,
                max_tokens=4096,
                timeout=180,
                preferred_backend="delegate"  # 优先对话模型
            )
            if result.success:
                return result.text
            # 失败时llm_bridge已自动fallback到本地LLM
            return None
        except Exception:
            return None

    def _rule_based_persona(self, trigger_info: dict) -> Optional[dict]:
        """
        L3降级路径: 当LLM不可用时，使用规则引擎从 memory_scene + memory_semantic 生成画像
        """
        try:
            conn = self._get_db()
            cur = conn.cursor()
            
            # 提取场景标签形成兴趣
            cur.execute("SELECT name, tags, frequency FROM memory_scene ORDER BY frequency DESC LIMIT 10")
            scenes = cur.fetchall()
            
            interests = set()
            for s in scenes:
                name = s[0] or ""
                tags_str = s[2] or ""
                if isinstance(tags_str, str) and tags_str:
                    try:
                        tags = json.loads(tags_str) if tags_str.startswith('[') else [tags_str]
                    except:
                        tags = [tags_str]
                    for t in tags:
                        if isinstance(t, str) and len(t) >= 2:
                            interests.add(t)
                elif name:
                    interests.add(name[:30])
            
            # 提取偏好
            cur.execute("SELECT fact FROM memory_semantic WHERE cat='preference' AND active=1 ORDER BY confidence DESC LIMIT 5")
            prefs = [r[0] for r in cur.fetchall()]
            
            conn.close()
            
            domain = "general"
            for s in scenes:
                n = (s[0] or "").lower()
                if any(kw in n for kw in ['开发', 'programming', 'coding', 'code', 'dev']):
                    domain = "technology/development"
                    break
                if any(kw in n for kw in ['写作', 'writing', 'content']):
                    domain = "content/creation"
                    break
            
            num_facts = trigger_info.get("total_facts", 0)
            num_scenes = trigger_info.get("total_scenes", 0)
            
            persona = {
                "archetype": f"Active user ({domain} focused, {num_facts} facts, {num_scenes} scenes)" if num_facts > 0 else "New user",
                "basic_info": {
                    "role": "user",
                    "domain": domain,
                    "mode": "interactive"
                },
                "interests": list(interests)[:10] if interests else ["general"],
                "protocol": {
                    "comm_style": "technical",
                    "quality_standard": "high",
                    "workflow_pref": "iterative"
                },
                "core": {
                    "decision_logic": "goal-oriented",
                    "driving_force": "task completion",
                    "values": ["efficiency", "accuracy"]
                },
                "summary": (
                    f"Rule-generated persona based on {num_facts} facts and {num_scenes} scenes. "
                    f"Domains: {domain}. "
                    f"{'Preferences: ' + '; '.join(prefs[:3]) if prefs else 'No explicit preferences recorded.'}"
                )[:200]
            }
            print(f"  [L3] 规则引擎降级完成: archetype={persona['archetype'][:50]}")
            return persona
            
        except Exception as e:
            print(f"  [L3] 规则降级失败: {e}")
            return None


# ====================== CLI ======================

if __name__ == "__main__":
    scheduler = L3PersonaScheduler()
    
    if len(sys.argv) > 1 and sys.argv[1] == "--force":
        result = scheduler.run(force=True)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif len(sys.argv) > 1 and sys.argv[1] == "check":
        should_run, info = scheduler.check_trigger()
        print(f"触发条件: {'✅ 可触发' if should_run else '❌ 不满足'}")
        print(f"  变化场景: {info['changed_scenes_since_last_persona']} (阈值: {info['threshold']})")
        print(f"  总事实: {info['total_facts']}, 总场景: {info['total_scenes']}")
        if info.get('last_persona_at'):
            print(f"  上次画像: {info['last_persona_at']}")
    elif len(sys.argv) > 1 and sys.argv[1] == "stats":
        conn = sqlite3.connect(str(ACTIVE_MEMORY_DB))
        cur = conn.cursor()
        cur.execute("SELECT name, profile_type, updated_at FROM memory_profile ORDER BY updated_at DESC")
        for r in cur.fetchall():
            print(f"  {r[0]} ({r[1]}): {r[2]}")
        conn.close()
    else:
        result = scheduler.run()
        print(json.dumps(result, ensure_ascii=False, indent=2))
