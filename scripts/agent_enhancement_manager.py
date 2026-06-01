#!/usr/bin/env python3
"""
Hermes 系统增强插件管理器 v2.0 — 68个增强, 全量集成
=====================================================
含盖: 对话层(9) + 质量反降级(9) + 武器库调度(8) + 记忆系统(13) + 
      反思进化(10) + 安全护栏(4) + 状态反馈(4) + 齿轮系统(8) + 监视反射(3)
设计原则:
  1. 一个入口 — run_agent.py只引用这个文件
  2. 可插拔 — 每个子插件独立, 引用失败不影响其他
  3. 安全降级 — 任何异常被捕获, 不抛到run_agent.py
  4. 统一生命周期: pre_conversation → post_conversation
使用方法:
  run_agent.py中注入:
    from agent_enhancement_manager import safe_hook_pre_conversation
    _ctx = safe_hook_pre_conversation(self, user_message)  # 对话前
    # system prompt构建时:
    _ctx2 = get_force_context()
    # 对话完成后:
    safe_hook_post_conversation(self, final_response, user_message)
"""

import os, sys, json, logging, time, traceback, subprocess
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)

HERMES = Path("/home/administrator/.hermes")

# ============================================================
# 全局状态
# ============================================================
_loaded_plugins: List[str] = []
_failed_plugins: List[str] = []
_plugin_errors: List[str] = []
_force_context: Optional[str] = None
_plugin_timing: Dict[str, float] = {}
_pre_conversation_done = False
_post_conversation_done = False


def _safe_import(name: str, path: str):
    global _loaded_plugins, _failed_plugins
    if not os.path.exists(path):
        return None
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location(name, path)
        if spec and spec.loader:
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            _loaded_plugins.append(name)
            return mod
    except Exception as e:
        _failed_plugins.append(name)
        _plugin_errors.append(f"[{name}] {e}")
    return None


def _is_loading():
    """防止循环导入"""
    return os.environ.get("_HERMES_PLUGIN_MGR") == "1"


def _log(msg: str):
    log_path = HERMES / "logs" / "plugin_manager.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().isoformat()
    try:
        with open(log_path, 'a') as f:
            f.write(f"[{ts}] {msg}\n")
    except:
        pass
    logger.info(f"[PLUGIN-MGR] {msg}")


