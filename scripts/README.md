# 部署说明 / Deployment Guide

## 模型配置 (Model Configuration)

Hermes 使用模型梯队(Model Tier)系统来选择最合适的LLM:

| 梯队 | 名称 | 用途 | 说明 |
|------|------|------|------|
| value | 通用 | 日常任务 | 省钱方案，适合简单问答/摘要/常规工具调用 |
| performance | 强力 | 复杂任务 | 高性能方案，适合编程/架构/分析/推理 |

**不绑定具体模型名称** - 模型由 ModelRouter 根据 task_type 自动路由：
- task_type 包含 code/develop/编程/开发 → 自动选择代码专用模型
- 普通任务 → 通用模型
- 复杂分析 → 强力模型

切换命令: `--model-tier value` 或 `--model-tier performance`

## 部署检查

```bash
python3 scripts/deploy.py                    # 默认通用梯队
python3 scripts/deploy.py --model-tier value # 通用梯队
python3 scripts/deploy.py --performance      # 强力梯队
```

## Crontab 提醒

- 自进化集群: `0 */6 * * *` (每6小时)
- GEPA低分Skill进化: `0 4 * * *` (每天凌晨4点)
- 齿轮执行器: `* * * * *` (每分钟)
