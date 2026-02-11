#!/bin/bash
# 前端 Weekly 生成脚本

# 进入项目根目录
cd "$(dirname "$0")/.."

# 激活虚拟环境
source venv/bin/activate

# 加载本地环境变量（如 AI_API_KEY）
if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

# 生成 Weekly
echo "🚀 开始生成前端 Weekly..."
python main.py --weekly "$@"

echo "✅ 完成！"
