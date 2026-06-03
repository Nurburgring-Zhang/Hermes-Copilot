# Hermes 全量强化

测试版！！！
必须做好备份或者新开Hermes！！！
必须做好备份或者新开Hermes！！！
必须做好备份或者新开Hermes！！！

**让 Hermes Agent 从"能跑"变成"真他妈能打"**

## 这是什么

这是 Hermes Agent 的全量强化备份包。包含完整的底层强化代码、全部脚本、配置、cron任务和生产级引擎。

## 强化了什么

Hermes Agent 本身是个通用 AI 代理框架。但默认状态下它：不会主动调用自己的全量能力、不会主动把复杂任务拆成多段、偷懒进行降级实现、缺失长程记忆纠偏、任务队列管理薄弱。

这个备份包把这五个问题全干了。**不是写规则让LLM自觉遵守，是底层代码注入强制它执行。**

### 核心注入

**PRE钩子** — 在 `agent/conversation_loop.py` 中注入，每次LLM调用前自动执行21个插件，结果注入system prompt。LLM无法决定用不用武器——武器已经被系统调用了。

**POST钩子** — 在 `run_agent.py` 中注入，每次对话返回后自动执行45个插件，复盘/记忆提取/无损压缩/质量检查后台跑。

### 66个插件矩阵

| 类型 | 数量 | 作用 |
|------|------|------|
| PRE（对话前注入） | 21 | 强制武器调用、段管理、任务分解、记忆召回、安全检测 |
| POST（对话后处理） | 45 | 复盘反思、记忆提取、自进化、安全审计、状态反馈、自动修复 |

### 齿轮系统 G0-G8

每分钟到每30分钟循环，确保系统永远在线：
- G1: gear_enforcer — 中断检测+AI评分
- G2: context_failsafe — 断点保护
- G3: gear_context_compressor — 上下文压缩检查点
- G4: hermes_retrospect — 复盘审计
- G5: hermes_super_guardian — 全系统兜底
- G6: gear_task_validator — 完整性验证
- G7: wake_guide — 醒来指南
- G8: production_loop_cron — 生产可靠性

齿轮之间相互啮合互审：G1写wake_guide→G2验证G1心跳→G3验证G2恢复包→G5全系统兜底→G6验证G0到G5全链。任何一个齿轮失效都会被上游发现并触发修复。

### 记忆系统

- L1提取: 每2小时从对话中提取语义事实
- L2场景: 每6小时归纳场景模式
- L3画像: 每天生成用户画像
- 关键词权重自动进化

## 无损记忆压缩与token节省

### 三级无损压缩引擎（compression_engine.py）

合并自9个压缩脚本的统一压缩引擎，包含7大模块：

**LosslessClawCompressor（三级无损压缩）**
对话上下文经过三级压缩，上下文使用量降低60-70%，无信息损失：
- Level 1（zlib快速压缩）: 即时压缩当前会话，压缩比约30-50%
- Level 2（gzip中等压缩）: 周期压缩低频访问数据，压缩比约50-70%
- Level 3（深度归档）: 7天以上低访问数据归档，压缩比约70-90%

每个级别都带SHA256校验和，解压时逐字节验证完整性。

**EmergencyCompressor（三级紧急压缩）**
当对话上下文token超过阈值时自动触发：
- Mild（50%）: 用[ref:xxx]摘要标记替换大块工具输出
- Aggressive（85%）: 从头部删除旧轮次，保留最后1/3
- Emergency（92%）: 仅保留最后1/5轮次，插入紧急压缩标记

**RTK压缩器（实时token杀手）**
- HTML→净文本（剥离script/style标签，压缩比可达80%）
- 文本去重（相似度>0.9段落合并）
- JSON瘦身（移除null/空数组/元数据字段，截断长列表）
- 根据背压级别动态调整压缩比

**ContextCompressor（对话/检查点压缩）**
每次关键步骤后自动压缩对话历史到数据库，对话中只传摘要ref，完整内容按需读文件。

**FidelityValidator（五级保真度验证）**
每次压缩后自动验证：
- L1: 字节级完整性（md5校验）
- L2: 语义完整性（关键术语保留率）
- L3: 结构完整性（JSON/格式保持）
- L4: 压缩比合理性
- L5: 传输/存储完整性

### token节省对比

| 场景 | 优化前 | 优化后 | 节省 |
|------|--------|--------|------|
| 每轮强制上下文 | 6767 chars (~4060 tokens) | 2045 chars (~1227 tokens) | **69%** |
| 50轮对话一段 | ~338K chars (~203K tokens) | ~102K chars (~61K tokens) | **~142K tokens** |
| 大工具结果卸载 | 完整输出留在上下文 | [ref:xxx]摘要标记，完整内容写文件 | **数千tokens/次** |
| 老旧数据归档 | 永久留在cleaned_intelligence | 归档到compressed_intelligence | **数据库减少70%+** |
| 7天+低访问检查点 | 占用存储和查询时间 | L3深度归档，VACUUM回收空间 | **存储减少80%+** |

### 工具卸载器

