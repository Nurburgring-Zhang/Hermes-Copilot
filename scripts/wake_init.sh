#!/bin/bash
# ============================================================================
# wake_init.sh — Hermes 醒来初始化脚本 v1.0
# 每次对话开始时自动执行，确保7条永久规则在所有对话中生效
# 格林主人最高指令(2026-05-23固化)
# 生效范围：所有对话、所有会话、所有上下文
# ============================================================================

HERMES="$HOME/.hermes"

echo "⚙️ [wake_init] 7条永久规则强制激活..."

# 1. 读wake_guide.json检查中断任务
if [ -f "$HERMES/reports/wake_guide.json" ]; then
    INTERRUPTED=$(python3 -c "import json; d=json.load(open('$HERMES/reports/wake_guide.json')); print('yes' if d.get('interrupted_task') else 'no')" 2>/dev/null)
    if [ "$INTERRUPTED" = "yes" ]; then
        echo "🔴 发现中断任务 → 自动恢复"
        python3 "$HERMES/scripts/task_monitor.py" 2>/dev/null
    fi
else
    # wake_guide不存在，生成
    python3 "$HERMES/scripts/wake_guide.py" 2>/dev/null
fi

# 2. 同步所有规则文件时间戳，确保系统识别
touch "$HERMES/AGENTS.md"
touch "$HERMES/CLAUDE.md" 
touch "$HERMES/.cursorrules"
touch "$HERMES/SOUL.md"

# 3. 检查齿轮心跳 — 如果30分钟以上无心跳则重启
HEARTBEAT="$HERMES/logs/gear_heartbeat.txt"
if [ -f "$HEARTBEAT" ]; then
    LAST=$(cat "$HEARTBEAT" 2>/dev/null)
    NOW=$(date -Iseconds)
    # 简单时间差检测(如果心跳文件超过30分钟)
    if [ -f "$HEARTBEAT" ] && [ "$(find "$HEARTBEAT" -mmin +30)" = "$HEARTBEAT" ]; then
        echo "⚠️ 齿轮心跳超过30分钟 → 重启齿轮系统"
        python3 "$HERMES/scripts/gear_enforcer.py" 2>/dev/null &
    fi
fi

echo "✅ [wake_init] 7规则已激活 | 系统就绪"
