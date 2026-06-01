#!/usr/bin/env python3
"""
Hermes 无限对话策略 — 轮次段式上下文管理
==========================================
目标: 支持 1000+ 轮对话不超限

核心原理:
  不追求"每轮都小"，而是"每N轮重建上下文"
  把对话拆成"段(segment)", 每段~50轮
  段内正常累积，段结束时归档，下段重建

工作流:
  1. 当前段第1轮: 注入核心身份+任务上下文(约2K tokens)
  2. 段内2-50轮: 正常累积(每轮约200-500t, 50轮约25Kt)  
  3. 段结束(第50轮): 生成段摘要 → 写入文件 → 输出交接笔记
  4. 下段第1轮: 读交接笔记恢复上下文(约3K tokens)
  5. 循环: 每段~50轮, 每段一个独立上下文窗口

理论上限:
  每段50轮 × 每段用25K tokens = 50×25K=1.25M tokens的等效处理能力
  1000轮 = 20段 × 每段重建3K tokens上下文 = 60K tokens总消耗
"""

import json, os, time, hashlib
from pathlib import Path
from datetime import datetime

HERMES = Path(os.path.expanduser("~/.hermes"))

class SegmentManager:
    """
    段管理器 — 负责段的创建、维护、切换
    """
    
    def __init__(self):
        self.state_file = HERMES / "reports" / "segment_state.json"
        self.handoff_dir = HERMES / "reports" / "handoff_notes"
        self.handoff_dir.mkdir(parents=True, exist_ok=True)
        self.state = self._load_state()
    
    def _load_state(self) -> dict:
        if self.state_file.exists():
            try:
                with open(self.state_file) as f:
                    return json.load(f)
            except:
                pass
        return {
            "segment_id": 0,
            "turn_in_segment": 0,
            "max_turns_per_segment": 50,
            "total_turns_all": 0,
            "created_at": datetime.now().isoformat(),
            "tasks_completed_in_segment": [],
            "key_decisions": [],
            "step_log": [],  # 步骤日志 - 用于段内压缩
            "last_compress_turn": 0,  # 上次压缩的轮次
        }
    
    def _save_state(self):
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.state_file, "w") as f:
            json.dump(self.state, f, indent=2, ensure_ascii=False)
    
    def current_segment(self) -> int:
        return self.state["segment_id"]
    
    def turn_in_segment(self) -> int:
        return self.state["turn_in_segment"]
    
    def advance_turn(self, action_summary: str = "", decision: str = ""):
        """推进一轮"""
        self.state["turn_in_segment"] += 1
        self.state["total_turns_all"] += 1
        
        # 记录步骤日志
        entry = {
            "turn": self.state["turn_in_segment"],
            "action_summary": action_summary[:200],
            "decision": decision[:200],
            "timestamp": datetime.now().isoformat(),
        }
        self.state.setdefault("step_log", []).append(entry)
        
        if action_summary:
            self.state["tasks_completed_in_segment"].append({
                "turn": self.state["turn_in_segment"],
                "summary": action_summary[:200],
                "ts": datetime.now().isoformat(),
            })
        if decision:
            self.state["key_decisions"].append({
                "turn": self.state["turn_in_segment"],
                "decision": decision[:200],
                "ts": datetime.now().isoformat(),
            })
        self._save_state()
        
        # 段内中间压缩: 每25轮触发一次段内精简
        if self.state["turn_in_segment"] > 0 and self.state["turn_in_segment"] % 25 == 0:
            self._compact_within_segment()
        
        # 检查是否需要切换段
        if self.state["turn_in_segment"] >= self.state["max_turns_per_segment"]:
            return self._rotate_segment()
        return None
    
    def _compact_within_segment(self):
        """段内精简: 压缩step_log到只保留最近5条+关键节点摘要, 不影响交接笔记"""
        step_log = self.state.get("step_log", [])
        if not step_log:
            return
        
        turn = self.state["turn_in_segment"]
        last_compress = self.state.get("last_compress_turn", 0)
        if turn == last_compress:
            return  # 已压缩过
        
        # 保留最近5条
        recent = step_log[-5:]
        
        # 提取关键节点摘要(之前的关键决策/里程碑)
        key_nodes = []
        for entry in step_log[:-5]:  # 除了最近的
            if entry.get("decision"):
                key_nodes.append({
                    "turn": entry["turn"],
                    "summary": f"关键决策: {entry['decision'][:100]}",
                    "type": "key_decision"
                })
        
        # 生成摘要
        summary = {
            "compressed_at_turn": turn,
            "total_entries_before": len(step_log),
            "key_nodes_summary": key_nodes,
            "compressed_range": f"1-{turn - len(recent)}",
        }
        
        # 重新构建step_log = 摘要节点 + 最近5条
        compressed = []
        if summary["key_nodes_summary"] or summary["total_entries_before"] > len(recent):
            compressed.append({
                "turn": 0,
                "type": "compression_summary",
                "summary": summary,
            })
        compressed.extend(recent)
        
        self.state["step_log"] = compressed
        self.state["last_compress_turn"] = turn
        self._save_state()
        
        log_msg = f"  [段内压缩] 第{turn}轮: step_log从{summary['total_entries_before']}条压缩到{len(compressed)}条, key_nodes: {len(key_nodes)}个"
        print(log_msg)
    
    def _rotate_segment(self) -> str:
        """切换段 — 生成交接笔记 + 保存检查点 + 同步到cross_session_cache"""
        old_segment = self.state["segment_id"]
        new_segment = old_segment + 1
        
        # 生成交接笔记
        handoff = self._generate_handoff(old_segment)
        
        # 保存到cross_session_cache
        try:
            import json
            csc_path = HERMES / "reports" / "cross_session_cache.json"
            if csc_path.exists():
                csc = json.loads(csc_path.read_text())
            else:
                csc = {}
            csc["last_segment_handoff"] = handoff
            csc["last_segment_id"] = old_segment
            csc["new_segment_id"] = new_segment
            csc["handoff_time"] = datetime.now().isoformat()
            csc["total_segments"] = new_segment
            csc_path.parent.mkdir(parents=True, exist_ok=True)
            csc_path.write_text(json.dumps(csc, ensure_ascii=False, indent=2))
        except Exception as e:
            print(f"[segment_manager] cross_session_cache保存失败: {e}")
        
        # 保存到checkpoint_recorder
        try:
            cp_path = HERMES / "scripts" / "checkpoint_recorder.py"
            if cp_path.exists():
                import subprocess
                subprocess.run(
                    [sys.executable, str(cp_path), "save", 
                     f"segment_{old_segment}", 
                     f"段{old_segment}完成, 共{len(self.state['tasks_completed_in_segment'])}项任务"],
                    capture_output=True, text=True, timeout=15
                )
        except Exception as e:
            print(f"[segment_manager] checkpoint_recorder保存失败: {e}")
        
        # 重置段状态
        self.state["segment_id"] = new_segment
        self.state["turn_in_segment"] = 0
        self.state["tasks_completed_in_segment"] = []
        self.state["key_decisions"] = []
        self._save_state()
        
        return handoff
    
    def _generate_handoff(self, segment_id: int) -> str:
        """生成段交接笔记 + 轨迹JSONL归档"""
        tasks = self.state["tasks_completed_in_segment"]
        decisions = self.state["key_decisions"]
        step_log = self.state.get("step_log", [])
        
        handoff = f"""# Hermes 段{segment_id}交接笔记 (轮次{self.state['total_turns_all'] - len(tasks) + 1}-{self.state['total_turns_all']})

## 完成的任务 ({len(tasks)}项)
"""
        for t in tasks[-10:]:  # 只保留最近10项
            handoff += f"- 第{t['turn']}轮: {t['summary']}\n"
        
        handoff += f"\n## 关键决策 ({len(decisions)}项)\n"
        for d in decisions[-5:]:
            handoff += f"- 第{d['turn']}轮: {d['decision']}\n"
        
        handoff += f"\n## 当前未完成任务\n"
        handoff += f"(从wake_guide.json读取)\n"
        
        handoff += f"\n## 段{segment_id + 1}起始上下文\n"
        handoff += f"- 核心身份不变\n"
        handoff += f"- 8条永久规则不变\n"
        handoff += f"- 任务上下文从上表恢复\n"
        
        # 写入MD交接笔记
        fname = f"handoff_s{segment_id}_to_s{segment_id+1}_{int(time.time())}.md"
        fpath = self.handoff_dir / fname
        with open(fpath, "w") as f:
            f.write(handoff)
        
        # 写入完整轨迹JSONL
        trajectory = []
        for entry in step_log:
            trajectory.append({
                "turn": entry.get("turn", 0),
                "action_summary": entry.get("action_summary", ""),
                "decision": entry.get("decision", ""),
                "timestamp": entry.get("timestamp", ""),
            })
        # 如果step_log已被压缩,补充tasks和decisions中的完整信息
        used_turns = {e.get("turn") for e in trajectory if e.get("turn")}
        for t in tasks:
            if t["turn"] not in used_turns:
                trajectory.append({
                    "turn": t["turn"],
                    "action_summary": t.get("summary", ""),
                    "decision": "",
                    "timestamp": t.get("ts", ""),
                })
        for d in decisions:
            if d["turn"] not in used_turns:
                # 检查是否已存在
                exists = any(e.get("turn") == d["turn"] and e.get("decision") == d["decision"] for e in trajectory)
                if not exists:
                    trajectory.append({
                        "turn": d["turn"],
                        "action_summary": "",
                        "decision": d.get("decision", ""),
                        "timestamp": d.get("ts", ""),
                    })
        
        # 按turn排序
        trajectory.sort(key=lambda x: x["turn"])
        
        jsonl_fname = f"trajectory_s{segment_id}_{int(time.time())}.jsonl"
        jsonl_path = self.handoff_dir / jsonl_fname
        with open(jsonl_path, "w", encoding="utf-8") as f:
            for entry in trajectory:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        
        return handoff
    
    def get_handoff_for_new_segment(self) -> str:
        """获取上一段的交接笔记(新段第1轮读取)"""
        handoff_files = sorted(self.handoff_dir.glob("handoff_*.md"))
        if not handoff_files:
            return ""
        return handoff_files[-1].read_text()
    
    def get_stats(self) -> dict:
        return {
            "current_segment": self.state["segment_id"],
            "turns_in_segment": self.state["turn_in_segment"],
            "max_turns_per_segment": self.state["max_turns_per_segment"],
            "total_turns_all": self.state["total_turns_all"],
            "tasks_in_segment": len(self.state["tasks_completed_in_segment"]),
            "decisions_in_segment": len(self.state["key_decisions"]),
        }


