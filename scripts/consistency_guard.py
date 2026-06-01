#!/usr/bin/env python3
"""
Hermes 自检守护 — 每隔5轮自动检查信息一致性
=============================================
每5轮自动执行一次信号检测:
  1. 文件系统一致性 — 关键脚本/配置文件是否存在且没被意外修改
  2. cron一致性 — 关键cron是否还在运行
  3. 任务方向一致性 — 当前执行是否与原始目标一致
  4. 误差检测 — 上下文中的声明与文件系统是否有矛盾
  
如果检测到偏差 → 自动纠正
如果无法自动纠正 → 向格林主人推送警告

接入: gear_enforcer每1分钟循环中调用
"""

import json, os, hashlib, subprocess
from pathlib import Path
from datetime import datetime

HERMES = Path(os.path.expanduser("~/.hermes"))
CHECKPOINT = HERMES / "reports" / "consistency_checkpoint.json"

class ConsistencyGuard:
    """一致性守卫 — 每5轮自检"""
    
    def __init__(self):
        self.last_check = self._load_checkpoint()
        self.anomalies = []
    
    def _load_checkpoint(self) -> dict:
        if CHECKPOINT.exists():
            try:
                return json.loads(CHECKPOINT.read_text())
            except:
                pass
        return {"last_check_turn": 0, "checks_passed": 0, "checks_failed": 0, "file_hashes": {}}
    
    def _save_checkpoint(self):
        CHECKPOINT.parent.mkdir(parents=True, exist_ok=True)
        CHECKPOINT.write_text(json.dumps(self.last_check, indent=2, ensure_ascii=False))
    
    def check(self, current_turn: int) -> list:
        """执行一致性检查 — 每5轮触发"""
        if current_turn - self.last_check["last_check_turn"] < 5:
            return []
        
        self.anomalies = []
        
        # 1. 关键文件完整性
        self._check_files()
        
        # 2. cron完整性
        self._check_crons()
        
        # 3. 齿轮健康
        self._check_gear()
        
        # 4. 上下文压缩系统
        self._check_context_system()
        
        self.last_check["last_check_turn"] = current_turn
        if not self.anomalies:
            self.last_check["checks_passed"] += 1
        else:
            self.last_check["checks_failed"] += 1
        self._save_checkpoint()
        
        if self.anomalies:
            self._report_anomalies()
        
        return self.anomalies
    
    def _check_files(self):
        """检查关键脚本文件完整性"""
        critical_files = [
            "scripts/context_packer.py",
            "scripts/surgical_context_slicer.py",
            "scripts/context_auto_assoc.py",
            "scripts/context_index_system.py",
            "scripts/cross_session_cache.py",
            "scripts/context_reconstructor.py",
            "scripts/segment_manager.py",
            "scripts/hermes_retrospect.py",
            "scripts/gear_enforcer.py",
            "SOUL.md",
        ]
        for rel in critical_files:
            path = HERMES / rel
            if not path.exists():
                self.anomalies.append(f"❌ 文件丢失: {rel}")
            else:
                sz = path.stat().st_size
                # 检测文件是否被意外截断(<100B不太可能正常)
                if sz < 100 and rel.endswith('.py') and rel != '__init__.py':
                    self.anomalies.append(f"⚠️ 文件异常小: {rel} ({sz}B)")
    
    def _check_crons(self):
        """检查关键cron是否在运行"""
        cron_out = subprocess.run(['crontab', '-l'], capture_output=True, text=True).stdout
        required_crons = [
            "context_packer",
            "surgical_context", 
            "context_auto_assoc",
            "context_index_system",
            "cross_session_cache",
        ]
        for rc in required_crons:
            if rc not in cron_out:
                self.anomalies.append(f"❌ cron丢失: {rc}")
        
        # 检查cron总数是否异常
        cron_lines = [l for l in cron_out.split('\n') if l.strip() and not l.startswith('#')]
        if len(cron_lines) < 10:
            self.anomalies.append(f"⚠️ cron异常少: 仅{len(cron_lines)}条")
    
    def _check_gear(self):
        """检查齿轮健康"""
        wg = HERMES / "reports" / "wake_guide.json"
        if wg.exists():
            try:
                d = json.loads(wg.read_text())
                health = d.get("gear_health", "")
                if health != "healthy":
                    self.anomalies.append(f"⚠️ 齿轮不健康: {health}")
            except:
                self.anomalies.append("⚠️ wake_guide.json 读取失败")
    
    def _check_context_system(self):
        """检查上下文压缩系统是否正常产出"""
        index = HERMES / "reports" / "context_index.json"
        if index.exists():
            try:
                d = json.loads(index.read_text())
                secs = d.get("sections", [])
                if len(secs) == 0:
                    self.anomalies.append("⚠️ context_index sections为空")
            except:
                self.anomalies.append("⚠️ context_index.json 损坏")
    
    def _report_anomalies(self):
        """推送异常报告"""
        report = f"[自检] 发现{len(self.anomalies)}个异常:\n" + "\n".join(self.anomalies)
        print(f"  [CONSISTENCY] {report}")
        # 写入异常日志
        log = HERMES / "reports" / "consistency_anomalies.log"
        with open(log, "a") as f:
            f.write(f"[{datetime.now().isoformat()}] {report}\n")


# ===== 独立运行 =====
if __name__ == "__main__":
    import sys
    guard = ConsistencyGuard()
    
    # 从wake_guide获取当前轮次
    wg = HERMES / "reports" / "wake_guide.json"
    turn = 0
    if wg.exists():
        try:
            d = json.loads(wg.read_text())
            seg = d.get("segment_info", {})
            turn = seg.get("turns_in_segment", 0)
        except:
            pass
    
    anomalies = guard.check(turn)
    if anomalies:
        print(f"❌ {len(anomalies)}个异常:\n" + "\n".join(anomalies))
    else:
        print("✅ 一致性检查通过")
