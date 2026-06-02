#!/bin/bash
# WorldMonitor 部署验证脚本

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/../skills/worldmonitor"

echo "================================"
echo "WorldMonitor Deployment Check"
echo "================================"
echo ""

# 1. 检查 Python 语法
echo "1. Checking Python syntax..."
for file in *.py; do
    python3 -m py_compile "$file" 2>&1 && echo "  ✓ $file" || { echo "  ✗ $file has syntax errors"; exit 1; }
done
echo ""

# 2. 检查配置文件
echo "2. Validating configuration..."
python3 ~/.hermes/scripts/validate-worldmonitor-config.py || exit 1
echo ""

# 3. 检查目录结构
echo "3. Checking directories..."
for dir in data logs; do
    if [ -d "~/.hermes/$dir" ]; then
        echo "  ✓ ~/.hermes/$dir exists"
    else
        echo "  ⚠ Creating ~/.hermes/$dir"
        mkdir -p "~/.hermes/$dir"
    fi
done
echo ""

# 4. 检查导入
echo "4. Testing imports..."
python3 -c "
import sys
sys.path.insert(0, '~/.hermes/skills/worldmonitor')
from event_bus import EventBus
from event_sources import SourceManager
from event_processor import PipelineManager
from world_monitor import WorldMonitor
print('  ✓ All imports successful')
" || { echo "  ✗ Import failed"; exit 1; }
echo ""

# 5. 运行单元测试
echo "5. Running unit tests..."
python3 ~/.hermes/examples/worldmonitor/test_worldmonitor.py || { echo "  ✗ Tests failed"; exit 1; }
echo ""

# 6. 检查端口
echo "6. Checking port 11000..."
if lsof -Pi :11000 -sTCP:LISTEN -t >/dev/null 2>&1; then
    echo "  ⚠ Port 11000 is already in use"
else
    echo "  ✓ Port 11000 is available"
fi
echo ""

echo "================================"
echo "✓ Deployment validation passed"
echo "================================"
echo ""
echo "Next steps:"
echo "  1. Edit ~/.hermes/config/worldmonitor.yaml to configure sources"
echo "  2. Start the service:"
echo "     ~/.hermes/scripts/start-worldmonitor.sh"
echo "  3. Check status:"
echo "     ~/.hermes/scripts/worldmonitor-cli status"
echo ""
echo "Access admin UI at: http://localhost:11000/monitor_status"
