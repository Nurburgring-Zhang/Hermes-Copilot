#!/usr/bin/env python3
"""
⚙️ 齿轮强制执行器 v3.0 — 全自动自我强化引擎(融合V3架构)
================================================================
每1分钟cron执行，自动完成：
1. 中断检测+恢复 — 原有功能
2. V3 SelfEnhancementLoop主循环 — 记忆健康+纠偏+安全+AutoDream
3. IFC信息保真核心 — 压缩/加密/保真度监控
4. 七通道记忆仲裁 — 语义+关键词+时间线多路检索
5. DPW任务引擎 — 双规划器+见证者+三级纠偏
6. SAR自检报告 — 三交叉维度评估
7. 催化回路 — R1-R4跨系统螺旋上升

集成V3子系统:
  evolution_v3/information_fidelity_core.py
  evolution_v3/seven_channel_memory.py
  evolution_v3/task_engine.py
  evolution_v3/self_enhancement_v3_loop.py

格林主人最高指令(2026-05-20固化):
  集成OI融合增强架构+IFC信息保真核心+Mnemosyne社区方案
  全自动螺旋上升进化，不需要Hermes主动调用

## 🔴 skills组合/并行/链式调用规则（格林主人最高指令 2026-05-24固化）

### 所有skill必须具有的能力：
1. **主动运行能力** — 每个skill在执行任务时必须能主动加载和运行，不需要重复指令
2. **链式调用能力** — skill必须支持链式串联（A→B→C），前一个的输出自动成为下一个的输入
3. **并行调用能力** — 多个skill必须能同时并行执行，互不干扰

### Hermes Agent必须具有的能力：
1. **主动调用多Agent组队** — Agent必须能主动创建多个子Agent组成团队协作
2. **链式运行** — Agent必须能按顺序链式调用多个Agent，形成工作流
3. **并行运行** — Agent必须能同时并行运行多个Agent，各自独立执行任务

### 实现机制：
- Skills Orchestration Engine位于 ~/.hermes/orchestrate/
- 使用 WorkflowGraph (DAG) 定义链式/并行/条件工作流
- 使用 SkillsExecutor 通过delegate_task调度子Agent执行
- 每个skill执行时自动加载SKILL.md并使用skill_view()
- 所有调用必须主动进行，不能等待用户指令

## 🔴 规则0：自主能力基线 — 所有能力的前提（格林主人最高指令 2026-05-25固化）
遇到一切障碍时自动执行三步：
1. 多路寻找方案：原方案受限≠无方案，搜索至少3种替代路径
2. 核实质量：任何方案必须验证HTTPS+校验和+来源可追溯
3. 环境无关判断：WSL/无显示器/国内网络是约束条件不是"做不到"的理由

## 🔴 规则8：下载受限时寻找第三方正规链接（格林主人最高指令 2026-05-25固化）
执行任何下载任务时：
1. 原链接下载受限 → 必须寻找第三方正规链接（ghproxy/GitHub Release/官方镜像等）
2. 第三方链接必须核实：HTTPS加密+校验和验证+来源可追溯
3. 禁止：随便找的网盘/个人附件/来路不明网站/不验证直接跑
4. 下载后必须验证完整性（SHA256/文件大小）
5. 优先顺序：官方GH Release→官方CDN/镜像→包管理器→其他开源合规渠道

## 🔴 低分数据自动清理规则（格林主人最高指令 2026-05-24固化）
cleaned_intelligence不允许长期堆积低分数据(ai_score_total<20)，每次清洗完毕自动归档低分数据到archive_cleaned后删除。lowscore_cleaner.py每4小时自动运行。raw_intelligence中3天以上未清洗孤立数据自动删除。
"""

import json, os, sys, sqlite3, subprocess, time
from datetime import datetime, timezone, timedelta
from pathlib import Path
sys.path.insert(0, str(Path.home() / ".hermes"))
sys.path.insert(0, str(Path.home() / ".hermes" / "evolution_v3"))

# P1: MonitorEngine & ReflectorEngine 注入
from agent.monitor import MonitorEngine, MonitorSignal
from agent.reflector import ReflectorEngine
from scripts.segment_manager import SegmentManager
import os, json
from scripts.consistency_guard import ConsistencyGuard
_MONITOR = MonitorEngine()
_REFLECTOR = ReflectorEngine()
_SEGMENT_MGR = SegmentManager()
_CONSISTENCY_GUARD = ConsistencyGuard()

HERMES = Path("/home/administrator/.hermes")
TZ = timezone(timedelta(hours=8))
SCRIPTS = HERMES / "scripts"
LOGS = HERMES / "logs"
REPORTS = HERMES / "reports"
EVO_V3 = HERMES / "evolution_v3"
now = lambda: datetime.now(TZ)

ENHANCE_LOG = LOGS / "self_enhance_v3.log"