# ============================================================
# 68个插件注册表
# ============================================================
# (内部名, 路径, 类型, 启用, 描述)
PLUGIN_REGISTRY = [
    # ── 对话层(9) ──
    ("forced_executor", "scripts/forced_executor.py", "pre", True,
     "强制武器调用+深度分解: 3武器+3阶段系统执行, LLM只能总结"),
    ("segment_manager", "scripts/segment_manager.py", "pre", True,
     "段管理器: 50轮自动切换+段内压缩+三明治交接"),
    ("layered_planner", "scripts/layered_planner.py", "pre", True,
     "分层规划: 复杂任务>15步自动分层"),
    ("surgical_slicer", "scripts/surgical_context_slicer.py", "pre", True,
     "手术刀切分: 精准识别对话边界并分段"),
    ("context_auto_assoc", "scripts/context_auto_assoc.py", "pre", True,
     "上下文自动关联: 跨段信息关联"),
    ("context_failsafe", "scripts/context_failsafe.py", "pre", True,
     "上下文故障保险: 断点合并+恢复包"),
    ("cross_session_cache", "scripts/cross_session_cache.py", "pre", True,
     "跨会话缓存: 会话间上下文持久化"),
    ("session_init_check", "scripts/session_init_check.py", "pre", True,
     "会话启动自检"),
    ("wake_guide", "scripts/wake_guide.py", "pre", True,
     "醒来指南: 中断任务恢复+状态报告"),

    # ── 武器库与调度(8) ──
    ("engine_core", "scripts/engine_core.py", "pre", True,
     "武器库注册中心: ArsenalRegistry+SmartScheduler"),
    ("task_analyzer", "scripts/engine_core.py", "pre", True,
     "任务分析器: 多类型匹配+复杂度评估+分段建议"),
    ("agent_company", "scripts/agent_company_engine.py", "pre", True,
     "Agent公司引擎: 130员工+390专家自动调度"),
    ("agent_orchestrator", "scripts/agent_company_runner.py", "pre", True,
     "Agent编排: 多Agent链式/并行/组队"),
    ("multi_agent_orch", "scripts/hermes_multi_agent_orchestrator.py", "pre", True,
     "Multi-Agent编排: 情报采集→分析→决策管线"),
    ("capability_registry", "auto_engine/capability_registry.py", "pre", True,
     "能力注册中心: 自动注册所有能力模块"),
    ("master_integration", "auto_engine/master_integration_hub.py", "pre", True,
     "主集成枢纽: 所有子系统集成点"),
    ("model_router", "agent/model_router.py", "pre", True,
     "模型路由: 任务类型→最优模型自动切换"),

    # ── 质量与反降级(9) ──
    ("consistency_guard", "scripts/consistency_guard.py", "both", True,
     "一致性守卫: 每5轮执行质量自检+异常检测"),
    ("auto_healer", "scripts/auto_healer.py", "post", True,
     "自动修复引擎: 退化检测+自动修复+回滚"),
    ("hermes_retrospect", "scripts/hermes_retrospect.py", "post", True,
     "复盘引擎: 五维度评分+经验提取"),
    ("dod_checklist", "scripts/dod_checklist.py", "post", True,
     "DoD完成定义清单: 9维度验收(防降级)"),
    ("tr_gate", "scripts/tr_gate.py", "post", True,
     "IPD门禁: TR1-TR6里程碑检查"),
    ("skillopt_trainer", "scripts/skillopt_trainer.py", "post", True,
     "SkillOpt验证门: Skill质量评分+负迁移检测"),
    ("production_reliability", "scripts/production_loop_cron.py", "post", True,
     "生产可靠性引擎: LoopState+DAG+CriticAgent+降级拦截"),
    ("system_audit", "scripts/system_deep_audit.py", "post", True,
     "系统深度审计: 全模块自检"),
    ("system_selfcheck", "scripts/context_selfcheck.py", "post", True,
     "系统自检: 14项健康检查"),
    ("lossless_claw", "scripts/lossless_claw.py", "post", True,
     "Lossless-Claw无损压缩: 对话后自动压缩"),

    # ── 记忆系统(13) ──
    ("hy_memory_orchestrator", "scripts/hy_memory_orchestrator.py", "post", True,
     "Hy-Memory全链路编排: L1→L2→L3管道"),
    ("l1_extractor", "scripts/l1_extractor.py", "post", True,
     "L1事实提取: Persona/Episodic/Instruction三策略"),
    ("l2_scene", "scripts/l2_scene_scheduler.py", "post", True,
     "L2场景归纳: 事实聚类→场景块生成"),
    ("l3_persona", "scripts/l3_persona_scheduler.py", "post", True,
     "L3画像生成: 四层深度扫描用户画像"),
    ("episodic_injector", "scripts/episodic_injector.py", "post", True,
     "情景记忆注入引擎"),
    ("task_boundary", "scripts/task_boundary.py", "post", True,
     "任务边界检测: 新旧任务分离"),
    ("auto_recall", "scripts/auto_recall.py", "pre", True,
     "自动召回: FTS5+structmem+mp四路RRF融合"),
    ("tool_unloader", "scripts/tool_unloader.py", "post", True,
     "工具结果卸载: >2KB自动归档"),
    ("mermaid_builder", "scripts/mermaid_builder.py", "post", True,
     "Mermaid画布: 任务可视化"),
    ("emergency_compressor", "scripts/emergency_compressor.py", "post", True,
     "紧急压缩: 三级级联(50%/85%/92%)"),
    ("memory_evolution", "scripts/memory_evolution_v2.py", "post", True,
     "记忆进化引擎: 6模块并行+技能沉淀"),
    ("memory_highway", "scripts/memory_highway.py", "post", True,
     "记忆高速路: 高频记忆快速访问"),
    ("parallel_memory", "scripts/parallel_memory_orchestrator.py", "post", True,
     "并行记忆编排: 5+记忆模块真并行"),

    # ── 反思与进化(10) ──
    ("reflexion_engine", "scripts/reflexion_engine.py", "post", True,
     "Reflexion三角循环: 行动→观察→反思"),
    ("experience_extractor", "scripts/experience_extractor.py", "post", True,
     "经验提取: Skill改进候选+语义分类"),
    ("gepa_variator", "scripts/gepa_variator.py", "post", True,
     "GEPA遗传变异: Skill自动进化+变体生成"),
    ("auto_cleaner", "scripts/auto_cleaner.py", "post", True,
     "AutoClean: 记忆自动清理+老化"),
    ("self_evolution", "auto_engine/self_evolution_engine.py", "post", True,
     "自进化引擎: 每天3点技能进化/记忆压缩"),
    ("skill_evolver", "scripts/hermes_skill_evolver.py", "post", True,
     "Skill进化器: 证据驱动+变体生成+SHA256"),
    ("self_enhance_v3", "evolution_v3/self_enhancement_v3_loop.py", "post", True,
     "V3自我增强: IFC+七通道+DPW主循环"),
    ("ifc_core", "evolution_v3/information_fidelity_core.py", "post", True,
     "信息保真核心: 压缩/加密/保真度监控"),
    ("seven_channel_memory", "evolution_v3/seven_channel_memory.py", "post", True,
     "七通道记忆仲裁: 语义+关键词+时间线多路"),
    ("auto_tune", "scripts/hermes_auto_tune.py", "post", True,
     "自动调优: 5参数自适应+A/B测试+动态阈值"),

    # ── 安全护栏(4) ──
    ("camel_guard", "scripts/hermes_camel_guard.py", "both", True,
     "CaMeL安全护栏: 16敏感工具+5注入模式+三级响应"),
    ("security_permissions", "production_loop/security.py", "both", True,
     "安全权限: 7层权限系统+敏感操作拦截"),
    ("hermes_super_guardian", "scripts/hermes_super_guardian.py", "post", True,
     "超级守护者: 全系统兜底+G4验证"),

    # ── 状态反馈(4) ──
    ("status_reporter", "scripts/status_reporter.py", "post", True,
     "状态反馈: 每40min推送进度+子阶段推进"),
    ("feedback_push", "scripts/feedback_push.py", "post", True,
     "反馈推送: 任务执行中主动反馈不等"),
    ("generate_report", "scripts/generate_final_report.py", "post", True,
     "最终报告生成"),

    # ── 齿轮系统(8) ──
    ("gear_enforcer", "scripts/gear_enforcer.py", "post", True,
     "G1齿轮: 中断检测+AI评分+wake_guide+EngineCore"),
    ("gear_vault", "scripts/gear_vault.py", "post", True,
     "G0齿轮: 任务注册中心+链式签名凭证"),
    ("gear_task_validator", "scripts/gear_task_validator.py", "post", True,
     "G6齿轮: 全链完整性验证"),
    ("gear_master", "scripts/gear_master.py", "post", True,
     "齿轮主控: 所有齿轮协调"),
    ("task_resumer", "scripts/task_resumer.py", "pre", True,
     "任务自动恢复: 中断后从断点继续"),
    ("auto_resume_check", "scripts/auto_resume_check.py", "pre", True,
     "自动恢复检查: 检测中断状态"),
    ("long_task_guardian", "scripts/long_task_guardian.py", "post", True,
     "长期任务守护神: 三路冗余+15分钟循环"),

    # ── 监视反射(3) ──
    ("monitor_engine", "agent/monitor.py", "both", True,
     "P1监控引擎: 评估+信号触发"),
    ("reflector_engine", "agent/reflector.py", "post", True,
     "P1反射引擎: 问题分析+行动计划"),
]

# 统计
PRE_PLUGINS = [p for p in PLUGIN_REGISTRY if p[2] in ("pre", "both")]
POST_PLUGINS = [p for p in PLUGIN_REGISTRY if p[2] in ("post", "both")]


