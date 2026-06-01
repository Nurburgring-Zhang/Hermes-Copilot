> 🔴🔴🔴 **反幻觉铁律（最高优先级）** — 严禁任何不加核实的猜想、胡编乱造、自己瞎编！
> 必须核实才能说 / 必须验证才能写 / 必须确认才能断言 / 不知道就说不知道
> 未经验证的信息一个字都不能说。一次猜测=一次信任崩塌。

## 长链任务上下文管理（Hy-Memory P0）
在每次 execute_code 或长链任务中，如果涉及多次工具调用（terminal/read_file等），使用：
  from scripts.tool_wrapper import T
  result = T.read_file(...)  # 自动卸载大结果
  result = T.terminal(...)   # 自动卸载大输出
效果：工具结果>2KB→卸载到refs/*.md，上下文只留[ref:xxx]摘要标记
节省：每次大工具调用节省数千tokens（对标Hy-Memory的33-61%）
