#!/usr/bin/env python3
"""
🧬 自我增强闭环循环 v1.0 — 全自动 7×24 无人值守
========================================================
每5分钟cron执行一次。完全独立自主运行。

闭环流程:
  1. 读取当前上下文文件
  2. ContextManager自动更新热/温/冷三层
  3. MemoryOrchestrator三引擎并行存储
  4. LCM DAG增量摘要节点创建
  5. MetaThinker漂移检测
  6. 漂移>阈值 → ContextEquilibria自动恢复
  7. EncryptionLayer敏感数据自动加密
  8. AuditLogger审计链写入+完整性验证
  9. 报告写入齿轮检查点

格林主人最高指令:
  此脚本是"全自动自我强化"的完整闭环实现。
  它是物理层强制,不依赖Hermes的记忆或主动调用。
"""

import json, os, sys, subprocess, time, hashlib, sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path

HERMES = Path("/home/administrator/.hermes")
TZ = timezone(timedelta(hours=8))
SCRIPTS = HERMES / "scripts"
LOGS = HERMES / "logs"
REPORTS = HERMES / "reports"
now = lambda: datetime.now(TZ)

CLOSED_LOOP_LOG = LOGS / "self_enhance_closed_loop.log"


def log(msg: str):
    ts = now().isoformat()
    entry = f"[{ts}] {msg}"
    CLOSED_LOOP_LOG.parent.mkdir(exist_ok=True)
    with open(CLOSED_LOOP_LOG, 'a', encoding='utf-8') as f:
        f.write(entry + '\n')
    print(entry)


def run(script: str, args: list = None, timeout: int = 30) -> dict:
    path = SCRIPTS / script
    if not path.exists():
        return {"ok": False, "error": f"脚本不存在: {script}"}
    cmd = [sys.executable, str(path)]
    if args:
        cmd.extend(args)
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=timeout, text=True)
        return {"ok": r.returncode == 0, "stdout": r.stdout[:1000], "stderr": r.stderr[:300]}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "超时"}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


