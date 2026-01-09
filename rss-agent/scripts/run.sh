#!/bin/bash
# RSS Agent 启动脚本

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$SCRIPT_DIR"

# 激活虚拟环境
source venv/bin/activate

# 运行主程序，传递所有命令行参数
python main.py "$@"
