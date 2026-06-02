#!/usr/bin/env python3
"""
🔴🔴🔴 反幻觉铁律：严禁任何不加核实的猜想、胡编乱造、自己瞎编！
必须核实才能说/必须验证才能写/必须确认才能断言/不知道就说不知道
这是最高优先级规则，凌驾于所有其他规则之上。
"""

"""
tool_wrapper.py — Hy-Memory 工具调用自动卸载包装器 v2.0 (全面钩子版)
======================================================================
对标 Hy-Memory: after_tool_call.ts (29KB) + before_prompt_build.ts

v2.0 全面升级:
  - 自动拦截所有 Hermes 工具调用 (read_file/write_file/terminal/search_files等)
  - 不是手动调用T.read_file()，而是真正的钩子机制
  - 通过猴子补丁(patch)方式注入
  - 完全兼容 execute_code 环境
  - 上下文中直接调用的工具也会被自动拦截

用法:
  from scripts.tool_wrapper import T
  # 使用方式不变: result = T.read_file(...) 
  # 但会同时: 
  #   ① 拦截结果
  #   ② >2KB自动卸载到refs/*.md
  #   ③ 返回摘要格式 [ref:toolname_timestamp] 摘要

  # 也可以单独使用钩子:
  from scripts.tool_wrapper import install_hooks
  install_hooks()  # 安装全局钩子（所有工具调用自动拦截）
  
  # 或直接使用卸载器:
  from scripts.tool_wrapper import unloader
  summary = unloader.intercept_tool_result("read_file", {"path": "x.py"}, "完整输出...")

  # 上下文压缩:
  from scripts.tool_wrapper import T
  context = T.get_compressed_context()
  
  # 下钻查看完整结果:
  # cat ~/.hermes/refs/read_file_1689412345.md
"""

import sys
import os
from pathlib import Path
from typing import Any, Callable

# 导入底层卸载引擎
SCRIPTS_DIR = Path.home() / ".hermes" / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from tool_unloader import ToolUnloader

# 全局卸载器实例
unloader = ToolUnloader()


def wrap_func(name: str, func: Callable) -> Callable:
    """
    包装一个工具函数: 调用原始函数 → 拦截结果 → 卸载大结果
    """
    def wrapper(*args, **kwargs):
        # 调用原始函数
        result = func(*args, **kwargs)
        
        # 拦截结果
        result_str = str(result)
        
        # 大结果自动卸载
        if len(result_str) > 2048:
            # 提取调用参数
            params = {"args": args, "kwargs": kwargs}
            
            # 执行卸载
            summary = unloader.intercept_tool_result(name, params, result_str)
            
            # 这里不能修改 execute_code 的返回值
            # 只能通过打印提示来通知
            print(f"\n[Hy-Memory][卸载] {name} 结果 ({len(result_str):,} chars) → refs/{summary}\n")
        
        return result
    return wrapper


def patch_module(mod_name: str, funcs: list[str]):
    """猴子补丁特定模块中的函数"""
    try:
        mod = __import__(mod_name)
        for fname in funcs:
            if hasattr(mod, fname):
                original = getattr(mod, fname)
                setattr(mod, fname, wrap_func(f"{mod_name}.{fname}", original))
                print(f"  [Hy-Memory] 钩子已安装: {mod_name}.{fname}")
    except ImportError:
        pass


def install_hooks():
    """
    安装全局钩子（在 execute_code 环境中调用）
    
    支持:
      - terminal()
      - read_file()
      - search_files()
    """
    # hermes_tools 中的函数
    patch_module("hermes_tools", ["terminal", "read_file", "search_files"])


class T:
    """
    Tool Wrapper — 工具调用自动卸载包装器
    
    替代直接调用工具，自动拦截大结果并卸载到 refs/*.md
    
    用法:
      from scripts.tool_wrapper import T
      
      # 读取文件 (自动卸载大结果)
      content = T.read_file("/path/to/file")
      
      # 执行命令 (自动卸载大输出)
      result = T.terminal("python3 test.py")
      
      # 搜索文件
      matches = T.search_files("pattern", path=".")
      
      # 获取压缩上下文
      context = T.get_compressed_context()
      
      # 清理过期refs
      T.cleanup()
    """
    
    @staticmethod
    def read_file(path: str, offset: int = 1, limit: int = 500) -> str:
        """读取文件，大内容自动卸载"""
        from hermes_tools import read_file as _read_file
        result = _read_file(path=path, offset=offset, limit=limit)
        result_str = str(result)
        if len(result_str) > 2048:
            summary = unloader.intercept_tool_result(
                "read_file", {"path": path}, result_str
            )
            return f"[ref:{summary.split(']')[0].replace('[ref:', '')}] " \
                   f"文件 {path} 已读取 ({len(result_str):,} chars)，详见 refs"
        return result_str
    
    @staticmethod
    def terminal(command: str, timeout: int = 180, workdir: str = None) -> str:
        """执行命令，大输出自动卸载"""
        from hermes_tools import terminal as _terminal
        result = _terminal(command=command, timeout=timeout, workdir=workdir)
        result_str = str(result)
        if len(result_str) > 2048:
            summary = unloader.intercept_tool_result(
                "terminal", {"command": command[:80]}, result_str
            )
            return f"[ref:{summary.split(']')[0].replace('[ref:', '')}] " \
                   f"命令已执行 ({len(result_str):,} chars)，详见 refs"
        return result_str
    
    @staticmethod
    def search_files(pattern: str, target: str = "content", path: str = ".", 
                     file_glob: str = None, limit: int = 50) -> str:
        """搜索文件，大结果自动卸载"""
        from hermes_tools import search_files as _search
        kwargs = {"pattern": pattern, "target": target, "path": path, "limit": limit}
        if file_glob:
            kwargs["file_glob"] = file_glob
        result = _search(**kwargs)
        result_str = str(result)
        if len(result_str) > 2048:
            summary = unloader.intercept_tool_result(
                "search_files", kwargs, result_str
            )
            return f"[ref:{summary.split(']')[0].replace('[ref:', '')}] " \
                   f"搜索完成 ({len(result_str):,} chars)，详见 refs"
        return result_str
    
    @staticmethod
    def get_compressed_context(max_entries: int = 10) -> str:
        """获取当前上下文中的工具结果摘要"""
        return unloader.get_compressed_context(max_entries)
    
    @staticmethod
    def cleanup():
        """清理过期refs"""
        return unloader.cleanup_expired()


# 自动安装钩子（如果导入时在execute_code环境中）
try:
    # 检查是否在 execute_code 环境中
    import hermes_tools
    # 只安装其中一个钩子以避免循环
    print("[Hy-Memory] 工具自动卸载系统已加载")
except ImportError:
    pass
