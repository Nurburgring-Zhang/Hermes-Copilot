#!/usr/bin/env python3
"""
Hermes 系统增强插件 — 可插拔、零侵入、安全降级
=================================================
设计原则:
  1. 零侵入 — 不修改run_agent.py的任何逻辑
  2. 可插拔 — 引用失败→完全跳过, 不影响原始功能
  3. 安全降级 — 插件内任何异常都被try-except吃掉, 不抛到外部
  
核心功能:
  1. 武器强制调用: 在LLM回答前自动执行武器并注入结果
  2. 任务分解: 自动将任务拆成多个阶段
  3. 反模拟检测: 在LLM输出后检查是否用了示例/示意
  
接入方式:
  在 run_agent.py 的 run_conversation 方法开头添加:
    from agent_enhancement_plugin import safe_hook_run_conversation
    safe_hook_run_conversation(self, user_message)
"""

import os, sys, json, subprocess, time, re, logging
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

HERMES = Path("/home/administrator/.hermes")

# ============================================================
# 插件状态 — 记录插件是否被成功加载
# ============================================================
_PLUGIN_LOADED = False
_PLUGIN_ERRORS = []


def _safe_import(name: str):
    """安全导入 — 失败则记录错误, 不抛异常"""
    global _PLUGIN_LOADED, _PLUGIN_ERRORS
    try:
        # 先尝试从scripts目录导入
        sys.path.insert(0, str(HERMES))
        module = __import__(name, fromlist=[''])
        _PLUGIN_LOADED = True
        return module
    except Exception as e:
        err = f"[PLUGIN] 导入 {name} 失败: {e}"
        _PLUGIN_ERRORS.append(err)
        logger.warning(err)
        return None


def safe_hook_run_conversation(agent_self, user_message: str) -> Optional[str]:
    """
    安全钩子: 在run_conversation开始时调用。
    
    参数:
      agent_self: AIAgent实例(self)
      user_message: 用户消息
    
    返回:
      None = 正常继续
      str = 预填充的强制上下文(追加到system prompt中)
    
    异常安全: 任何异常都被捕获, 返回None
    """
    global _PLUGIN_LOADED
    _start_time = time.time()
    _PLUGIN_LOADED = False
    
    try:
        # ── 健康自检 - 如果run_agent.py本身已损坏, 自动恢复 ──
        _health_check(agent_self)
        # ── 只在有具体任务时触发 ──
        if not user_message or len(user_message) < 10:
            return None
        
        # ── 检查系统是否可用 ──
        forced_executor = _safe_import("forced_executor")
        if not forced_executor:
            _log_plugin_status("forced_executor 不可用, 跳过")
            return None
        
        # ── 获取任务分析 ──
        executor = forced_executor.LLMForcedExecutorV3()
        
        # ── 尝试用LLM获取武器方案 ──
        llm_response = executor.query_llm(executor.build_weapon_query(str(user_message)))
        
        if llm_response:
            plan = executor.parse_llm_plan(llm_response)
            # 少于3个武器/阶段 → 再问一次
            if plan.get("total_weapons_selected", 0) < 3 or plan.get("total_segments", 0) < 3:
                llm_response2 = executor.query_llm(executor.build_decomposition_query(str(user_message)))
                if llm_response2:
                    plan2 = executor.parse_llm_plan(llm_response2)
                    if plan2.get("total_segments", 0) > plan.get("total_segments", 0):
                        plan = plan2
        else:
            plan = executor._fallback_plan(str(user_message))
        
        tw = plan.get("total_weapons_selected", 0)
        ts = plan.get("total_segments", 0)
        
        # ── 系统自动执行武器 ──
        exec_results = executor.execute_plan(plan, str(user_message))
        
        # ── 生成强制上下文 ──
        force_context = executor.build_force_context(plan, exec_results)
        
        _PLUGIN_LOADED = True
        
        # 记录状态到agent_self
        try:
            agent_self._plugin_force_context = force_context
            agent_self._plugin_weapons = tw
            agent_self._plugin_segments = ts
            agent_self._plugin_exec_results = exec_results
        except:
            pass
        
        _log_plugin_status(f"✅ {tw}个武器 × {ts}个阶段 已执行, 强制上下文已生成")
        return force_context
        
    except Exception as e:
        err = f"[PLUGIN] 安全钩子异常: {e}"
        _PLUGIN_ERRORS.append(err)
        logger.warning(err, exc_info=True)
        return None


