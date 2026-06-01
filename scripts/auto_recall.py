#!/usr/bin/env python3
"""
🔴🔴🔴 反幻觉铁律：严禁任何不加核实的猜想、胡编乱造、自己瞎编！
必须核实才能说/必须验证才能写/必须确认才能断言/不知道就说不知道
这是最高优先级规则，凌驾于所有其他规则之上。
"""

"""
auto_recall.py — Hy-Memory 跨 Session 自动召回注入引擎 v2.0 (LLM增强)
======================================================================
v2.0 核心改进：
  1. FTS5+structmem+mp 三路关键字检索（保留v1基础）
  2. ✅ LLM深度筛选：对召回结果做语义相关性排序（不是所有匹配的都注入）
  3. ✅ LLM摘要重写：把原始fact重写成当前上下文相关的高质量摘要
  4. ✅ 规则降级：LLM不可用时保留原RRF融合逻辑

每轮对话开始前自动执行：
  1. 三路检索 + RRF融合（同v1）
  2. LLM筛选：判断每条结果对当前对话的语义相关性
  3. LLM重写：用当前问题上下文重写召回内容的摘要
  4. 注入到 prompt（自动添加到 wake_guide）
"""

import sqlite3
import json
import time
import re
import sys
from pathlib import Path
from typing import Optional

ACTIVE_MEMORY_DB = Path.home() / ".hermes" / "active_memory.db"


class LLMRecallFilter:
    """
    LLM驱动的召回结果筛选与重写引擎
    
    职责：
      1. 判断召回结果对当前用户问题的语义相关性（不仅仅是关键词匹配）
      2. 把原始fact重写为当前上下文相关的摘要
    """
    
    FILTER_PROMPT = """你是一个记忆召回质量评审专家。分析以下信息：

用户当前问题：[USER_QUERY]
召回的历史记忆：[RECALLED_MEMORY]

请判断这条记忆是否对回答用户问题有实际帮助。不仅要看关键词匹配，还要看语义相关性。

评分标准：
- score: 0.0(完全无关) 到 1.0(高度相关)
  - 0.0-0.3: 只有表面关键词匹配，语义完全不相关 → 应该丢弃
  - 0.3-0.6: 部分相关，可以作为背景参考 → 建议保留
  - 0.6-0.8: 明显相关，对推理有帮助 → 应该保留
  - 0.8-1.0: 高度相关，直接辅助回答 → 必须保留

- rewritten: 如果相关(>=0.3)，用当前问题的上下文重写这条记忆的摘要（50字以内）
            如果不相关(<0.3)，设为null

返回JSON:
{
  "score": 0.0-1.0,
  "keep": true/false,
  "rewritten": "重写的摘要" 或 null,
  "reason": "简短判断理由"
}"""
    
    def filter_with_llm(self, user_query: str, recalled_memory: str) -> Optional[dict]:
        """用LLM评估单条召回质量"""
        prompt = self.FILTER_PROMPT.replace("[USER_QUERY]", user_query[:300]) \
                                   .replace("[RECALLED_MEMORY]", recalled_memory[:500])
        
        
        from llm_bridge import llm_call_json
        
        result = llm_call_json(
            system_prompt=self.FILTER_PROMPT,
            user_prompt=(
                f"用户当前问题: {user_query[:300]}\n"
                f"召回的历史记忆: {recalled_memory[:500]}\n\n"
                f"请分析返回JSON。"
            ),
            fallback=None,
            max_tokens=300,
            timeout=10,
        )
        
        if result.success and result.data is not None:
            return result.data
        
        return None