class SelfEnhanceClosedLoop:
    """全自动自我增强闭环"""

    def __init__(self):
        self.session_id = self._get_session_id()
        self.results = {
            "ts": now().isoformat(),
            "session_id": self.session_id,
            "steps": {},
            "status": "ok"
        }

    def _get_session_id(self) -> str:
        sid_file = REPORTS / ".current_session_id.txt"
        if sid_file.exists():
            sid = sid_file.read_text().strip()
            if sid:
                return sid
        sid = f"auto_{int(time.time())}"
        sid_file.write_text(sid)
        return sid

    def _get_goal(self) -> str:
        goal_file = REPORTS / "task_goal.txt"
        if goal_file.exists():
            return goal_file.read_text(encoding='utf-8').strip()
        return ""

    def _get_context(self) -> dict:
        """读取当前上下文,返回{user, assistant}"""
        ctx_file = REPORTS / "current_context.txt"
        if not ctx_file.exists():
            return {}
        try:
            content = ctx_file.read_text(encoding='utf-8').strip()
            lines = content.split('\n')
            result = {}
            for line in lines:
                clean = line.strip()
                if clean.startswith("USER:"):
                    result["user"] = clean[5:].strip()
                elif clean.startswith("ASSISTANT:"):
                    result["assistant"] = clean[10:].strip()
            if not result:
                result["raw"] = content[:500]
            return result
        except Exception:
            return {"raw": ctx_file.read_text(encoding='utf-8').strip()[:500]}

    def _write_checkpoint(self, step: str, detail: str):
        """写入齿轮检查点"""
        cp_file = REPORTS / "gear_checkpoint.json"
        cp = {
            "task_id": f"self_enhance_{int(time.time())}",
            "round": int(time.time()) % 10000,
            "step": step,
            "detail": detail[:200],
            "next_action": "continue_closed_loop",
            "status": "running" if step != "complete" else "completed",
            "ts": time.time()
        }
        cp_file.write_text(json.dumps(cp, ensure_ascii=False, indent=2))
        self.results["checkpoint"] = cp

    def step_1_context_manager(self):
        """步骤1: ContextManager自动更新"""
        ctx = self._get_context()
        if not ctx:
            return {"ok": True, "msg": "无上下文,跳过"}

        user_msg = ctx.get("user", ctx.get("raw", ""))[:300]
        assistant_msg = ctx.get("assistant", "")[:500]

        r = run("context_manager.py", ["add", user_msg, assistant_msg])
        if r["ok"]:
            self._write_checkpoint("context_manager", f"已更新: {len(user_msg)}字+{len(assistant_msg)}字")
            return {"ok": True, "msg": f"ContextManager已更新"}
        return {"ok": False, "msg": r.get("error", "未知错误")}

    def step_2_three_engine_store(self):
        """步骤2: 三引擎并行存储"""
        ctx = self._get_context()
        if not ctx:
            return {"ok": True, "msg": "无上下文,跳过"}

        user_msg = ctx.get("user", "")[:500]
        assistant_msg = ctx.get("assistant", "")[:500]

        stored = 0
        for role, msg in [("user", user_msg), ("assistant", assistant_msg)]:
            if len(msg) < 5:
                continue
            r = run("memory_orchestrator_v3.py", ["store", self.session_id, role, msg])
            if r["ok"]:
                stored += 1
            dag_r = run("lcm_dag_engine.py", ["store", self.session_id, role, msg])
            if dag_r["ok"]:
                stored += 1

        self._write_checkpoint("three_engine_store", f"已存储{stored}条到三引擎")
        return {"ok": stored > 0, "msg": f"三引擎已存储{stored}条"}

    def step_3_lcm_dag_summary(self):
        """步骤3: LCM DAG自动摘要节点创建"""
        status_r = run("lcm_dag_engine.py", ["status"])
        if not status_r["ok"]:
            return {"ok": False, "msg": status_r.get("error", "")}

        try:
            for line in status_r["stdout"].split('\n'):
                if "原始消息数" in line:
                    count = int(line.split(':')[1].strip())
                    if count >= 5 and count % 5 == 0:
                        msg_ids = json.dumps(list(range(max(1, count-4), count+1)))
                        leaf_r = run("lcm_dag_engine.py", ["leaf", msg_ids, 
                            f"自动摘要: session={self.session_id} round={count}"])
                        if leaf_r["ok"]:
                            self._write_checkpoint("lcm_summary", f"摘要节点创建: round={count}")
                            return {"ok": True, "msg": f"LCM摘要节点已创建(消息#{count})"}
        except Exception as e:
            return {"ok": False, "msg": str(e)}

        return {"ok": True, "msg": "无需创建摘要"}

    def step_4_drift_detection(self):
        """步骤4: MetaThinker漂移检测"""
        goal = self._get_goal()
        if not goal:
            return {"ok": True, "msg": "无目标,跳过漂移检测"}

        ctx = self._get_context()
        context_text = json.dumps(ctx, ensure_ascii=False)

        r = run("meta_thinker.py", ["check", "--goal", goal[:200], "--context", context_text[:500]])
        if not r["ok"]:
            return {"ok": False, "msg": r.get("error", "")}

        # 解析漂移分数
        drift_score = 0.7  # 默认critical(如果解析失败)
        level = "critical"
        for line in r["stdout"].split('\n'):
            if "综合漂移分数" in line:
                try:
                    drift_score = float(line.split(':')[1].strip())
                except Exception:
                    pass
            if "等级" in line:
                level = line.split(':')[1].strip()

        self.results["drift_score"] = drift_score
        self.results["drift_level"] = level

        return {"ok": True, "msg": f"漂移检测: score={drift_score:.3f} level={level}"}

    def step_5_auto_recovery(self):
        """步骤5: 漂移>阈值自动恢复"""
        drift_score = self.results.get("drift_score", 0.0)
        level = self.results.get("drift_level", "ok")

        if level not in ("critical", "fail") and drift_score < 0.5:
            return {"ok": True, "msg": "漂移阈值未超,无需恢复"}

        goal = self._get_goal()
        task_id = f"auto_recovery_{int(time.time())}"

        r = run("context_equilibria.py", ["restore", task_id, "--goal", goal[:200]])
        if r["ok"]:
            self._write_checkpoint("auto_recovery", f"已恢复: task={task_id}")
            return {"ok": True, "msg": f"自动恢复已触发: task={task_id}"}
        return {"ok": False, "msg": r.get("error", "")}

    def step_6_encrypt_sensitive(self):
        """步骤6: 加密敏感数据"""
        # 检查是否有旧的检查点文件需要加密
        sensitive_files = [
            REPORTS / "gear_checkpoint.json",
            REPORTS / "task_current.json",
            HERMES / "task_current.json",
        ]
        encrypted = 0
        for f in sensitive_files:
            if f.exists() and f.stat().st_size > 100:
                r = run("encryption_layer.py", ["encrypt", str(f)])
                if r["ok"]:
                    encrypted += 1
                    log(f"  → 已加密: {f.name}")

        return {"ok": True, "msg": f"已加密{encrypted}个文件"}

    def step_7_audit_chain(self):
        """步骤7: 审计链写入+验证"""
        # 写入本轮操作摘要
        r1 = run("audit_logger.py", ["write", "closed_loop_tick", 
            f"session={self.session_id} drift={self.results.get('drift_score',0):.2f}", 
            "--source", "self_enhance_loop", "--level", "info"])

        # 验证链完整性
        r2 = run("audit_logger.py", ["verify"])

        chain_ok = r2.get("ok", False)
        chain_entries = 0
        if chain_ok and r2.get("stdout"):
            import re
            for line in r2["stdout"].split('\n'):
                if "全部通过" in line:
                    m = re.search(r'(\d+)条', line)
                    if m:
                        chain_entries = int(m.group(1))

        self.results["audit_entries"] = chain_entries
        self.results["audit_ok"] = chain_ok

        self._write_checkpoint("audit_chain", f"链完整: {chain_entries}条通过")
        return {"ok": chain_ok, "msg": f"审计链: {chain_entries}条 {'✅' if chain_ok else '❌'}"}

    def step_8_final_verify(self):
        """步骤8: 最终完整性验证"""
        checks = {}

        # LCM DAG完整性
        dag_v = run("lcm_dag_engine.py", ["verify"])
        checks["lcm_dag"] = dag_v.get("ok", False)

        # 三引擎健康
        health_r = run("memory_orchestrator_v3.py", ["health"])
        checks["three_engines"] = health_r.get("ok", False)

        # ContextManager完整性
        ctx_v = run("context_manager.py", ["verify"])
        checks["context_manager"] = ctx_v.get("ok", False)

        self.results["final_checks"] = checks
        all_ok = all(checks.values())
        self.results["status"] = "ok" if all_ok else "degraded"

        passed = sum(1 for v in checks.values() if v)
        failed_names = [k for k, v in checks.items() if not v]
        detail = f"最终校验: {passed}/{len(checks)}通过"
        if failed_names:
            detail += f" | 失败: {', '.join(failed_names)}"

        return {"ok": all_ok, "msg": detail}

    def run(self):
        """完整闭环执行"""
        log("=" * 60)
        log(f"🧬 自我增强闭环 - 开始 (session={self.session_id})")
        log("=" * 60)

        steps = [
            ("step_1_context_manager", self.step_1_context_manager, "ContextManager热/温/冷"),
            ("step_2_three_engine_store", self.step_2_three_engine_store, "三引擎并行存储"),
            ("step_3_lcm_dag_summary", self.step_3_lcm_dag_summary, "LCM DAG摘要"),
            ("step_4_drift_detection", self.step_4_drift_detection, "MetaThinker漂移检测"),
            ("step_5_auto_recovery", self.step_5_auto_recovery, "ContextEquilibria恢复"),
            ("step_6_encrypt_sensitive", self.step_6_encrypt_sensitive, "加密敏感数据"),
            ("step_7_audit_chain", self.step_7_audit_chain, "审计链写入+验证"),
            ("step_8_final_verify", self.step_8_final_verify, "最终完整性校验"),
        ]

        all_ok = True
        for name, func, desc in steps:
            log(f"[{desc}]...")
            try:
                result = func()
                self.results["steps"][name] = result
                status = "✅" if result.get("ok") else "❌"
                log(f"  {status} {result.get('msg', '')}")
                if not result.get("ok", True):
                    all_ok = False
            except Exception as e:
                self.results["steps"][name] = {"ok": False, "error": str(e)}
                log(f"  ❌ 异常: {e}")
                all_ok = False

        self.results["all_ok"] = all_ok
        log(f"\n状态: {'✅全部通过' if all_ok else '❌部分失败'}")

        # 写入运行历史
        history_file = REPORTS / "closed_loop_history.json"
        history = []
        if history_file.exists():
            try:
                history = json.loads(history_file.read_text())
                if not isinstance(history, list):
                    history = []
            except Exception:
                history = []
        history.append(self.results)
        if len(history) > 500:
            history = history[-500:]
        history_file.write_text(json.dumps(history, ensure_ascii=False, indent=2))

        return self.results


def main():
    loop = SelfEnhanceClosedLoop()
    result = loop.run()
    print(f"\n[CLOSED-LOOP] status={result['status']} all_ok={result.get('all_ok', False)}")
    return result


if __name__ == "__main__":
    main()
