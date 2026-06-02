#!/bin/bash
# WorldMonitor 快速启动脚本

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MONITOR_SCRIPT="${SCRIPT_DIR}/world_monitor.py"
CLI_SCRIPT="${SCRIPT_DIR}/worldmonitor-cli"

# 颜色定义
GREEN='\033[0;32m'
CYAN='\033[0;36m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${CYAN}WorldMonitor - External Event Monitoring System${NC}"
echo "----------------------------------------"

# 检查依赖
echo "Checking dependencies..."
python3 -c "import yaml" 2>/dev/null || { echo -e "${RED}Error: PyYAML not installed${NC}"; exit 1; }
python3 -c "import aiohttp" 2>/dev/null || { echo -e "${RED}Error: aiohttp not installed${NC}"; exit 1; }
python3 -c "import watchdog" 2>/dev/null || { echo -e "${RED}Error: watchdog not installed${NC}"; exit 1; }
echo -e "${GREEN}✓ All dependencies OK${NC}"

# 创建必要的目录
mkdir -p ~/.hermes/data
mkdir -p ~/.hermes/logs
mkdir -p ~/.hermes/config

# 检查配置文件
if [ ! -f ~/.hermes/config/worldmonitor.yaml ]; then
    echo "Creating default configuration..."
    cp "${SCRIPT_DIR}/../config/worldmonitor.yaml" ~/.hermes/config/worldmonitor.yaml
    echo "Edit ~/.hermes/config/worldmonitor.yaml to customize sources"
fi

# 启动服务
echo ""
echo "Starting WorldMonitor..."
echo "  Admin UI: http://localhost:11000"
echo "  CLI: ${CLI_SCRIPT}"
echo "  Config: ~/.hermes/config/worldmonitor.yaml"
echo ""
echo "Press Ctrl+C to stop"
echo "----------------------------------------"
echo ""

exec python3 "${MONITOR_SCRIPT}" "$@"