class AutoRecall:
    """
    跨 session 自动召回注入器 v2.0 (LLM增强)
    
    三路检索 → RRF融合 → LLM筛选 → 语义重写 → 注入
    """
    
    def __init__(self, db_path: str = str(ACTIVE_MEMORY_DB)):
        self.db_path = db_path
        self.llm_filter = LLMRecallFilter()
    
    def _get_db(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn
    
    def _extract_keywords(self, text: str) -> list[str]:
        """从用户输入中提取关键词（同v1）"""
        chinese_stop = {'的', '了', '在', '是', '有', '和', '就', '不', '人', '都',
                        '也', '很', '到', '说', '要', '去', '你', '我', '他', '她',
                        '会', '着', '没有', '看', '好', '自己', '这', '那', '什么',
                        '怎么', '为', '与', '及', '但', '而', '或', '被', '把',
                        '从', '对', '用', '以', '能', '可', '让', '将', '向', '比',
                        '还', '又', '才', '只', '再', '就', '都', '吗', '吧', '呢',
                        '啊', '哦', '嗯', '哈', '呀', '给', '做', '来', '上', '下',
                        '中', '大', '小', '多', '少', '个', '些', '点', '些', '因',
                        '如', '果', '虽', '然', '但', '是', '因', '为', '所', '以',
                        '如', '果', '虽', '然', '但', '是', '一', '两', '样', '想',
                        '把', '被', '让', '叫', '使', '用', '靠', '通', '过',
                        '帮', '能', '够', '可', '以', '应', '该', '需', '要', '必',
                        '须', '得', '可能', '也许', '大概', '大约', '左右',
                        '配置', '系统', '检查', '查看'}
        
        chinese_all = re.findall(r'[\u4e00-\u9fff]+', text)
        chinese_keywords = []
        for phrase in chinese_all:
            if phrase in chinese_stop:
                continue
            if len(phrase) >= 4:
                for i in range(len(phrase) - 1):
                    sub = phrase[i:i+2]
                    if sub not in chinese_stop and sub not in ('配置', '系统', '检查', '查看'):
                        chinese_keywords.append(sub)
                for i in range(len(phrase) - 2):
                    sub = phrase[i:i+3]
                    if sub not in chinese_stop:
                        chinese_keywords.append(sub)
                if len(phrase) <= 6:
                    chinese_keywords.append(phrase)
            else:
                chinese_keywords.append(phrase)
        
        english_words = re.findall(r'[a-zA-Z]{2,}', text.lower())
        english_stop = {'the', 'this', 'that', 'and', 'for', 'with', 'from',
                        'what', 'how', 'why', 'when', 'where', 'which', 'who',
                        'check', 'look', 'show', 'get', 'set', 'run', 'do', 'my'}
        english_words = [w for w in english_words if w not in english_stop]
        
        all_keywords = list(set(chinese_keywords + english_words))
        return all_keywords if all_keywords else ['']
    
    def _search_semantic_fts(self, keywords: list[str], top_k: int = 20) -> list[dict]:
        """FTS5全文搜索（同v1）"""
        if not keywords:
            return []
        conn = self._get_db()
        c = conn.cursor()
        results = []
        try:
            fts_query = ' OR '.join(f'"{kw}"' for kw in keywords)
            c.execute("""
                SELECT s.id, s.fact, s.cat, s.confidence, s.src_count, s.keywords
                FROM memory_semantic_fts f
                JOIN memory_semantic s ON f.rowid = s.rowid
                WHERE memory_semantic_fts MATCH ?
                ORDER BY rank
                LIMIT ?
            """, (fts_query, top_k))
            for r in c.fetchall():
                results.append({"id": r[0], "fact": r[1], "cat": r[2], "confidence": r[3],
                               "src_count": r[4], "keywords": r[5], "score": 1.0, "source": "semantic"})
            if results:
                conn.close()
                return results
        except Exception:
            pass
        for kw in keywords:
            try:
                c.execute("""
                    SELECT id, fact, cat, confidence, src_count, keywords
                    FROM memory_semantic WHERE (fact LIKE ? OR keywords LIKE ?) AND active = 1
                    ORDER BY confidence DESC LIMIT ?
                """, (f'%{kw}%', f'%{kw}%', top_k // len(keywords) + 1))
                for r in c.fetchall():
                    results.append({"id": r[0], "fact": r[1], "cat": r[2], "confidence": r[3],
                                   "src_count": r[4], "keywords": r[5], "score": 0.7, "source": "semantic"})
            except Exception:
                continue
        conn.close()
        return results
    
    def _search_structmem(self, keywords: list[str], top_k: int = 10) -> list[dict]:
        """搜索 structmem_events（同v1）"""
        if not keywords:
            return []
        conn = self._get_db()
        c = conn.cursor()
        results = []
        try:
            for kw in keywords:
                c.execute("""
                    SELECT id, session_id, facts, relations, mem_quality, source_preview
                    FROM structmem_events WHERE facts LIKE ? AND mem_quality >= 1.0
                    ORDER BY id DESC LIMIT ?
                """, (f'%{kw}%', top_k // len(keywords) + 1))
                for r in c.fetchall():
                    results.append({"id": r[0], "session_id": r[1], "facts": r[2], "relations": r[3],
                                   "mem_quality": r[4], "source_preview": r[5], "score": 0.8, "source": "structmem"})
        except Exception:
            pass
        finally:
            conn.close()
        return results
    
    def _search_mp_fts(self, keywords: list[str], top_k: int = 10) -> list[dict]:
        """搜索 memory palace FTS5（同v1）"""
        if not keywords:
            return []
        conn = self._get_db()
        c = conn.cursor()
        fts_query = ' OR '.join(f'"{kw}"' for kw in keywords)
        try:
            c.execute("""
                SELECT content FROM mp_fts WHERE mp_fts MATCH ? ORDER BY rank LIMIT ?
            """, (fts_query, top_k))
            return [{"fact": r[0], "score": 0.9, "source": "mp_fts"} for r in c.fetchall()]
        except Exception:
            return []
        finally:
            conn.close()
    
    def _rrf_merge(self, results: list[list[dict]], k: int = 60) -> list[dict]:
        """RRF融合排序（同v1）"""
        scores = {}
        dedup = {}
        for result_list in results:
            for rank, entry in enumerate(result_list):
                key = entry.get("fact", entry.get("source_preview", ""))
                if not key:
                    continue
                if key not in dedup:
                    dedup[key] = entry
                    scores[key] = 0
                scores[key] += 1.0 / (rank + k)
        sorted_keys = sorted(scores, key=scores.get, reverse=True)
        ranked = []
        for key in sorted_keys:
            entry = dedup[key]
            entry["rrf_score"] = scores[key]
            ranked.append(entry)
        return ranked
    
    def _build_summary_line(self, entry: dict) -> str:
        """从一条记忆条目构建单行摘要（同v1）"""
        fact = entry.get("fact", entry.get("source_preview", entry.get("facts", "")))
        cat = entry.get("cat", entry.get("source", "memory"))
        if cat == "preference":
            return f"  {fact[:200]}"
        elif cat == "knowledge":
            return f"  {fact[:200]}"
        elif cat == "environment":
            return f"  {fact[:200]}"
        elif cat == "system_config":
            return f"  {fact[:200]}"
        else:
            return f"  {fact[:200]}"
    
    def recall_for_session(self, user_input: str, max_results: int = 5) -> str:
        """
        为当前 session 做自动召回注入 v2.0
        
        改进: LLM语义筛选 + 摘要重写
        """
        keywords = self._extract_keywords(user_input)
        if not keywords:
            return ""
        
        # 三路并行检索
        semantic_results = self._search_semantic_fts(keywords)
        structmem_results = self._search_structmem(keywords)
        mp_results = self._search_mp_fts(keywords)
        
        if not any([semantic_results, structmem_results, mp_results]):
            return ""
        
        # RRF融合
        merged = self._rrf_merge([semantic_results[:10], structmem_results[:5], mp_results[:5]])
        top_results = merged[:max_results * 2]  # 先取更多给LLM筛选
        
        if not top_results:
            return ""
        
        # LLM语义筛选
        llm_enriched = []
        for entry in top_results:
            fact = entry.get("fact", entry.get("facts", entry.get("source_preview", "")))
            if not fact:
                continue
            
            # 尝试LLM评估
            llm_judgment = self.llm_filter.filter_with_llm(user_input, fact)
            
            if llm_judgment:
                score = llm_judgment.get("score", 0.5)
                keep = llm_judgment.get("keep", True)
                rewritten = llm_judgment.get("rewritten")
                
                if keep and score >= 0.3:
                    entry["llm_score"] = score
                    entry["llm_rewritten"] = rewritten or fact[:200]
                    entry["llm_reason"] = llm_judgment.get("reason", "")
                    llm_enriched.append(entry)
            else:
                # LLM不可用，保留原结果（降级）
                entry["llm_score"] = 0.5
                llm_enriched.append(entry)
        
        # 按LLM分数排序取top
        llm_enriched.sort(key=lambda e: e.get("llm_score", 0), reverse=True)
        final_results = llm_enriched[:max_results]
        
        # 构建注入文本
        lines = []
        for entry in final_results:
            cat = entry.get("cat", entry.get("source", "memory"))
            if entry.get("llm_rewritten"):
                lines.append(f"  {entry['llm_rewritten']}")
            else:
                lines.append(self._build_summary_line(entry))
        
        return "\n".join(lines) if lines else ""
    
    def get_persona_context(self) -> str:
        """从 memory_semantic 提取用户画像（同v1）"""
        conn = self._get_db()
        c = conn.cursor()
        c.execute("SELECT fact FROM memory_semantic WHERE cat = 'preference' AND active = 1 ORDER BY confidence DESC LIMIT 15")
        preferences = [r[0] for r in c.fetchall()]
        c.execute("SELECT fact FROM memory_semantic WHERE cat = 'knowledge' AND active = 1 ORDER BY confidence DESC LIMIT 10")
        knowledge = [r[0] for r in c.fetchall()]
        parts = []
        if preferences:
            parts.append("## 用户偏好\n" + "\n".join(f"- {p}" for p in preferences))
        if knowledge:
            parts.append("## 系统知识\n" + "\n".join(f"- {k}" for k in knowledge))
        conn.close()
        return "\n\n".join(parts)


if __name__ == "__main__":
    recaller = AutoRecall()
    if len(sys.argv) > 1:
        if sys.argv[1] == "recall" and len(sys.argv) > 2:
            text = " ".join(sys.argv[2:])
            result = recaller.recall_for_session(text)
            print(result if result else "No relevant memories found")
        elif sys.argv[1] == "persona":
            print(recaller.get_persona_context())
        else:
            print("Usage: python3 auto_recall.py [recall|persona] ...")
    else:
        print(recaller.get_persona_context())