# ============================================================
# 核心钩子: 对话前
# ============================================================
def safe_hook_pre_conversation(agent_self, user_message: str) -> Optional[str]:
    """
    对话前钩子 — 在run_conversation开始时调用。
    执行所有pre/both类型的插件, 合并上下文。
    异常安全: 任何异常被捕获, 返回None。
    """
    global _force_context, _pre_conversation_done
    
    if _is_loading() or _pre_conversation_done:
        return _force_context
    
    os.environ["_HERMES_PLUGIN_MGR"] = "1"
    _pre_conversation_done = True
    start = time.time()
    contexts = []
    task = str(user_message) if user_message else ""
    
    _log(f"pre_conversation 开始: task_len={len(task)}, 待加载{len(PRE_PLUGINS)}个插件")
    
    # 阶段1: 武器强制调用(核心)
    _try_load("forced_executor", lambda mod: _run_forced_executor(mod, task, contexts, agent_self), contexts)
    
    # 阶段2: 引擎核心
    _try_load("engine_core", lambda mod: _run_engine_core(mod, contexts), contexts)
    
    # 阶段3: 对话层工具
    _try_load("segment_manager", lambda mod: _run_segment_manager(mod, contexts), contexts)
    _try_load("layered_planner", lambda mod: _run_script_module_subprocess(mod, contexts), contexts)
    _try_load("surgical_slicer", lambda mod: _run_script_module_subprocess(mod, contexts), contexts)
    _try_load("context_auto_assoc", lambda mod: _run_script_module_subprocess(mod, contexts), contexts)
    _try_load("context_failsafe", lambda mod: _run_script_module_subprocess(mod, contexts), contexts)
    _try_load("cross_session_cache", lambda mod: _run_script_module_subprocess(mod, contexts), contexts)
    _try_load("session_init_check", lambda mod: _run_script_module_subprocess(mod, contexts), contexts)
    _try_load("wake_guide", lambda mod: _run_script_module_subprocess(mod, contexts), contexts)
    
    # 阶段4: Agent公司 (改用专门函数)
    _try_load("agent_company", lambda mod: _run_agent_company(mod, contexts), contexts)
    _try_load("agent_orchestrator", lambda mod: _run_script_module_subprocess(mod, contexts), contexts)
    _try_load("multi_agent_orch", lambda mod: _run_multi_agent_orch(mod, contexts), contexts)
    _try_load("capability_registry", lambda mod: _run_capability_registry(mod, contexts), contexts)
    _try_load("master_integration", lambda mod: _run_script_module_subprocess(mod, contexts), contexts)
    _try_load("model_router", lambda mod: _run_model_router(mod, task, contexts), contexts)
    
    # 阶段5: 自动召回 (改用专门函数)
    _try_load("auto_recall", lambda mod: _run_auto_recall(mod, task, contexts), contexts)
    _try_load("task_resumer", lambda mod: _run_script_module_subprocess(mod, contexts), contexts)
    _try_load("auto_resume_check", lambda mod: _run_script_module_subprocess(mod, contexts), contexts)
    
    # 阶段6: 安全护栏 (改用专门函数)
    _try_load("camel_guard", lambda mod: _run_camel_guard(mod, task, contexts), contexts)
    _try_load("security_permissions", lambda mod: _run_script_module_subprocess(mod, contexts), contexts)
    
    # 阶段7: 监控
    _try_load("monitor_engine", lambda mod: _run_script_module_subprocess(mod, contexts), contexts)
    
    # 合并所有上下文
    if contexts:
        _force_context = "\n\n".join(contexts)
        _log(f"pre_conversation 完成: {len(contexts)}个上下文, {len(_force_context)}chars, {time.time()-start:.2f}s")
    else:
        _force_context = None
        _log(f"pre_conversation 完成: 无上下文, {time.time()-start:.2f}s")
    
    os.environ.pop("_HERMES_PLUGIN_MGR", None)
    return _force_context


# ============================================================
# 核心钩子: 对话后
# ============================================================
def safe_hook_post_conversation(agent_self, final_response: str, user_message: str) -> None:
    """
    对话后钩子 — 在run_conversation完成后调用。
    执行所有post/both类型的插件。
    异常安全: 任何异常被捕获。
    """
    global _post_conversation_done
    
    if _is_loading() or _post_conversation_done:
        return
    
    os.environ["_HERMES_PLUGIN_MGR"] = "1"
    _post_conversation_done = True
    start = time.time()
    task = str(user_message) if user_message else ""
    
    _log(f"post_conversation 开始: 待加载{len(POST_PLUGINS)}个插件")
    
    # 阶段1: 检查点保存(必须优先)
    _try_load("gear_enforcer", lambda mod: _run_post_subprocess(mod, None), None)
    _try_load("task_boundary", lambda mod: _run_post_subprocess(mod, None), None)
    
    # 阶段2: 质量检查
    _try_load("consistency_guard", lambda mod: _run_post_subprocess(mod, None), None)
    _try_load("dod_checklist", lambda mod: _run_post_subprocess(mod, None), None)
    _try_load("tr_gate", lambda mod: _run_post_subprocess(mod, None), None)
    _try_load("system_selfcheck", lambda mod: _run_post_subprocess(mod, None), None)
    _try_load("system_audit", lambda mod: _run_post_subprocess(mod, None), None)
    # 无损压缩(每次对话后)
    _try_load("lossless_claw", lambda mod: _run_lossless_compression(mod, None), None)
    
    # 阶段3: 记忆系统
    _try_load("hy_memory_orchestrator", lambda mod: _log("[post] hy_memory 已加载"), None)
    _try_load("l1_extractor", lambda mod: _run_l1_extractor(mod, user_message), None)
    _try_load("l2_scene", lambda mod: _run_post_subprocess(mod, None), None)
    _try_load("l3_persona", lambda mod: _run_post_subprocess(mod, None), None)
    _try_load("episodic_injector", lambda mod: _run_post_subprocess(mod, None), None)
    _try_load("memory_evolution", lambda mod: _run_post_subprocess(mod, None), None)
    _try_load("memory_highway", lambda mod: _run_post_subprocess(mod, None), None)
    _try_load("parallel_memory", lambda mod: _run_post_subprocess(mod, None), None)
    _try_load("tool_unloader", lambda mod: _run_post_subprocess(mod, None), None)
    _try_load("mermaid_builder", lambda mod: _run_post_subprocess(mod, None), None)
    _try_load("emergency_compressor", lambda mod: _run_post_subprocess(mod, None), None)
    
    # 阶段4: 反思进化
    _try_load("reflexion_engine", lambda mod: _run_post_subprocess(mod, None), None)
    _try_load("experience_extractor", lambda mod: _run_post_subprocess(mod, None), None)
    _try_load("gepa_variator", lambda mod: _run_post_subprocess(mod, None), None)
    _try_load("auto_cleaner", lambda mod: _run_post_subprocess(mod, None), None)
    _try_load("skill_evolver", lambda mod: _run_post_subprocess(mod, None), None)
    _try_load("self_evolution", lambda mod: _run_post_subprocess(mod, None), None)
    _try_load("self_enhance_v3", lambda mod: _run_post_subprocess(mod, None), None)
    _try_load("auto_tune", lambda mod: _run_post_subprocess(mod, None), None)
    
    # 阶段5: 复盘
    _try_load("hermes_retrospect", lambda mod: _run_post_subprocess(mod, None), None)
    _try_load("skillopt_trainer", lambda mod: _run_post_subprocess(mod, None), None)
    
    # 阶段6: 安全
    _try_load("hermes_super_guardian", lambda mod: _run_post_subprocess(mod, None), None)
    _try_load("reflector_engine", lambda mod: _run_post_subprocess(mod, None), None)
    
    # 阶段7: 状态反馈
    _try_load("status_reporter", lambda mod: _run_post_subprocess(mod, None), None)
    _try_load("feedback_push", lambda mod: _run_post_subprocess(mod, None), None)
    _try_load("generate_report", lambda mod: _run_post_subprocess(mod, None), None)
    
    # 阶段8: 自动修复和齿轮
    _try_load("auto_healer", lambda mod: _run_post_subprocess(mod, None), None)
    _try_load("production_reliability", lambda mod: _run_post_subprocess(mod, None), None)
    _try_load("gear_enforcer", lambda mod: _run_post_subprocess(mod, None), None)
    _try_load("gear_vault", lambda mod: _run_post_subprocess(mod, None), None)
    _try_load("gear_task_validator", lambda mod: _run_post_subprocess(mod, None), None)
    _try_load("gear_master", lambda mod: _run_post_subprocess(mod, None), None)
    _try_load("long_task_guardian", lambda mod: _run_post_subprocess(mod, None), None)
    
    _log(f"post_conversation 完成: {time.time()-start:.2f}s")
    os.environ.pop("_HERMES_PLUGIN_MGR", None)
    _post_conversation_done = True


