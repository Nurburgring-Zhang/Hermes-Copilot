#!/usr/bin/env python3
"""
🔬 OI全文档优化方案提取器 v1.0
从6份OI文档中提取所有优化/强化/进化/增强方案
"""

import json
from pathlib import Path

# ============================================================
# 以下是从6份文档中提取的所有方案（去重+归类）
# ============================================================

MASTER_PLANS = {
    "title": "OI集成增强·所有方案全清单",
    "version": "v1.0",
    "source_docs": [
        "1. OI项目极端详细开发文档（融合增强 v4.0）",
        "2. OI项目国内生态开发文档（v5.0）",
        "3. 面向Hermes Agent/OpenHuman的自我强化增强计划",
        "4. Mnemosyne与任务的全域持久能力提升优化方案",
        "5. hermes agent自我强化与长期记忆技术解决方案",
        "6. Hermes_Agent_OpenHuman_自我强化技术解决方案_Windows版"
    ],
    "categories": {}
}

# ===== 一、记忆系统 =====
MASTER_PLANS["categories"]["一、记忆系统（持久记忆引擎）"] = {
    "priority": "最高",
    "description": "所有涉及记忆增强、持久化、压缩、检索的方案集合",
    "items": [
        {
            "name": "OPME七通道记忆架构",
            "source": ["doc1", "doc4"],
            "channels": [
                "语义向量通道（语义嵌入检索）",
                "实体图谱通道（知识图谱关联）",
                "时间线通道（时间序列检索）",
                "关键词/全文通道（FTS5全文搜索）",
                "扩散激活通道（联想扩散）",
                "整合记忆通道（跨通道融合）",
                "Hopfield联想通道（Hopfield网络联想）"
            ],
            "arbiter": "预过滤(信号vs噪音) + 交叉评分(历史准确率+上下文匹配度) + 加权融合",
            "code": "evolution_v3/seven_channel_memory.py"
        },
        {
            "name": "五层记忆模型（L0-L4）",
            "source": ["doc3", "doc4", "doc5", "doc6"],
            "levels": [
                "L0瞬时/感知记忆：环形缓冲区+注意力过滤，0.2-4秒",
                "L1工作记忆：8K-128K tokens，当前会话，五索引并立（向量+图谱+全文+时间+Skills）",
                "L2短期记忆（热/温/冷三层）：GB级，0-30天，Redis(热)→PostgreSQL(温)→对象存储(冷)",
                "L3长期记忆：TB级，永久，ZEP Graphiti时序知识图谱+A-MEM笔记网络+差分压缩",
                "L4永久记忆(参数级)：理论永久，MemOS动态转换+LoRA蒸馏(1.2TB→35MB)"
            ]
        },
        {
            "name": "三冗余记忆引擎",
            "source": ["doc3", "doc4"],
            "engines": [
                "Hindsight（四路并行检索+Cross-Encoder重排序，PostgreSQL+embedding）",
                "M-Flow（Rust编译图引擎，RocksDB存储）",
                "MemOS（纯Python，PostgreSQL+Qdrant双后端）"
            ],
            "orchestrator": "MemoryOrchestrator类，asyncio+aiohttp，三引擎通过localhost端口通信",
            "read_write": "写入流：三引擎同步写入；读取流：RRF+交叉验证；自检流：每日一致性校验"
        },
        {
            "name": "三路径压缩管道+压缩仲裁器",
            "source": ["doc1", "doc4", "doc5", "doc6"],
            "paths": [
                "路径零：TokenJuice基础管道（HTML→Markdown+URL缩短，Token降低80%）",
                "路径一：R³Mem可逆层级压缩（压缩比64:1）",
                "路径二：SimpleMem语义结构化压缩（F1提升26.4%，Token降低30倍）",
                "路径三：增量差分编码（每30天基准快照）"
            ],
            "arbiter": "压缩仲裁器交叉验证，语义指纹比对>0.95确认",
            "more": [
                "delta-ltsc无损差分压缩",
                "Hypernym Mercury上位词语义压缩",
                "Structurally Lossless Trimming"
            ]
        },
        {
            "name": "认知退化模型（非删除式遗忘）",
            "source": ["doc1"],
            "description": "遗忘定义为极低精度存储而非删除",
            "levels": [
                "Active 32-bit（活跃记忆）→ Warm 8-bit（温记忆）→ Cold 4-bit（冷记忆）→ Archive 2-bit（归档）"
            ]
        },
        {
            "name": "Sleeptime深度整合",
            "source": ["doc1", "doc4"],
            "time": "凌晨2:00-5:00",
            "operations": [
                "递归合并情景记忆为语义记忆",
                "更新摘要层级",
                "清理矛盾记忆",
                "记忆预演",
                "Auto Dream（自动梦生成新关联）"
            ]
        },
        {
            "name": "永久记忆动态转换机制",
            "source": ["doc6"],
            "trigger": "高频访问≥7天10次 → 激活记忆(KV Cache)；6月稳定+精度损失<2%+3任务验证 → 参数记忆(LoRA注入)",
            "fallback": "6月零访问或知识过时 → 回退纯文本"
        },
        {
            "name": "LCM DAG递归凝练",
            "source": ["doc4"],
            "mechanism": "超出阈值自动生成Leaf摘要→同层积累到阈值→向上凝练更高层抽象→递归上下文压缩",
            "storage": "SQLite持久化存储摘要节点",
            "xml_format": "XML格式包装节点ID/深度/时间范围"
        }
    ]
}

