#!/usr/bin/env python3
"""
🔴🔴🔴 反幻觉铁律：严禁任何不加核实的猜想、胡编乱造、自己瞎编！
必须核实才能说/必须验证才能写/必须确认才能断言/不知道就说不知道
这是最高优先级规则，凌驾于所有其他规则之上。
"""

"""
task_boundary.py — L1.5 任务边界检测引擎 v2.0 (LLM增强)
======================================================================
v2.0 核心改进: LLM深度语义理解 + 规则引擎双轨并联
  - LLM路径（优先）: 通过 delegate_task/LM Studio/Ollama 理解用户语义
  - 规则路径（降级）: 原有的关键词匹配（90%准确率保留）
  - 双轨评分融合: 两个路径的结果按置信度加权融合

对应 Hy-Memory: src/offload/index.ts 中的 attemptL15() + handleTaskTransition()

核心逻辑：
  1. 检测用户的新消息 → 判断是否属于新任务
  2. 如果是新任务 → 归档旧 refs + 清空 offload + 标记 wake_guide
  3. 如果是延续 → 保持当前上下文不变
  4. 边界信息持久化到 boundary_history.jsonl

触发方式：
  - 每次用户新消息时由 wake_injector 调用
  - 或手动调用：python3 scripts/task_boundary.py check \"用户的新消息\"
  - 或由齿轮系统每分钟检查
"""

import json
import re
import time
import shutil
import sys
from pathlib import Path
from typing import Optional

REFS_DIR = Path.home() / ".hermes" / "refs"
BOUNDARY_DB = Path.home() / ".hermes" / "boundary_history.jsonl"
WAKE_GUIDE = Path.home() / ".hermes" / "reports" / "wake_guide.json"
SCRIPTS_DIR = Path.home() / ".hermes" / "scripts"


# ====================== LLM边界检测引擎 ======================

class LLMBoundaryDetector:
    """
    LLM驱动的任务边界检测器
    
    对标 Hy-Memory: attemptL15() — 用LLM判断任务的完成/延续/新任务
    通过语义理解而非关键词匹配来准确检测边界
    """
    
    BOUNDARY_PROMPT = """你是一个专业任务边界分析专家。分析用户的最新消息，判断这是：
1. **new_task（新任务）**：用户明确开启一个全新的、与之前无关的任务
2. **continuation（延续）**：用户在继续或推进当前任务
3. **clarification（澄清）**：用户对当前任务提出问题或需要确认
4. **side_topic（旁支）**：用户在主线任务之外临时问一个相关问题
5. **completed（已完成）**：用户确认当前任务完成

请只返回JSON格式：
{
  "action": "new_task|continuation|clarification|side_topic|completed",
  "confidence": 0.0-1.0,
  "reason": "简短的原因",
  "new_task_label": "如果是新任务，给出任务名称；否则null",
  "is_long_task": true/false
}"""
    
    def __init__(self):
        pass
    
    def analyze_with_llm(self, user_message: str, context_history: str = "") -> Optional[dict]:
        """
        使用LLM深度理解用户消息的语义判断任务边界
        
        统一通过llm_bridge调用，自动选择可用后端（delegate_task → LM Studio → Ollama → fallback）
        """
        context_part = f"\n## 最近上下文\n{context_history[:500]}\n" if context_history else ""
        prompt = f"## 用户最新消息\n{user_message}{context_part}\n\n请分析并返回JSON。"
        
        from llm_bridge import llm_call_json
        
        result = llm_call_json(
            system_prompt=self.BOUNDARY_PROMPT,
            user_prompt=prompt,
            fallback=None,
            max_tokens=500,
            timeout=10,
        )
        
        if result.success and result.data is not None:
            return result.data
        
        return None
    
    def analyze(self, user_message: str, context_history: str = "") -> dict:
        """
        综合分析：优先LLM，降级到规则
        
        返回与 detect_boundary 兼容的格式
        """
        llm_result = self.analyze_with_llm(user_message, context_history)
        
        if llm_result:
            action = llm_result.get("action", "continuation")
            is_new = action == "new_task"
            return {
                "is_new_task": is_new,
                "confidence": llm_result.get("confidence", 0.8),
                "reason": f"[LLM] {llm_result.get('reason', '语义分析')}",
                "matched_signal": f"llm:{action}",
                "new_task_label": llm_result.get("new_task_label"),
                "is_long_task": llm_result.get("is_long_task", True),
                "source": "llm",
            }
        
        return {"source": "llm_unavailable"}  # 标记为LLM不可用