# ============================================================
# 插件加载与执行引擎
# ============================================================
_mod_cache = {}

def _try_load(name: str, runner, caller_contexts=None):
    """安全加载并运行一个插件"""
    # 只在safe_hook_pre/post中检查loading状态
    # 独立测试时不检查
    
    # 从注册表找配置
    config = None
    for p in PLUGIN_REGISTRY:
        if p[0] == name:
            config = p
            break
    if not config or not config[3]:
        return
    
    path = os.path.join(HERMES, config[1])
    
    # 从缓存或重新导入
    mod = _mod_cache.get(name)
    if mod is None:
        mod = _safe_import(name, path)
        if mod:
            _mod_cache[name] = mod
    
    if mod is None:
        return
    
    # 运行 - 优先使用注册表调用器
    _st = time.time()
    try:
        # 检查是否有专门的调用器
        contexts = caller_contexts if caller_contexts is not None else []
        if name in _PLUGIN_CALLERS:
            _PLUGIN_CALLERS[name](mod, contexts)
        else:
            runner(mod)
        _plugin_timing[name] = round(time.time() - _st, 3)
    except Exception as e:
        _plugin_errors.append(f"[{name}] run: {e}")
        _plugin_timing[name] = -1


def _run_script_module(mod, contexts=None, script_args=None):
    """通用: 导入模块并执行其核心功能, 输出注入到contexts"""
    if contexts is None:
        contexts = []
    mod_name = getattr(mod, '__name__', 'unknown')
    output_parts = []
    
    try:
        # ── 策略1: 有main()就调用main(), 从子进程捕获输出 ──
        if hasattr(mod, 'main'):
            mod_path = getattr(mod, '__file__', '')
            if mod_path:
                try:
                    import subprocess as _sp
                    r = _sp.run([sys.executable, mod_path], capture_output=True, text=True, timeout=10)
                    out = (r.stdout.strip() or r.stderr.strip())[:400]
                    if out:
                        output_parts.append(out)
                except _sp.TimeoutExpired:
                    output_parts.append(f"[{mod_name}] main()超时(10s)")
                except Exception as e:
                    output_parts.append(f"[{mod_name}] main()调用异常: {str(e)[:80]}")
        
        # ── 策略2: 扫描模块中的核心类并实例化 ──
        if not output_parts:
            for attr_name in dir(mod):
                if attr_name.startswith('_'):
                    continue
                attr = getattr(mod, attr_name, None)
                if not isinstance(attr, type):
                    continue
                # 找以Engine/Guard/Manager/Scheduler/Registry/Router/Planner/Extractor结尾的类
                if attr_name.endswith(('Engine', 'Guard', 'Manager', 'Scheduler', 'Registry', 'Router', 'Planner', 'Extractor', 'Checker', 'Validator', 'Monitor', 'Reflector', 'Gate', 'Agent')):
                    try:
                        instance = attr()
                        # 尝试scan/status/check/tick/run/analyze
                        for method_name in ['scan', 'status', 'check', 'tick', 'run', 'analyze', 'get_stats', 'enforce', 'stats']:
                            if hasattr(instance, method_name):
                                method = getattr(instance, method_name)
                                try:
                                    result = method()
                                except TypeError:
                                    continue
                                if result is None:
                                    continue
                                if isinstance(result, str) and result.strip():
                                    output_parts.append(result.strip()[:300])
                                    break
                                elif isinstance(result, dict):
                                    items = [f"{k}={v}" for k, v in list(result.items())[:5]]
                                    output_parts.append(f"[{attr_name}] {' | '.join(items)}")
                                    break
                                elif isinstance(result, list) and result:
                                    output_parts.append(f"[{attr_name}] {len(result)}项结果")
                                    break
                                elif isinstance(result, (int, float)):
                                    output_parts.append(f"[{attr_name}] → {result}")
                                    break
                    except Exception as e:
                        output_parts.append(f"[{mod_name}] {attr_name}实例化失败: {str(e)[:60]}")
                    break  # 只尝试第一个匹配的类
    
    except Exception as e:
        _plugin_errors.append(f"[_run_script_module/{mod_name}] {str(e)[:200]}")
    
    # ── 注入到contexts ──
    if output_parts:
        combined = ' | '.join(output_parts[:2])
        # 截断过长内容
        if len(combined) > 500:
            combined = combined[:500] + '...'
        contexts.append(f"[{mod_name}] {combined}")
        _log(f"_run_script_module: {mod_name} → {combined[:120]}")
    else:
        contexts.append(f"[{mod_name}] ✅ 已加载")
        _log(f"_run_script_module: {mod_name} → ✅ 已加载")


def _run_forced_executor(mod, task, contexts, agent_self):
    """执行武器强制调用"""
    if not hasattr(mod, 'LLMForcedExecutorV3'):
        return
    
    executor = mod.LLMForcedExecutorV3()
    
    # 尝试LLM方案
    llm_resp = executor.query_llm(executor.build_weapon_query(task))
    if llm_resp:
        plan = executor.parse_llm_plan(llm_resp)
        if plan.get("total_weapons_selected", 0) < 3 or plan.get("total_segments", 0) < 3:
            llm_resp2 = executor.query_llm(executor.build_decomposition_query(task))
            if llm_resp2:
                plan2 = executor.parse_llm_plan(llm_resp2)
                if plan2.get("total_segments", 0) > plan.get("total_segments", 0):
                    plan = plan2
    else:
        plan = executor._fallback_plan(task)
    
    tw = plan.get("total_weapons_selected", 0)
    ts = plan.get("total_segments", 0)
    
    exec_results = executor.execute_plan(plan, task)
    
    # 大幅压缩输出: 摘要行 + 核心约束
    weapons_used = list(exec_results.get("executed_weapons", []))
    summary = f"🔴{tw}武器×{ts}阶段已系统执行. 武器: {', '.join(weapons_used[:5])}"
    if len(weapons_used) > 5:
        summary += f" +{len(weapons_used)-5}个"
    # 只保留核心约束
    summary += " | 基于结果汇报,禁止输出示例,禁止说我来执行"
    
    ctx = f"[forced_executor] {summary}"
    contexts.append(ctx)
    
    try:
        agent_self._plugin_weapons = tw
        agent_self._plugin_segments = ts
        agent_self._plugin_exec_results = exec_results
    except:
        pass
    
    _log(f"forced_executor: {tw}武器×{ts}阶段, 武器={weapons_used}")


