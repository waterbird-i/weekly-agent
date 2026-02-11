# RSS Agent

Python RSS/网页抓取 + AI 摘要分析工具，支持通用日报和前端 Weekly 生成。

## Features

- 多源抓取：支持 RSS 与普通网页（含公众号链接）
- 预过滤：时间、内容长度、关键词、URL 去重
- AI 提取：生成结构化条目并自动分类
- Markdown 输出：支持通用报告与 Weekly 模板
- 状态持久化：Weekly 期号存储到 `cache/weekly_state.json`，不改写主配置

## Project Layout

```text
rss-agent/
├── main.py
├── requirements.txt
├── .env.example
├── config/
│   ├── config.example.yaml
│   ├── config.yaml
│   ├── weekly_config.example.yaml
│   └── weekly_config.yaml
├── scripts/
│   ├── run.sh
│   └── generate_weekly.sh
├── src/
│   ├── core/
│   ├── fetchers/
│   ├── formatters/
│   ├── generators/
│   └── utils.py
├── output/   # 生成文件（默认忽略）
└── cache/    # 去重与运行状态（默认忽略）
```

## Quick Start

1. 创建并激活虚拟环境

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

2. 准备本地配置文件（首次）

```bash
cp config/config.example.yaml config/config.yaml
cp config/weekly_config.example.yaml config/weekly_config.yaml
```

3. 配置环境变量（推荐，放在 `.env`）

```bash
cp .env.example .env
# 编辑 .env，填入你的真实 key
```

也可直接使用 shell 环境变量：

```bash
export AI_API_KEY="your-api-key"
```

4. 运行

```bash
# 通用分析流程
bash scripts/run.sh --config config/config.yaml --dry-run

# Weekly 生成
bash scripts/generate_weekly.sh
```

## Config Notes

- `ai.api_key_env`：默认读取 `AI_API_KEY`
- `ai.api_key`：默认留空，不要提交真实 key
- `state.issue_file`：Weekly 期号状态文件（默认 `cache/weekly_state.json`）
- `dedup.cache_file`：URL 去重缓存

## Security Checklist

上传前建议执行：

```bash
git diff --cached
rg -n "sk-|api[_-]?key\\s*:\\s*[\"']?.+" config .env README.md
```

## Test

```bash
source venv/bin/activate
python -m unittest discover -s tests -p "test_*.py" -v
```