# ===== 二、任务执行引擎 =====
MASTER_PLANS["categories"]["二、任务执行引擎（MPESCE架构）"] = {
    "priority": "最高",
    "description": "所有涉及任务执行、多路径规划、上下文管理的方案集合",
    "items": [
        {
            "name": "DPW双规划器+见证者架构",
            "source": ["doc1", "doc6"],
            "components": [
                "规划器A：Tree-of-Thoughts，系统性，保守",
                "规划器B：ReAct，直觉性，激进",
                "见证者：比较裁决，一致>0.8执行，不一致则反思重规划（最多3轮）",
                "TACT激活校准集成"
            ],
            "layered_activation": "简单任务单规划器，中等任务双规划器抽样检查，复杂任务完整DPW"
        },
        {
            "name": "KDN关键决策节点审计器",
            "source": ["doc1", "doc6"],
            "triggers": "不可逆外部效果、改变目标、消耗大量资源、多Agent协调",
            "process": "摘要→语义距离计算→阈值0.3触发警报→双重确认",
            "levels": "低→不需要、中→审计器单确认、高→见证者+审计器双确认"
        },
        {
            "name": "三级纠偏注入",
            "source": ["doc1"],
            "levels": [
                "轻度[0.3,0.5)：提示性纠偏，最多3次",
                "中度[0.5,0.7)：强行回退N步，最多2次",
                "重度>0.7：完全重置+复盘+失败案例注入+通知用户"
            ],
            "experience_pool": "纠偏经验库记录到记忆系统，越用越聪明"
        },
        {
            "name": "COMPASS三层架构（上下文管理器+主Agent+Meta-Thinker）",
            "source": ["doc5", "doc6"],
            "layers": [
                "Context Manager：组织和综合执行历史，生成优化Context Briefs",
                "Main Agent：ReAct循环战术执行",
                "Meta-Thinker：战略监督者，漂移检测与干预（Pivot/Verify）"
            ]
        },
        {
            "name": "上下文管理热/温/冷三层",
            "source": ["doc5", "doc6"],
            "hot": "最近10轮，完整逐字存储",
            "warm": "第11-40轮，滚动详细摘要",
            "cold": "更早历史，压缩为广泛摘要"
        },
        {
            "name": "四级漂移检测与校正",
            "source": ["doc5", "doc6"],
            "L1": "软提醒 — MeaningBERT<阈值，注入目标提醒",
            "L2": "自动回滚 — SGDCI确认不一致，回滚至最近Checkpoint",
            "L3": "Meta-Thinker — 三层检测均确认深层漂移，重写Context Brief+重新规划",
            "L4": "人工介入 — 恶意漂移/3次回滚失败，任务暂停+人工裁决"
        },
        {
            "name": "Kitaru+LangGraph双持久化检查点",
            "source": ["doc3", "doc6"],
            "kitaru": "ZenML引擎+PostgreSQL后端，checkpoint_strategy=function级断点",
            "langgraph": "PostgresSaver检查点持久化，链表快照支持历史回放和分支探索",
            "recovery_Target": "恢复时间目标<5秒"
        },
        {
            "name": "DAG子任务解耦（TDP）",
            "source": ["doc6"],
            "benefit": "Token消耗减少82%，子任务分解+错误隔离+并行调度"
        },
        {
            "name": "任务状态机规则",
            "source": ["doc4"],
            "states": "IDLE→PLANNING→EXECUTING→VERIFYING→DEVIATION_DETECTED→SELF_HEALING→COMPLETED"
        },
        {
            "name": "TodoWrite/Task七大工具",
            "source": ["doc1"],
            "tools": ["TaskCreate", "List", "Get", "Update", "Stop", "Claim", "Output"],
            "persistence": "双写策略：JSON文件+PostgreSQL",
            "philosophy": "工具，不是调度器"
        },
        {
            "name": "PIVOT跨任务联合推理",
            "source": ["doc1"],
            "steps": "PLAN→INSPECT→EVOLVE→VERIFY",
            "for": "目标相似/实体共享/依赖/冲突四种关联类型的跨任务知识关联"
        },
        {
            "name": "CaveAgent双流运行时",
            "source": ["doc4"],
            "architecture": "持久化Python运行时作为中心状态，轻量级语义流作为编排器"
        }
    ]
}