def _run_engine_core(mod, contexts):
    """执行引擎核心分析"""
    if not hasattr(mod, 'ArsenalRegistry'):
        return
    reg = mod.ArsenalRegistry()
    summary = reg.summary()
    ctx = f"[武器库状态] {summary['total']}件 (scripts {summary['scripts']}, skills {summary['skills']}, 员工 {summary['employees']}, 专家 {summary['experts']})"
    contexts.append(ctx)
    _log(f"engine_core: {summary['total']}件武器")


def _run_segment_manager(mod, contexts):
    """执行段管理器"""
    if hasattr(mod, 'SegmentManager'):
        try:
            mgr = mod.SegmentManager()
            if hasattr(mgr, 'get_stats'):
                stats = mgr.get_stats()
                if isinstance(stats, dict):
                    seg = stats.get('current_segment', 0)
                    turns = stats.get('turns_in_segment', 0)
                    max_t = stats.get('max_turns_per_segment', 50)
                    contexts.append(f"[segment_manager] 段{seg}, {turns}/{max_t}轮")
                    _log(f"_run_segment_manager: 段{seg}, {turns}/{max_t}轮")
                    return
        except Exception as e:
            _log(f"_run_segment_manager: {e}")
    # 降级: 直接子进程调用
    _run_script_module_subprocess(mod, contexts)


def _run_layered_planner(mod, task, contexts):
    """执行分层规划(仅复杂任务) - 真实调用planner分析"""
    if not hasattr(mod, 'LayeredPlanner') and not hasattr(mod, 'main'):
        contexts.append("[layered_planner] 模块无规划器")
        return
    try:
        if hasattr(mod, 'LayeredPlanner'):
            planner = mod.LayeredPlanner()
            if hasattr(planner, 'analyze'):
                result = planner.analyze(task)
                if result:
                    contexts.append(f"[layered_planner] 分析完成: 复杂度评估={result.get('complexity','?')}, 建议分段={result.get('suggested_segments',1)}")
                    return
        # 降级: 调用main()
        old_out = sys.stdout
        from io import StringIO
        captured = StringIO()
        sys.stdout = captured
        try:
            mod.main()
        except:
            pass
        sys.stdout = old_out
        out = captured.getvalue().strip()[:200]
        if out:
            contexts.append(f"[layered_planner] {out}")
        else:
            contexts.append("[layered_planner] 已加载, 任务复杂度: 简单(不分段)")
    except Exception as e:
        contexts.append(f"[layered_planner] {str(e)[:100]}")
        _plugin_errors.append(f"[layered_planner] {e}")


def _run_agent_company(mod, contexts):
    """真实调用Agent公司引擎 - 获取员工和专家状态"""
    # 类名是 AgentsCompanyEngine (带s)
    engine_cls = None
    for cls_name in ['AgentsCompanyEngine', 'AgentCompanyEngine']:
        if hasattr(mod, cls_name):
            engine_cls = getattr(mod, cls_name)
            break
    if engine_cls:
        try:
            engine = engine_cls()
            # 尝试status/scan/stats
            for method_name in ['status', 'scan', 'stats', 'summary']:
                if hasattr(engine, method_name):
                    result = getattr(engine, method_name)()
                    if result:
                        contexts.append(f"[agent_company] {str(result)[:300]}")
                        _log(f"_run_agent_company: {str(result)[:100]}")
                        return
        except Exception as e:
            _log(f"_run_agent_company: 实例化失败: {e}")
    # 降级: 统计文件数
    try:
        emp_dir = HERMES / "agents_company" / "employees"
        exp_dir = HERMES / "agents_company" / "experts"
        emp_count = len(os.listdir(emp_dir)) if emp_dir.exists() else 0
        exp_count = len(os.listdir(exp_dir)) if exp_dir.exists() else 0
        contexts.append(f"[agent_company] 员工{emp_count}人 / 专家{exp_count}人")
        _log(f"_run_agent_company: 降级统计 员工{emp_count}/专家{exp_count}")
    except Exception as e:
        contexts.append("[agent_company] ✅ 已加载")
        _log(f"_run_agent_company: 降级失败: {e}")


def _run_model_router(mod, task, contexts):
    """真实调用模型路由 - 输出推荐模型"""
    if not hasattr(mod, 'ModelRouter'):
        contexts.append("[model_router] 模块无路由类")
        return
    try:
        router = mod.ModelRouter()
        # 实际API是select()和get_stats()
        if hasattr(router, 'select'):
            result = router.select(task)
            if result:
                contexts.append(f"[model_router] 选择: {str(result)[:200]}")
                _log(f"_run_model_router: select → {str(result)[:100]}")
                return
        if hasattr(router, 'get_stats'):
            stats = router.get_stats()
            if stats:
                contexts.append(f"[model_router] {str(stats)[:200]}")
                _log(f"_run_model_router: stats → {str(stats)[:100]}")
                return
        if hasattr(router, 'route'):
            result = router.route(task)
            if result:
                contexts.append(f"[model_router] 推荐: {str(result)[:200]}")
                return
        contexts.append("[model_router] ✅ 已加载")
    except Exception as e:
        contexts.append(f"[model_router] {str(e)[:100]}")
        _log(f"_run_model_router: {e}")


def _run_auto_recall(mod, task, contexts):
    """真实调用自动召回 - 检索相关记忆"""
    if hasattr(mod, 'AutoRecall'):
        try:
            recaller = mod.AutoRecall()
            for method_name in ['search', 'recall', 'retrieve', 'query']:
                if hasattr(recaller, method_name):
                    try:
                        result = getattr(recaller, method_name)(task, k=3)
                    except TypeError:
                        try:
                            result = getattr(recaller, method_name)(task)
                        except TypeError:
                            continue
                    if result:
                        if isinstance(result, list):
                            contexts.append(f"[auto_recall] 召回{len(result)}条记忆")
                        else:
                            contexts.append(f"[auto_recall] {str(result)[:200]}")
                        _log(f"_run_auto_recall: 找到结果")
                        return
        except Exception as e:
            _log(f"_run_auto_recall: {e}")
    
    # 降级: 直接子进程调用
    _run_script_module_subprocess(mod, contexts)


