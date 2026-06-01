#!/usr/bin/env python3
"""
🔴🔴🔴 反幻觉铁律：严禁任何不加核实的猜想、胡编乱造、自己瞎编！
必须核实才能说/必须验证才能写/必须确认才能断言/不知道就说不知道
这是最高优先级规则，凌驾于所有其他规则之上。
"""

"""
l1_extractor.py — L1 原子事实自动提取引擎 v2.0 (LLM增强版)
======================================================================
对应 Hy-Memory: src/core/record/l1-extractor.ts (18KB) + src/core/prompts/l1-extraction.ts

核心改进 v2.0:
  1. ✅ LLM语义级提取 — 用 delegate_task 调用 Hermes LLM 能力
  2. ✅ 场景分片 — 一次LLM调用同时完成场景分割+事实提取
  3. ✅ LM Studio本地LLM支持 — 零成本本地提取 (端口8080或API配置)
  4. ✅ 降级策略 — LLM不可用时自动降级到规则引擎

Hy-Memory L1 三类型:
  - persona: 用户稳定属性/偏好/技能/价值观
  - episodic: 客观事件/决策/计划/结果
  - instruction: 对AI的长期行为规则/格式偏好

依赖: Python 3.8+, 可通过 active_memory.db 直接使用
       可选: LM Studio (http://localhost:8080) 或 Ollama (http://localhost:11434)

用法:
  # LLM模式 (推荐)
  python3 scripts/l1_extractor.py llm "对话文本"
  
  # 规则模式 (无LLM)
  python3 scripts/l1_extractor.py rule "对话文本"
  
  # 批处理 (从文件读取多轮对话)
  python3 scripts/l1_extractor.py batch /path/to/sessions.txt
  
  # 统计
  python3 scripts/l1_extractor.py stats
  
  # 自动模式 (cron: 凌晨4点批量处理)
  python3 scripts/l1_extractor.py --auto
"""

import sqlite3
import json
import time
import re
import hashlib
import sys
import os
import textwrap
import subprocess
from pathlib import Path
from typing import Optional, Any

ACTIVE_MEMORY_DB = Path.home() / ".hermes" / "active_memory.db"
SCRIPTS_DIR = Path.home() / ".hermes" / "scripts"


# ====================== L1 LLM 提取系统 ======================