# ===== 三、自我强化/进化引擎 =====
MASTER_PLANS["categories"]["三、自我强化/进化引擎"] = {
    "priority": "最高",
    "description": "所有涉及自我进化、强化学习、技能固化的方案集合",
    "items": [
        {
            "name": "三级自我强化循环（日/周/月）",
            "source": ["doc1"],
            "daily": "凌晨1:00：记忆健康度扫描+纠偏经验统计+安全规则更新+Auto Dream",
            "weekly": "周日3:00：Sleeptime深度整合+规划器权重微调(CASE框架)+安全态势评估+跨任务关联图谱重建",
            "monthly": "第一周日4:00：全系统健康度评估+SAR自检报告+GEPA遗传优化+防护策略升级+知识库版本快照"
        },
        {
            "name": "GEPA遗传优化器",
            "source": ["doc1", "doc5"],
            "mechanism": "分析Agent执行记录→自动生成改良版技能指令和系统提示",
            "performance": "比GRPO平均高出6%，所需数据量仅1/35，每次优化成本$2-10",
            "comparison": "比RL快35倍"
        },
        {
            "name": "CASE框架模型编辑",
            "source": ["doc1"],
            "capability": "终身模型编辑，1000次编辑后准确率提高近10%，额外参数不足1MB"
        },
        {
            "name": "五环节学习循环（自我记忆→自我技能→回顾强化→自我输出→安全审计）",
            "source": ["doc3"],
            "steps": [
                "自我记忆：三记忆引擎同步写入",
                "自我技能：高频成功模式自动提炼为Skill文件",
                "回顾强化：Nudge Engine定时回顾历史任务（Windows Task Scheduler触发）",
                "自我输出：新任务关联Skill自动加载",
                "安全审计：SEPL协议版本管理和回滚"
            ]
        },
        {
            "name": "SelfEvolution Engine六步循环",
            "source": ["doc4"],
            "steps": "Observe(日志记录)→Analyze(失败模式)→Propose(改进方案)→Human Review→Apply(合并)→Verify(验证)"
        },
        {
            "name": "HyperAgents自指性架构",
            "source": ["doc4"],
            "feature": "任务智能体与元智能体合为一个可编辑程序",
            "benchmark": "100次迭代后自主发明持久记忆系统+性能追踪，跨领域迁移"
        },
        {
            "name": "Memento-Skills Read-Write反射学习循环",
            "source": ["doc4"],
            "feature": "零参数更新的持续学习",
            "benchmark": "从5个原子技能自动增长到235个技能，GAIA提升26.2%，Humanity's Last Exam提升116.2%"
        },
        {
            "name": "SkillOS体验驱动RL训练",
            "source": ["doc4"],
            "feature": "训练技能策展器更新外部SkillRepo，实现技能库自主优化增长"
        },
        {
            "name": "反思微调（每15轮强制反思）",
            "source": ["doc1", "doc5"],
            "trigger": "每15轮/10次工具调用",
            "action": "强制触发反思→生成结构化Skill→后续任务速度提升40%"
        },
        {
            "name": "Council仲裁机制（四轮共识）",
            "source": ["doc4"],
            "rounds": "第1轮独立提案→第2轮交叉评审(AutoGen协商式对话)→第3轮修正提案→第4轮投票共识"
        },
        {
            "name": "三条自我固化路径",
            "source": ["doc6"],
            "deepest": "SFT/RL训练（权重级，小时-天）",
            "medium": "RPA代码生成（代码级，分钟-小时）",
            "shallow": "知识库构建（知识级，秒-分钟）"
        },
        {
            "name": "催化回路（R1-R4）",
            "source": ["doc1"],
            "R1": "记忆驱动的任务优化：记忆检索→推送规划器→执行后写入→更新权重→越执行越聪明",
            "R2": "安全-记忆相互强化：异常模式→安全知识图谱→预警←→记忆访问监控",
            "R3": "Skills的知识结晶：记忆识别模式→执行引擎提建议→安全验证→新Skill入生态",
            "R4": "Hooks驱动的实时自适应：事件触发→安全评估→策略调整→记录经验→未来优化"
        }
    ]
}