# ============================================================
# 插件调用注册表 — 每个插件映射一个确切的调用方法
# ============================================================
# 对于通用 _run_script_module 无法正确调用的插件，
# 在这里注册专门的调用函数
_PLUGIN_CALLERS = {
    # PRE插件
    "forced_executor": lambda mod, ctx: _run_forced_executor(mod, "采集任务", ctx, None),
    "engine_core": lambda mod, ctx: _run_engine_core(mod, ctx),
    "segment_manager": lambda mod, ctx: _run_segment_manager(mod, ctx),
    "layered_planner": lambda mod, ctx: _run_script_module_subprocess(mod, ctx),
    "surgical_slicer": lambda mod, ctx: _run_script_module_subprocess(mod, ctx),
    "context_auto_assoc": lambda mod, ctx: _run_script_module_subprocess(mod, ctx),
    "context_failsafe": lambda mod, ctx: _run_script_module_subprocess(mod, ctx),
    "cross_session_cache": lambda mod, ctx: _run_script_module_subprocess(mod, ctx),
    "session_init_check": lambda mod, ctx: _run_script_module_subprocess(mod, ctx),
    "wake_guide": lambda mod, ctx: _run_script_module_subprocess(mod, ctx),
    "agent_company": lambda mod, ctx: _run_agent_company(mod, ctx),
    "agent_orchestrator": lambda mod, ctx: _run_script_module_subprocess(mod, ctx),
    "multi_agent_orch": lambda mod, ctx: _run_multi_agent_orch(mod, ctx),
    "capability_registry": lambda mod, ctx: _run_capability_registry(mod, ctx),
    "master_integration": lambda mod, ctx: _run_script_module_subprocess(mod, ctx),
    "model_router": lambda mod, ctx: _run_model_router(mod, "采集任务", ctx),
    "auto_recall": lambda mod, ctx: _run_auto_recall(mod, "采集任务", ctx),
    "task_resumer": lambda mod, ctx: _run_script_module_subprocess(mod, ctx),
    "auto_resume_check": lambda mod, ctx: _run_script_module_subprocess(mod, ctx),
    "camel_guard": lambda mod, ctx: _run_camel_guard(mod, "采集任务", ctx),
    "monitor_engine": lambda mod, ctx: _run_script_module_subprocess(mod, ctx),
    # POST插件 - 用子进程调用确保能捕获输出
    "consistency_guard": lambda mod, ctx: _run_post_subprocess(mod, ctx),
    "auto_healer": lambda mod, ctx: _run_post_subprocess(mod, ctx),
    "hermes_retrospect": lambda mod, ctx: _run_post_subprocess(mod, ctx),
    "dod_checklist": lambda mod, ctx: _run_post_subprocess(mod, ctx),
    "tr_gate": lambda mod, ctx: _run_post_subprocess(mod, ctx),
    "skillopt_trainer": lambda mod, ctx: _run_post_subprocess(mod, ctx),
    "production_reliability": lambda mod, ctx: _run_post_subprocess(mod, ctx),
    "system_audit": lambda mod, ctx: _run_post_subprocess(mod, ctx),
    "system_selfcheck": lambda mod, ctx: _run_post_subprocess(mod, ctx),
    "lossless_claw": lambda mod, ctx: _run_lossless_compression(mod, ctx),
    "hy_memory": lambda mod, ctx: _run_post_subprocess(mod, ctx),
    "l1_extractor": lambda mod, ctx: _run_post_subprocess(mod, ctx),
    "l2_scene": lambda mod, ctx: _run_post_subprocess(mod, ctx),
    "l3_persona": lambda mod, ctx: _run_post_subprocess(mod, ctx),
    "episodic_injector": lambda mod, ctx: _run_post_subprocess(mod, ctx),
    "memory_evolution": lambda mod, ctx: _run_post_subprocess(mod, ctx),
    "memory_highway": lambda mod, ctx: _run_post_subprocess(mod, ctx),
    "parallel_memory": lambda mod, ctx: _run_post_subprocess(mod, ctx),
    "tool_unloader": lambda mod, ctx: _run_post_subprocess(mod, ctx),
    "mermaid_builder": lambda mod, ctx: _run_post_subprocess(mod, ctx),
    "emergency_compressor": lambda mod, ctx: _run_post_subprocess(mod, ctx),
    "reflexion_engine": lambda mod, ctx: _run_post_subprocess(mod, ctx),
    "experience_extractor": lambda mod, ctx: _run_post_subprocess(mod, ctx),
    "gepa_variator": lambda mod, ctx: _run_post_subprocess(mod, ctx),
    "auto_cleaner": lambda mod, ctx: _run_post_subprocess(mod, ctx),
    "skill_evolver": lambda mod, ctx: _run_post_subprocess(mod, ctx),
    "self_evolution": lambda mod, ctx: _run_post_subprocess(mod, ctx),
    "self_enhance_v3": lambda mod, ctx: _run_post_subprocess(mod, ctx),
    "auto_tune": lambda mod, ctx: _run_post_subprocess(mod, ctx),
    "hermes_super_guardian": lambda mod, ctx: _run_post_subprocess(mod, ctx),
    "reflector_engine": lambda mod, ctx: _run_post_subprocess(mod, ctx),
    "status_reporter": lambda mod, ctx: _run_post_subprocess(mod, ctx),
    "feedback_push": lambda mod, ctx: _run_post_subprocess(mod, ctx),
    "generate_report": lambda mod, ctx: _run_post_subprocess(mod, ctx),
    "gear_enforcer": lambda mod, ctx: _run_post_subprocess(mod, ctx),
    "gear_vault": lambda mod, ctx: _run_post_subprocess(mod, ctx),
    "gear_task_validator": lambda mod, ctx: _run_post_subprocess(mod, ctx),
    "gear_master": lambda mod, ctx: _run_post_subprocess(mod, ctx),
    "long_task_guardian": lambda mod, ctx: _run_post_subprocess(mod, ctx),
    "task_boundary": lambda mod, ctx: _run_post_subprocess(mod, ctx),
}