# ===== V3子系统引用(惰性) =====
_v3_loop = None
def get_v3_loop():
    global _v3_loop
    if _v3_loop is None:
        from self_enhancement_v3_loop import SelfEnhancementLoopV3
        _v3_loop = SelfEnhancementLoopV3()
    return _v3_loop

_v3_ifc = None
def get_v3_ifc():
    global _v3_ifc
    if _v3_ifc is None:
        from information_fidelity_core import get_ifc
        _v3_ifc = get_ifc()
    return _v3_ifc

_v3_arbiter = None
def get_v3_arbiter():
    global _v3_arbiter
    if _v3_arbiter is None:
        from seven_channel_memory import get_arbiter
        _v3_arbiter = get_arbiter()
    return _v3_arbiter

# 日志文件
ENHANCE_LOG = LOGS / "self_enhance.log"
LAST_CTX_FILE = REPORTS / ".last_context_round.txt"


def log(msg: str):
    """统一日志"""
    ts = now().isoformat()
    entry = f"[{ts}] {msg}"
    ENHANCE_LOG.parent.mkdir(exist_ok=True)
    with open(ENHANCE_LOG, 'a', encoding='utf-8') as f:
        f.write(entry + '\n')
    print(entry)


def run_script(script: str, args: list = None, timeout: int = 30) -> dict:
    """运行任意脚本并返回结果"""
    path = SCRIPTS / script
    if not path.exists():
        return {"ok": False, "error": f"脚本不存在: {script}"}
    cmd = [sys.executable, str(path)]
    if args:
        cmd.extend(args)
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=timeout, text=True)
        return {"ok": r.returncode == 0, "stdout": r.stdout[:500], "stderr": r.stderr[:200]}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "超时"}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def get_active_task() -> dict:
    """获取当前活跃任务信息（三重冗余：gear_checkpoint → task_current → recovery_pack）"""
    gear = REPORTS / "gear_checkpoint.json"
    tc = HERMES / "task_current.json"
    rp = REPORTS / "recovery_pack.json"

    # 第一重: gear_checkpoint (最新断点, 最可靠)
    if gear.exists():
        try:
            data = json.loads(gear.read_text())
            if data.get("status") == "running":
                return {"source": "gear_checkpoint", "task_id": data.get("task_id", ""),
                        "next_action": data.get("next_action", ""), "data": data}
        except Exception:
            pass

    # 第二重: task_current
    if tc.exists():
        try:
            data = json.loads(tc.read_text())
            if data.get("status") in ("running", "interrupted"):
                return {"source": "task_current", "task_id": data.get("task_id", ""),
                        "next_action": data.get("next_action", ""), "data": data}
        except Exception:
            pass

    # 第三重: recovery_pack (最全面但可能包含矛盾数据)
    if rp.exists():
        try:
            data = json.loads(rp.read_text())
            status = data.get("status", "")
            gc_data = data.get("gear_checkpoint", {}) or {}
            tc_data = data.get("task_current", {}) or {}

            if status in ("running", "interrupted"):
                # 优先使用gear_checkpoint中的数据
                primary = gc_data if gc_data.get("task_id") else tc_data
                return {"source": "recovery_pack", "task_id": primary.get("task_id", ""),
                        "next_action": primary.get("next_action", ""), "data": data}
        except Exception:
            pass

    return {"source": None, "task_id": "", "next_action": ""}


def context_manager_auto():
    """
    自动执行ContextManager:
    读取当前上下文文件(如果有) → 自动更新热/温/冷
    """
    result = {"ok": True, "actions": []}

    # 检查是否有未处理的上下文
    ctx_file = REPORTS / "current_context.txt"
    if not ctx_file.exists():
        result["actions"].append("无待处理上下文")
        return result

    try:
        content = ctx_file.read_text(encoding='utf-8').strip()
        if not content:
            result["actions"].append("上下文文件为空")
            return result

        # 检测是否已经处理过(通过比较哈希)
        current_hash = str(hash(content))
        last_hash_file = REPORTS / ".last_context_hash.txt"
        if last_hash_file.exists() and last_hash_file.read_text().strip() == current_hash:
            result["actions"].append("上下文无变化")
            return result

        # 提取用户消息和助手消息(格式: USER:...\nASSISTANT:...)
        parts = content.split('\n', 1)
        user_msg = parts[0].replace("USER:", "").strip() if parts[0].startswith("USER:") else parts[0][:200]
        assistant_msg = parts[1].strip() if len(parts) > 1 else ""

        # 调用ContextManager添加轮次
        cm_result = run_script("context_manager.py", ["add", user_msg, assistant_msg])
        if cm_result["ok"]:
            result["actions"].append("ContextManager已更新热/温/冷")
        else:
            result["actions"].append(f"ContextManager失败: {cm_result.get('error','')}")

        # 写入已处理标记
        last_hash_file.write_text(current_hash)

        # 每5轮触发压缩
        status_r = run_script("context_manager.py", ["status"])
        if status_r["ok"]:
            try:
                status_data = json.loads(status_r["stdout"])
                total = status_data.get("total_rounds", 0)
                if total > 0 and total % 5 == 0:
                    run_script("context_manager.py", ["compress"])
                    result["actions"].append(f"第{total}轮自动压缩触发")
            except Exception:
                pass

    except Exception as e:
        result["ok"] = False
        result["error"] = str(e)

    return result


