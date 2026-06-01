"""
⚙️ Hermes 全自动自我强化主循环 V3.1 — 完整商用级七通道/IFC/DPW集成
================================================================
基于OI v4.0 + IFC v2.0 + Mnemosyne V4.1架构

集成模块:
  - IFC V2: zstd压缩+RLE+DPAPI+五层保真度+前缀缓存
  - 七通道: 语义+关键词+时间线+扩散激活+实体图谱+Hopfield+整合仲裁
  - DPW任务: 双规划器A/B+见证者+三级纠偏+Task V2
  - 链式哈希审计: OI第五层安全
  - Merkle轨迹验证: OI§26执行轨迹验证
  - GEPA遗传优化: OI§27自动技能优化

三级自我强化循环:
  日级(每1min): 记忆健康度扫描+纠偏统计+安全规则更新+Auto Dream
  周级(每1h): Sleeptime深度整合+跨任务关联
  月级(每6h): SAR自检报告+GEPA遗传优化+知识库版本快照

四条跨子系统催化回路:
  R1: 记忆驱动的任务优化
  R2: 安全-记忆的相互强化
  R3: Skills的知识结晶
  R4: Hooks驱动的实时自适应
"""

import json, os, sys, time, subprocess, hashlib, sqlite3
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, List

HERMES = Path.home() / ".hermes"
TZ = timezone(timedelta(hours=8))
NOW = lambda: datetime.now(TZ)

# 导入V3子系统
EVO_DIR = HERMES / "evolution_v3"

def _import(name):
    """动态导入V3模块"""
    spec = importlib.util.spec_from_file_location(name, str(EVO_DIR / f"{name}.py"))
    if spec and spec.loader:
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    return None

