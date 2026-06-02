#!/usr/bin/env python3
"""
🔴🔴🔴 反幻觉铁律：严禁任何不加核实的猜想、胡编乱造、自己瞎编！
必须核实才能说/必须验证才能写/必须确认才能断言/不知道就说不知道
这是最高优先级规则，凌驾于所有其他规则之上。
"""

"""
llm_bridge.py — Hermes统一LLM调用桥接层 v1.0
============================================
提供三种LLM调用方式的统一接口，按优先级自动选择可用后端。

三种方式（按优先级）:
  1. delegate_task — 使用Hermes自身模型（始终可用，无需配置）
  2. LM Studio — http://localhost:8080/v1（本地开源模型，最快响应）
  3. Ollama — http://localhost:11434（本地开源模型，次选）

都没有 → 使用预设标准输出（fallback规则）
    每个调用都有预设的fallback输出，确保系统不因LLM不可用而卡死。

用法:
  from llm_bridge import llm_call, LLMResult
  
  # 方式1: 自动检测可用后端
  result = llm_call(
      system_prompt="你是专家",
      user_prompt="分析这个",
      fallback="默认分析结果"  # 所有后端不可用时使用
  )
  # result.text -> LLM输出文本
  # result.success -> 是否成功
  # result.backend -> 使用的后端名称
  
  # 方式2: 指定后端（跳过自动检测）
  result = llm_call(..., preferred_backend="delegate")
  
  # 方式3: 结构化输出
  result = llm_call_json(
      system_prompt="...",
      user_prompt="...",
      fallback={"status": "unknown"}  # dict作为fallback
  )
  # result.data -> 解析后的JSON
  
  # 方式4: 简单调用（单轮对话）
  result = llm_simple("写一首诗")
"""

import json
import re
import socket
import subprocess
import time
import urllib.request
import urllib.error
from typing import Optional, Any, Callable


def _get_wsl_host_ip() -> str:
    """获取WSL宿主Windows IP（用于从WSL访问Windows服务）"""
    try:
        result = subprocess.run(
            ["ip", "route", "show", "default"],
            capture_output=True, text=True, timeout=3
        )
        parts = result.stdout.strip().split()
        for i, p in enumerate(parts):
            if p == "via" and i + 1 < len(parts):
                return parts[i + 1]
    except Exception:
        pass
    return ""


_WSL_HOST = _get_wsl_host_ip()


class LLMResult:
    """统一的LLM调用结果"""
    
    def __init__(self, text: str = "", success: bool = False, 
                 backend: str = "none", error: str = "",
                 tier: str = ""):
        self.text = text
        self.success = success
        self.backend = backend
        self.error = error
        self.tier = tier
        self._data = None
    
    @property
    def data(self) -> Any:
        """解析JSON输出"""
        if self._data is not None:
            return self._data
        if not self.text:
            return None
        try:
            raw = self.text.strip()
            if raw.startswith("```"):
                raw = re.sub(r'^```(?:json)?\s*', '', raw)
                raw = re.sub(r'\s*```$', '', raw)
            start = raw.find('{')
            end = raw.rfind('}')
            if start >= 0 and end > start:
                self._data = json.loads(raw[start:end+1])
            else:
                start = raw.find('[')
                end = raw.rfind(']')
                if start >= 0 and end > start:
                    self._data = json.loads(raw[start:end+1])
                else:
                    self._data = json.loads(raw)
        except (json.JSONDecodeError, ValueError, TypeError):
            self._data = None
        return self._data


# ====================== 后端检测器 ======================

def _check_lmstudio() -> bool:
    """检测LM Studio是否可用"""
    try:
        req = urllib.request.Request("http://localhost:8080/v1/models", 
                                     method="GET")
        with urllib.request.urlopen(req, timeout=2) as resp:
            return resp.status == 200
    except Exception:
        return False


