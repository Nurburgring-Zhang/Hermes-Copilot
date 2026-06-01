#!/usr/bin/env python3
"""
🔴🔴🔴 反幻觉铁律：严禁任何不加核实的猜想、胡编乱造、自己瞎编！
必须核实才能说/必须验证才能写/必须确认才能断言/不知道就说不知道
这是最高优先级规则，凌驾于所有其他规则之上。
"""

"""
episodic_injector.py — 情景记忆自动注入引擎
================================================
将对话轮次、任务边界、工具调用等"情景"写入 memory_episodic 表。
对标 Hy-Memory L0 层（原始对话记录）。

写入后 auto_recall 的 structmem 搜索可以召回历史对话情景。

用法：
  python3 scripts/episodic_injector.py inject --session "会话摘要" --source "对话"
  python3 scripts/episodic_injector.py stats
"""

import sqlite3
import json
import time
import hashlib
import re
from pathlib import Path
from typing import Optional

ACTIVE_MEMORY_DB = Path.home() / ".hermes" / "active_memory.db"


class LLMEnhancedInjector:
    """
    LLM增强的情景摘要生成器
    
    自动从对话文本中提取关键情景信息，生成高质量的摘要
    """
    
    SUMMARIZE_PROMPT = """你是对话情景分析专家。分析以下对话片段，提取核心情景信息。

对话内容：
{DIALOG}

请输出JSON格式的情景记录：
{{"summary": "50字以内的一句话摘要", "tags": ["关键词1", "关键词2", "关键词3"], "importance": 0.0-1.0, "source_type": "conversation|system|task"}}"""
    
    def generate_summary(self, content: str) -> Optional[dict]:
        """用LLM生成高质量情景摘要"""
        prompt = self.SUMMARIZE_PROMPT.format(DIALOG=content[:2000].replace('{','(').replace('}',')'))
        
        from llm_bridge import llm_call_json
        
        result = llm_call_json(
            system_prompt="",
            user_prompt=prompt,
            fallback=None,
            max_tokens=400,
            timeout=30,
        )
        
        if result.success and result.data is not None:
            return result.data
        
        return None

class EpisodicInjector:
    """情景记忆注入器 v2.0（LLM增强）"""
    
    def __init__(self):
        self.llm = LLMEnhancedInjector()
    
    def _get_db(self):
        conn = sqlite3.connect(str(ACTIVE_MEMORY_DB))
        conn.row_factory = sqlite3.Row
        return conn
    
    def inject(self, content: str, source: str = "system",
               importance: float = 0.5, tags: list = None,
               ttl_hours: int = 72, context: str = "") -> dict:
        """
        注入一条情景记忆 v2.0
        
        LLM分析对话 → 自动生成高质量摘要+标签+重要性评分
        规则降级：使用原始的提取关键词方法
        """
        if tags is None:
            tags = []
        
        # 尝试LLM生成高质量摘要
        llm_result = self.llm.generate_summary(content)
        
        if llm_result:
            llm_summary = llm_result.get("summary", "")
            llm_tags = llm_result.get("tags", [])
            llm_importance = llm_result.get("importance", importance)
            source_type = llm_result.get("source_type", source)
            
            print(f"  [Episodic] LLM摘要: {llm_summary[:50]}... (importance={llm_importance})")
            
            # 使用LLM结果
            final_content = llm_summary or content[:300]
            final_tags = tags + [t for t in llm_tags if t not in tags]
            final_importance = max(importance, llm_importance)
        else:
            # LLM不可用，原始方法
            keywords = self._extract_keywords(content)
            final_content = content[:300]
            final_tags = tags + list(keywords[:3])
            final_importance = importance
            print(f"  [Episodic] 规则引擎: {content[:50]}... (no LLM)")
        
        # 写入数据库
        # 生成ID
        ts = time.strftime('%Y%m%d%H%M%S')
        h = hashlib.md5(content.encode()).hexdigest()[:8]
        entry_id = f"ep_{ts}_{h}"
        
        conn = self._get_db()
        c = conn.cursor()
        
        try:
            c.execute("""
                INSERT INTO memory_episodic 
                (id, timestamp, source, content, context, importance, 
                 compressed, tags, keywords, ttl_hours, source_count)
                VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?, ?, 1)
            """, (
                entry_id,
                time.strftime('%Y-%m-%dT%H:%M:%S'),
                source,
                final_content[:500],  # 只保留前500字符
                context[:200],
                final_importance,
                json.dumps(list(set(final_tags)), ensure_ascii=False),
                json.dumps(final_tags[:5], ensure_ascii=False),
                ttl_hours,
            ))
            conn.commit()
            result = {"id": entry_id, "written": True}
        except sqlite3.IntegrityError:
            result = {"id": entry_id, "written": False, "reason": "duplicate"}
        except Exception as e:
            result = {"id": entry_id, "written": False, "reason": str(e)}
        finally:
            conn.close()
        
        return result

    def inject_conversation_turn(self, user_msg: str, assistant_msg: str,
                                  task_label: str = "") -> dict:
        """
        从一轮对话注入情景记忆
        
        Hy-Memory L0 对标：将 tool call pair 卸载到 offload
        """
        content = f"{task_label + ': ' if task_label else ''}用户: {user_msg[:200]} → 助手响应"
        
        tags = ["conversation"]
        if task_label:
            tags.append(f"task:{task_label}")
        
        # 从用户消息中提取技术相关标签
        tech_pattern = r'[A-Z][a-zA-Z0-9._-]{2,}|[\u4e00-\u9fff]{4,}'
        tech_terms = re.findall(tech_pattern, user_msg)
        tags.extend(tech_terms[:3])
        
        return self.inject(
            content=content,
            source="conversation",
            importance=0.6,
            tags=tags,
            ttl_hours=48,
            context=f"user: {user_msg[:100]}"
        )

    def inject_task_boundary(self, old_task: str, new_task: str) -> dict:
        """注入任务边界切换事件"""
        return self.inject(
            content=f"任务切换: {old_task} → {new_task}",
            source="task_boundary",
            importance=0.8,
            tags=["task_switch", f"from:{old_task[:20]}", f"to:{new_task[:20]}"],
            ttl_hours=168,  # 任务切换保留一周
        )

    def inject_system_event(self, event_desc: str, importance: float = 0.7) -> dict:
        """注入系统事件（cron执行/齿轮触发等）"""
        return self.inject(
            content=event_desc,
            source="system",
            importance=importance,
            tags=["system_event"],
            ttl_hours=24,
        )

    def _extract_keywords(self, text: str) -> list:
        """提取关键词"""
        english = re.findall(r'[a-zA-Z][a-zA-Z0-9._-]{2,}', text)
        chinese = re.findall(r'[\u4e00-\u9fff]{2,6}', text)
        stop_words = {'的', '了', '在', '是', '有', '和', '就', '不', '人',
                      '都', '也', '很', '到', '说', '要', '去', '你', '我',
                      '他', '她', '会', '着', '没有', '看', '好', '自己',
                      '这', '那', '什么', '怎么', 'the', 'this', 'that',
                      'and', 'for', 'with', 'from'}
        return [w for w in chinese + english if w.lower() not in stop_words and len(w) >= 2]

    def get_stats(self) -> dict:
        """获取统计"""
        conn = self._get_db()
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM memory_episodic")
        total = c.fetchone()[0]
        c.execute("SELECT source, COUNT(*) FROM memory_episodic GROUP BY source")
        sources = {r[0]: r[1] for r in c.fetchall()}
        conn.close()
        return {"total": total, "by_source": sources}


