#!/usr/bin/env python3
"""
Hermes 监控层引擎 (Monitor Engine)
=====================================
源自: 三层认知架构 — 执行层/监控层/反思层
功能: 持续监控执行状态，检测异常，发出控制信号
接入: hermes_retrospect.py / hermes_self_evolve_cluster.py / gear_enforcer.py

信号系统:
  CONTINUE    — 正常进行
  CHECKPOINT  — 保存中间状态后继续
  REFLECT     — 触发反思（异常积累到阈值）
  RECOVER     — 检测到中断/退化，需要恢复
  ABORT       — 严重异常，终止当前任务

用法:
  from agent.monitor import MonitorEngine
  m = MonitorEngine()
  signal = m.evaluate({"turns": 5, "max_turns": 100, "errors": [], "task_type": "fix"})

部署:
  集成到齿轮G1每1分钟循环中自动调用
"""

import json, os, time, sqlite3, datetime
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from enum import Enum

HERMES_HOME = Path(os.path.expanduser("~/.hermes"))

class MonitorSignal(str, Enum):
    CONTINUE = "CONTINUE"
    CHECKPOINT = "CHECKPOINT"
    REFLECT = "REFLECT"
    RECOVER = "RECOVER"
    ABORT = "ABORT"

class MonitorEngine:
    """
    监控层核心引擎
    
    监控维度:
    1. 进度监控 — 当前步数 vs 预算步数
    2. 错误率监控 — 连续失败/错误率上升
    3. 时间预算监控 — 执行时长超限预警
    4. 退化检测 — 性能和之前轮次对比下降
    5. 循环检测 — 同一模式反复执行无进展
    """
    
    def __init__(self, config_path: Optional[Path] = None):
        self.config = self._load_config(config_path)
        self.history = []  # 本轮监控历史
        self.anomaly_count = 0
        
    def _load_config(self, config_path: Optional[Path]) -> dict:
        """加载监控配置"""
        default = {
            "checkpoint_interval": 5,      # 每5步保存检查点
            "max_errors_per_phase": 3,      # 每阶段最大错误数
            "error_rate_threshold": 0.3,    # 错误率超过30%触发反思
            "max_stall_steps": 5,           # 连续5步无进展触发恢复
            "time_budget_warning_min": 120, # 2小时预警
            "degradation_threshold": 0.2,   # 性能下降20%触发检测
            "history_window": 20,           # 保留最近20步历史
        }
        if config_path and config_path.exists():
            try:
                with open(config_path) as f:
                    custom = json.load(f)
                default.update(custom)
            except:
                pass
        return default
    
    def evaluate(self, state: Dict[str, Any]) -> Tuple[MonitorSignal, Dict[str, Any]]:
        """
        评估当前执行状态，返回控制信号+详情
        
        输入state应包含:
          turns: int — 当前已执行步数
          max_turns: int — 最大允许步数
          errors: List[str] — 本轮错误列表
          task_type: str — 任务类型(fix/push/research/develop/...)
          elapsed_min: float — 已执行分钟数
          last_signals: List[str] — 前几轮的信号历史(可选)
        """
        turns = state.get("turns", 0)
        max_turns = state.get("max_turns", 100)
        errors = state.get("errors", [])
        task_type = state.get("task_type", "general")
        elapsed = state.get("elapsed_min", 0)
        last_signals = state.get("last_signals", [])
        
        detail = {"turns": turns, "errors": len(errors), "elapsed_min": elapsed}
        signal = MonitorSignal.CONTINUE
        
        # --- 检查点触发 ---
        if turns > 0 and turns % self.config["checkpoint_interval"] == 0:
            signal = MonitorSignal.CHECKPOINT
            detail["reason"] = f"达到检查点间隔({self.config['checkpoint_interval']}步)"
        
        # --- 错误率检测 ---
        if len(errors) > 0 and turns > 0:
            error_rate = len(errors) / max(turns, 1)
            if error_rate >= self.config["error_rate_threshold"]:
                signal = MonitorSignal.REFLECT
                detail["reason"] = f"错误率{error_rate:.0%}超过阈值{self.config['error_rate_threshold']:.0%}"
                detail["error_rate"] = error_rate
                self.anomaly_count += 1
            
            if len(errors) >= self.config["max_errors_per_phase"]:
                if signal != MonitorSignal.REFLECT:
                    signal = MonitorSignal.REFLECT
                    detail["reason"] = f"错误数{len(errors)}达到阈值{self.config['max_errors_per_phase']}"
                detail["error_count"] = len(errors)
        
        # --- 无进展循环检测 ---
        if len(last_signals) >= self.config["max_stall_steps"]:
            last_n = last_signals[-self.config["max_stall_steps"]:]
            if all(s == "CONTINUE" for s in last_n):
                # 全部是CONTINUE但不是停滞的信号——需要检查是否真的在推进
                # 目前简单处理：如果错误数不变且步数没超过max的20%，认为是正常
                progress_ratio = turns / max(max_turns, 1)
                if progress_ratio < 0.2 and turns >= self.config["max_stall_steps"]:
                    signal = MonitorSignal.RECOVER
                    detail["reason"] = f"连续{self.config['max_stall_steps']}步无显著进展"
        
        # --- 时间预算预警 ---
        if elapsed >= self.config["time_budget_warning_min"]:
            detail["time_warning"] = True
            if signal == MonitorSignal.CONTINUE:
                signal = MonitorSignal.CHECKPOINT
                detail["reason"] = f"执行时间{elapsed:.0f}分钟超过预警{self.config['time_budget_warning_min']}分钟"
        
        # --- 严重异常终止 ---
        if self.anomaly_count >= 5:
            signal = MonitorSignal.ABORT
            detail["reason"] = f"连续{self.anomaly_count}次异常，终止任务"
        
        # 记录历史
        self.history.append({
            "turns": turns,
            "signal": signal.value,
            "errors": len(errors),
            "elapsed_min": elapsed,
            "ts": datetime.datetime.now().isoformat()
        })
        if len(self.history) > self.config["history_window"]:
            self.history = self.history[-self.config["history_window"]:]
        
        detail["anomaly_count"] = self.anomaly_count
        detail["signal"] = signal.value
        
        return signal, detail
    
    def get_history(self) -> List[Dict]:
        """获取监控历史"""
        return self.history
    
    def health_check(self) -> Dict[str, Any]:
        """自检"""
        return {
            "engine": "MonitorEngine",
            "status": "healthy",
            "config": self.config,
            "history_len": len(self.history),
            "anomaly_count": self.anomaly_count,
            "last_signal": self.history[-1]["signal"] if self.history else "NONE",
        }

# ===== 独立运行入口 =====
if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "test"
    
    engine = MonitorEngine()
    
    if cmd == "test":
        # 模拟测试
        test_cases = [
            {"turns": 3, "max_turns": 100, "errors": [], "task_type": "fix", "elapsed_min": 5},
            {"turns": 5, "max_turns": 100, "errors": [], "task_type": "fix", "elapsed_min": 10},
            {"turns": 6, "max_turns": 100, "errors": ["err1","err2","err3"], "task_type": "fix", "elapsed_min": 15},
            {"turns": 15, "max_turns": 100, "errors": ["err1","err2","err3","err4"], "task_type": "fix", "elapsed_min": 120},
        ]
        for i, tc in enumerate(test_cases):
            sig, det = engine.evaluate(tc)
            print(f"  Case{i+1}: signal={sig.value} | {det.get('reason','')}")
        print(f"  Health: {json.dumps(engine.health_check(), indent=2, ensure_ascii=False)}")
    
    elif cmd == "health":
        print(json.dumps(engine.health_check(), indent=2, ensure_ascii=False))