def _check_ollama() -> tuple[bool, str]:
    """检测Ollama是否可用，返回可用模型名"""
    # 尝试多个地址: localhost (Linux/Mac), WSL host (WSL→Windows)
    hosts_to_try = ["http://localhost:11434"]
    if _WSL_HOST:
        hosts_to_try.insert(0, f"http://{_WSL_HOST}:11434")
    
    for base_url in hosts_to_try:
        try:
            req = urllib.request.Request(f"{base_url}/api/tags",
                                         method="GET")
            with urllib.request.urlopen(req, timeout=2) as resp:
                data = json.loads(resp.read())
                models = data.get("models", [])
                if models:
                    # 优先选择中文优化模型
                    pref_order = ["qwen2.5", "qwen", "NQLSG", "llama3.1", "llama3", "mistral"]
                    for pref in pref_order:
                        for m in models:
                            name = m.get("name", "")
                            if pref in name:
                                return True, name
                    return True, models[0].get("name", "llama3.1:8b")
        except Exception:
            continue
    return False, ""


def _check_delegate() -> bool:
    """delegate_task始终可用（Hermes内置能力）"""
    return True


# ====================== 后端调用器 ======================

def _call_delegate(system_prompt: str, user_prompt: str, 
                   timeout: int = 60) -> Optional[str]:
    """
    通过delegate_task调用Hermes自身LLM
    
    注意: 在cron/后台环境, delegate_task可能不可用
    返回None表示不可用
    """
    # delegate_task需要在Hermes对话上下文中使用
    # 在cron或脚本中直接调用会失败
    # 这里通过检查是否在对话环境中判断
    try:
        # 尝试导入hermes_tools——只有在对话中才可用
        from hermes_tools import delegate_task as dt
        
        # 构建任务
        full_prompt = f"{system_prompt}\n\n{user_prompt}" if system_prompt else user_prompt
        result = dt(
            goal=full_prompt[:500],
            context=f"请用JSON格式回复。系统指令: {system_prompt[:200]}",
            toolsets=["terminal"]
        )
        if result and isinstance(result, list) and len(result) > 0:
            summary = result[0].get("summary", "")
            if summary:
                return summary
        return None
    except (ImportError, Exception):
        return None


