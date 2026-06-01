#!/usr/bin/env python3
"""
🔴🔴🔴 反幻觉铁律：严禁任何不加核实的猜想、胡编乱造、自己瞎编！
必须核实才能说/必须验证才能写/必须确认才能断言/不知道就说不知道
这是最高优先级规则，凌驾于所有其他规则之上。
"""

"""
l2_scene_scheduler.py — L2 场景归纳自动调度器 (LLM驱动)
======================================================================
对应 Hy-Memory: src/core/scene/scene-extractor.ts (20KB) + src/offload/pipelines/l2-mermaid.ts

核心逻辑:
  1. 从 memory_semantic 读取最近新增的事实
  2. 通过 delegate_task 调用 Hermes LLM 归纳场景
  3. 写入 memory_scene 表
  4. 更新 wake_injector 的场景导航索引

触发条件: 
  - 每次 L1 提取后检查 (由 hy_memory_orchestrator.py 统一调度)
  - 或每2小时由 cron 自动触发
  - 条件: 自上次场景归纳后的新增事实 >= 10 条

用法:
  python3 scripts/l2_scene_scheduler.py
  python3 scripts/l2_scene_scheduler.py --force   # 强制重新归纳所有场景
  python3 scripts/l2_scene_scheduler.py stats
"""

import sqlite3
import json
import time
import hashlib
import re
import sys
from pathlib import Path
from typing import Optional

ACTIVE_MEMORY_DB = Path.home() / ".hermes" / "active_memory.db"
SCENE_TRIGGER_THRESHOLD = 10  # 新增10条事实触发一次场景归纳
L2_MAX_SCENES = 15  # 最大场景数 (对应 Hy-Memory maxScenes)