# ====================== CLI ======================

if __name__ == "__main__":
    import sys
    
    injector = EpisodicInjector()
    
    if len(sys.argv) > 1 and sys.argv[1] == "inject":
        # python3 episodic_injector.py inject --session "..." --source "..."
        content = ""
        source = "manual"
        for i, arg in enumerate(sys.argv):
            if arg == "--session" and i + 1 < len(sys.argv):
                content = sys.argv[i + 1]
            elif arg == "--source" and i + 1 < len(sys.argv):
                source = sys.argv[i + 1]
        
        if content:
            result = injector.inject(content=content, source=source)
            print(f"✅ 注入: {result['id']}")
        else:
            print("❌ 需要 --session 参数")
    
    elif len(sys.argv) > 1 and sys.argv[1] == "bounds":
        # 从边界记录注入
        bounds_file = Path.home() / ".hermes" / "boundary_history.jsonl"
        if bounds_file.exists():
            with open(bounds_file) as f:
                lines = [json.loads(l) for l in f if l.strip()]
            new_tasks = [l for l in lines if l.get('action') == 'new_task']
            for nt in new_tasks[-3:]:
                label = nt.get('new_task_label', 'Unknown')
                result = injector.inject_task_boundary("previous", label)
                print(f"  ✅ 任务边界: {label} → {result['id']}")
        else:
            print("❌ boundary_history.jsonl 不存在")
    
    elif len(sys.argv) > 1 and sys.argv[1] == "stats":
        stats = injector.get_stats()
        print(f"情景记忆: {stats['total']} 条")
        for s, cnt in stats.get('by_source', {}).items():
            print(f"  {s}: {cnt}")
    
    else:
        # cron默认模式: 从边界记录自动注入
        import json
        bounds_file = Path.home() / ".hermes" / "boundary_history.jsonl"
        if bounds_file.exists():
            try:
                with open(bounds_file) as f:
                    lines = [json.loads(l) for l in f if l.strip()]
                new_tasks = [l for l in lines if l.get('action') == 'new_task']
                for nt in new_tasks[-3:]:
                    label = nt.get('new_task_label', 'Unknown')
                    result = injector.inject_task_boundary("previous", label)
                    print(f"  ✅ cron注入: {label} → {result['id']}")
            except Exception as e:
                print(f"  cron注入失败: {e}")
        else:
            stats = injector.get_stats()
            print(f"情景记忆统计(cron): {stats['total']} 条")
        print("---")
        print("使用参数手动调用:")
        print("  python3 scripts/episodic_injector.py inject --session '内容' --source '来源'")
        print("  python3 scripts/episodic_injector.py bounds   # 从边界记录注入")
        print("  python3 scripts/episodic_injector.py stats    # 查看统计")