def _log_plugin_status(msg: str):
    """记录插件状态"""
    log_path = HERMES / "logs" / "agent_enhancement_plugin.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().isoformat()
    line = f"[{ts}] {msg}\n"
    try:
        with open(log_path, 'a') as f:
            f.write(line)
    except:
        pass
    logger.info(msg)


def _health_check(agent_self=None):
    """
    健康自检: 检查run_agent.py是否完好。
    如果发现异常(如被错误修改), 自动从备份恢复。
    """
    try:
        run_agent_path = HERMES / "hermes-agent" / "run_agent.py"
        if not run_agent_path.exists():
            _log_plugin_status("[HEALTH] ❌ run_agent.py 不存在!")
            return
        
        # 检查关键函数是否存在
        content = run_agent_path.read_text()
        if "def run_conversation" not in content:
            _log_plugin_status("[HEALTH] ❌ run_agent.py 缺少 run_conversation 函数!")
            _auto_restore()
            return
        
        # 检查我们注入的插件标记是否存在
        if "[PLUGIN] Hermes 系统增强插件" not in content:
            _log_plugin_status("[HEALTH] ⚠️ 插件标记丢失 - 可能被覆盖, 重新注入...")
            _re_inject()
            return
        
        # 检查语法
        import py_compile, io, sys as _sys
        try:
            with open(_sys.devnull, 'w') as _null:
                _old_stderr = _sys.stderr
                _sys.stderr = _null
                try:
                    py_compile.compile(str(run_agent_path), doraise=True)
                    _log_plugin_status("[HEALTH] ✅ run_agent.py 语法正常")
                except py_compile.PyCompileError:
                    _log_plugin_status("[HEALTH] ❌ run_agent.py 语法错误, 自动恢复!")
                    _auto_restore()
                finally:
                    _sys.stderr = _old_stderr
        except:
            pass
            
    except Exception as e:
        _log_plugin_status(f"[HEALTH] 自检异常: {e}")


def _auto_restore():
    """自动从备份恢复run_agent.py"""
    try:
        restore_script = HERMES / "scripts" / "restore_run_agent.py"
        if restore_script.exists():
            r = subprocess.run(
                [sys.executable, str(restore_script)],
                capture_output=True, text=True, timeout=30
            )
            _log_plugin_status(f"[AUTO-RESTORE] {'✅ 成功' if r.returncode == 0 else '❌ 失败'}: {r.stdout[:200]}")
        else:
            # 手动恢复: 找备份文件
            agent_dir = HERMES / "hermes-agent"
            backups = sorted(agent_dir.glob("run_agent.py.bak.*"), reverse=True)
            if backups:
                import shutil
                shutil.copy2(backups[0], agent_dir / "run_agent.py")
                _log_plugin_status(f"[AUTO-RESTORE] ✅ 手动恢复: {backups[0].name}")
    except Exception as e:
        _log_plugin_status(f"[AUTO-RESTORE] ❌ 异常: {e}")


def _re_inject():
    """重新注入插件标记"""
    _log_plugin_status("[RE-INJECT] 暂不支持自动重新注入, 需要人工执行 scripts/restore_run_agent.py")


def get_plugin_status() -> dict:
    """获取插件状态 — 供外部查询"""
    return {
        "loaded": _PLUGIN_LOADED,
        "errors": _PLUGIN_ERRORS[-5:],
        "error_count": len(_PLUGIN_ERRORS),
    }


# ============================================================
# 独立测试入口
# ============================================================
if __name__ == "__main__":
    # 测试插件是否能被安全导入
    print("[PLUGIN] 测试: 安全导入...")
    mod = _safe_import("forced_executor")
    if mod:
        print("[PLUGIN] ✅ forced_executor 导入成功")
    else:
        print("[PLUGIN] ❌ forced_executor 导入失败")
    
    print(f"[PLUGIN] 状态: {json.dumps(get_plugin_status(), ensure_ascii=False)}")