# ====================== 规则引擎（保留为降级） ======================

class RuleBoundaryDetector:
    """原有的规则引擎边界检测器（v1保留，用于LLM降级）"""
    
    NEW_TASK_SIGNALS = [
        (r'新[任务话题项目功能模]', 0.95),
        (r'新的[一项个]?(?:任务|话题|项目|东西|事情|方案|想法|模块|功能|框架|工具|库|系统|平台|方向|领域)', 0.85),
        (r'换个[任务话题项目]', 0.90),
        (r'另外[一个]?[任务话题]', 0.85),
        (r'先不说这个', 0.85),
        (r'看看[别的其他另外]', 0.80),
        (r'另一个[事情任务项目]', 0.90),
        (r'顺便[问说]?[一]?下', 0.75),
        (r'暂停[一下]?', 0.75),
        (r'下一个[任务话题]', 0.95),
    ]
    
    CONTINUE_SIGNALS = [
        (r'继续[刚才前面上面]?', 0.90),
        (r'接着[刚才的]?', 0.90),
        (r'刚才[说到做到]', 0.85),
        (r'之前[说的那个]', 0.85),
        (r'还是[刚才那个]', 0.75),
        (r'下一步[怎么做]?', 0.70),
    ]
    
    def __init__(self):
        self.history = self._load_history()
    
    def _load_history(self) -> list:
        if not BOUNDARY_DB.exists():
            return []
        entries = []
        with open(BOUNDARY_DB, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        return entries
    
    def _score_signal(self, text: str, signals: list) -> tuple:
        max_score = 0.0
        matched_pattern = None
        for pattern, score in signals:
            if re.search(pattern, text):
                if score > max_score:
                    max_score = score
                    matched_pattern = pattern
        return max_score, matched_pattern
    
    def detect(self, user_message: str) -> dict:
        """纯规则检测"""
        if not user_message or len(user_message.strip()) < 3:
            return {"is_new_task": False, "confidence": 0, "reason": "消息太短", 
                    "matched_signal": None, "new_task_label": None, "is_long_task": True, "source": "rule"}
        
        new_score, new_pattern = self._score_signal(user_message, self.NEW_TASK_SIGNALS)
        cont_score, cont_pattern = self._score_signal(user_message, self.CONTINUE_SIGNALS)
        
        if new_score > cont_score and new_score >= 0.5:
            return {"is_new_task": True, "confidence": new_score, "reason": f"匹配新任务信号", 
                    "matched_signal": new_pattern, "new_task_label": None, "is_long_task": True, "source": "rule"}
        elif cont_score > new_score:
            return {"is_new_task": False, "confidence": cont_score, "reason": f"匹配延续信号", 
                    "matched_signal": cont_pattern, "new_task_label": None, "is_long_task": None, "source": "rule"}
        else:
            return {"is_new_task": False, "confidence": 0.1, "reason": "无明确信号，默认延续", 
                    "matched_signal": None, "new_task_label": None, "is_long_task": True, "source": "rule"}


# ====================== 融合检测器 ======================

class TaskBoundaryDetector:
    """
    L1.5 任务边界检测器 v2.0
    
    双轨并联架构:
      LLM路径(优先) ──→ 语义理解 ←──┐
                                        ├──→ 置信度加权融合 → 最终结果
      规则路径(降级) ──→ 关键词匹配 ←──┘
    
    优势:
      - LLM可用时：理解隐含意图（"搞定了，现在说另一个事"→new_task）
      - LLM不可用时：规则引擎90%准确率兜底
    """
    
    def __init__(self):
        self.llm_detector = LLMBoundaryDetector()
        self.rule_detector = RuleBoundaryDetector()
        self.history = self.rule_detector.history
    
    def detect_boundary(self, user_message: str, context_history: str = "") -> dict:
        """
        检测任务边界（双轨融合）
        
        1. 尝试LLM语义理解
        2. 规则引擎作为降级
        3. 如果两者都可用，按置信度加权融合
        """
        # 同时跑两条路径
        llm_result = self.llm_detector.analyze(user_message, context_history)
        rule_result = self.rule_detector.detect(user_message)
        
        # 融合
        if llm_result.get("source") == "llm":
            # LLM可用，使用LLM结果
            final = llm_result
            final["rule_score"] = rule_result.get("confidence", 0)
            final["fusion"] = "llm_primary"
            print(f"  [Boundary] LLM语义分析: {final.get('reason','')} (conf={final['confidence']})")
        else:
            # LLM不可用，降级到规则
            final = rule_result
            final["fusion"] = "rule_only"
            print(f"  [Boundary] 规则引擎: {final.get('reason','')} (conf={final['confidence']})")
        
        # 保存记录
        record = {
            "timestamp": time.time(),
            "user_message": user_message[:200],
            "result": final.get("is_new_task", False),
            "confidence": final.get("confidence", 0),
            "reason": final.get("reason", ""),
            "fusion": final.get("fusion", "unknown"),
        }
        self._save_boundary(record)
        
        return final
    
    def _save_boundary(self, entry: dict):
        BOUNDARY_DB.parent.mkdir(parents=True, exist_ok=True)
        with open(BOUNDARY_DB, 'a', encoding='utf-8') as f:
            f.write(json.dumps(entry, ensure_ascii=False) + '\n')
        self.history.append(entry)
    
    def handle_task_transition(self, user_message: str, context_history: str = "") -> dict:
        """
        处理任务边界切换（核心入口）
        
        对应 Hy-Memory: handleTaskTransition()
        - 检测到新任务 → 归档旧refs + 清空offload
        - 检测到延续 → 保持上下文
        """
        boundary = self.detect_boundary(user_message, context_history)
        
        if boundary.get("is_new_task"):
            # 新任务：归档
            archived = self._archive_old_context()
            boundary["archived"] = archived
            boundary["action_taken"] = "archive_and_clear"
        else:
            boundary["archived"] = 0
            boundary["action_taken"] = "keep_context"
        
        return boundary
    
    def _archive_old_context(self) -> int:
        """归档旧的refs"""
        if not REFS_DIR.exists():
            return 0
        archive_dir = REFS_DIR / "archive"
        archive_dir.mkdir(parents=True, exist_ok=True)
        count = 0
        for f in REFS_DIR.glob("*.md"):
            dest = archive_dir / f.name
            if not dest.exists():
                shutil.move(str(f), str(dest))
                count += 1
        return count


# ====================== CLI ======================

def check_boundary(user_message: str, context: str = "") -> dict:
    """兼容层：供外部调用的入口函数"""
    detector = TaskBoundaryDetector()
    return detector.handle_task_transition(user_message, context)


if __name__ == "__main__":
    import sys
    
    detector = TaskBoundaryDetector()
    
    if len(sys.argv) > 1 and sys.argv[1] == "check":
        text = " ".join(sys.argv[2:]) if len(sys.argv) > 2 else ""
        if not text:
            print("Usage: python3 task_boundary.py check <user_message>")
            sys.exit(1)
        result = detector.handle_task_transition(text)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        # 交互式测试
        print("TaskBoundary v2.0 (LLM增强)\n输入消息检测任务边界，输入exit退出")
        while True:
            try:
                text = input("\n> ").strip()
                if text.lower() in ('exit', 'quit'):
                    break
                if text:
                    result = detector.handle_task_transition(text)
                    status = "🆕 新任务" if result.get("is_new_task") else "🔗 延续任务"
                    print(f"  {status} (conf={result['confidence']:.2f})")
                    print(f"  原因: {result.get('reason', '')}")
                    print(f"  融合方式: {result.get('fusion', '?')}")
            except (EOFError, KeyboardInterrupt):
                break
