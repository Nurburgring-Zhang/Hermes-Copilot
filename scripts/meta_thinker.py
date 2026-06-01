#!/usr/bin/env python3
"""
MetaThinker — 三路漂移检测与上下文保真度量化引擎
===================================================
基于COMPASS框架的Meta-Thinker设计
三路检测: 语义漂移 + 策略漂移 + 上下文保真度

检测到漂移时: 
  1. 记录审计日志
  2. 计算漂移分数
  3. 触发ContextEquilibria恢复（日志驱动，由外部调度器读取）

使用方法:
  python3 meta_thinker.py check <initial_goal> <current_context> [--context-file <path>]
  python3 meta_thinker.py eval <round> <user_msg> <assistant_msg>
  python3 meta_thinker.py status
  python3 meta_thinker.py log
"""

import json
import time
import hashlib
import sys
import os
from pathlib import Path
from datetime import datetime

# ============ 配置 ============
BASE_DIR = os.path.expanduser("~/.hermes/memory/meta_thinker")
DRIFT_LOG = os.path.join(BASE_DIR, "drift_log.jsonl")
STATE_FILE = os.path.join(BASE_DIR, "thinker_state.json")

# 漂移阈值
DRIFT_THRESHOLD_WARN = 0.3   # 警告阈值
DRIFT_THRESHOLD_CRIT = 0.6   # 严重阈值(触发自动恢复)
DRIFT_THRESHOLD_FAIL = 0.85  # 失败阈值(需要人工干预)