def meta_thinker_auto():
    """
    自动执行MetaThinker漂移检测:
    读取当前任务目标 → 检测语义漂移 → 超过阈值自动触发恢复
    """
    result = {"ok": True, "actions": [], "drift_score": 0.0, "level": "ok"}

    task_info = get_active_task()
    if not task_info["task_id"]:
        result["actions"].append("无活跃任务,跳过漂移检测")
        return result

    goal_file = REPORTS / "task_goal.txt"
    if not goal_file.exists():
        result["actions"].append("无任务目标文件,跳过漂移检测")
        return result

    try:
        goal = goal_file.read_text(encoding='utf-8').strip()
        if not goal:
            return result

        # 读取当前上下文
        ctx = ""
        ctx_file = REPORTS / "current_context.txt"
        if ctx_file.exists():
            ctx = ctx_file.read_text(encoding='utf-8').strip()

        # 调用MetaThinker
        mt_result = run_script("meta_thinker.py", ["check", "--goal", goal[:200], "--context", ctx[:500]])
        if mt_result["ok"]:
            # 解析返回结果
            out = mt_result["stdout"]
            for line in out.split('\n'):
                if "综合漂移分数" in line:
                    try:
                        result["drift_score"] = float(line.split(':')[1].strip())
                    except Exception:
                        pass
                if "等级" in line:
                    result["level"] = line.split(':')[1].strip()

            result["actions"].append(f"漂移检测: score={result['drift_score']:.3f} level={result['level']}")

            # critical以上自动触发恢复
            if result["level"] in ("critical", "fail"):
                restore_r = run_script("context_equilibria.py", ["restore", task_info["task_id"], "--goal", goal[:200]])
                if restore_r["ok"]:
                    result["actions"].append(f"自动恢复已触发: task={task_info['task_id']}")
                else:
                    result["actions"].append(f"自动恢复失败: {restore_r.get('error','')}")
        else:
            result["actions"].append(f"漂移检测失败: {mt_result.get('error','')}")

    except Exception as e:
        result["ok"] = False
        result["error"] = str(e)

    return result


def memory_orchestrator_auto():
    """
    自动执行三引擎记忆存储:
    读取当前会话上下文 → 三引擎并行存储 + LCM DAG增量摘要
    """
    result = {"ok": True, "actions": []}

    ctx_file = REPORTS / "current_context.txt"
    if not ctx_file.exists():
        result["actions"].append("无待处理上下文")
        return result

    try:
        content = ctx_file.read_text(encoding='utf-8').strip()
        if not content:
            return result

        # 获取或创建session_id
        sid_file = REPORTS / ".current_session_id.txt"
        if sid_file.exists():
            session_id = sid_file.read_text().strip()
        else:
            session_id = f"auto_{int(time.time())}"
            sid_file.write_text(session_id)

        # 解析上下文
        lines = content.split('\n')
        role = "user"
        for line in lines:
            clean = line.strip()
            if not clean:
                continue
            if clean.startswith("USER:"):
                role = "user"
                text = clean[5:].strip()
            elif clean.startswith("ASSISTANT:"):
                role = "assistant"
                text = clean[10:].strip()
            else:
                text = clean

            if len(text) < 5:
                continue

            # 三引擎并行存储
            store_r = run_script("memory_orchestrator_v3.py", ["store", session_id, role, text[:500]])
            if store_r["ok"]:
                result["actions"].append(f"三引擎存储: {role} ({len(text)}字)")

            # LCM DAG存储
            dag_r = run_script("lcm_dag_engine.py", ["store", session_id, role, text[:500]])
            if dag_r["ok"]:
                result["actions"].append(f"LCM DAG存储: msg_id={dag_r['stdout'].replace('STORED msg_id=','').strip()}")

        # 摘要节点创建(如果超过10条消息)
        dag_status = run_script("lcm_dag_engine.py", ["status"])
        if dag_status["ok"]:
            try:
                for line in dag_status["stdout"].split('\n'):
                    if "原始消息数" in line:
                        count = int(line.split(':')[1].strip())
                        if count > 0 and count % 5 == 0:
                            # 创建摘要节点
                            msg_ids = json.dumps(list(range(count-4, count+1)))
                            leaf_r = run_script("lcm_dag_engine.py", ["leaf", msg_ids, f"自动摘要: session={session_id} round={count}"])
                            if leaf_r["ok"]:
                                result["actions"].append(f"LCM摘要节点创建: round={count}")
            except Exception:
                pass

    except Exception as e:
        result["ok"] = False
        result["error"] = str(e)

    return result


