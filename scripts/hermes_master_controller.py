#!/usr/bin/env python3
"""
Hermes 全能主控控制器 v2.0
融合Agent驱动 + Multi-Agent编排 + StructMem记忆 + Lossless-Claw压缩 + 5维度交叉审核

架构:
  调度Agent(主) → 多个专项Agent(子) → 汇总输出
  每步并行最大化,上下文最小化,专业度最大化
"""

import json
import subprocess
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

TZ = timezone(timedelta(hours=8))
BASE = Path("/home/administrator/.hermes")
SCRIPTS = BASE / "scripts"
OUTPUTS = BASE / "outputs"

class HermesMasterController:
    """全能主控控制器"""

    def __init__(self):
        self.log = []

    def log_step(self, step: str, status: str, detail: str = ""):
        entry = {
            "timestamp": datetime.now(TZ).isoformat(),
            "step": step,
            "status": status,
            "detail": detail[:200]
        }
        self.log.append(entry)
        print(f"[{step}] {status}: {detail[:120]}")

    def run_script(self, name: str, args: list = None, timeout: int = 120) -> dict:
        """运行一个脚本"""
        script = SCRIPTS / name
        if not script.exists():
            # 尝试找skill中的脚本
            skill_script = BASE / "skills" / "autonomous-systems" / name.replace(".py", "") / "scripts" / name
            if skill_script.exists():
                script = skill_script
            else:
                return {"status": "error", "error": f"Script {name} not found"}

        cmd = ["python3", str(script)]
        if args:
            cmd.extend(args)

        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=timeout
            )
            return {
                "status": "ok" if result.returncode == 0 else "error",
                "stdout": result.stdout[-2000:],
                "stderr": result.stderr[-500:],
                "exit_code": result.returncode
            }
        except subprocess.TimeoutExpired:
            return {"status": "timeout", "error": f"Timed out after {timeout}s"}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    # ========== 核心功能模块 ==========

    def run_structmem_integration(self) -> dict:
        """运行StructMem跨事件整合"""
        result = self.run_script("structmem_memory.py", timeout=30)
        self.log_step("structmem", "ok" if result["status"] == "ok" else "error",
                      f"事件整合状态检查: {result.get('stdout', '')[:100]}")
        return result

    def run_lossless_claw(self, level: int = 1) -> dict:
        """运行Lossless-Claw压缩"""
        levels = {1: "level1", 2: "level2", 3: "level3"}
        cmd = levels.get(level, "level1")
        result = self.run_script("lossless_claw.py", [cmd], timeout=60)
        self.log_step(f"claw_l{level}", "ok" if result["status"] == "ok" else "error",
                      f"压缩结果: {result.get('stdout', '')[:100]}")
        return result

    def run_self_evolve(self) -> dict:
        """运行自进化"""
        result = self.run_script("hermes_self_evolve_cluster.py", timeout=300)
        self.log_step("self_evolve", "ok" if result["status"] == "ok" else "error",
                      f"自进化: {result.get('stdout', '')[:100]}")
        return result

    def run_system_audit(self) -> dict:
        """运行系统审计"""
        result = self.run_script("system_deep_audit.py", timeout=300)
        self.log_step("system_audit", "ok" if result["status"] == "ok" else "error",
                      f"审计: {result.get('stdout', '')[:100]}")
        return result

    def run_guardian(self) -> dict:
        """运行守护神检查"""
        result = self.run_script("guardian.py", timeout=60)
        self.log_step("guardian", "ok" if result["status"] == "ok" else "error",
                      f"守护: {result.get('stdout', '')[:100]}")
        return result

    def run_all(self, skip_audit: bool = False):
        """运行全线检查"""
        print(f"\n{'='*60}")
        print(f"Hermes 全线主控检查 @ {datetime.now(TZ).isoformat()}")
        print(f"{'='*60}\n")

        # 步骤1: 守护神检查
        self.log_step("START", "running", "启动全线检查")
        g = self.run_guardian()

        # 步骤2: StructMem整合
        s = self.run_structmem_integration()

        # 步骤3: Lossless-Claw L1压缩
        c = self.run_lossless_claw(1)

        # 步骤4: 自进化检查
        e = self.run_self_evolve()

        # 步骤5: 系统审计(可选)
        if not skip_audit:
            a = self.run_system_audit()

        # 步骤6: Lossless-Claw L2压缩
        c2 = self.run_lossless_claw(2)

        # 汇总
        print(f"\n{'='*60}")
        print(f"主控检查完成 @ {datetime.now(TZ).isoformat()}")
        print(f"总步骤: {len(self.log)}")
        ok_count = sum(1 for l in self.log if l["status"] == "ok")
        print(f"成功: {ok_count}/{len(self.log)}")
        print(f"{'='*60}\n")

        report = {
            "timestamp": datetime.now(TZ).isoformat(),
            "summary": {
                "total_steps": len(self.log),
                "ok": ok_count,
                "error": len(self.log) - ok_count
            },
            "steps": self.log
        }

        # 输出报告
        report_path = OUTPUTS / "master_controller"
        report_path.mkdir(parents=True, exist_ok=True)
        report_file = report_path / f"master_{datetime.now(TZ).strftime('%Y%m%d_%H%M%S')}.json"
        report_file.write_text(json.dumps(report, ensure_ascii=False, indent=2))

        return report


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Hermes 全能主控控制器")
    parser.add_argument("--skip-audit", action="store_true", help="跳过系统审计")
    parser.add_argument("--module", choices=["structmem", "claw", "evolve", "audit", "guardian", "all"],
                        default="all", help="运行指定模块")
    parser.add_argument("--claw-level", type=int, default=1, choices=[1, 2, 3],
                        help="压缩级别")

    args = parser.parse_args()

    ctrl = HermesMasterController()
    modules = {
        "structmem": lambda: ctrl.run_structmem_integration(),
        "claw": lambda: ctrl.run_lossless_claw(args.claw_level),
        "evolve": lambda: ctrl.run_self_evolve(),
        "audit": lambda: ctrl.run_system_audit(),
        "guardian": lambda: ctrl.run_guardian(),
    }

    if args.module == "all":
        ctrl.run_all(skip_audit=args.skip_audit)
    else:
        result = modules[args.module]()
        print(json.dumps(result, ensure_ascii=False, indent=2))
