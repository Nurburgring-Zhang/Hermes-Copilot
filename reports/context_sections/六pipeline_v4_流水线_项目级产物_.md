> 🔴🔴🔴 **反幻觉铁律（最高优先级）** — 严禁任何不加核实的猜想、胡编乱造、自己瞎编！
> 必须核实才能说 / 必须验证才能写 / 必须确认才能断言 / 不知道就说不知道
> 未经验证的信息一个字都不能说。一次猜测=一次信任崩塌。

## 六、Pipeline v4 流水线（项目级产物）

| 文件 | 用途 |
|------|------|
| `~/.hermes/agents_company/pipeline_stages.py` | 12个stage的delegate_task prompt模板 |
| `~/.hermes/agents_company/pipeline_executor.py` | cron调度的主执行器 |
| `~/.hermes/agents_company/pipeline_guardian.py` | G6齿轮验证+wake_guide写入 |
| `~/.hermes/agents_company/pipeexec_runner.py` | Hermes醒来读取queue执行 |

### 自动恢复流
```
醒来 → SOUL.md§0强制→ cat wake_guide.json
→ 有pipeline队列？→ python3 pipeexec_runner.py --show → delegate_task
→ 有中断任务？→ 从next_action续跑
→ 没中断？→ 正常对话
→ 每步checkpoint → 每5轮compress → 完成sign到G0
```

---
