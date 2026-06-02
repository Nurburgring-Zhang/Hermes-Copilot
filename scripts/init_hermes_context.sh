#!/bin/bash
# ============================================================================
# Hermes 对话上下文初始化脚本 v1.0
# 由hermes唤醒时调用，决定使用全量SOUL.md还是索引摘要
# ============================================================================
# 部署方案（二选一）：
#   方案A: 在 ~/.hermes/config.yaml 的 system_prompt 中引用此脚本
#   方案B: 作为 cron @reboot 任务启动时检测并替换system prompt
#      (需要Hermes支持动态prompt加载)
# ============================================================================

HERMES_ROOT="${HERMES_ROOT:-/home/administrator/.hermes}"
SESSION_COUNTER="$HERMES_ROOT/reports/cross_session_cache.json"
INDEX_FILE="$HERMES_ROOT/reports/context_index.json"
SOUL_FILE="$HERMES_ROOT/SOUL.md"
SECTION_DIR="$HERMES_ROOT/reports/context_sections"
RECONSTRUCTOR="$HERMES_ROOT/scripts/context_reconstructor.py"

# 日志
log() {
    echo "[$(date '+%H:%M:%S')] $*" >> "$HERMES_ROOT/logs/context_init.log"
}

log "=== 对话上下文初始化 ==="

# 1. 判断是否是首次对话
IS_FIRST=true
if [ -f "$SESSION_COUNTER" ]; then
    SESSION_NUM=$(python3 -c "import json; d=json.load(open('$SESSION_COUNTER')); print(d.get('session_count', 0))" 2>/dev/null)
    if [ "$SESSION_NUM" != "" ] && [ "$SESSION_NUM" -gt 1 ]; then
        IS_FIRST=false
    fi
fi

# 2. 检查核心文件完整性
if [ ! -f "$INDEX_FILE" ] && [ ! -d "$SECTION_DIR" ]; then
    log "⚠️ 索引/章节文件不存在，回退到全量SOUL.md"
    cat "$SOUL_FILE"
    exit 0
fi

# 3. 根据轮次决定输出内容
if [ "$IS_FIRST" = true ]; then
    log "📖 首次对话: 输出全量SOUL.md"
    cat "$SOUL_FILE"
    echo ""
    echo "# SOUL.md 已全量加载"
    echo "# 索引摘要已生成至: reports/context_index.json"
    echo "# 后续对话将自动切换为索引模式"
else
    log "📑 第${SESSION_NUM}轮对话: 输出索引摘要"
    echo "# ============================================"
    echo "# Hermes 上下文索引摘要"
    echo "# ⚠️ 需要完整原文时，调用:"
    echo "#   python3 $RECONSTRUCTOR show <章节ID>"
    echo "# 或"
    echo "#   read_file('reports/context_sections/<ID>.md')"
    echo "# ============================================"
    echo ""
    
    if [ -f "$INDEX_FILE" ]; then
        # 从索引文件中提取index_text字段
        python3 -c "
import json
with open('$INDEX_FILE') as f:
    idx = json.load(f)
print(idx.get('index_text', '⚠️ 索引内容为空'))
" 2>/dev/null || cat "$SOUL_FILE"
    else
        log "⚠️ 索引文件不存在，回退全量"
        cat "$SOUL_FILE"
    fi
    
    echo ""
    echo "# ============================================"
    echo "# 📌 需要完整章节? 用 read_file 或 context_reconstructor.py"
    echo "# 例: read_file('reports/context_sections/八_七条永久执行规则...md')"
    echo "# 例: python3 $RECONSTRUCTOR show 八_七条永久执行规则"
    echo "# ============================================"
fi