# ===== 四、安全引擎 =====
MASTER_PLANS["categories"]["四、安全引擎（DDSPE五层纵深防御）"] = {
    "priority": "高",
    "description": "所有涉及数据安全、隐私保护、审计的方案集合",
    "items": [
        {
            "name": "DDSPE五层纵深防御",
            "source": ["doc1"],
            "layers": [
                "物理与OS安全（BitLocker全盘加密）",
                "网络微隔离（Windows防火墙+IPSec，所有服务绑定127.0.0.1）",
                "应用沙箱（Windows Sandbox+WSL2沙盒+LiteBox Library OS）",
                "数据安全（AES-256-GCM+链式哈希审计+隔离记忆区）",
                "审计与异常检测（Windows事件日志+Wazuh FIM+安全事件自动隔离）"
            ]
        },
        {
            "name": "零信任AI七支柱+DMEG四维空间",
            "source": ["doc6"],
            "principles": "数据不出域、不落盘、不缓存（纯内网闭环三不原则）",
            "methods": [
                "差分隐私联邦学习（FATE框架，ε≤3.0，BERT微调仅损失2.4%）",
                "FHE全同态加密（Zama Concrete-ML，加密状态下推理，延迟<2秒）",
                "零信任mTLS双向认证+Agent唯一加密身份"
            ],
            "audit": "联盟链+Merkle树+时间戳，100%操作可追溯"
        },
        {
            "name": "安全等级L0-L3",
            "source": ["doc1"],
            "L0": "公开→全部访问",
            "L1": "内部→授权用户",
            "L2": "机密→精度降低",
            "L3": "绝密→审计增强"
        },
        {
            "name": "安全事件分级",
            "source": ["doc1"],
            "P0": "严重→立即隔离",
            "P1": "高级→通知管理员",
            "P2": "中级→24小时审查",
            "P3": "低级→日志汇总"
        }
    ]
}

# ===== 五、架构原则 =====
MASTER_PLANS["categories"]["五、设计原则与架构规则"] = {
    "priority": "最高",
    "description": "所有必须固化的设计原则和架构规则",
    "items": [
        {
            "name": "四大根本设计原则",
            "source": ["doc1", "doc6"],
            "principles": [
                "多方法相互啮嵌与催化——不信任单一方法",
                "信息守恒与可验证性——压缩操作的语义等价性必须可检验",
                "全链路本地化与零信任——所有数据通路在设备边界内闭环",
                "渐进演进与可测量性——每个组件具备可测量指标和可验证标准"
            ]
        },
        {
            "name": "三三制生物免疫式多样性冗余原则",
            "source": ["doc6"],
            "rule": "每层部署至少3种独立方法（方法A主路径、方法B独立备份、方法C监督验证），算法原理/实现代码/故障模式三者均不同",
            "consensus": "小群体内加权共识(CP-WBFT)，群体间事件驱动解耦(MCP+A2A)"
        },
        {
            "name": "信息保真核心（IFC）架构",
            "source": ["doc6"],
            "core": "记忆、任务、安全三个子系统围绕统一的无损压缩内核进行啮嵌设计",
            "sub_principles": [
                "核心收敛原则——所有信息流必经无损压缩核心",
                "子系统啮嵌原则——三个子系统接口围绕压缩核心设计",
                "多样性冗余原则——每个子系统至少运行3种独立方法",
                "时间分层原则——热数据全精度、温数据无损压缩、冷数据无损归档+冗余备份"
            ]
        },
        {
            "name": "Windows原生部署（严禁Docker/WSL2容器）",
            "source": ["doc1", "doc3", "doc4", "doc5", "doc6"],
            "rule": "所有组件以Windows原生方式安装运行，exe安装包+PowerShell脚本+Windows服务注册(NSSM/WinSW)",
            "toolchain": "Ollama(exe)+ChromaDB/Qdrant(pip)+NSSM(服务管理)+Caddy(反向代理)+uv(包管理)"
        },
        {
            "name": "事件驱动Hooks系统（八事件）",
            "source": ["doc1"],
            "events": [
                "PreToolUse→KDN审计器",
                "PostToolUse→审计日志",
                "SessionStart→记忆预加载",
                "SessionEnd→context_handoff",
                "UserPromptSubmit→安全过滤",
                "KDNTriggered→事件响应",
                "SubagentStart→生命周期管理",
                "SubagentStop→结果汇总"
            ]
        },
        {
            "name": "子Agent独立上下文管理",
            "source": ["doc1"],
            "rules": [
                "独立系统提示",
                "精选工具权限集",
                "隔离上下文窗口",
                "完成后返回压缩摘要",
                "与AppContainer沙箱结合",
                "生命周期Hooks事件"
            ]
        },
        {
            "name": "3+1矩阵架构全景",
            "source": ["doc1"],
            "horizontal": "Tauri Shell层→Rust Core层→React前端层",
            "vertical": "持久记忆引擎+多路径任务执行引擎+纵深防御安全引擎",
            "cross": "Skills生态系统作为横向串联层"
        }
    ]
}