class L2SceneScheduler:
    """
    L2 场景归纳调度器
    
    对标 Hy-Memory 的:
      - SceneExtractor.extract() — 从L1记忆生成L2场景
      - L2触发条件: everyNConversations=5 轮 + idleTimeout=600s + 
        minInterval=900s, maxInterval=3600s
    """
    
    def __init__(self):
        pass
    
    def _get_db(self):
        conn = sqlite3.connect(str(ACTIVE_MEMORY_DB))
        conn.row_factory = sqlite3.Row
        return conn
    
    def _get_new_facts_count(self) -> int:
        """获取自上次场景归纳后的新增事实数"""
        conn = self._get_db()
        cur = conn.cursor()
        # memory_scene使用last_activated作为更新时间
        cur.execute("SELECT MAX(last_activated) FROM memory_scene")
        last_scene = cur.fetchone()[0]
        
        if last_scene:
            cur.execute("""
                SELECT COUNT(*) FROM memory_semantic 
                WHERE created_at > ? AND active = 1
            """, (last_scene,))
        else:
            cur.execute("SELECT COUNT(*) FROM memory_semantic WHERE active = 1")
        
        count = cur.fetchone()[0]
        conn.close()
        return count
    
    def _get_recent_facts(self, limit: int = 50) -> list[dict]:
        """获取最近的事实（用于LLM场景归纳）"""
        conn = self._get_db()
        cur = conn.cursor()
        cur.execute("""
            SELECT id, fact, cat, confidence, created_at
            FROM memory_semantic 
            WHERE active = 1
            ORDER BY created_at DESC
            LIMIT ?
        """, (limit,))
        facts = [{"id": r[0], "fact": r[1], "cat": r[2], 
                  "confidence": r[3], "created_at": r[4]} 
                 for r in cur.fetchall()]
        conn.close()
        return facts
    
    def _get_existing_scenes(self) -> list[str]:
        """获取已有场景列表"""
        conn = self._get_db()
        cur = conn.cursor()
        cur.execute("SELECT name FROM memory_scene ORDER BY frequency DESC")
        scenes = [r[0] for r in cur.fetchall()]
        conn.close()
        return scenes
    
    def check_trigger(self) -> tuple[bool, dict]:
        """
        检查是否满足 L2 场景归纳触发条件
        对应 Hy-Memory: checkL2Trigger()
        
        返回: (should_run, info)
        """
        new_count = self._get_new_facts_count()
        existing = self._get_existing_scenes()
        
        should_run = new_count >= SCENE_TRIGGER_THRESHOLD
        info = {
            "new_facts_since_last_scene": new_count,
            "threshold": SCENE_TRIGGER_THRESHOLD,
            "existing_scenes": len(existing),
            "scene_names": existing,
            "should_run": should_run,
        }
        
        return should_run, info
    
    def build_scene_prompt(self, facts: list[dict], existing_scenes: list[str]) -> str:
        """
        构建场景归纳任务的提示词
        对应 Hy-Memory: src/core/prompts/scene-extraction.ts
        """
        facts_json = json.dumps(facts[:40], ensure_ascii=False, indent=2)
        scenes_summary = "\n".join(f"- {s}" for s in existing_scenes) if existing_scenes else "无"
        
        return f"""# L2 场景归纳任务

## 现有场景
{scenes_summary}

## 待归纳的事实（最近{len(facts)}条）
{facts_json}

## 任务要求
1. 分析以上事实，归纳出主题一致的"场景块"
2. 每个场景块包含: 名称、描述、关键词、关联事实ID列表
3. 最多{min(L2_MAX_SCENES, 20)}个场景
4. 已有场景如果仍有相关新事实，请合并到已有场景中
5. 全新主题的事实，创建新场景
6. 输出JSON格式: [{{"name": "场景名", "description": "描述", "keywords": ["kw1","kw2"], "fact_ids": ["id1","id2"], "frequency": N, "confidence": 0.N}}]"""

    def consume_llm_result(self, llm_result: str, facts: list[dict]) -> list[dict]:
        """
        解析LLM输出的场景归纳结果
        返回场景列表: [{name, description, keywords, frequency, confidence}, ...]
        """
        raw = llm_result.strip()
        if raw.startswith("```"):
            raw = re.sub(r'^```(?:json)?\s*\n?', '', raw)
            raw = re.sub(r'\n?```\s*$', '', raw)
        
        try:
            start = raw.find('[')
            end = raw.rfind(']')
            if start >= 0 and end > start:
                scenes = json.loads(raw[start:end+1])
            else:
                scenes = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            print(f"  [L2] JSON解析失败，原始输出前500字: {raw[:500]}")
            return []
        
        if not isinstance(scenes, list):
            return []
        
        # 标准化场景
        standardized = []
        seen_names = set()
        for s in scenes:
            if not isinstance(s, dict):
                continue
            name = str(s.get("name", "")).strip()
            if not name or name in seen_names:
                continue
            seen_names.add(name)
            standardized.append({
                "name": name,
                "description": str(s.get("description", ""))[:200],
                "keywords": s.get("keywords", []),
                "frequency": int(s.get("frequency", 1)),
                "confidence": float(s.get("confidence", 0.5)),
            })
        
        return standardized
    
    def write_scenes(self, scenes: list[dict]) -> dict:
        """写入场景到数据库"""
        if not scenes:
            return {"written": 0, "updated": 0}
        
        conn = self._get_db()
        cur = conn.cursor()
        
        result = {"written": 0, "updated": 0}
        now = time.strftime('%Y-%m-%d %H:%M:%S')
        
        for scene in scenes:
            try:
                name = scene["name"]
                desc = scene.get("description", "")
                tags = json.dumps(scene.get("keywords", []), ensure_ascii=False)
                freq = scene.get("frequency", 1)
                conf = scene.get("confidence", 0.5)
                
                # 检查是否已存在
                cur.execute("SELECT id FROM memory_scene WHERE name = ?", (name,))
                existing = cur.fetchone()
                
                if existing:
                    cur.execute("""
                        UPDATE memory_scene SET 
                            description = ?, tags = ?, 
                            frequency = frequency + ?, 
                            confidence = MAX(confidence, ?),
                            last_activated = ?
                        WHERE name = ?
                    """, (desc, tags, freq, conf, now, name))
                    result["updated"] += 1
                else:
                    scene_id = f"scene_{int(time.time())}_{hashlib.md5(name.encode()).hexdigest()[:8]}"
                    cur.execute("""
                        INSERT INTO memory_scene 
                        (id, name, description, tags, frequency, confidence, last_activated, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """, (scene_id, name, desc, tags, freq, conf, now, now))
                    result["written"] += 1
                
                conn.commit()
            except sqlite3.Error as e:
                print(f"  [L2] DB error: {e}", file=sys.stderr)
                continue
        
        conn.close()
        return result
    
    def run(self, force: bool = False) -> dict:
        """
        执行 L2 场景归纳
        使用 LLM 分析事实并生成场景
        
        返回: {triggered, scene_count, ...}
        """
        should_run, info = self.check_trigger()
        
        if not should_run and not force:
            return {
                "triggered": False,
                "new_facts": info["new_facts_since_last_scene"],
                "threshold": SCENE_TRIGGER_THRESHOLD,
                "message": f"未达触发条件 (新增{info['new_facts_since_last_scene']}条 < 阈值{SCENE_TRIGGER_THRESHOLD})",
            }
        
        facts = self._get_recent_facts(50)
        existing = self._get_existing_scenes()
        
        print(f"  [L2] 触发场景归纳: {len(facts)} 条事实, {len(existing)} 个已有场景")
        
        # 构建场景归纳提示词
        prompt = self.build_scene_prompt(facts, existing)
        
        # 尝试调用本地LLM
        llm_result = self._call_local_llm(prompt)
        
        if not llm_result:
            # LLM不可用，使用规则引擎简易版本
            scenes = self._rule_based_scenes(facts, existing)
        else:
            scenes = self.consume_llm_result(llm_result, facts)
        
        if not scenes:
            return {"triggered": True, "scene_count": 0, "message": "无场景可归纳"}
        
        # 写入数据库
        write_result = self.write_scenes(scenes)
        
        return {
            "triggered": True,
            "scene_count": len(scenes),
            "new_facts": len(facts),
            "written": write_result["written"],
            "updated": write_result["updated"],
            "scenes": [s["name"] for s in scenes],
        }
    
    def _call_local_llm(self, prompt: str) -> Optional[str]:
        """
        调用本地LLM (LM Studio 或 Ollama)
        对应 Hy-Memory: LLM工具调用
        """
        # 尝试 LM Studio
        try:
            import urllib.request
            payload = json.dumps({
                "model": "local-model",
                "messages": [
                    {"role": "system", "content": "你是专业的记忆整合架构师。分析事实数据，归纳出场景块。"},
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.2,
                "max_tokens": 4096,
            }).encode()
            req = urllib.request.Request(
                "http://localhost:8080/v1/chat/completions",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=180) as resp:
                result = json.loads(resp.read())
                return result["choices"][0]["message"]["content"]
        except Exception:
            pass
        
        # 尝试 Ollama
        try:
            import urllib.request
            # 检测可用模型
            req = urllib.request.Request("http://localhost:11434/api/tags")
            with urllib.request.urlopen(req, timeout=5) as resp:
                models = json.loads(resp.read())
                model_name = "llama3.1:8b"
                for m in models.get("models", []):
                    name = m.get("name", "")
                    if "qwen" in name.lower() or "llama" in name.lower():
                        model_name = name
                        break
            
            payload = json.dumps({
                "model": model_name,
                "system": "你是专业的记忆整合架构师。",
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.2, "num_predict": 4096}
            }).encode()
            req = urllib.request.Request(
                "http://localhost:11434/api/generate",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=180) as resp:
                result = json.loads(resp.read())
                return result.get("response", "")
        except Exception:
            pass
        
        return None
    
    def _rule_based_scenes(self, facts: list[dict], existing: list[str]) -> list[dict]:
        """无LLM时的简易场景归纳（降级方案）"""
        # 按类别分组作为场景
        cat_scenes = {}
        for f in facts:
            cat = f.get("cat", "other")
            if cat not in cat_scenes:
                cat_scenes[cat] = {"facts": [], "keywords": set()}
            cat_scenes[cat]["facts"].append(f["fact"])
            # 从事实提取关键词
            words = re.findall(r'[\u4e00-\u9fff]{2,}', f["fact"])
            cat_scenes[cat]["keywords"].update(words[:5])
        
        scenes = []
        CAT_TO_DESC = {
            "preference": "用户的偏好、喜好与习惯",
            "knowledge": "系统知识与技术原理",
            "environment": "开发环境与系统配置",
            "system_config": "系统设置与工作规则",
            "product_direction": "产品方向与决策",
            "feedback": "用户反馈与评价",
            "tech_breakthrough": "技术趋势与突破",
            "cost_trend": "成本与资源管理",
            "open_source": "开源生态与社区",
        }
        
        for cat, data in cat_scenes.items():
            if len(data["facts"]) < 2:  # 少于2条不构成场景
                continue
            desc = CAT_TO_DESC.get(cat, f"与{cat}相关的话题")
            scenes.append({
                "name": cat,
                "description": desc,
                "keywords": list(data["keywords"])[:10],
                "frequency": len(data["facts"]),
                "confidence": 0.5,
            })
        
        return scenes