# ===== 独立运行 =====
if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "stats"
    
    sm = SegmentManager()
    
    if cmd == "stats":
        print(json.dumps(sm.get_stats(), indent=2, ensure_ascii=False))
    elif cmd == "test":
        print("=== 模拟50轮对话段切换 ===")
        for i in range(52):
            action = f"执行第{i+1}步: {'修复' if i%2==0 else '优化'}操作"
            sm.advance_turn(action, f"决定采用方案{'A' if i%3==0 else 'B'}")
            if (i+1) % 10 == 0:
                s = sm.get_stats()
                print(f"  第{i+1}轮: seg={s['current_segment']}, seg_turn={s['turns_in_segment']}, total={s['total_turns_all']}")
        
        print(f"\n最终统计: {json.dumps(sm.get_stats(), indent=2, ensure_ascii=False)}")
        print(f"\n交接笔记预览(前300字):")
        handoff = sm.get_handoff_for_new_segment()
        print(handoff[:300])
    elif cmd == "reset":
        sm.state = {
            "segment_id": 0, "turn_in_segment": 0, "max_turns_per_segment": 50,
            "total_turns_all": 0, "created_at": datetime.now().isoformat(),
            "tasks_completed_in_segment": [], "key_decisions": [],
        }
        sm._save_state()
        print("✅ 段状态已重置")
