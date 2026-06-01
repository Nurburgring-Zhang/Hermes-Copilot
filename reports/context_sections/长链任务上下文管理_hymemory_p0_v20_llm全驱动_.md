## 长链任务上下文管理（Hy-Memory P0 v2.0 LLM全驱动）

**全部能力已集成LLM深度辅助**，不再纯机械执行：

| 能力 | LLM辅助方式 | LLM可用时 | LLM不可用时 |
|------|------------|-----------|------------|
| `task_boundary.py` | 语义理解任务边界 | LLM理解隐含意图（"搞定了，说另一个事"→新任务） | 规则引擎90%准确率 |
| `auto_recall.py` | LLM筛选召回质量 | LLM评估每条召回对当前问题的语义相关性 | RRF关键词匹配 |
| `tool_unloader.py` | LLM判断卸载优先级 | LLM评估结果价值(high/low)，高价值保留更久 | 机械2KB阈值 |
| `episodic_injector.py` | LLM生成情景摘要 | LLM提取核心信息+标签+重要性评分 | 关键词提取 |
| `skillopt_trainer.py` | LLM验证Skill质量 | LLM评估5维度(触发/步骤/故障/验证/可读性) | 规则引擎结构检查 |
| `self_evolution_engine.py` | LLM生成进化建议 | LLM分析性能数据给出有洞察的建议 | 固定模板建议 |
| `l1_extractor.py` | LLM提取事实 | LLM语义级提取persona/episodic/instruction三类事实 | 规则引擎关键词 |
| `l2_scene_scheduler.py` | LLM归纳场景 | LLM分析事实生成场景块 | 按类别分组 |
| `l3_persona_scheduler.py` | LLM生成画像 | 四层深度扫描生成用户画像 | 仅标记不可用 |

**自动模式（推荐）**：每次 execute_code 中：
```python
from scripts.tool_wrapper import install_hooks
install_hooks()  # 所有 terminal/read_file/search_files 自动LLM评估后卸载
```

**手动模式**：
```python
from scripts.tool_wrapper import T
result = T.read_file(...)  # >2KB + LLM高价值判断 → refs/*.md
```