# ====================== CLI ======================

if __name__ == "__main__":
    scheduler = L2SceneScheduler()
    
    if len(sys.argv) > 1 and sys.argv[1] == "--force":
        result = scheduler.run(force=True)
    elif len(sys.argv) > 1 and sys.argv[1] == "check":
        should_run, info = scheduler.check_trigger()
        print(f"触发条件: {'✅ 可触发' if should_run else '❌ 不满足'}")
        print(f"  新增事实: {info['new_facts_since_last_scene']} (阈值: {info['threshold']})")
        print(f"  已有场景: {info['existing_scenes']} 个")
        if info['scene_names']:
            for s in info['scene_names']:
                print(f"    - {s}")
    elif len(sys.argv) > 1 and sys.argv[1] == "stats":
        conn = sqlite3.connect(str(ACTIVE_MEMORY_DB))
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM memory_scene")
        count = cur.fetchone()[0]
        cur.execute("SELECT name, frequency, confidence FROM memory_scene ORDER BY frequency DESC")
        print(f"场景总数: {count}")
        for r in cur.fetchall():
            print(f"  {r[0]}: freq={r[1]}, conf={r[2]}")
        conn.close()
    else:
        result = scheduler.run()
        print(json.dumps(result, ensure_ascii=False, indent=2))
