#!/bin/bash
# RSS Agent Web UI 启动脚本

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$SCRIPT_DIR"

source venv/bin/activate

if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

echo "🚀 启动 RSS Agent 可视化界面: http://127.0.0.1:8765"
python web_app.py
