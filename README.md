<div align="center">
<p style="color: #ff0000; font-size: 24px; font-weight: bold; background: #fff0f0; padding: 16px 20px; border: 2px solid #ff0000; border-radius: 8px; display: inline-block;">
⚠️ 测试版！有可能导致 Hermes 崩溃或失效！<br>
务必先做好备份！<br>
务必先做好备份！<br>
务必先做好备份！
</p>
</div>

<br>

# Hermes 全量增强包

**让 Hermes Agent 从"能跑"变成"真他妈能打"**

---

## 这包是干啥的

Hermes Agent 本身是个通用 AI 代理框架。但默认状态下它：

- ❌ 不会主动调用自己的全量能力（有枪不用）
- ❌ 不会主动把复杂任务拆成多段（一口气干到超token）
- ❌ 偷懒进行降级实现（输出示例/示意/占位符糊弄你）
- ❌ 缺失长程记忆纠偏（做50轮对话后忘了最初目标）
- ❌ 任务队列管理薄弱（试试你就知道）

这个增强包把这五个问题全干了。**不是写规则让LLM自觉遵守，是底层代码注入强制它执行。**

---

## 怎么做到的

### 核心改动：run_agent.py 注入两个钩子

```python
run_agent.py (15679行核心对话循环, 零逻辑入侵)
  │
  ├── [L11725] PRE钩子 → agent_enhancement_manager.safe_hook_pre_conversation()
  │     在LLM回答之前执行21个插件，结果注入system prompt
  │     → LLM无法决定用不用武器——武器已经被系统调用了
  │     → LLM无法决定拆不拆任务——任务已经被系统分解了
  │
  ├── [L12266] System Prompt注入 → 强制上下文追加到system prompt
  │     2045 chars (~1227 tokens)，每轮对话LLM必读
  │
  └── [L15465] POST钩子 → agent_enhancement_manager.safe_hook_post_conversation()
        在LLM回答之后执行45个插件，结果写日志
        → 复盘/记忆提取/无损压缩/质量检查后台跑
```

关键点：**两个钩子总共7行try-except代码，任何异常都被捕获，不影响原始逻辑。** 插件文件被删了？跳过。插件抛异常了？跳过。Hermes照常运行。

### 66个插件矩阵

分两组：**21个PRE（对话前注入system prompt）+ 45个POST（对话后写日志）**

插件管理器 `agent_enhancement_manager.py` 维护一个注册表：

```python
_PLUGIN_REGISTRY = [
    # 每个插件(内部名, 文件路径, 类型, 启用, 描述)
    ("forced_executor", "scripts/forced_executor.py", "pre", True,
     "强制武器调用: ≥6武器×≥3阶段自动执行"),
    ("engine_core", "scripts/engine_core.py", "pre", True,
     "武器库注册中心: 970件能力扫描"),
    ("segment_manager", "scripts/segment_manager.py", "pre", True,
     "段管理器: 50轮自动切换"),
    # ... 共66个
]
```

每个插件要么有专门的调用函数（了解其真实API），要么通过子进程调用其main()捕获输出。没有通用猜测逻辑，每个插件都是"我知道它有什么方法，我精确调用它"。

---

## 插件清单

### PRE 21个（对话前执行，输出注入system prompt，LLM每次对话都能看到）