每次工具调用结果大于2KB时自动拦截，卸载到refs/*.md文件，上下文只留 `[ref:xxx]` 摘要标记。调用 `tool_unloader.cleanup_expired()` 定期清理过期ref。

### 记忆高速公路

每30分钟自动运行的全量记忆持久化管道：
1. 从intelligence.db获取系统统计
2. 备份到active_memory.db
3. 注入memory API（真实持久化，不是模拟）
4. 清理7天前旧记录
5. 关键词权重自动进化

## 长程任务执行

### 三层反思结构化规则

每轮对话自动执行三层递进反思：
- **操作层**（每步后）：这一步做得对不对？结果是否符合预期？
- **策略层**（每3步后）：当前策略是否有效？是否需要换方法？
- **目标层**（每10步后）：整体方向是否正确？是否需要重新规划？

### 段管理器（segment_manager）

每50轮对话自动切换段，生成交接笔记（包含完成任务、关键决策），下一段LLM读交接笔记恢复上下文。当前段: 2/5，总104轮，齿轮状态healthy。

### 任务分解与强制武器调用

对话开始时自动分析任务类型，拆成3个以上阶段，每阶段分配武器，每段完成后保存检查点到`task_current.json`。POST阶段检测输出是否有"示例/示意/占位符"关键词，有就记违规。

### 执行质量墙

- 每步检查：每完成一个子任务验证输出
- 里程碑检查：每3个子任务检查整体方向
- 方向对齐：复杂任务中途检查是否偏离原始目标
- 超过10步的任务保存中间检查点

### 生产级可靠性引擎（8模块）

| 模块 | 作用 |
|------|------|
| loop_state.py | 全局状态管理 |
| dag_manager.py | DAG任务图编排 |
| engine.py | 确定性主循环 |
| main_loop.py | 主循环执行器 |
| agent_committee.py | 专家委员会(6子代理) |
| verification.py | 步骤验证器 |
| security.py | 7层权限系统 |
| dag_manager.py | 降级拦截器(5种模式检测) |

每10分钟cron检查，每30分钟Critic审计，每2小时深度检查。

### 复盘反思引擎

每次对话返回后自动执行复盘反思：
1. 目标回顾 vs 实际完成
2. 五维度质量评分（功能/正确/完整/质量/可维护）
3. 经验提取+知识固化
4. 评分<60自动触发Skill进化候选

### 自进化集群（每天03:00）

- 技能自动进化: 扫描全部skill，检测重复，生成改进提案
- 记忆压缩: 清理60天+数据，合并重复关键词
- Token压缩: FTS5重建，清理空会话
- 能力进化: 关键词权重微调(+5%~+10%)

### 外部集成

- **WebUI**: http://127.0.0.1:8899 网页端管理 Hermes
- **GBrain桥接**: 知识图谱检索+实体提取+关系查询
- **Desktop桥接**: 会话管理+技能管理+会话缓存

## 怎么恢复

### 一键恢复（推荐）

```bash
cd M:\Hermes\hermes_full_backup_20260603_0109
python3 restore.py
```

脚本自动完成以下步骤：
1. 检测备份完整性
2. 备份当前 Hermes 状态到 /tmp/
3. 恢复核心引擎（run_agent.py + conversation_loop.py 钩子注入）
4. 恢复全部259个强化脚本
5. 恢复agent监控模块（监控/反射/路由）
6. 恢复 SOUL.md + AGENTS.md 核心规则
7. 恢复生产引擎（8模块）+ 进化引擎（18模块）
8. 恢复53条cron任务（齿轮+记忆+进化+安全）
9. 启动 WebUI
10. 验证全部11项强化能力

### 指定备份目录

```bash
python3 restore.py --backup /path/to/backup
```

### 仅检查不恢复

```bash
python3 restore.py --check
```

### 强制覆盖不确认

```bash
python3 restore.py --force
```

## 备份内容

```
hermes_full_backup_20260603_0109/
├── restore.py              # 一键恢复脚本
├── MANIFEST.txt            # 备份清单
├── run_agent.py            # 核心引擎(POST钩子已注入)
├── conversation_loop.py    # 对话循环(PRE钩子已注入)
├── SOUL.md                 # 核心规则
├── AGENTS.md               # 规则索引
├── crontab.txt             # 全部cron配置(53条)
├── scripts/                # 259个强化脚本
│   ├── agent_enhancement_manager.py  # 66插件管理器
│   ├── compression_engine.py         # 压缩引擎(9合1: 三级无损+紧急+RTK+保真度验证)
│   ├── memory_engine.py              # 记忆引擎(7合1)
│   ├── orchestrator.py               # 编排引擎(5合1)
│   ├── memory_tools.py               # 记忆工具(3合1)
│   ├── gear_enforcer.py              # G1齿轮
│   ├── segment_manager.py            # 段管理器(50轮自动切换)
│   ├── hermes_retrospect.py          # 复盘引擎
│   ├── hermes_camel_guard.py         # CaMeL安全护栏
│   ├── gbrain_bridge.py              # GBrain知识桥接
│   ├── desktop_bridge.py             # Desktop会话管理
│   └── ...共259个
├── agent/                  # 3个监控模块
├── production_loop/        # 8个生产可靠性模块
└── evolution_v3/           # 18个V3进化模块
```

## 验证清单

恢复完成后，脚本自动验证以下11项：

1. PRE钩子（conversation_loop.py）
2. POST钩子（run_agent.py）
3. 66插件管理器
4. compression_engine统一模块
5. memory_engine统一模块
6. orchestrator统一模块
7. memory_tools统一模块
8. WebUI（8899端口）
9. 齿轮cron（gear_enforcer）
10. 记忆cron（l1_extractor）
11. 进化cron（self_evolve）

全部通过即表示强化体系完全生效。

## 作者

**Nurburgring-Zhang**

最后更新: 2026-06-03

声明：所有引用代码的所有权利归原作者所有
