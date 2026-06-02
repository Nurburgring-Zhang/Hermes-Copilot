#!/bin/bash
# start_eternal.sh — 自动启动永恒守护 + 7条规则强制激活
# 已在~/.bashrc中配置自动运行

# 确保wake_init执行
if [ -f ~/.hermes/scripts/wake_init.sh ]; then
    bash ~/.hermes/scripts/wake_init.sh
fi