# ===== 六、Token/性能优化 =====
MASTER_PLANS["categories"]["六、Token与性能优化"] = {
    "priority": "高",
    "description": "所有涉及Token消耗、推理性能的方案集合",
    "items": [
        {
            "name": "TokenJuice智能压缩",
            "source": ["doc1", "doc5"],
            "effect": "HTML→Markdown+长URL缩短，Token消耗降低高达80%"
        },
        {
            "name": "Mermaid上下文卸载",
            "source": ["doc4"],
            "effect": "Token消耗降低61%，成功率提升52%"
        },
        {
            "name": "Mem0记忆层",
            "source": ["doc4"],
            "effect": "减少90%的LLM调用成本"
        },
        {
            "name": "TriAttention注意力优化",
            "source": ["doc5"],
            "effect": "10.7倍内存降低"
        },
        {
            "name": "GPU推理优化",
            "source": ["doc1"],
            "effect": "INT8/INT4量化，延迟降低2-4倍，内存减少50%-75%"
        },
        {
            "name": "LRU缓存",
            "source": ["doc1"],
            "effect": "命中率40%-60%"
        },
        {
            "name": "大工具输出写磁盘仅2KB预览",
            "source": ["doc1"],
            "effect": "借鉴Claude Code第1层策略"
        },
        {
            "name": "动态上下文发现模式",
            "source": ["doc1"],
            "effect": "工具响应转文件，按需读取"
        }
    ]
}

# ===== 七、多Agent协作 =====
MASTER_PLANS["categories"]["七、多Agent协作与工作流"] = {
    "priority": "中",
    "description": "所有涉及多Agent协作、通信的方案集合",
    "items": [
        {
            "name": "A2A协议（NATS JetStream）",
            "source": ["doc3", "doc4"],
            "description": "NATS Server + nats-py发布/订阅，Agent到Agent通信"
        },
        {
            "name": "ACP协议",
            "source": ["doc3"],
            "description": "通过subprocess调用外部编码Agent（Claude Code）"
        },
        {
            "name": "六模块全自动激活调度系统",
            "source": ["doc3"],
            "modules": [
                "Capability Registry → PostgreSQL注册中心",
                "Capability Graph → Qdrant向量索引+Ontology知识图谱",
                "Task Dispatcher → NATS+A2A协议动态多Agent选择",
                "DAG任务拆解 → Commander LLM自动拆解为并行子任务",
                "Skill Chain Orchestrator → 自动串联多Skill为流水线",
                "Result Aggregator → 收集输出+部分失败自动重分发"
            ]
        },
        {
            "name": "Crew认知五操作",
            "source": ["doc4"],
            "operations": ["encode", "consolidate", "recall", "extract", "forget"]
        }
    ]
}

# 输出
print(json.dumps(MASTER_PLANS, ensure_ascii=False, indent=2))
print(f"\n\n共 {len(MASTER_PLANS['categories'])} 大类")
total = sum(len(v['items']) for v in MASTER_PLANS['categories'].values())
print(f"共 {total} 个子方案")