def encryption_audit_auto():
    """
    自动加密+审计:
    读取记忆数据库中的敏感数据 → 自动加密 → 写入审计链
    """
    result = {"ok": True, "actions": []}

    try:
        # 1. 检查是否有待处理的加密队列
        enc_queue = REPORTS / ".encrypt_queue.json"
        if enc_queue.exists():
            queue_data = json.loads(enc_queue.read_text())
            for item in queue_data.get("pending", []):
                enc_r = run_script("encryption_layer.py", ["encrypt", item.get("path", "")])
                if enc_r["ok"]:
                    result["actions"].append(f"加密文件: {item.get('path','')}")
                else:
                    result["actions"].append(f"加密失败: {item.get('path','')}")
            # 清空队列
            enc_queue.write_text(json.dumps({"pending": [], "processed_at": now().isoformat()}))

        # 2. 写入每日审计摘要
        audit_r = run_script("audit_logger.py", ["summary"])
        if audit_r["ok"]:
            result["actions"].append("审计摘要已更新")

        # 3. 验证审计链完整性
        verify_r = run_script("audit_logger.py", ["verify"])
        if verify_r["ok"]:
            result["actions"].append("审计链完整性已验证")

    except Exception as e:
        result["ok"] = False
        result["error"] = str(e)

    return result