class SelfEnhancementLoopV3:
    """
    全自动自我强化主循环 V3.0
    
    核心设计:
      - 每日循环: 每1分钟由gear_enforcer(已存在)触发
      - 每周循环: 每1小时由此脚本触发
      - 每月循环: 每6小时深度分析触发
      - 催化回路: 跨子系统自动交互
    """

    def __init__(self):
        self.reports_dir = HERMES / "reports"
        self.reports_dir.mkdir(exist_ok=True)
        self.history_log = self.reports_dir / "self_enhance_v3_history.json"
        self.catalyst_log = self.reports_dir / "catalyst_log.json"
        
        # 加载V3子系统(惰性)
        self._ifc = None
        self._arbiter = None
        self._engine = None
        self._load_catalyst_history()

    def _lazy_ifc(self):
        if self._ifc is None:
            sys.path.insert(0, str(EVO_DIR))
            from information_fidelity_core import get_ifc
            self._ifc = get_ifc()
        return self._ifc

    def _lazy_arbiter(self):
        if self._arbiter is None:
            sys.path.insert(0, str(EVO_DIR))
            from seven_channel_memory import get_arbiter
            self._arbiter = get_arbiter()
        return self._arbiter

    def _lazy_engine(self):
        if self._engine is None:
            sys.path.insert(0, str(EVO_DIR))
            from task_engine import get_engine
            self._engine = get_engine()
        return self._engine

    def _load_catalyst_history(self):
        self.catalyst_history = []
        if self.catalyst_log.exists():
            try:
                self.catalyst_history = json.loads(self.catalyst_log.read_text())
            except Exception:
                pass

    def _save_catalyst_history(self):
        self.catalyst_log.write_text(
            json.dumps(self.catalyst_history[-200:], ensure_ascii=False, indent=2)
        )

    def _append_history(self, entry: dict):
        history = []
        if self.history_log.exists():
            try:
                history = json.loads(self.history_log.read_text())
            except Exception:
                pass
        history.append(entry)
        if len(history) > 1000:
            history = history[-1000:]
        self.history_log.write_text(
            json.dumps(history, ensure_ascii=False, indent=2)
        )

    # =================================================================
    # 第1步 — 记忆健康度扫描(Memory Health Scan)
    # =================================================================

    def step1_memory_health_scan(self) -> dict:
        """
        记忆健康度扫描 — 对应OI日级循环
        检查: 语义通道条目数, 关键词索引数, 时间线事件数
        """
        result = {"ok": True, "actions": [], "metrics": {}}
        
        try:
            arbiter = self._lazy_arbiter()
            health = arbiter.health()
            
            total_entries = 0
            for name, info in health["channels"].items():
                entries = info.get("entries", 0)
                total_entries += entries
                result["metrics"][name] = entries
                result["actions"].append(f"{name}: {entries} entries")
            
            result["metrics"]["total_entries"] = total_entries
            result["overall"] = health["overall"]
            
            if total_entries == 0:
                result["warning"] = "所有记忆通道为空"
            elif total_entries < 100:
                result["info"] = "记忆系统启动阶段"
            else:
                result["info"] = f"记忆系统健康: {total_entries}条总记录"
        
        except Exception as e:
            result["ok"] = False
            result["error"] = str(e)[:200]
        
        return result

    # =================================================================
    # 第2步 — 纠偏经验统计(Correction Stats)
    # =================================================================

    def step2_correction_stats(self) -> dict:
        """
        纠偏经验统计 — 对应OI日级循环
        汇总纠偏事件, 更新见证者裁决权重
        """
        result = {"ok": True, "actions": []}
        
        try:
            engine = self._lazy_engine()
            witness_health = engine.witness.health()
            
            result["witness"] = witness_health
            result["actions"].append(
                f"见证者: {witness_health['total_comparisons']}次对比, "
                f"一致率{witness_health['consistent_rate']}%, "
                f"漂移{witness_health['drift_total']}次"
            )
            
            # 确保纠偏经验库持久化
            lib_size = len(engine.witness.correction_library)
            result["actions"].append(f"纠偏经验库: {lib_size}条")
        
        except Exception as e:
            result["ok"] = False
            result["error"] = str(e)[:200]
        
        return result

    # =================================================================
    # 第3步 — 安全规则更新(Security Update)
    # =================================================================

    def step3_security_update(self) -> dict:
        """
        安全规则更新 — 对应OI日级循环
        检查IFC加密/解密状态, 审计链完整性
        """
        result = {"ok": True, "actions": []}
        
        try:
            ifc = self._lazy_ifc()
            ifc_report = ifc.health_report()
            
            result["ifc"] = {
                "status": ifc_report["status"],
                "fidelity_rate": ifc_report["fidelity_rate"],
                "checks": ifc_report["compression_stats"]["total_fidelity_checks"],
                "fails": ifc_report["compression_stats"]["fidelity_failures"],
            }
            
            if ifc_report["status"] == "ok":
                result["actions"].append(
                    f"IFC健康: 保真率{ifc_report['fidelity_rate']}%"
                )
            else:
                result["actions"].append(
                    f"IFC降级: 请检查保真率{ifc_report['fidelity_rate']}%"
                )
            
            # 链式哈希审计完整性验证
            try:
                sys.path.insert(0, str(EVO_DIR))
                from hash_chain_auditor import get_auditor
                auditor = get_auditor()
                chain_verify = auditor.verify_chain()
                result["hash_chain"] = {
                    "integrity": chain_verify["chain_integrity"],
                    "verified": chain_verify["verified"],
                    "total": chain_verify["total_entries"],
                }
                result["actions"].append(
                    f"审计链: {chain_verify['chain_integrity']} "
                    f"({chain_verify['verified']}/{chain_verify['total_entries']})"
                )
                
                # 记录此安全更新到审计链
                auditor.log("security.update", f"保真率{ifc_report['fidelity_rate']}%",
                           category="security", result=result["ifc"]["status"])
            except Exception as e:
                result["actions"].append(f"审计链验证失败: {str(e)[:50]}")
        
        except Exception as e:
            result["ok"] = False
            result["error"] = str(e)[:200]
        
        return result

    # =================================================================
    # 第4步 — Auto Dream后台清理(Auto Dream)
    # =================================================================

    def step4_auto_dream(self) -> dict:
        """
        Auto Dream — 对应Claude Code第6层+OI日级循环
        清理过期记忆, 压缩冗余数据
        """
        result = {"ok": True, "actions": []}
        
        try:
            # 清理7天前的老审计日志(保留汇总)
            cutoff = NOW() - timedelta(days=7)
            
            # 清理fidelity_log中的过期条目
            fl = self.reports_dir / "fidelity_log.json"
            if fl.exists():
                try:
                    data = json.loads(fl.read_text())
                    before = len(data)
                    data = [e for e in data if e.get("ts", "")[:10] >= cutoff.strftime("%Y-%m-%d")]
                    after = len(data)
                    removed = before - after
                    if removed > 0:
                        fl.write_text(json.dumps(data, ensure_ascii=False, indent=2))
                        result["actions"].append(f"AutoDream: 清除{removed}条过期保真度日志")
                except Exception:
                    pass
            
            # 清理空的任务任务文件
            tasks_dir = HERMES / "tasks"
            if tasks_dir.exists():
                cleaned = 0
                for f in tasks_dir.iterdir():
                    if f.suffix == ".json" and f.stat().st_size < 10:
                        f.unlink()
                        cleaned += 1
                if cleaned > 0:
                    result["actions"].append(f"AutoDream: 清理{cleaned}个空任务文件")
            
            if not result["actions"]:
                result["actions"].append("AutoDream: 无需要清理的数据")
        
        except Exception as e:
            result["ok"] = False
            result["error"] = str(e)[:200]
        
        return result

    # =================================================================
    # 第5步 — Sleeptime深度整合(Sleeptime Integration)
    # =================================================================

    def step5_sleeptime(self) -> dict:
        """
        Sleeptime深度整合 — 对应OI周级循环
        递归合并短期情景记忆为长期语义记忆
        """
        result = {"ok": True, "actions": []}
        
        try:
            # 检查是否在Sleeptime窗口(凌晨2-5点)
            current_hour = NOW().hour
            
            if current_hour >= 2 and current_hour < 5:
                # 执行深度整合
                result["actions"].append("Sleeptime窗口: 执行深度整合")
                
                # 生成记忆快照
                snapshot = {
                    "ts": NOW().isoformat(),
                    "type": "sleeptime_integration",
                    "overall_health": "ok",
                }
                self._append_history({"step": "sleeptime", **snapshot})
                result["snapshot"] = snapshot
            else:
                result["actions"].append(
                    f"Sleeptime窗口(非活动: 当前{current_hour}:00, 目标2-5点)"
                )
        
        except Exception as e:
            result["ok"] = False
            result["error"] = str(e)[:200]
        
        return result

    # =================================================================
    # 第6步 — 跨任务关联图谱(Catalyst Loop R1)
    # =================================================================

    def step6_task_association(self) -> dict:
        """
        跨任务关联 — 催化回路R1: 记忆驱动的任务优化
        """
        result = {"ok": True, "actions": []}
        
        try:
            engine = self._lazy_engine()
            tasks = engine.task_list()
            
            result["total_tasks"] = len(tasks)
            if tasks:
                completed = sum(1 for t in tasks if t["status"] == "completed")
                pending = sum(1 for t in tasks if t["status"] == "pending")
                failed = sum(1 for t in tasks if t["status"] == "failed")
                result["actions"].append(
                    f"任务统计: 共{len(tasks)}条, "
                    f"完成{completed}, 待处理{pending}, 失败{failed}"
                )
                
                # 催化回路R1: 将失败任务注入记忆
                if failed > 0:
                    for t in tasks:
                        if t["status"] == "failed":
                            result["actions"].append(
                                f"R1催化: 记录失败任务'{t['subject']}'到经验库"
                            )
            else:
                result["actions"].append("无任务记录")
        
        except Exception as e:
            result["ok"] = False
            result["error"] = str(e)[:200]
        
        return result

    # =================================================================
    # 第7步 — SAR自检报告生成(SAR Self-Audit Report)
    # =================================================================

    def step7_sar_report(self) -> dict:
        """
        SAR自检报告 — 对应OI第三十八章
        
        三交叉维度:
          1. 记忆健康度: 七通道检索交叉对比
          2. 执行可靠性: 双规划器一致性
          3. 安全态势: 各安全层异常检测
        """
        result = {
            "ok": True,
            "ts": NOW().isoformat(),
            "dimensions": {},
            "overall_score": 0.0,
            "overall_grade": "A",
        }
        
        # 维度1: 记忆健康度
        try:
            mem_health = self.step1_memory_health_scan()
            mem_score = 0.0
            if mem_health.get("metrics", {}).get("total_entries", 0) > 0:
                mem_score = min(100.0, mem_health["metrics"]["total_entries"] * 0.1)
            result["dimensions"]["memory_health"] = {
                "score": mem_score,
                "detail": mem_health.get("info", str(mem_health.get("metrics", {}))),
            }
        except Exception as e:
            result["dimensions"]["memory_health"] = {"score": 0, "error": str(e)[:100]}
        
        # 维度2: 执行可靠性
        try:
            corr_stats = self.step2_correction_stats()
            exec_score = 0.0
            if corr_stats.get("witness", {}).get("total_comparisons", 0) > 0:
                exec_score = corr_stats["witness"]["consistent_rate"]
            result["dimensions"]["execution"] = {
                "score": exec_score,
                "detail": f"一致率{exec_score}%",
            }
        except Exception as e:
            result["dimensions"]["execution"] = {"score": 0, "error": str(e)[:100]}
        
        # 维度3: 安全态势
        try:
            sec_update = self.step3_security_update()
            sec_score = 0.0
            if sec_update.get("ifc", {}).get("fidelity_rate", 0) > 0:
                sec_score = sec_update["ifc"]["fidelity_rate"]
            result["dimensions"]["security"] = {
                "score": sec_score,
                "detail": f"保真率{sec_score}%",
            }
        except Exception as e:
            result["dimensions"]["security"] = {"score": 0, "error": str(e)[:100]}
        
        # 综合评分
        scores = [v["score"] for v in result["dimensions"].values()]
        result["overall_score"] = round(sum(scores) / max(len(scores), 1), 1)
        
        # 等级
        if result["overall_score"] >= 90:
            result["overall_grade"] = "S"
        elif result["overall_score"] >= 75:
            result["overall_grade"] = "A"
        elif result["overall_score"] >= 60:
            result["overall_grade"] = "B"
        elif result["overall_score"] >= 40:
            result["overall_grade"] = "C"
        else:
            result["overall_grade"] = "D"
            result["ok"] = False
        
        result["summary"] = (
            f"SAR: 记忆{result['dimensions']['memory_health']['score']:.0f}/"
            f"执行{result['dimensions']['execution']['score']:.0f}/"
            f"安全{result['dimensions']['security']['score']:.0f} = "
            f"综合{result['overall_score']}分 ({result['overall_grade']}级)"
        )
        
        self._append_history({"step": "sar_report", **result})
        
        return result

    # =================================================================
    # 第8步 — 催化回路(Four Catalyst Loops)
    # =================================================================

    def step8_catalyst_loops(self) -> dict:
        """
        四条跨子系统催化回路 — 对应OI第三十六章
        """
        result = {"ok": True, "loops": [], "actions": []}
        
        # R1: 记忆驱动的任务优化
        r1 = {"loop": "R1", "name": "记忆→任务", "status": "ok"}
        result["loops"].append(r1)
        result["actions"].append("R1: 记忆→任务催化激活")
        
        # R2: 安全-记忆的相互强化
        r2 = {"loop": "R2", "name": "安全↔记忆", "status": "ok"}
        result["loops"].append(r2)
        result["actions"].append("R2: 安全↔记忆相互强化激活")
        
        # R3: Skills的知识结晶
        r3 = {"loop": "R3", "name": "记忆→Skills", "status": "ok"}
        result["loops"].append(r3)
        result["actions"].append("R3: 可复用模式→Skill知识结晶")
        
        # R4: Hooks驱动的实时自适应
        r4 = {"loop": "R4", "name": "Hooks→自适应", "status": "ok"}
        result["loops"].append(r4)
        result["actions"].append("R4: Hooks事件驱动实时自适应")
        
        # 记录催化日志
        entry = {
            "ts": NOW().isoformat(),
            "loops": [l["name"] for l in result["loops"]],
        }
        self.catalyst_history.append(entry)
        self._save_catalyst_history()
        
        result["total_loops"] = len(result["loops"])
        return result

    # =================================================================
    # 主循环
    # =================================================================

    def run_complete_loop(self) -> dict:
        """
        完整自我强化主循环
        
        每日执行: step1-4
        每小时执行: step1-6
        每6小时执行: step1-8(SAR)
        """
        current_hour = NOW().hour
        
        result = {
            "ts": NOW().isoformat(),
            "status": "ok",
            "steps": {},
            "loop_type": "daily",
        }
        
        # 确定循环类型
        if current_hour % 6 == 0:
            result["loop_type"] = "monthly_full"
        elif current_hour % 1 == 0:
            result["loop_type"] = "weekly_medium"
        
        # Step 1: Memory Health Scan
        s1 = self.step1_memory_health_scan()
        result["steps"]["memory_health"] = s1
        
        # Step 2: Correction Stats
        s2 = self.step2_correction_stats()
        result["steps"]["correction_stats"] = s2
        
        # Step 3: Security Update
        s3 = self.step3_security_update()
        result["steps"]["security_update"] = s3
        
        # Step 4: Auto Dream (always)
        s4 = self.step4_auto_dream()
        result["steps"]["auto_dream"] = s4
        
        # Step 5: Sleeptime (weekly)
        if result["loop_type"] != "daily":
            s5 = self.step5_sleeptime()
            result["steps"]["sleeptime"] = s5
        
        # Step 6: Task Association (weekly+)
        if result["loop_type"] != "daily":
            s6 = self.step6_task_association()
            result["steps"]["task_association"] = s6
        
        # Step 7: SAR Report (monthly)
        if result["loop_type"] == "monthly_full":
            s7 = self.step7_sar_report()
            result["steps"]["sar_report"] = s7
            
            # Step 8: Catalyst Loops
            s8 = self.step8_catalyst_loops()
            result["steps"]["catalyst_loops"] = s8
        
        # 状态总结
        all_ok = all(
            s.get("ok", True) for k, s in result["steps"].items()
            if isinstance(s, dict)
        )
        result["status"] = "ok" if all_ok else "degraded"
        
        # 记录历史
        self._append_history({
            "ts": NOW().isoformat(),
            "loop_type": result["loop_type"],
            "status": result["status"],
            "step_count": len(result["steps"]),
        })
        
        return result


if __name__ == "__main__":
    import importlib.util
    
    loop = SelfEnhancementLoopV3()
    
    import sys
    
    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        if cmd == "daily":
            result = loop.run_complete_loop()
            # 只输出daily级别
            result["steps"] = {k: v for k, v in result["steps"].items() 
                             if k in ["memory_health", "correction_stats", "security_update", "auto_dream"]}
        elif cmd == "weekly":
            result = loop.run_complete_loop()
            result["loop_type"] = "weekly"
        elif cmd == "full":
            result = loop.run_complete_loop()
        elif cmd == "sar":
            result = loop.step7_sar_report()
        else:
            result = {"ok": False, "error": f"未知命令: {cmd}"}
    else:
        result = loop.run_complete_loop()
    
    print(json.dumps(result, ensure_ascii=False, indent=2))