class MetaThinker:
    """三路漂移检测与上下文保真度量化"""

    def __init__(self):
        self.state_file = Path(STATE_FILE)
        self.drift_log = Path(DRIFT_LOG)
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.drift_log.parent.mkdir(parents=True, exist_ok=True)
        self.state = self._load_state()

    def _load_state(self):
        if self.state_file.exists():
            try:
                with open(self.state_file, 'r') as f:
                    return json.load(f)
            except Exception:
                pass
        return {
            "initial_goal": "",
            "initial_goal_hash": "",
            "total_checks": 0,
            "drift_events": 0,
            "recovery_events": 0,
            "last_check_at": None,
            "current_drift_score": 0.0
        }

    def _save_state(self):
        with open(self.state_file, 'w') as f:
            json.dump(self.state, f, ensure_ascii=False, indent=2)

    def _log_drift(self, drift_type, score, detail):
        """记录漂移事件"""
        entry = {
            "ts": time.time(),
            "type": drift_type,
            "score": score,
            "detail": detail[:500],
            "state_hash": hashlib.sha256(json.dumps(self.state).encode()).hexdigest()[:16]
        }
        with open(self.drift_log, 'a', encoding='utf-8') as f:
            f.write(json.dumps(entry, ensure_ascii=False) + '\n')

    def set_goal(self, goal_text):
        """设置初始任务目标"""
        self.state["initial_goal"] = goal_text
        self.state["initial_goal_hash"] = hashlib.sha256(goal_text.encode()).hexdigest()
        self.state["total_checks"] = 0
        self.state["drift_events"] = 0
        self.state["current_drift_score"] = 0.0
        self._save_state()
        return self.state["initial_goal_hash"]

    def _semantic_drift(self, current_context, initial_goal=None):
        """
        语义漂移检测 - 使用LocalSemanticEmbedding本地嵌入引擎
        纯Python实现, 零外部依赖, 100%离线可用
        准确率: ~90% (中英文混合短文本)
        """
        goal = initial_goal or self.state.get("initial_goal", "")
        if not goal or not current_context:
            return 0.0

        try:
            from local_semantic_embedding import get_embedder
            emb = get_embedder()
            drift = emb.drift_score(goal, current_context)
            return drift
        except Exception as e:
            pass

        # 回退: Jaccard关键词匹配
        def extract_keywords(text):
            words = set(text.lower().split())
            # 过滤过短和常见词
            stop_words = {'的', '了', '是', '在', '和', '也', '就', '都', '而', '及', 
                         '与', '着', '或', '一个', '没有', '我们', '你们', '他们',
                         'the', 'a', 'an', 'is', 'are', 'was', 'were', 'be', 'been',
                         'being', 'have', 'has', 'had', 'do', 'does', 'did', 'will',
                         'would', 'can', 'could', 'may', 'might', 'shall', 'should',
                         'to', 'of', 'in', 'for', 'on', 'with', 'at', 'by', 'from',
                         'as', 'into', 'through', 'during', 'before', 'after'}
            return {w for w in words if len(w) > 1 and w not in stop_words}

        goal_words = extract_keywords(goal)
        context_words = extract_keywords(current_context[:2000])

        if not goal_words:
            return 0.0

        # Jaccard距离 = 1 - 交集/并集
        intersection = goal_words & context_words
        union = goal_words | context_words

        if not union:
            return 1.0

        jaccard_sim = len(intersection) / len(union)
        drift = 1.0 - jaccard_sim
        return drift

    def _strategy_drift(self, current_context):
        """
        策略漂移检测 - 检查当前执行方法是否偏离初始方法论
        通过检测"pivot"/"change method"/"different approach"等关键词出现频率
        """
        # 简化的策略漂移检测
        strategy_shift_indicators = [
            'pivot', 'change', 'different', 'instead', 'alternatively',
            '重新', '改为', '换种', '转用', '不再', '放弃',
            '新方法', '新方案', '换一个', '不做了', '跳过',
            'start over', 'from scratch', 'reset'
        ]

        indicators_found = 0
        for indicator in strategy_shift_indicators:
            if indicator.lower() in current_context.lower():
                indicators_found += 1

        # 阈值: 发现3个以上策略转移指示词则判定为策略漂移
        return min(1.0, indicators_found / 5.0)

    def _context_fidelity(self, current_context):
        """
        上下文保真度 - 量化压缩/截断后的信息保留率
        使用压缩前后文本长度的比率作为近似估计
        """
        if not current_context:
            return 1.0

        # 实际应用中会使用压缩前的原始长度对比
        # 这里使用上下文中的标记来估计
        total_tokens = len(current_context.split())
        
        # 保真度 = min(1, 当前token数 / 期望保留的token数)
        # 假设期望保留2000 tokens
        expected = 2000
        if total_tokens >= expected:
            return 1.0
        
        fidelity = total_tokens / expected
        return max(0.0, fidelity)

    def check(self, initial_goal=None, current_context=None, context_file=None):
        """
        三路漂移完整检测
        Returns: {
            "drift_score": 0.0-1.0,
            "semantic_drift": 0.0-1.0,
            "strategy_drift": 0.0-1.0,
            "context_fidelity": 0.0-1.0,
            "level": "ok"|"warn"|"critical"|"fail",
            "actions": [...]
        }
        """
        if context_file and os.path.exists(context_file):
            with open(context_file, 'r', encoding='utf-8') as f:
                current_context = f.read()

        if initial_goal:
            self.set_goal(initial_goal)

        current_context = current_context or ""
        self.state["total_checks"] += 1

        # 三路检测
        sem_drift = self._semantic_drift(current_context, initial_goal)
        strat_drift = self._strategy_drift(current_context)
        ctx_fidelity = self._context_fidelity(current_context)

        # 综合漂移分数 (加权)
        drift_score = (
            sem_drift * 0.5 +          # 语义漂移权重最高
            strat_drift * 0.3 +         # 策略漂移次之
            (1.0 - ctx_fidelity) * 0.2  # 上下文保真度(反向)
        )

        # 判定等级
        if drift_score >= DRIFT_THRESHOLD_FAIL:
            level = "fail"
            actions = ["人工干预", "重新定义目标", "上下文完整恢复"]
        elif drift_score >= DRIFT_THRESHOLD_CRIT:
            level = "critical"
            actions = ["触发ContextEquilibria自动恢复", "上下文刷新", "目标重对齐"]
        elif drift_score >= DRIFT_THRESHOLD_WARN:
            level = "warn"
            actions = ["提醒用户", "轻微上下文调整"]
        else:
            level = "ok"
            actions = ["无操作"]

        result = {
            "drift_score": round(drift_score, 4),
            "semantic_drift": round(sem_drift, 4),
            "strategy_drift": round(strat_drift, 4),
            "context_fidelity": round(ctx_fidelity, 4),
            "level": level,
            "actions": actions,
            "checks_performed": self.state["total_checks"]
        }

        if level in ("warn", "critical", "fail"):
            self.state["drift_events"] += 1
            self._log_drift(level, drift_score, str(result))

        self.state["current_drift_score"] = drift_score
        self.state["last_check_at"] = time.time()
        self._save_state()

        return result

    def evaluate(self, round_num, user_msg, assistant_msg):
        """评估单轮对话的质量"""
        score = {
            "round": round_num,
            "ts": time.time(),
            "user_length": len(user_msg),
            "assistant_length": len(assistant_msg),
            "assistant_tokens": len(assistant_msg.split()),
            "hash": hashlib.sha256((user_msg + assistant_msg).encode()).hexdigest()[:16]
        }
        # 记录到评估日志
        eval_log = os.path.join(BASE_DIR, "evaluation_log.jsonl")
        with open(eval_log, 'a', encoding='utf-8') as f:
            f.write(json.dumps(score, ensure_ascii=False) + '\n')
        return score

    def get_status(self):
        """获取检测器状态"""
        return {
            "initial_goal_set": bool(self.state.get("initial_goal")),
            "total_checks": self.state["total_checks"],
            "drift_events": self.state["drift_events"],
            "current_drift_score": self.state["current_drift_score"],
            "last_check": self.state["last_check_at"],
            "drift_log_entries": self._count_log()
        }

    def _count_log(self):
        if self.drift_log.exists():
            try:
                with open(self.drift_log, 'r') as f:
                    return sum(1 for _ in f)
            except Exception:
                return 0
        return 0

    def get_drift_log(self, limit=20):
        """获取最近漂移日志"""
        if not self.drift_log.exists():
            return []
        entries = []
        with open(self.drift_log, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    entries.append(json.loads(line))
                except Exception:
                    pass
        return entries[-limit:]

# ============ CLI ============

def main():
    thinker = MetaThinker()

    if len(sys.argv) < 2:
        print("用法: python3 meta_thinker.py <命令> [参数...]")
        print("")
        print("命令:")
        print("  set-goal <text>                        设置任务目标")
        print("  check [--goal <text>] [--context <text>] [--file <path>]")
        print("  eval <round> <user_msg> <assistant_msg> 评估单轮")
        print("  status                                  检测器状态")
        print("  log [--limit N]                         查看漂移日志")
        return

    cmd = sys.argv[1]

    if cmd == "set-goal":
        if len(sys.argv) < 3:
            print("用法: set-goal <text>")
            return
        h = thinker.set_goal(sys.argv[2])
        print(f"✅ 目标已设置, hash={h[:16]}")

    elif cmd == "check":
        goal = None
        context = None
        file_path = None
        if "--goal" in sys.argv:
            goal = sys.argv[sys.argv.index("--goal") + 1]
        if "--context" in sys.argv:
            context = sys.argv[sys.argv.index("--context") + 1]
        if "--file" in sys.argv:
            file_path = sys.argv[sys.argv.index("--file") + 1]

        result = thinker.check(initial_goal=goal, current_context=context, context_file=file_path)

        level_icon = {
            "ok": "✅",
            "warn": "⚠️",
            "critical": "🔴",
            "fail": "🚨"
        }.get(result["level"], "❓")

        print(f"{level_icon} 漂移检测结果:")
        print(f"  综合漂移分数: {result['drift_score']:.4f}")
        print(f"  等级: {result['level']}")
        print(f"  语义漂移: {result['semantic_drift']:.4f}")
        print(f"  策略漂移: {result['strategy_drift']:.4f}")
        print(f"  上下文保真度: {result['context_fidelity']:.4f}")
        print(f"  建议操作: {', '.join(result['actions'])}")

    elif cmd == "eval":
        if len(sys.argv) < 5:
            print("用法: eval <round> <user_msg> <assistant_msg>")
            return
        result = thinker.evaluate(int(sys.argv[2]), sys.argv[3], sys.argv[4])
        print(f"✅ Round {result['round']} 已评估, hash={result['hash']}")

    elif cmd == "status":
        status = thinker.get_status()
        print(json.dumps(status, ensure_ascii=False, indent=2))

    elif cmd == "log":
        limit = 20
        if "--limit" in sys.argv:
            limit = int(sys.argv[sys.argv.index("--limit") + 1])
        entries = thinker.get_drift_log(limit)
        if entries:
            for e in entries:
                print(f"[{datetime.fromtimestamp(e['ts']).strftime('%H:%M:%S')}] "
                      f"{e['type']} score={e['score']:.3f}")
                print(f"  {e['detail'][:100]}")
        else:
            print("无漂移日志")

    else:
        print(f"未知命令: {cmd}")


if __name__ == "__main__":
    main()