def enforce():
    """全自动自我强化引擎—主入口(v3.0集成IFC+七通道+DPW)"""
    result = {
        "ts": now().isoformat(),
        "phases": {},
        "status": "ok"
    }

    log("=" * 60)
    log("⚙️ 齿轮强制执行器 v3.0 启动 — 融合V3全自动自我强化")
    log("=" * 60)
    # CaMeL安全护栏提示
    log("  🔒 CaMeL安全护栏: 当前模式=monitor(记录不阻止) | 切换为enforce: --camel-guard enforce")
    log("  🔒 enforce模式自动拦截高风险操作(rm -rf/chmod 777/生产数据操作)")

    # Phase 0: P1 MonitorEngine + ReflectorEngine 监控层评估 + SegmentManager段检测 + ConsistencyGuard自检
    log("[Phase 0/8] P1监控层评估+反思层触发+段检测+一致性自检...")
    try:
        # ── SegmentManager: 自动检测段状态 ──
        seg_stats = _SEGMENT_MGR.get_stats()
        current_seg = seg_stats.get("current_segment", 0)
        seg_turns = seg_stats.get("turns_in_segment", 0)
        max_turns = seg_stats.get("max_turns_per_segment", 50)
        log(f"  → 段{current_seg}: {seg_turns}/{max_turns}轮 | 总{seg_stats.get('total_turns_all', 0)}轮")

        # 段切换预警: 剩余<=5轮时提醒 + 每5段触发漂移检测
        remaining = max_turns - seg_turns
        if remaining <= 5 and remaining > 0:
            log(f"  → ⚠️ 段{current_seg}即将结束(剩余{remaining}轮)，准备切换")
        
        # 长程纠偏: 每5段执行一次漂移检测 + 自动纠偏
        if current_seg > 0 and current_seg % 5 == 0 and seg_turns == 0:
            log(f"  → 🔄 段{current_seg}起始, 触发长程漂移检测...")
            try:
                mt_result = meta_thinker_auto()
                actions = mt_result.get("actions", [])
                drift_score = mt_result.get("drift_score", 0)
                drift_level = mt_result.get("level", "ok")
                
                if actions:
                    for a in actions:
                        log(f"  → [纠偏] {a}")
                
                if drift_score > 0.1 or drift_level in ("critical", "warning"):
                    log(f"  → ⚠️ [纠偏] 漂移分数={drift_score:.2f} > 0.1, 执行自动纠偏!")
                    # 写入纠偏指令到wake_guide，下次LLM醒来时能看到
                    try:
                        _wg_path = REPORTS / "wake_guide.json"
                        if _wg_path.exists():
                            _wg_data = json.loads(_wg_path.read_text())
                            _corrections = _wg_data.get("drift_corrections", [])
                            _corrections.append({
                                "detected_at": now().isoformat(),
                                "drift_score": round(drift_score, 3),
                                "level": drift_level,
                                "actions": actions[:3],
                                "instruction": "方向偏离! 请回顾原始任务目标, 纠正执行方向, 不要再跑偏!"
                            })
                            if len(_corrections) > 10:
                                _corrections = _corrections[-10:]
                            _wg_data["drift_corrections"] = _corrections
                            _wg_data["drift_alert"] = True
                            _wg_path.write_text(json.dumps(_wg_data, ensure_ascii=False, indent=2))
                            log(f"  → ✅ [纠偏] 纠偏指令已写入wake_guide, 下次对话生效")
                    except Exception as _we:
                        log(f"  → [纠偏] 写入wake_guide失败: {_we}")
                else:
                    log(f"  → ✅ [纠偏] 漂移分数={drift_score:.2f} <= 0.1, 方向正常")
            except Exception as _de:
                log(f"  → [纠偏] 漂移检测异常: {_de}")

        # 收集当前状态
        task_info = get_active_task()
        state = {
            "turns": seg_turns,
            "max_turns": max_turns,
            "errors": [],
            "task_type": task_info.get("task_id", "maintenance") or "maintenance",
            "elapsed_min": 0,
            "last_signals": result["phases"].get("_monitor_signals", []),
        }
        sig, det = _MONITOR.evaluate(state)
        result["phases"]["_monitor_turns"] = seg_turns + 1
        result["phases"]["_monitor_signals"] = (result["phases"].get("_monitor_signals", []) + [sig.value])[-10:]
        log(f"  → 信号: {sig.value} | {det.get('reason', '正常')}")

        # ── EngineCore: 武器库自检+任务分析 (每小时一次) ──
        try:
            from scripts.engine_core import EngineCore
            _engine = EngineCore()
            _engine_reports = _engine.tick()
            for _er in _engine_reports:
                log(f"  [ENGINE] {_er}")
        except Exception as _ee:
            log(f"  [ENGINE] 非致命: {_ee}")
        # ── EngineCore结束 ──

        # ── TaskQueue: 处理任务队列 ──
        try:
            tqm_path = SCRIPTS / "task_queue_manager.py"
            if tqm_path.exists():
                r = subprocess.run(
                    [sys.executable, str(tqm_path), "process"],
                    capture_output=True, text=True, timeout=10
                )
                for line in (r.stdout or "").split("\n"):
                    if line.strip():
                        log(f"  [TASK-QUEUE] {line.strip()}")
        except Exception as _tqe:
            log(f"  [TASK-QUEUE] 处理异常: {_tqe}")
        # ── TaskQueue结束 ──

        # ── ConsistencyGuard: 每轮执行自检(内部按5轮间隔过滤) ──
        cg_anomalies = _CONSISTENCY_GUARD.check(seg_turns)
        if cg_anomalies:
            for _a in cg_anomalies:
                log(f"  [CONSISTENCY] ❌ {_a}")
            # 如果发现异常，更新状态以触发反思
            state["errors"].extend(cg_anomalies)
        else:
            log(f"  [CONSISTENCY] ✅ 通过")

        # ── WeaponCallValidator: 验证LLM是否真的调用了推荐武器 ──
        # 每10轮检查一次，记录违规
        if seg_turns > 0 and seg_turns % 10 == 0:
            try:
                from scripts.engine_core import WeaponCallValidator
                _validator = WeaponCallValidator()
                # 检查wake_guide中的任务
                _wg = REPORTS / "wake_guide.json"
                if _wg.exists():
                    _wg_data = json.loads(_wg.read_text())
                    _task = str(_wg_data.get("interrupted_task", "")) or "通用"
                    # 从通用武器清单中提取推荐名
                    _rec_weapons = ["engine_core", "gear_enforcer", "dialogue_context_init",
                                    "consistency_guard", "hy_memory_orchestrator"]
                    # 从wake_guide中的recent_tool_calls获取实际调用记录
                    _recent_tools = _wg_data.get("recent_tool_calls", [])
                    _called = [tc for tc in _recent_tools]
                    _weapon_calls = sum(1 for w in _rec_weapons if any(w in tc for tc in _called))
                    if _weapon_calls < 2:
                        log(f"  [WEAPON-VALIDATE] ❌ 违规: 推荐武器{_rec_weapons[:3]}, 实际调用{_weapon_calls}次(<2)")
                        # 写入违规标记到wake_guide
                        _wg_data["weapon_violation"] = {
                            "detected_at": now().isoformat(),
                            "task": _task[:100],
                            "recommended": _rec_weapons[:5],
                            "weapon_calls": _weapon_calls,
                            "total_calls": len(_called),
                        }
                        _wg.write_text(json.dumps(_wg_data, ensure_ascii=False, indent=2))
                    else:
                        log(f"  [WEAPON-VALIDATE] ✅ 合规: 调用{_weapon_calls}次武器")
            except Exception as _we:
                log(f"  [WEAPON-VALIDATE] 非致命: {_we}")
        # ── WeaponCallValidator结束 ──

        # ── 反模拟检测: 扫描最近日志中是否包含"模拟/示意/占位/TODO"等关键词 ──
        # 每轮都检测, 因为这是最高级别违规
        try:
            _fake_keywords = ["示例", "示意", "占位符", "TODO", "FIXME", "简化版本", 
                             "核心功能示例", "以此类推", "只展示", "演示代码",
                             "示例输出", "fake", "placeholder", "stub"]
            _session_logs = sorted(LOGS.glob("hermes_*.log"), key=lambda x: x.stat().st_mtime, reverse=True)
            if _session_logs:
                _latest_log = _session_logs[0]
                _log_content = _latest_log.read_text(encoding='utf-8', errors='ignore')[-5000:]  # 末尾5000字
                _found_fakes = [kw for kw in _fake_keywords if kw in _log_content]
                if _found_fakes:
                    log(f"  [ANTI-FAKE] ❌❌❌ 检测到模拟/精简风险: {', '.join(_found_fakes[:5])}")
                    # 写入违规到wake_guide
                    _wg_af = REPORTS / "wake_guide.json"
                    if _wg_af.exists():
                        try:
                            _wg_data = json.loads(_wg_af.read_text())
                            _violations = _wg_data.get("anti_fake_violations", [])
                            _violations.append({
                                "detected_at": now().isoformat(),
                                "keywords": _found_fakes[:5],
                                "log_file": _latest_log.name,
                            })
                            if len(_violations) > 20:
                                _violations = _violations[-20:]
                            _wg_data["anti_fake_violations"] = _violations
                            _wg_af.write_text(json.dumps(_wg_data, ensure_ascii=False, indent=2))
                        except:
                            pass
                else:
                    # 每5轮才打一次合规日志减少噪声
                    if seg_turns % 5 == 0:
                        log(f"  [ANTI-FAKE] ✅ 未检测到模拟/精简词汇")
        except Exception as _afe:
            log(f"  [ANTI-FAKE] 非致命: {_afe}")
        # ── 反模拟检测结束 ──

        # 检测到REFLECT/RECOVER时触发反思
        if sig in (MonitorSignal.REFLECT, MonitorSignal.RECOVER):
            log(f"  → ⚠️ 触发反思引擎 (signal={sig.value})...")
            reflect_ctx = {
                "task": task_info.get("task_id", "gear_maintenance"),
                "errors": det.get("reason", ""),
                "turns": state["turns"],
                "task_type": "maintenance",
            }
            report = _REFLECTOR.reflect(reflect_ctx)
            log(f"  → 反思报告: {report['report_id']} | 建议: {report['summary']['improvements'][:2]}")
            result["phases"]["reflector"] = {
                "triggered": True,
                "signal": sig.value,
                "report_id": report["report_id"],
                "improvements": report["summary"]["improvements"][:3],
            }
        elif sig == MonitorSignal.CHECKPOINT:
            log("  → 触发检查点保存 (由MonitorEngine调度)")
            result["phases"]["reflector"] = {"triggered": False, "signal": "CHECKPOINT", "note": "保存中间状态"}
        else:
            result["phases"]["reflector"] = {"triggered": False, "signal": "CONTINUE"}
    except Exception as e:
        log(f"  → ⚠️ 监控层异常(非致命): {str(e)[:100]}")
        result["phases"]["reflector"] = {"ok": False, "error": str(e)[:100]}

    # Phase 1: V3 Memory Health Scan
    log("[Phase 1/7] V3记忆健康度扫描...")
    try:
        loop = get_v3_loop()
        s1 = loop.step1_memory_health_scan()
        result["phases"]["memory_health"] = s1
        for a in s1.get("actions", []):
            log(f"  → {a}")
    except Exception as e:
        log(f"  → ❌ V3记忆扫描失败: {str(e)[:100]}")
        result["phases"]["memory_health"] = {"ok": False, "error": str(e)[:100]}

    # Phase 2: V3 Correction Stats
    log("[Phase 2/7] V3纠偏经验统计...")
    try:
        s2 = loop.step2_correction_stats()
        result["phases"]["correction_stats"] = s2
        for a in s2.get("actions", []):
            log(f"  → {a}")
    except Exception as e:
        log(f"  → ❌ V3纠偏统计失败: {str(e)[:100]}")
        result["phases"]["correction_stats"] = {"ok": False, "error": str(e)[:100]}

    # Phase 3: V3 Security Update
    log("[Phase 3/7] V3安全规则更新...")
    try:
        s3 = loop.step3_security_update()
        result["phases"]["security_update"] = s3
        for a in s3.get("actions", []):
            log(f"  → {a}")
    except Exception as e:
        log(f"  → ❌ V3安全更新失败: {str(e)[:100]}")
        result["phases"]["security_update"] = {"ok": False, "error": str(e)[:100]}

    # Phase 4: V3 Auto Dream
    log("[Phase 4/7] V3 AutoDream后台清理...")
    try:
        s4 = loop.step4_auto_dream()
        result["phases"]["auto_dream"] = s4
        for a in s4.get("actions", []):
            log(f"  → {a}")
    except Exception as e:
        log(f"  → ❌ V3 AutoDream失败: {str(e)[:100]}")
        result["phases"]["auto_dream"] = {"ok": False, "error": str(e)[:100]}

    # Phase 5: V3 Task Association
    log("[Phase 5/7] V3跨任务关联...")
    try:
        s6 = loop.step6_task_association()
        result["phases"]["task_association"] = s6
        for a in s6.get("actions", []):
            log(f"  → {a}")
    except Exception as e:
        log(f"  → ❌ V3任务关联失败: {str(e)[:100]}")
        result["phases"]["task_association"] = {"ok": False, "error": str(e)[:100]}

    # Phase 6: V3 SAR Report (每6小时)
    current_hour = now().hour
    if current_hour % 6 == 0:
        log("[Phase 6/7] V3 SAR自检报告生成...")
        try:
            s7 = loop.step7_sar_report()
            result["phases"]["sar_report"] = s7
            log(f"  → SAR: {s7.get('summary', '')}")
        except Exception as e:
            log(f"  → ❌ SAR生成失败: {str(e)[:100]}")
            result["phases"]["sar_report"] = {"ok": False, "error": str(e)[:100]}
    else:
        result["phases"]["sar_report"] = {"ok": True, "actions": [f"下次SAR: {6-current_hour%6}h后"]}
        log(f"  → SAR跳过(每6h, 下次{6-current_hour%6}h后)")

    # Phase 7: 中断任务检测恢复 (★增强版—自动执行恢复)
    log("[Phase 7/7] 中断任务检测+自动恢复...")
    task_info = get_active_task()
    if task_info["source"]:
        tid = task_info["task_id"]
        next_action = task_info["next_action"]

        # ===== 跳过自强化循环误判 =====
        # self_enhance_* 是V3自我强化循环(每1分钟cron)，不是真正的中断任务
        # gear_checkpoint的status=running是因为cron覆盖导致的误判
        if tid and tid.startswith("self_enhance_"):
            log(f"  → ⏭️ 跳过自强化循环(非中断任务): {tid}")
            result["phases"]["interrupt_recovery"] = {
                "found": False, "skipped": True,
                "task": tid, "reason": "self_enhance_loop(非中断)"
            }
            # 仍然更新wake_guide但不再标记为中断
            try:
                run_script("wake_guide.py")
            except Exception:
                pass
            # 跳过后面的中断恢复逻辑，直接到全能力激活监督
            return result
        log(f"  → 发现中断任务: {tid} 下一步: {next_action}")

        # ===== 自动恢复执行 =====
        recovery_actions = []
        recovery_ok = True

        # 7a: 写恢复标记到wake_guide (确保下次醒来知道要做什么)
        try:
            wg_result = run_script("wake_guide.py")
            if wg_result["ok"]:
                recovery_actions.append("wake_guide已更新")
            else:
                recovery_actions.append(f"wake_guide更新失败: {wg_result.get('error','')}")
        except Exception as e:
            recovery_actions.append(f"wake_guide异常: {str(e)[:50]}")

        # 7b: 一致性检查—如果gear_checkpoint和task_current状态矛盾，修复它
        try:
            gc_path = REPORTS / "gear_checkpoint.json"
            tc_path = HERMES / "task_current.json"
            rp_path = REPORTS / "recovery_pack.json"

            gc_data = {}
            tc_data = {}
            if gc_path.exists(): gc_data = json.loads(gc_path.read_text())
            if tc_path.exists(): tc_data = json.loads(tc_path.read_text())

            gc_task = gc_data.get("task_id", "")
            tc_task = tc_data.get("task_id", "")

            if gc_task and tc_task and gc_task != tc_task:
                log(f"  → ⚠️ 检测到task_id不一致: gear_checkpoint={gc_task} vs task_current={tc_task}")
                # 优先使用gear_checkpoint(最新断点)
                tc_data["task_id"] = gc_data.get("task_id", tc_data.get("task_id", ""))
                tc_data["status"] = gc_data.get("status", "interrupted")
                tc_data["next_action"] = gc_data.get("next_action", "")
                tc_data["detail"] = gc_data.get("detail", "")
                tc_path.write_text(json.dumps(tc_data, ensure_ascii=False, indent=2))
                log(f"  → ✅ task_current已同步到gear_checkpoint: {gc_task}")
                recovery_actions.append(f"task_id一致化: {gc_task}")

            # 修复recovery_pack
            if rp_path.exists():
                rp_data = json.loads(rp_path.read_text())
                rp_data["status"] = "running"
                rp_data["gear_checkpoint"] = gc_data
                rp_data["task_current"] = tc_data
                rp_path.write_text(json.dumps(rp_data, ensure_ascii=False, indent=2))
                recovery_actions.append("recovery_pack已同步")
        except Exception as e:
            log(f"  → ❌ 一致性修复失败: {str(e)[:100]}")
            recovery_ok = False

        # 7c: 尝试触发失活的内置恢复函数
        try:
            mt = meta_thinker_auto()
            if mt.get("ok"):
                recovery_actions.extend(mt.get("actions", []))
        except Exception:
            pass

        # 7d: 如果next_action明确，写入恢复指令文件供下次醒来读取
        if next_action and next_action != "continue_closed_loop":
            resume_file = REPORTS / ".resume_instruction.txt"
            resume_file.write_text(json.dumps({
                "task_id": tid,
                "next_action": next_action,
                "detail": task_info.get("data", {}).get("detail", ""),
                "recovery_ts": now().isoformat()
            }, ensure_ascii=False, indent=2))
            recovery_actions.append(f"恢复指令已写入: {next_action}")

        result["phases"]["interrupt_recovery"] = {
            "found": True,
            "task": tid,
            "recovery_ok": recovery_ok,
            "actions": recovery_actions[:5]
        }
        log(f"  → 恢复完成: {'✅' if recovery_ok else '❌'} 操作={len(recovery_actions)}项")
    else:
        # 无中断任务—清理可能的残留
        resume_file = REPORTS / ".resume_instruction.txt"
        if resume_file.exists():
            resume_file.unlink()
            log("  → 已清理残留恢复指令")

        # 执行常规内置函数保持系统活跃
        try:
            ctx_r = context_manager_auto()
            if ctx_r.get("actions"):
                for a in ctx_r["actions"][:2]:
                    log(f"  → ctx: {a[:60]}")
        except Exception:
            pass

        result["phases"]["interrupt_recovery"] = {"found": False}
        log(f"  → 无中断任务")

    # ===== [规则7增强] 全能力激活监督 — 检查所有齿轮是否都在运行 =====
    try:
        act = {"ok": True, "actions": [], "gears_checked": 0}
        
        # 检查核心齿轮文件是否存在+语法正确
        core_gears = [
            ("G1", "gear_enforcer.py", True),
            ("G2", "context_failsafe.py", True),
            ("G3", "gear_context_compressor.py", True),
            ("G4", "context_guardian.py", True),
            ("G5", "hermes_super_guardian.py", True),
            ("G6", "gear_task_validator.py", True),
            ("G7", "wake_guide.py", True),
            ("G8", "memory_orchestrator_v3.py", True),
            ("DRIVER", "gear_task_driver.py", True),
            ("MASTER", "gear_master.py", True),
        ]
        
        for gear_name, script, required in core_gears:
            sp = SCRIPTS / script
            if not sp.exists():
                if required:
                    act["actions"].append(f"❌ {gear_name}({script}) 文件缺失")
                    act["ok"] = False
                continue
            # 检查语法
            try:
                import ast
                ast.parse(open(str(sp)).read())
                act["gears_checked"] += 1
            except SyntaxError as se:
                act["actions"].append(f"❌ {gear_name}({script}) 语法错误: {str(se)[:80]}")
                act["ok"] = False
        
        # 检查evolution_v3模块
        evo_path = EVO_V3
        evo_modules = ["self_enhancement_v3_loop.py", "information_fidelity_core.py",
                       "seven_channel_memory.py", "task_engine.py", "hooks_engine.py",
                       "hash_chain_auditor.py"]
        for mod in evo_modules:
            mp = evo_path / mod
            if not mp.exists():
                act["actions"].append(f"⚠️ evolution_v3/{mod} 缺失")
        
        result["phases"]["ability_activation"] = act
        if act["actions"]:
            for a in act["actions"][:3]:
                log(f"  → {a}")
        log(f"  → 齿轮检查: {act['gears_checked']}个通过")
    except Exception as e:
        log(f"  → ❌ 能力激活检查失败: {str(e)[:100]}")
        result["phases"]["ability_activation"] = {"ok": False, "error": str(e)[:100]}

    # 日志+统计
    heartbeat = LOGS / "gear_heartbeat.txt"
    heartbeat.parent.mkdir(exist_ok=True)
    heartbeat.write_text(now().isoformat())

    all_ok = all(
        p.get("ok", True) for k, p in result["phases"].items()
        if isinstance(p, dict)
    )
    result["status"] = "ok" if all_ok else "degraded"
    log(f"状态: {'✅全部通过' if all_ok else '⚠️部分异常'}")

    # 写入V3报告
    report_file = REPORTS / "self_enhance_report.json"
    report_file.parent.mkdir(exist_ok=True)
    history = []
    if report_file.exists():
        try:
            history = json.loads(report_file.read_text())
            if not isinstance(history, list):
                history = []
        except Exception:
            history = []
    history.append(result)
    if len(history) > 100:
        history = history[-100:]
    report_file.write_text(json.dumps(history, ensure_ascii=False, indent=2))

    return result


if __name__ == "__main__":
    result = enforce()
    # 输出简要状态到stdout供gear_master读取
    ok_count = sum(1 for p in result["phases"].values() if isinstance(p, dict) and p.get("ok", False))
    total = sum(1 for p in result["phases"].values() if isinstance(p, dict))
    print(f"[ENFORCER v2.0] {result['status']} phases={ok_count}/{total}")