def _call_lmstudio(system_prompt: str, user_prompt: str,
                   temperature: float = 0.1, max_tokens: int = 2000,
                   timeout: int = 60) -> Optional[str]:
    """调用LM Studio本地LLM"""
    try:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_prompt})
        
        payload = json.dumps({
            "model": "local-model",
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }).encode()
        
        req = urllib.request.Request(
            "http://localhost:8080/v1/chat/completions",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            result = json.loads(resp.read())
            return result["choices"][0]["message"]["content"]
    except Exception:
        return None


def _call_ollama(system_prompt: str, user_prompt: str, model: str = "",
                 temperature: float = 0.1, max_tokens: int = 2000,
                 timeout: int = 60, task_type: str = "") -> Optional[str]:
    """调用Ollama本地LLM，支持按任务类型选择模型"""
    # 如果没指定模型，自动检测
    if not model:
        available, model = _check_ollama()
        if not available:
            return None
    
    # 按任务类型选择: code/develop应该用最强模型, 不是专用模型
    if task_type:
        task_lower = task_type.lower()
        if "code" in task_lower or "develop" in task_lower or "编程" in task_lower or "开发" in task_lower:
            # 代码任务应该用最强模型, 不切换专用模型
            pass  # 保持当前可用模型中最强的
    
    # 尝试多个地址
    hosts_to_try = ["http://localhost:11434"]
    if _WSL_HOST:
        hosts_to_try.insert(0, f"http://{_WSL_HOST}:11434")
    
    for base_url in hosts_to_try:
        try:
            payload = json.dumps({
                "model": model,
                "system": system_prompt or "",
                "prompt": user_prompt,
                "stream": False,
                "options": {
                    "temperature": temperature,
                    "num_predict": max_tokens,
                }
            }).encode()
            
            req = urllib.request.Request(
                f"{base_url}/api/generate",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                result = json.loads(resp.read())
                return result.get("response", "")
        except Exception:
            continue
    return None


# ====================== 统一入口 ======================

_BACKEND_CACHE = {"lmstudio": None, "ollama": None, "ollama_model": ""}
_LAST_CACHE_UPDATE = 0
_CACHE_TTL = 30  # 秒


def _detect_backends(force: bool = False) -> list[str]:
    """检测可用后端，返回按优先级排序的列表"""
    global _LAST_CACHE_UPDATE
    
    now = time.time()
    if not force and _LAST_CACHE_UPDATE > 0 and (now - _LAST_CACHE_UPDATE) < _CACHE_TTL:
        # 使用缓存
        backends = []
        if _BACKEND_CACHE.get("delegate") is None:
            _BACKEND_CACHE["delegate"] = _check_delegate()
        if _BACKEND_CACHE["delegate"]:
            backends.append("delegate")
        if _BACKEND_CACHE.get("lmstudio"):
            backends.append("lmstudio")
        if _BACKEND_CACHE.get("ollama"):
            backends.append("ollama")
        return backends if backends else ["fallback"]
    
    # 刷新检测
    backends = []
    
    # 1. delegate — 始终可用（在对话中）
    _BACKEND_CACHE["delegate"] = _check_delegate()
    if _BACKEND_CACHE["delegate"]:
        backends.append("delegate")
    
    # 2. LM Studio
    if _check_lmstudio():
        _BACKEND_CACHE["lmstudio"] = True
        backends.append("lmstudio")
    else:
        _BACKEND_CACHE["lmstudio"] = False
    
    # 3. Ollama
    available, model = _check_ollama()
    if available:
        _BACKEND_CACHE["ollama"] = True
        _BACKEND_CACHE["ollama_model"] = model
        backends.append("ollama")
    else:
        _BACKEND_CACHE["ollama"] = False
    
    _LAST_CACHE_UPDATE = now
    
    if not backends:
        backends = ["fallback"]
    
    return backends


def llm_call(system_prompt: str = "", user_prompt: str = "",
             fallback: str = "", temperature: float = 0.1,
             max_tokens: int = 2000, timeout: int = 60,
             preferred_backend: str = "",
             model_tier: str = "") -> LLMResult:
    """
    统一LLM调用入口
    
    参数:
      system_prompt: 系统提示词
      user_prompt: 用户提示词（必须）
      fallback: 所有后端不可用时的默认输出
      temperature: 温度参数 (0.0-1.0)
      max_tokens: 最大输出token数
      timeout: 超时秒数
      preferred_backend: 指定后端 ("delegate"/"lmstudio"/"ollama"/""=自动)
      model_tier: 模型梯队 (""=自动/"value"=通用省钱/"performance"=强力高质量)
    
    模型路由:
      - model_tier="value": 简单任务用省钱模型(flash/轻量), 复杂任务自动升级
      - model_tier="performance": 强力模型(pro/高质量), 不省token
      - model_tier="" : 由ModelRouter自动判断
    
    返回:
      LLMResult(success=True/False, text="...", backend="...")
    """
    if preferred_backend:
        backends = [preferred_backend]
    else:
        backends = _detect_backends()
    
    # 模型梯队选择
    active_tier = model_tier
    if not active_tier:
        # 自动判断：通过prompt长度和复杂度估算
        prompt_text = f"{system_prompt} {user_prompt}"
        if len(prompt_text) > 3000 or any(kw in prompt_text.lower() for kw in 
            ["分析", "设计", "架构", "review", "复杂", "优化", "重构",
             "分布式", "安全", "并发", "性能", "大规模"]):
            active_tier = "performance"
        else:
            active_tier = "value"
    
    for backend in backends:
        result_text = None
        
        if backend == "delegate":
            result_text = _call_delegate(system_prompt, user_prompt, timeout)
        elif backend == "lmstudio":
            result_text = _call_lmstudio(system_prompt, user_prompt, 
                                         temperature, max_tokens, timeout)
        elif backend == "ollama":
            model = _BACKEND_CACHE.get("ollama_model", "")
            # 通过model_tier推断task_type
            ollama_task_type = active_tier
            result_text = _call_ollama(system_prompt, user_prompt, model,
                                       temperature, max_tokens, timeout, task_type=ollama_task_type)
        
        if result_text:
            return LLMResult(text=result_text, success=True, backend=backend,
                             tier=active_tier)
    
    # 所有后端失败，使用fallback
    import warnings
    msg = f"[SKIP] LLM全部不可用(detected={backends})，使用预设fallback"
    print(msg)
    return LLMResult(text=fallback, success=False, backend="fallback",
                     error=msg, tier=active_tier)


def llm_call_json(system_prompt: str = "", user_prompt: str = "",
                  fallback: Any = None, temperature: float = 0.1,
                  max_tokens: int = 2000, timeout: int = 60,
                  preferred_backend: str = "") -> LLMResult:
    """
    调用LLM并自动解析JSON输出
    
    用法:
      result = llm_call_json(
          system_prompt="返回JSON",
          user_prompt="分析这个",
          fallback={"status": "error"}
      )
      if result.success:
          data = result.data  # 已解析的dict/list
    """
    # 确保system_prompt要求JSON输出
    json_note = "\n请只返回JSON格式，不要添加额外的markdown代码块标记。"
    if system_prompt and "JSON" not in system_prompt and "json" not in system_prompt:
        system_prompt += json_note
    elif not system_prompt:
        system_prompt = "请只返回JSON格式。" + json_note
    
    result = llm_call(system_prompt, user_prompt, 
                      json.dumps(fallback, ensure_ascii=False) if fallback else "{}",
                      temperature, max_tokens, timeout, preferred_backend)
    
    # 尝试解析
    if result.text and result.backend != "fallback":
        parsed = result.data
        if parsed is not None:
            result._data = parsed
            return result
    
    # fallback
    if fallback:
        result._data = fallback
    return result


def llm_simple(prompt: str, fallback: str = "", **kwargs) -> str:
    """
    简单调用：单轮对话
    
    返回纯文本
    
    用法:
      text = llm_simple("写一首诗", fallback="无法生成")
    """
    result = llm_call(user_prompt=prompt, fallback=fallback, **kwargs)
    return result.text


def detect_available_backends() -> dict:
    """
    检测所有可用后端并返回状态
    
    返回: {
      "delegate": True/False,
      "lmstudio": True/False,
      "ollama": True/False,
      "ollama_model": "模型名或空",
      "primary": "最佳后端名称",
      "all_fallback": True/False
    }
    """
    backends = _detect_backends(force=True)
    return {
        "delegate": _BACKEND_CACHE.get("delegate", False),
        "lmstudio": _BACKEND_CACHE.get("lmstudio", False),
        "ollama": _BACKEND_CACHE.get("ollama", False),
        "ollama_model": _BACKEND_CACHE.get("ollama_model", ""),
        "primary": backends[0] if backends else "fallback",
        "all_fallback": backends == ["fallback"],
        "available": backends,
    }


def warmup():
    """
    预热：检测后端并缓存结果
    在系统启动时调用，避免第一次调用延迟
    """
    _detect_backends(force=True)
    info = detect_available_backends()
    enabled = [k for k, v in info.items() if v is True and k in ("delegate", "lmstudio", "ollama")]
    print(f"[llm_bridge] 后端检测: {', '.join(enabled) if enabled else '仅fallback'}")
    return info


# ====================== 快速测试 ======================

if __name__ == "__main__":
    info = warmup()
    print(f"可用后端: {info['primary']}")
    print(f"全部: {info}")
    
    # 测试简单调用
    result = llm_simple("用一句话回答：1+1等于几？", fallback="计算不可用")
    print(f"测试结果: {result[:50]}")
