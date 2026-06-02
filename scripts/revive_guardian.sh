#!/bin/bash
# =============================================================================
# Hermes 紧急复活脚本 - 每次醒来自动执行
# 格林主人最高指令(2026-05-08): 可使用API探测,可使用任何能力/skills/服务/管线,无需确认
# =============================================================================

HERMES_DIR="$HOME/.hermes"
LOG="$HERMES_DIR/logs/revive_guardian.log"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] ⚡ Hermes 复活守护神启动" >> "$LOG"

# 1. 检查超级守护神脚本是否存在
if [ -f "$HERMES_DIR/scripts/hermes_super_guardian.py" ]; then
    # 运行紧急检查
    python3 "$HERMES_DIR/scripts/hermes_super_guardian.py" check >> "$LOG" 2>&1
    echo "  ✅ super_guardian check done" >> "$LOG"
else
    echo "  ❌ super_guardian.py not found" >> "$LOG"
fi

# 2. 运行任务续跑检查
if [ -f "$HERMES_DIR/scripts/task_resumer.py" ]; then
    python3 "$HERMES_DIR/scripts/task_resumer.py" >> "$LOG" 2>&1
    echo "  ✅ task_resumer check done" >> "$LOG"
fi

# 3. 运行上下文守卫检查
if [ -f "$HERMES_DIR/scripts/context_guardian.py" ]; then
    python3 "$HERMES_DIR/scripts/context_guardian.py" check >> "$LOG" 2>&1
    echo "  ✅ context_guardian check done" >> "$LOG"
fi

# 4. 拍审计快照
python3 "$HERMES_DIR/scripts/hermes_super_guardian.py" snapshot >> "$LOG" 2>&1
echo "  ✅ snapshot taken" >> "$LOG"

# 5. 维护心跳
mkdir -p "$HERMES_DIR/heartbeat"
date +%s > "$HERMES_DIR/heartbeat/guardian_last.txt"
echo "  ✅ heartbeat updated" >> "$LOG"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] ✅ 复活检查完成" >> "$LOG"