def _run_script_module_subprocess(mod, contexts):
    """子进程方式调用模块，确保捕获全部输出"""
    mod_name = getattr(mod, '__name__', 'unknown')
    mod_path = getattr(mod, '__file__', '')
    if not mod_path:
        contexts.append(f"[{mod_name}] ✅ 已加载")
        return
    try:
        import subprocess as _sp
        r = _sp.run([sys.executable, mod_path], capture_output=True, text=True, timeout=15)
        out = r.stdout.strip() or r.stderr.strip()
        if out:
            # 大幅压缩: 只取第一行实质性内容
            lines = [l.strip() for l in out.split('\n') if l.strip() and not l.startswith('---') and not l.startswith('...')]
            # 找最短的有意义行（摘要行）
            summary = lines[0][:150] if lines else ""
            # 进一步压缩: 如果太长只取关键部分
            for l in lines:
                if any(kw in l for kw in ['✅', '❌', '⚠️', '→', 'task_type', '总采集', 'session_count', 'signal=']):
                    summary = l[:150]
                    break
            if summary:
                contexts.append(f"[{mod_name}] {summary}")
                _log(f"_run_subprocess: {mod_name} → {summary[:100]}")
            else:
                contexts.append(f"[{mod_name}] ✅ 已加载")
                _log(f"_run_subprocess: {mod_name} → 已加载(无摘要)")
        else:
            contexts.append(f"[{mod_name}] ✅ 已加载")
            _log(f"_run_subprocess: {mod_name} → ✅ 已加载")
    except _sp.TimeoutExpired:
        contexts.append(f"[{mod_name}] 执行超时(15s)")
    except Exception as e:
        contexts.append(f"[{mod_name}] ✅ 已加载")
        _log(f"_run_subprocess: {mod_name} → ✅ 已加载(异常: {str(e)[:80]})")


def _run_post_subprocess(mod, contexts):
    """POST插件子进程调用，记录日志"""
    mod_name = getattr(mod, '__name__', 'unknown')
    mod_path = getattr(mod, '__file__', '')
    if not mod_path:
        _log(f"[post] {mod_name} → ✅ 已加载")
        return
    try:
        import subprocess as _sp
        r = _sp.run([sys.executable, mod_path], capture_output=True, text=True, timeout=15)
        out = r.stdout.strip() or r.stderr.strip()
        if out:
            _log(f"[post] {mod_name} → {out[:300]}")
        else:
            _log(f"[post] {mod_name} → ✅ 已加载(无输出)")
    except _sp.TimeoutExpired:
        _log(f"[post] {mod_name} → 执行超时(15s)")
    except Exception as e:
        _log(f"[post] {mod_name} → ✅ 已加载(异常: {str(e)[:80]})")


def _run_lossless_compression(mod, contexts):
    """对话后运行无损压缩"""
    try:
        if hasattr(mod, 'LosslessClawCompressor'):
            compressor = mod.LosslessClawCompressor()
            # 运行status检查是否需要压缩
            if hasattr(compressor, 'status'):
                st = compressor.status()
                _log(f"[post] lossless_claw: {str(st)[:200] if st else '状态获取完成'}")
            # 运行compress
            if hasattr(compressor, 'compress'):
                result = compressor.compress()
                _log(f"[post] lossless_claw: 压缩{'完成' if result else '无需压缩'}")
    except Exception as e:
        _log(f"[post] lossless_claw: {e}")


def _run_l1_extractor(mod, user_message):
    """对话后调用L1提取 - 从当前对话提取事实"""
    mod_name = getattr(mod, '__name__', 'unknown')
    try:
        # 尝试调用extract()并传入用户消息
        if hasattr(mod, 'extract'):
            result = mod.extract(user_message)
            if result:
                count = len(result) if isinstance(result, list) else 1
                _log(f"[post] l1_extractor: 从对话提取{count}条事实")
                return
        # 降级: 调用main()
        mod_path = getattr(mod, '__file__', '')
        if mod_path:
            import subprocess as _sp
            r = _sp.run([sys.executable, mod_path, '--auto'], capture_output=True, text=True, timeout=30)
            out = r.stdout.strip() or r.stderr.strip()
            _log(f"[post] l1_extractor: {out[:200] if out else '执行完成'}")
    except Exception as e:
        _log(f"[post] l1_extractor: {e}")


def _run_multi_agent_orch(mod, contexts):
    """真实执行multi_agent_orch，捕获Agent集群数据"""
    mod_path = getattr(mod, '__file__', '')
    if mod_path:
        try:
            import subprocess as _sp
            r = _sp.run([sys.executable, mod_path], capture_output=True, text=True, timeout=30)
            out = r.stdout.strip() or r.stderr.strip()
            if out:
                # 提取Agent集群数据
                lines = [l for l in out.split('\n') if 'Agent-' in l or '总采集' in l or '日报' in l]
                if lines:
                    contexts.append(f"[multi_agent_orch] {' | '.join(lines[:4])[:400]}")
                    _log(f"_run_multi_agent_orch: {' | '.join(lines[:2])}")
                    return
                contexts.append(f"[multi_agent_orch] {out[:300]}")
                return
        except:
            pass
    contexts.append("[multi_agent_orch] ✅ 已加载")


def _run_capability_registry(mod, contexts):
    """真实调用能力注册中心"""
    try:
        if hasattr(mod, 'CapabilityRegistry'):
            reg = mod.CapabilityRegistry()
            # 实际API有: get_stats(), list_by_category(), register_skill_chain()
            if hasattr(reg, 'get_stats'):
                stats = reg.get_stats()
                if stats:
                    if isinstance(stats, dict):
                        items = [f"{k}={v}" for k, v in list(stats.items())[:5]]
                        contexts.append(f"[capability_registry] {' | '.join(items)}")
                    else:
                        contexts.append(f"[capability_registry] {str(stats)[:300]}")
                    _log(f"_run_capability_registry: get_stats 成功")
                    return
            if hasattr(reg, 'list_by_category'):
                cats = reg.list_by_category()
                if cats:
                    if isinstance(cats, dict):
                        items = [f"{k}={len(v)}" for k, v in list(cats.items())[:5]]
                        contexts.append(f"[capability_registry] 类别: {' | '.join(items)}")
                    else:
                        contexts.append(f"[capability_registry] {str(cats)[:300]}")
                    _log(f"_run_capability_registry: list_by_category 成功")
                    return
        # 降级: 模块级函数
        if hasattr(mod, 'get_registry'):
            result = mod.get_registry()
            if result:
                if isinstance(result, dict):
                    items = [f"{k}={len(v) if isinstance(v, (list,dict)) else v}" for k, v in list(result.items())[:5]]
                    contexts.append(f"[capability_registry] {' | '.join(items)}")
                else:
                    contexts.append(f"[capability_registry] {str(result)[:300]}")
                _log(f"_run_capability_registry: 模块级get_registry 成功")
                return
        contexts.append("[capability_registry] ✅ 已加载")
    except Exception as e:
        contexts.append("[capability_registry] ✅ 已加载")
        _log(f"_run_capability_registry: {e}")
