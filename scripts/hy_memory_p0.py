# Hy-Memory P0 集成核心 — tool_unloader + auto_recall
# ============================================================
# 对应 Hy-Memory: Context Offload Module + Recall before-prompt-build
# 
# 在每轮对话开始时自动调用的两个功能：
# 1. tool_unloader.intercept_tool_result() — 每次工具调用后自动卸裁大结果
# 2. auto_recall.recall_for_session() — 对话前注入相关历史记忆
#
# 用法（在 AGENTS.md 或 SOUL.md 中引用）：
#   对话开始时自动加载：
#     python3 scripts/recall_injector.py "$(echo $USER_INPUT)"
#     python3 scripts/tool_unloader.py cleanup
#
#   每次工具调用后（大结果时）：
#     from scripts.tool_unloader import ToolUnloader
#     unloader = ToolUnloader()
#     summary = unloader.intercept_tool_result(tool_name, params, result)
#     # 用 summary 替换完整结果

HY_MEMORY_P0_READY = True  # 标记 P0 已就绪