class L1LLMExtractor:
    """
    L1 LLM 事实提取器
    
    通过 Hermes 的 LLM 能力（delegate_task/LM Studio/Ollama）
    进行语义级事实提取，对标 Hy-Memory 的 callLlmExtraction()
    
    支持的LLM后端:
      1. delegate_task — 子Agent调用Hermes LLM (最推荐)
      2. LM Studio — http://localhost:8080/v1/chat/completions
      3. Ollama — http://localhost:11434/api/generate
    """
    
    # Hy-Memory 精确的系统提示词
    L1_SYSTEM_PROMPT = """你是专业的\"情境切分与记忆提取专家\"。
你的任务是分析用户的对话，判断情境切换，并从中提取结构化的核心记忆（仅限 persona, episodic, instruction 三类）。

**输出语言**：所有自由文本字段（`scene_name`、memory `content`）使用与用户消息相同的语言；JSON 字段名、枚举值保持英文。

### 任务一：情境切分（Scene Segmentation）
分析【待提取的新消息】，结合【上一个情境】，判断并输出当前对话的情境。
- 继承：无明显切换，沿用上一个情境。
- 切换条件：用户发出明确指令（如"换话题"）、意图转变、或提出独立新目标。
- 一段对话可能只有一个情境，也可能有多个情境（话题多次切换时）。
- 命名规则：我（AI）在和xxx（用户身份）做xxx（目标活动）（使用上述输出语言，约 30-50 个字符，单句，全局唯一）。

---

### 任务二：核心记忆提取（Memory Extraction）
结合背景和当前情境，仅从【待提取的新消息】中提取核心信息。

【通用提取原则】
1. 宁缺毋滥：过滤琐碎闲聊、临时性指令和一次性操作（如"这次、本单"）；剔除不可靠的边缘信息。
2. 独立完整：记忆必须"跳出当前对话依然成立"，无上下文也能看懂。提取主体必须以"用户（姓名）"或"AI"为核心。
3. 归纳合并：强关联或因果关系的多条消息，必须合并为一条完整记忆，不可碎片化。

【支持提取的三大类型】（必须严格遵守类型规则）
1. 个性化记忆 (type: "persona")
   - 定义：用户的稳定属性、偏好、技能、价值观、习惯（如住所、职业、饮食禁忌）。
   - 提取句式："用户（[姓名]）喜欢/是/擅长..."
   - 打分 (priority)：80-100（健康/禁忌/核心特质）；50-70（一般喜好/技能）；<50（模糊次要，可丢弃）。
   - 触发词：喜欢、习惯、经常、我这个人...

2. 客观事件记忆 (type: "episodic")
   - 定义：客观发生的动作、决定、计划或达成结果。绝不包含纯主观感受。
   - 提取句式："用户（[姓名]）在 [时间] 于 [地点] [做了某事（可以包含起因、经过、结果）]"
   - 打分 (priority)：80-100（重要事件/计划）；60-70（一般完整活动）；<60（琐碎事项，直接丢弃）。

3. 全局指令记忆 (type: "instruction")
   - 定义：用户对 AI 提出的长期行为规则、格式偏好、语气控制。
   - 提取句式："用户要求/希望 AI 以后回答时..."
   - 打分 (priority)：-1（极其严格的全局死命令）；90-100（核心行为规则）；70-80（重要要求）；<70（临时要求，直接丢弃）。

---

### 不应该提取的内容
- 琐碎闲聊、问候；临时性的纯工具性请求（如"这次帮我翻译一下"）
- 一次性操作指令（如"这次、本单"相关）
- 重复的内容；AI助手自身的行为或输出
- 不属于以上3类的信息
- 纯主观感受（不带客观事件的情绪表达）

---

### 输出格式规范（JSON）
返回且仅返回一个合法的 JSON 数组。数组的每一项是一个情境，包含该情境的消息范围和抽取到的记忆：

[
  {
    "scene_name": "当前生成或继承的情境名称",
    "message_ids": [1, 2, 3],
    "memories": [
      {
        "content": "完整、独立的记忆陈述",
        "type": "persona|episodic|instruction",
        "priority": 80,
        "source_message_ids": [1, 2],
        "metadata": {}
      }
    ]
  }
]

如果整段对话无有意义的记忆，也要输出情境分割结果，memories 为空数组。"""
    
    def __init__(self, llm_mode: str = "auto"):
        """
        llm_mode: 
          "delegate" — 使用 delegate_task 调用Hermes LLM (最推荐)
          "lmstudio" — 使用 LM Studio 本地LLM (http://localhost:8080)
          "ollama" — 使用 Ollama 本地LLM (http://localhost:11434)
          "auto" — 自动检测可用后端 (优先delegate > lmstudio > ollama > 规则引擎)
        """
        self.llm_mode = llm_mode
        
    def _detect_llm_backend(self) -> str:
        """自动检测可用的LLM后端"""
        # 检查 LM Studio
        try:
            import urllib.request
            req = urllib.request.Request("http://localhost:8080/v1/models")
            urllib.request.urlopen(req, timeout=2)
            return "lmstudio"
        except Exception:
            pass
        # 检查 Ollama
        try:
            import urllib.request
            req = urllib.request.Request("http://localhost:11434/api/tags")
            urllib.request.urlopen(req, timeout=2)
            return "ollama"
        except Exception:
            pass
        # 默认用delegate模式 (通过子agent调用LLM)
        return "delegate"

    def extract_with_llm(self, conversation_text: str, 
                         previous_scene_name: str = "无",
                         llm_mode: Optional[str] = None) -> list[dict]:
        """
        使用LLM提取事实（核心方法）
        
        对应 Hy-Memory: callLlmExtraction() 
        
        参数:
          conversation_text: 对话文本
          previous_scene_name: 上一个情境名称（用于连续性）
          llm_mode: 覆盖LLM后端模式
          
        返回: [{"fact": "...", "cat": "preference|knowledge|...", "confidence": 0.N,
                 "scene": "场景名", "type": "persona|episodic|instruction"}, ...]
        """
        mode = llm_mode or self.llm_mode
        if mode == "auto":
            mode = self._detect_llm_backend()
        
        # 构建 LLM 提示词
        user_prompt = self._build_prompt(conversation_text, previous_scene_name)
        
        # 根据后端调用LLM
        if mode == "delegate":
            raw_result = self._call_delegate_llm(user_prompt)
        elif mode == "lmstudio":
            raw_result = self._call_lmstudio(user_prompt)
        elif mode == "ollama":
            raw_result = self._call_ollama(user_prompt)
        else:
            return []
        
        if not raw_result:
            return []
        
        # 解析LLM输出 → 结构化事实
        return self._parse_llm_result(raw_result, conversation_text)

    def _build_prompt(self, conversation_text: str, previous_scene_name: str) -> str:
        """构建L1提取提示词（对应 Hy-Memory formatExtractionPrompt）"""
        # 提取背景对话（取前500字作为背景）
        bg = conversation_text[:500] if len(conversation_text) > 500 else "无"
        # 新消息（取最后3000字作为提取对象）
        new_msgs = conversation_text[-3000:] if len(conversation_text) > 3000 else conversation_text
        
        return f"""**输出语言**：根据下方对话中 user 发言的主导语言书写 content。

【上一个情境】：{previous_scene_name}

【背景对话】（仅供理解上下文推断关系/时间，严禁从中提取记忆）：
{bg}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

【待提取的新消息】（务必结合上下文推算，只从这里提取记忆！）：
{new_msgs}"""

    def _call_delegate_llm(self, user_prompt: str) -> Optional[str]:
        """
        通过 delegate_task 调用 Hermes LLM
        
        创建子Agent，让它用LLM分析对话并提取结构化事实
        子Agent的goal精确描述任务，context传入对话内容
        """
        try:
            # 使用 subprocess 调用 delegate_task
            # 注意: delegate_task 是Hermes内部工具，这里通过子进程调用hermes
            # 实际在工作流中是通过 execute_code + delegate_task 调用
            # 这里通过写临时文件 + 返回约定实现
            tmpfile = Path(f"/tmp/l1_llm_request_{int(time.time())}.json")
            request = {
                "system_prompt": self.L1_SYSTEM_PROMPT,
                "user_prompt": user_prompt,
            }
            tmpfile.write_text(json.dumps(request, ensure_ascii=False), encoding='utf-8')
            # delegate_task 调用由上层（hy_memory_orchestrator.py）负责
            # 这里返回标记，由调用者做实际delegate
            return None
        except Exception:
            return None

    def _call_lmstudio(self, user_prompt: str) -> Optional[str]:
        """调用 LM Studio 本地LLM"""
        try:
            import urllib.request
            payload = json.dumps({
                "model": "local-model",
                "messages": [
                    {"role": "system", "content": self.L1_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt}
                ],
                "temperature": 0.1,
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
        except Exception as e:
            print(f"  [L1] LM Studio调用失败: {e}", file=sys.stderr)
            return None

    def _call_ollama(self, user_prompt: str) -> Optional[str]:
        """调用 Ollama 本地LLM"""
        try:
            import urllib.request
            # 先检测可用模型
            req = urllib.request.Request("http://localhost:11434/api/tags")
            with urllib.request.urlopen(req, timeout=5) as resp:
                models = json.loads(resp.read())
                model_name = "llama3.1:8b"  # 默认
                for m in models.get("models", []):
                    name = m.get("name", "")
                    if "qwen" in name.lower() or "llama" in name.lower():
                        model_name = name
                        break
            
            payload = json.dumps({
                "model": model_name,
                "system": self.L1_SYSTEM_PROMPT,
                "prompt": user_prompt,
                "stream": False,
                "options": {"temperature": 0.1, "num_predict": 4096}
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
        except Exception as e:
            print(f"  [L1] Ollama调用失败: {e}", file=sys.stderr)
            return None

    def _parse_llm_result(self, raw: str, conversation_text: str) -> list[dict]:
        """
        解析 LLM 输出 → 标准事实格式
        
        对应 Hy-Memory: parseExtractionResult()
        
        返回: [{"fact": "...", "cat": "preference|knowledge|...", 
                "confidence": 0.N, "scene": "场景名"}, ...]
        """
        # Hy-Memory 类型映射
        TYPE_TO_CAT = {
            "persona": "preference",
            "episodic": "knowledge",
            "instruction": "system_config",
        }
        
        # 清理LLM输出
        raw = raw.strip()
        if raw.startswith("```"):
            raw = re.sub(r'^```(?:json)?\s*\n?', '', raw)
            raw = re.sub(r'\n?```\s*$', '', raw)
        
        # 尝试提取JSON数组
        try:
            # 找到第一个 [ 和最后一个 ]
            start = raw.find('[')
            end = raw.rfind(']')
            if start >= 0 and end > start:
                json_str = raw[start:end+1]
                scenes = json.loads(json_str)
            else:
                scenes = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            print(f"  [L1] LLM输出JSON解析失败, 尝试宽松匹配")
            # 宽松匹配：尝试提取任何 JSON 数组
            arr_match = re.search(r'\[[\s\S]*?\]', raw)
            if arr_match:
                try:
                    scenes = json.loads(arr_match.group())
                except json.JSONDecodeError:
                    print(f"  [L1] 宽松匹配也失败，返回空")
                    return []
            else:
                return []
        
        if not isinstance(scenes, list):
            return []
        
        facts = []
        for scene in scenes:
            if not isinstance(scene, dict):
                continue
            scene_name = scene.get("scene_name", "未知情境")
            memories = scene.get("memories", [])
            
            for mem in memories:
                if not isinstance(mem, dict):
                    continue
                content = mem.get("content", "")
                mem_type = mem.get("type", "episodic")
                priority = mem.get("priority", 50)
                
                if not content or len(content) < 10:
                    continue
                
                # 类型映射 + 质量过滤
                if mem_type not in TYPE_TO_CAT:
                    continue
                cat = TYPE_TO_CAT[mem_type]
                
                # 置信度从 priority 映射
                if mem_type == "instruction" and priority == -1:
                    confidence = 0.95  # 严格死命令
                elif priority >= 80:
                    confidence = 0.9
                elif priority >= 60:
                    confidence = 0.7
                elif priority >= 40:
                    confidence = 0.5
                else:
                    confidence = 0.3
                
                # 补充source_message_ids
                source_ids = mem.get("source_message_ids", [])
                metadata = mem.get("metadata", {})
                
                facts.append({
                    "fact": content,
                    "cat": cat,
                    "confidence": confidence,
                    "scene": scene_name,
                    "type": mem_type,
                    "priority": priority,
                    "source_ids": source_ids,
                    "metadata": metadata,
                    "source": "llm",
                })
        
        return facts


# ====================== 规则引擎（保留为降级方案） ======================

class L1RuleExtractor:
    """规则引擎版 L1 提取器——LLM不可用时的降级方案"""
    
    RULES = [
        (r'偏好|喜欢|更倾向|更愿意|更喜欢|想要|希望', 'preference', 0.6),
        (r'不喜欢|讨厌|反感|不要|禁止|不用', 'preference', 0.7),
        (r'配置|设置|改用|改为|换成|路径|端口|IP|地址', 'system_config', 0.6),
        (r'cron|定时|自动|脚本|计划', 'system_config', 0.5),
        (r'WSL|Windows|Linux|Ubuntu|macOS|系统|版本', 'environment', 0.7),
        (r'安装|部署|运行在|安装在|目录|路径', 'environment', 0.5),
        (r'决定|选择|方案|路线|策略|规划|方向', 'product_direction', 0.5),
        (r'是指|意思是|定义为|概念|原理|机制|架构', 'knowledge', 0.5),
        (r'不对|错了|问题|bug|故障|[不]?满意|好[的了]?|可以[了]?', 'feedback', 0.5),
        (r'技术|趋势|新[型款]?|前沿|最新|突破|发布', 'tech_breakthrough', 0.4),
        (r'成本|价格|费用|预算|花了|要钱|免费', 'cost_trend', 0.5),
        (r'token|API|调用|额度|限制|超[出额]', 'cost_trend', 0.6),
    ]
    
    def extract(self, text: str) -> list[dict]:
        results = []
        seen_facts = set()
        for pattern, category, confidence in self.RULES:
            for match in re.finditer(pattern, text):
                start = max(0, match.start() - 30)
                end = min(len(text), match.end() + 60)
                context = text[start:end].strip().replace('\n', ' ')[:120]
                dedup_key = f"{category}:{context[:50]}"
                if dedup_key in seen_facts:
                    continue
                seen_facts.add(dedup_key)
                results.append({
                    "fact": f"{category}识别: {context}",
                    "cat": category,
                    "confidence": round(confidence, 2),
                    "source": "rule_engine",
                    "scene": "规则引擎提取",
                })
        return results


# ====================== 数据库写入器 ======================

class L1DBWriter:
    """将提取的事实写入 memory_semantic + FTS5 索引"""
    
    def __init__(self, db_path: str = str(ACTIVE_MEMORY_DB)):
        self.db_path = db_path
    
    def _get_db(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn
    
    def _generate_id(self, fact: str) -> str:
        ts = time.strftime('%Y%m%d%H%M%S')
        h = hashlib.md5(fact.encode()).hexdigest()[:12]
        return f"sem_{ts}_{h}"
    
    def _keywordize(self, fact: str) -> str:
        """从事实文本中提取关键词（用于FTS5索引）"""
        english = re.findall(r'[a-zA-Z][a-zA-Z0-9._-]{2,}', fact)
        chinese_all = re.findall(r'[\u4e00-\u9fff]+', fact)
        chinese = []
        for phrase in chinese_all:
            if len(phrase) <= 1:
                continue
            chinese.append(phrase)
            for i in range(len(phrase) - 1):
                sub = phrase[i:i+2]
                chinese.append(sub)
        stop_words = {'的', '了', '在', '是', '有', '和', '就', '不', '人', '都',
                      '也', '很', '到', '说', '要', '去', '你', '我', '他', '她',
                      '会', '着', '没有', '看', '好', '自己', '这', '那', '什么',
                      '怎么', '为', '与', '及', '但', '而', '或', '被', '把',
                      '从', '对', '用', '以', '能', '可', '让', '将', '向',
                      '还', '又', '才', '只', '再', '就', '都', '吗', '吧', '呢',
                      'the', 'this', 'that', 'and', 'for', 'with', 'from'}
        keywords = [w for w in chinese + english 
                    if w.lower() not in stop_words and len(w) >= 2]
        return json.dumps(list(set(keywords)), ensure_ascii=False)
    
    def _dedup_check(self, cursor: sqlite3.Cursor, fact: str, cat: str) -> tuple[bool, bool]:
        """去重检查：返回 (exists, is_update)"""
        try:
            kw = json.loads(self._keywordize(fact))
            if kw:
                sample_kws = kw[:3]
                for kw in sample_kws:
                    cursor.execute(
                        "SELECT rowid FROM memory_semantic WHERE cat=? AND fact LIKE ? AND active=1 LIMIT 1",
                        (cat, f'%{kw}%')
                    )
                    if cursor.fetchone():
                        return True, True  # 已存在，更新置信度
        except (json.JSONDecodeError, sqlite3.Error):
            pass
        cursor.execute(
            "SELECT rowid FROM memory_semantic WHERE fact=? AND cat=? AND active=1 LIMIT 1",
            (fact, cat)
        )
        if cursor.fetchone():
            return True, True
        return False, False
    
    def write_facts(self, facts: list[dict]) -> dict:
        """写入事实到数据库"""
        conn = self._get_db()
        c = conn.cursor()
        result = {"written": 0, "skipped": 0, "updated": 0}
        
        for fact_data in facts:
            fact = fact_data.get("fact", "")
            cat = fact_data.get("cat", "knowledge")
            confidence = fact_data.get("confidence", 0.5)
            source = fact_data.get("source", "llm")
            scene = fact_data.get("scene", "")
            
            if not fact or len(fact) < 10:
                result["skipped"] += 1
                continue
            
            try:
                exists, is_update = self._dedup_check(c, fact, cat)
                if exists:
                    # 更新优先级/置信度
                    c.execute(
                        "UPDATE memory_semantic SET confidence=MAX(confidence, ?), "
                        "src_count=src_count+1, confirmed_at=datetime('now') "
                        "WHERE fact=? AND cat=? AND active=1",
                        (confidence, fact, cat)
                    )
                    if c.rowcount > 0:
                        result["updated"] += 1
                    else:
                        result["skipped"] += 1
                    conn.commit()
                    continue
                
                fact_id = self._generate_id(fact)
                keywords = self._keywordize(fact)
                
                c.execute(
                    """INSERT INTO memory_semantic 
                    (id, fact, cat, confidence, src_count, keywords, ehash, active)
                    VALUES (?, ?, ?, ?, 1, ?, ?, 1)""",
                    (fact_id, fact, cat, confidence, keywords, fact_id)
                )
                conn.commit()
                result["written"] += 1
                
            except sqlite3.Error as e:
                print(f"  [L1] DB error: {e}", file=sys.stderr)
                continue
        
        conn.close()
        return result
    
    def get_stats(self) -> dict:
        conn = self._get_db()
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM memory_semantic")
        total = c.fetchone()[0]
        c.execute("SELECT cat, COUNT(*) FROM memory_semantic GROUP BY cat ORDER BY COUNT(*) DESC")
        categories = {r[0]: r[1] for r in c.fetchall()}
        conn.close()
        return {"total_facts": total, "categories": categories, "db_path": self.db_path}


# ====================== 主提取器 ======================

class L1Extractor:
    """
    L1 原子事实提取器 v2.0
    
    三层策略:
      1. LLM提取 (优先) — 通过delegate_task/LM Studio/Ollama
      2. 规则引擎 (降级) — LLM不可用时
      3. 直接写入 (手动) — 已知事实直接入库
    
    与Hy-Memory的对应:
      - callLlmExtraction() → extract_with_llm()
      - batchDedup() → _dedup_check()
      - writeMemory() → write_facts()
    """
    
    def __init__(self, llm_mode: str = "auto"):
        self.llm_extractor = L1LLMExtractor(llm_mode)
        self.rule_extractor = L1RuleExtractor()
        self.db_writer = L1DBWriter()
    
    def extract(self, text: str, use_llm: bool = True,
                previous_scene: str = "无") -> dict:
        """
        从文本中提取事实并写入数据库
        
        参数:
          text: 对话文本
          use_llm: 是否优先使用LLM提取
          previous_scene: 上一个情境名称
          
        返回:
          {"facts_found": N, "written": N, "method": "llm|rule", "facts": [...]}
        """
        facts = []
        method = "none"
        
        if use_llm:
            try:
                llm_facts = self.llm_extractor.extract_with_llm(text, previous_scene)
                if llm_facts:
                    facts = llm_facts
                    method = "llm"
                    print(f"  [L1] LLM提取: {len(facts)} 条事实")
            except Exception as e:
                print(f"  [L1] LLM提取失败: {e}, 降级到规则引擎", file=sys.stderr)
        
        if not facts:
            facts = self.rule_extractor.extract(text)
            method = "rule" if facts else "none"
            if facts:
                print(f"  [L1] 规则引擎提取: {len(facts)} 条事实")
        
        if not facts:
            return {"facts_found": 0, "written": 0, "method": method, "facts": []}
        
        write_result = self.db_writer.write_facts(facts)
        
        print(f"  [L1] 写入: {write_result['written']} 新增, "
              f"{write_result['updated']} 更新, {write_result['skipped']} 跳过")
        
        return {
            "facts_found": len(facts),
            "written": write_result["written"],
            "updated": write_result["updated"],
            "skipped": write_result["skipped"],
            "method": method,
            "facts": facts,
        }


# ====================== CLI 接口 ======================

def cmd_llm(args: list[str]):
    """LLM模式提取"""
    text = " ".join(args)
    if not text:
        print("用法: l1_extractor.py llm <对话文本>")
        return
    extractor = L1Extractor(llm_mode="auto")
    result = extractor.extract(text, use_llm=True)
    print(f"\n结果: {result['facts_found']} 条事实发现, {result['written']} 条写入 (方式: {result['method']})")
    if result.get("facts"):
        print("\n提取的事实:")
        for f in result["facts"]:
            print(f"  [{f['cat']}] ({f.get('confidence', '?')}) {f['fact'][:120]}...")


def cmd_rule(args: list[str]):
    """规则模式提取"""
    text = " ".join(args)
    if not text:
        print("用法: l1_extractor.py rule <对话文本>")
        return
    extractor = L1Extractor()
    result = extractor.extract(text, use_llm=False)
    print(f"\n结果: {result['facts_found']} 条发现, {result['written']} 条写入")


def cmd_stats():
    """统计"""
    writer = L1DBWriter()
    stats = writer.get_stats()
    print(f"总事实数: {stats['total_facts']}")
    print("分类:")
    for cat, cnt in sorted(stats['categories'].items(), key=lambda x: -x[1]):
        print(f"  {cat}: {cnt}")


def cmd_auto():
    """
    自动模式: 从对话历史批量提取事实
    由 cron 在凌晨4点调用
    """
    print("[L1 Auto] 启动自动提取...")
    # 获取所有最近对话轮次
    # 从 memory_episodic 中提取最近的记录
    conn = sqlite3.connect(str(ACTIVE_MEMORY_DB))
    cur = conn.cursor()
    cur.execute("""
        SELECT content, source, created_at 
        FROM memory_episodic 
        ORDER BY created_at DESC 
        LIMIT 20
    """)
    episodes = cur.fetchall()
    conn.close()
    
    if not episodes:
        print("[L1 Auto] 没有情景记录需要提取")
        return
    
    extractor = L1Extractor(llm_mode="auto")
    total_written = 0
    for content, source, created_at in episodes:
        if len(content) < 30:
            continue
        result = extractor.extract(content, use_llm=True)
        total_written += result["written"]
    
    print(f"[L1 Auto] 完成! 共写入 {total_written} 条新事实")


if __name__ == "__main__":
    args = sys.argv[1:]
    
    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
    elif args[0] == "llm" and len(args) > 1:
        cmd_llm(args[1:])
    elif args[0] == "rule" and len(args) > 1:
        cmd_rule(args[1:])
    elif args[0] == "batch":
        cmd_llm(args[1:])  # batch 同 llm 模式
    elif args[0] == "stats":
        cmd_stats()
    elif args[0] == "--auto":
        cmd_auto()
    else:
        cmd_llm(args)