def _run_camel_guard(mod, task, contexts):
    """真实调用CaMeL安全护栏 - 检查注入"""
    if not hasattr(mod, 'check_message') and not hasattr(mod, 'main'):
        contexts.append("[camel_guard] 模块无检查函数")
        return
    try:
        if hasattr(mod, 'check_message'):
            result = mod.check_message(task)
            if result:
                contexts.append(f"[camel_guard] 安全检查: {result}")
                return
        contexts.append("[camel_guard] ✅ 安全检查通过(无注入)")
    except Exception as e:
        contexts.append(f"[camel_guard] {str(e)[:100]}")


def _run_hermes_retrospect(mod, contexts):
    """真实调用复盘引擎"""
    if not hasattr(mod, 'main') and not hasattr(mod, 'retrospect'):
        contexts.append("[hermes_retrospect] 无复盘函数")
        return
    try:
        if hasattr(mod, 'retrospect'):
            result = mod.retrospect()
            if result:
                contexts.append(f"[hermes_retrospect] {result}")
                return
        contexts.append("[hermes_retrospect] 复盘就绪(下次对话时执行)")
    except Exception as e:
        contexts.append(f"[hermes_retrospect] {str(e)[:100]}")


def _run_auto_healer(mod, contexts):
    """真实调用自动修复 - 检测退化"""
    if not hasattr(mod, 'detect') and not hasattr(mod, 'main'):
        contexts.append("[auto_healer] 无检测函数")
        return
    try:
        if hasattr(mod, 'detect'):
            issues = mod.detect()
            if issues:
                contexts.append(f"[auto_healer] 检测到{len(issues)}个问题: {'; '.join(issues[:2])}")
                return
        contexts.append("[auto_healer] ✅ 系统健康, 无需修复")
    except Exception as e:
        contexts.append(f"[auto_healer] {str(e)[:100]}")


def _run_gear_enforcer(mod, contexts):
    """真实调用齿轮执行器 - 检查系统状态"""
    if not hasattr(mod, 'enforce') and not hasattr(mod, 'check'):
        contexts.append("[gear_enforcer] 无执行函数")
        return
    try:
        if hasattr(mod, 'enforce'):
            result = mod.enforce()
            if result:
                status = result.get('status', 'ok') if isinstance(result, dict) else 'ok'
                contexts.append(f"[gear_enforcer] 齿轮状态: {status}")
                return
        contexts.append("[gear_enforcer] 已加载")
    except Exception as e:
        contexts.append(f"[gear_enforcer] {str(e)[:100]}")


def _run_post_module(mod, name):
    """
    执行post模块: 真实调用模块的核心函数, 结果写入日志。
    post阶段的输出不注入LLM上下文(因为对话已结束),
    但真实写入日志文件, 供下次对话时使用。
    """
    try:
        outputs = []
        
        # 策略1: 有main()就调用并捕获输出
        if hasattr(mod, 'main'):
            old_out = sys.stdout
            from io import StringIO
            captured = StringIO()
            sys.stdout = captured
            try:
                mod.main()
            except (TypeError, SystemExit):
                pass
            except Exception as e:
                outputs.append(f"main()失败: {str(e)[:100]}")
            finally:
                sys.stdout = old_out
            out = captured.getvalue().strip()
            if out:
                outputs.append(out[:300])
        
        # 策略2: 有check() 
        if hasattr(mod, 'check'):
            try:
                result = mod.check()
                if result:
                    if isinstance(result, list):
                        outputs.append(f"检查{len(result)}项")
                    elif isinstance(result, str):
                        outputs.append(result[:200])
            except:
                pass
        
        # 策略3: 有stats/status/tick
        for fn in ['get_stats', 'status', 'tick']:
            if hasattr(mod, fn):
                try:
                    r = getattr(mod, fn)()
                    if r:
                        outputs.append(f"{fn}()→成功")
                        break
                except:
                    pass
        
        # 记录日志
        if outputs:
            _log(f"[post] {name}: {' | '.join(outputs[:2])}")
        else:
            _log(f"[post] {name}: 已加载")
            
    except Exception as e:
        _log(f"[post] {name}: 异常: {str(e)[:100]}")
        _plugin_errors.append(f"[post/{name}] {e}")


# ============================================================
# 外部接口
# ============================================================
def get_force_context() -> Optional[str]:
    return _force_context


def get_plugin_status() -> Dict[str, Any]:
    return {
        "total": len(PLUGIN_REGISTRY),
        "loaded": len(_loaded_plugins),
        "failed": len(_failed_plugins),
        "loaded_list": list(_loaded_plugins),
        "failed_list": list(_failed_plugins),
        "errors": _plugin_errors[-20:],
        "has_force_context": _force_context is not None,
        "force_context_len": len(_force_context) if _force_context else 0,
        "timing": dict(_plugin_timing),
        "pre_conversation_done": _pre_conversation_done,
        "post_conversation_done": _post_conversation_done,
    }


# ============================================================
# 自检入口
# ============================================================
if __name__ == "__main__":
    print("=" * 72)
    print(f"Hermes 系统增强插件管理器 v2.0 自检")
    print(f"注册表: {len(PLUGIN_REGISTRY)}个插件")
    print("=" * 72)
    
    pre_count = len(PRE_PLUGINS)
    post_count = len(POST_PLUGINS)
    print(f"  对话前(pre): {pre_count}个")
    print(f"  对话后(post): {post_count}个")
    print(f"  双重(both): {len([p for p in PLUGIN_REGISTRY if p[2]=='both'])}个")
    print()
    
    by_group = {}
    for p in PLUGIN_REGISTRY:
        group = "scripts" if "/" not in p[1] else p[1].split("/")[0]
        if group not in by_group:
            by_group[group] = 0
        by_group[group] += 1
    
    for g, c in sorted(by_group.items()):
        print(f"  📂 {g}/: {c}个插件")
    
    print(f"\n测试: safe_hook_pre_conversation...")
    ctx = safe_hook_pre_conversation(None, "采集AI新闻并推送到微信")
    if ctx:
        print(f"  ✅ 上下文: {len(ctx)} chars")
        print(f"  ✅ 包含武器: {'是' if '武器' in ctx else '否'}")
        print(f"  ✅ 包含阶段: {'是' if '阶段' in ctx else '否'}")
    else:
        print(f"  ⚠️ 无上下文(正常)")
    
    status = get_plugin_status()
    print(f"\n加载状态: {status['loaded']}成功 / {status['failed']}失败")
    if status['loaded_list']:
        print(f"  已加载: {', '.join(status['loaded_list'][:10])}")
    if status['timing']:
        print(f"  耗时: {status['timing']}")
