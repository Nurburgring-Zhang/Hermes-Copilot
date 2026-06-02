# Hermes 全量强化

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
- G4: hermes_retrospect — 复盘审计
- G6: gear_task_validator — 完整性验证
- G8: production_loop_cron — 生产可靠性

### 记忆系统

- L1提取: 每2小时从对话中提取语义事实
- L2场景: 每6小时归纳场景模式
- L3画像: 每天生成用户画像
- 关键词权重自动进化

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
│   ├── compression_engine.py         # 压缩引擎(9合1)
│   ├── memory_engine.py              # 记忆引擎(7合1)
│   ├── orchestrator.py               # 编排引擎(5合1)
│   ├── memory_tools.py               # 记忆工具(3合1)
│   ├── gear_enforcer.py              # G1齿轮
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