| 插件 | 注入内容 | 作用 |
|------|---------|------|
| **forced_executor** | 🔴6武器×3阶段已系统执行. 武器: xxx | **核心** — 强制武器调用+任务分解 |
| **engine_core** | [武器库状态] 960件 (scripts 264, skills 175... | LLM知道自己有什么能力 |
| **segment_manager** | 段2, 4/50轮 | LLM知道自己在对话的第几段 |
| **layered_planner** | P1-3 三层分层规划 | 复杂任务不慌，有规划 |
| **surgical_slicer** | task_type=general | 精准切分当前任务上下文 |
| **context_auto_assoc** | task_type=general | 跨段信息关联 |
| **context_failsafe** | RECOVERY_PACK updated | 断点保护 |
| **cross_session_cache** | session_count=2959 | 跨会话记忆 |
| **session_init_check** | ⚠️中断任务: xxx → 已完成 | 恢复中断任务 |
| **wake_guide** | Omni循环: ✅ 正常 | 系统健康状态 |
| **agent_company** | 员工130人 / 专家390人 | 知道自己有团队 |
| **agent_orchestrator** | [COMPANY] 部门状态 | 团队实时状态 |
| **multi_agent_orch** | Agent-C:94条, Agent-B:188条... | Agent集群数据 |
| **capability_registry** | total_capabilities=694 | 能力总量 |
| **master_integration** | 694 capabilities | 主集成状态 |
| **model_router** | 选择: deepseek-v4-flash | 模型自动路由 |
| **auto_recall** | 用户偏好... | 记忆召回 |
| **task_resumer** | 空content:raw=120 clean=291 push=12 | 任务断点 |
| **auto_resume_check** | ♻️任务未完成 | 中断恢复 |
| **camel_guard** | ✅安全检查通过 | 安全 |
| **monitor_engine** | signal=CONTINUE | 监控信号 |

### POST 45个（对话后执行，写入日志，下次对话可用）

按功能域分组：

| 域 | 插件 | 作用 |
|----|------|------|
| 📋 **质量检查** | consistency_guard, dod_checklist, tr_gate, system_selfcheck, system_audit, skillopt_trainer, production_reliability | 每轮对话后自检 |
| 🧠 **记忆系统** | hy_memory_orchestrator, l1/l2/l3, episodic_injector, memory_evolution, memory_highway, parallel_memory, tool_unloader, mermaid_builder, emergency_compressor | 记忆提取+压缩 |
| 🌀 **反思进化** | reflexion_engine, experience_extractor, gepa_variator, auto_cleaner, skill_evolver, self_evolution, self_enhance_v3, auto_tune | 自我改进 |
| 🔒 **安全** | hermes_super_guardian, reflector_engine | 安全审计 |
| 📤 **状态反馈** | status_reporter, feedback_push, generate_report | 主动汇报 |
| ⚙️ **自动修复** | auto_healer, gear_enforcer, gear_vault, gear_task_validator, gear_master, long_task_guardian | 系统自愈 |
| 🗜️ **压缩** | lossless_claw | 无损压缩 |

---

## 5个核心问题怎么解决的

### 问题1：不会主动调用武器

**Before**: 规则写在SOUL.md里"请调用武器"→LLM无视  
**After**: `forced_executor` 在PRE阶段自动执行武器，结果注入system prompt。LLM看到的是"6武器已经执行完毕"，**没机会决定用不用**

### 问题2：不会拆解任务

**Before**: 规则写"请分段执行"→LLM一口气干到超token  
**After**: PRE阶段分析任务类型→自动拆成≥3个阶段→每段分配武器→每段完成后保存检查点

### 问题3：输出示例/示意糊弄

**Before**: 写"禁止降级实现"→LLM继续输出示例  
**After**: 强制执行器注入"禁止输出示例,禁止说我来执行"到system prompt。POST阶段检测输出中是否有"示例/示意/占位符"关键词，有就记违规

### 问题4：长程对话记忆丢失

**Before**: 50轮对话后LLM忘了最初任务  
**After**: `segment_manager` 每50轮自动切换段，生成交接笔记（包含完成任务、关键决策），同步到cross_session_cache。下段LLM读交接笔记恢复上下文

### 问题5：长程任务漂移

**Before**: 做了100轮，方向早偏了  
**After**: `gear_enforcer` 每5段调用 `meta_thinker_auto()` 检测语义漂移。漂移分数>0.1时告警并自动纠偏

---

## Token消耗

| 指标 | 优化前 | 优化后 | 节省 |
|------|-------|-------|------|
| 每轮强制上下文 | 6767 chars (~4060 tokens) | **2045 chars (~1227 tokens)** | **69%** |
| 50轮一段 | ~338K chars (~203K tokens) | **~102K chars (~61K tokens)** | **~142K tokens** |

怎么省的：把11个插件的详细输出从"输出全文"改为"只输出摘要行"，完整内容写到文件，LLM需要时 `read_file`。

---

## 文件结构

```
hermes-full-enhancement-pack/
├── deploy.py                          # 一键恢复脚本
├── manifest.json                      # 完整性校验清单
├── README.md                          # 本文件
├── .gitignore
├── SOUL.md                            # 核心规则(15509字节)
├── AGENTS.md                          # 规则索引(8794字节)
├── config.yaml                        # 配置(API key已脱敏)
├── crontab.txt                        # 全部cron配置
├── hermes-agent/
│   ├── run_agent.py                   # 增强版(15679行, 7处注入)
│   └── run_agent.py.bak.*             # 原始备份
├── scripts/                           # 59个核心脚本
│   ├── agent_enhancement_manager.py   # 插件管理器(66插件)
│   ├── forced_executor.py             # 强制执行器(≥6武器×≥3阶段)
│   ├── engine_core.py                 # 武器库引擎(970件)
│   ├── segment_manager.py             # 段管理器
│   ├── task_queue_manager.py          # 任务队列
│   ├── gear_enforcer.py               # G1齿轮
│   ├── checkpoint_recorder.py         # 检查点
│   ├── lossless_claw.py               # 无损压缩
│   ├── restore_run_agent.py           # 恢复脚本
│   └── ...共59个
├── agent/                             # 3个监控模块
│   ├── monitor.py                     # P1监控引擎
│   ├── reflector.py                   # P1反射引擎
│   └── model_router.py                # 模型路由
├── auto_engine/                       # 4个自动引擎
│   ├── capability_registry.py         # 能力注册(694项)
│   ├── master_integration_hub.py      # 主集成枢纽
│   ├── multi_agent_orchestrator.py    # 多Agent编排
│   └── self_evolution_engine.py       # 自进化引擎
├── production_loop/                   # 8个生产可靠性模块
├── evolution_v3/                      # 6个V3进化模块
├── reports/
│   ├── context_sections/              # 49个章节文件
│   ├── context_index.json             # 上下文索引
│   ├── context_pack.json              # 上下文压缩包
│   └── ...其他报告
```

---

## 使用方式

```bash
# 1. 检查备份完整性(140个文件SHA256校验)
python3 deploy.py --check

# 2. 预览恢复操作(不写文件)
python3 deploy.py --dry-run

# 3. 恢复所有增强文件到 ~/.hermes/
# 恢复前自动备份现有run_agent.py
python3 deploy.py --restore
```

---

## 技术细节

### 插件加载机制

`_try_load()` → `_PLUGIN_CALLERS` 注册表 → 精确调用函数 / 子进程调用

```python
# 注册表里的每个插件都有精确的调用方式
_PLUGIN_CALLERS = {
    "forced_executor": lambda mod, ctx: _run_forced_executor(mod, task, ctx, agent_self),
    "engine_core": lambda mod, ctx: _run_engine_core(mod, ctx),
    "model_router": lambda mod, ctx: _run_model_router(mod, task, ctx),
    # 其他用子进程调用
    "surgical_slicer": lambda mod, ctx: _run_script_module_subprocess(mod, ctx),
}
```

### 上下文压缩策略

PRE阶段21个插件的输出合并成一个字符串，注入到system prompt。之前6767chars，现在2045chars。做了三件事：

1. **forced_executor**：从输出"8武器×4阶段详细报告"(~500chars)改为"🔴6武器×3阶段已系统执行. 武器: xxx"(~120chars)
2. **子进程插件**：`_run_script_module_subprocess` 从输出全文改为只取第一行含✅/❌/⚠️的摘要行
3. **capability_registry**：从输出全部类别改为只输出 `total_capabilities=694 | by_type={...}`

### 安全降级

- 插件文件不存在 → `os.path.exists()` 检查跳过
- 插件导入异常 → `try-except` 捕获，记录到 `_plugin_errors`
- 子进程超时 → 15s超时，记录到日志
- run_agent.py被破坏 → `restore_run_agent.py check/restore`
- 备份恢复 → `deploy.py --restore` 自动备份现有文件

---

## 作者

**Nurburgring-Zhang**

最后更新: 2026-06-02

声明：所有引用代码的所有权利归原作者所有
