# RSS Agent

Python RSS/网页抓取 + AI 摘要分析工具，支持通用日报与前端 Weekly 自动生成，并提供 Web 可视化面板。

## 能做什么

- 多源抓取：支持 RSS 和普通网页（含公众号文章链接）
- 预过滤：时间窗口、关键词、内容长度、URL 去重
- AI 处理：摘要提取、结构化输出、分类编排
- Markdown 产出：日报报告与 Weekly 模板
- 状态持久化：Weekly 期号保存在 `cache/weekly_state.json`，不改写主配置
- Web 管理：查看进度、日志、历史记录和产物

## 运行模式

- 日报模式：执行抓取 + 过滤 + AI 分析，输出 `output/rss_analysis.md`
- Weekly 模式：按 `config/weekly_config.yaml` 生成 `NOxxx.前端Weekly(...)`
- Web 面板：在浏览器中可视化运行任务与查看历史

## 项目结构

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
│   ├── generate_weekly.sh
│   └── web.sh
├── web_app.py
├── src/
│   ├── core/
│   ├── fetchers/
│   ├── formatters/
│   ├── generators/
│   ├── webui/
│   └── utils.py
├── output/   # 生成文件（默认忽略）
└── cache/    # 去重与运行状态（默认忽略）
```

## 快速开始

1. 创建并激活虚拟环境

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

2. 首次复制配置文件

```bash
cp config/config.example.yaml config/config.yaml
cp config/weekly_config.example.yaml config/weekly_config.yaml
```

3. 配置 API Key（推荐写入 `.env`）

```bash
cp .env.example .env
# 编辑 .env，填入真实 AI_API_KEY
```

也可直接使用 shell 环境变量：

```bash
export AI_API_KEY="your-api-key"
```

4. 先做一次 dry-run 验证抓取链路

```bash
bash scripts/run.sh --config config/config.yaml --dry-run
```

5. 正式运行

```bash
# 日报
bash scripts/run.sh --config config/config.yaml

# Weekly
bash scripts/generate_weekly.sh

# Web 面板（默认 8765 端口）
bash scripts/web.sh
# 打开 http://127.0.0.1:8765
```

## 常用命令速查

```bash
# 日报：只处理最近 24 小时，最多 10 篇
bash scripts/run.sh --hours 24 --max-articles 10

# 日报：指定输出文件
bash scripts/run.sh --output output/today.md

# Weekly：仅抓取过滤，不调用 AI
bash scripts/generate_weekly.sh --dry-run

# Weekly：使用自定义 weekly 配置
bash scripts/generate_weekly.sh --weekly-config config/weekly_config.yaml

# 查看主程序参数
python main.py --help
```

## CLI 参数说明

`main.py` 常用参数：

- `-c, --config`：日报配置文件路径，默认 `config/config.yaml`
- `-o, --output`：输出路径（覆盖配置中的 `output.file_path`）
- `-n, --max-articles`：最大处理文章数（覆盖配置）
- `--hours`：按小时过滤文章时间范围（覆盖配置）
- `--dry-run`：仅抓取/过滤，不调用 AI
- `--weekly`：切换到 Weekly 模式
- `--weekly-config`：Weekly 配置路径，默认 `config/weekly_config.yaml`
- `-v, --verbose`：输出更详细日志

## 配置说明

### `config/config.yaml`（日报）

- `rss_feeds`：订阅源列表（`name` + `url`）
- `time_filter.hours`：时间窗口（小时）
- `pre_filter.include_keywords`：包含关键词
- `pre_filter.exclude_keywords`：排除关键词
- `pre_filter.min_content_length`：最小正文长度
- `ai.api_base`：AI 接口地址
- `ai.model`：模型名
- `ai.api_key_env`：优先读取的环境变量名（默认 `AI_API_KEY`）
- `ai.api_key`：兜底 key（建议留空，避免明文提交）
- `ai.max_tokens`：单次请求 token 上限
- `output.file_path`：输出路径
- `output.max_articles`：每次最多处理文章数
- `dedup.cache_file`：URL 去重缓存文件
- `dedup.cache_expire_hours`：去重缓存过期时间

### `config/weekly_config.yaml`（Weekly）

- `categories.*.feeds`：每个分类的抓取来源
- `categories.*.min_count/max_count`：分类条目下限与上限
- `categories.training.leetcode.*`：训练模块配置（开关、数量、难度）
- `time_filter.hours`：Weekly 时间窗口
- `weekly.current_issue`：初始期号（仅在状态文件不存在时生效）
- `weekly.date_format`：日期格式（默认 `%Y%m%d`）
- `weekly.output_template`：输出文件命名模板
- `weekly.title_template`：标题模板
- `state.issue_file`：期号状态文件（优先于 `weekly.current_issue`）
- `dedup.cache_file`：Weekly 去重缓存

## 输出与状态文件

- `output/rss_analysis.md`：日报默认输出
- `output/NO{issue}.前端Weekly({date}).md`：Weekly 输出
- `cache/processed_urls.json`：日报 URL 去重
- `cache/weekly_processed_urls.json`：Weekly URL 去重
- `cache/weekly_state.json`：Weekly 期号状态
- `cache/webui_runs.db`：Web 面板任务历史

## Web Dashboard

- 实时查看阶段进度（抓取/过滤/AI/输出）
- 实时日志流（SSE）
- 历史任务记录与详情
- 任务管理（重跑、删除记录、删除记录+产物）
- Markdown 产物在线预览

## 常见问题

### 1) 提示缺少 API Key

确保以下任一项已配置：

- `.env` 中设置了 `AI_API_KEY=...`
- 当前 shell 执行过 `export AI_API_KEY="..."`
- 配置中的 `ai.api_key_env` 指向了正确变量名

### 2) 抓到文章但过滤后为 0

优先检查：

- `time_filter.hours` 是否太小
- `pre_filter.include_keywords` 是否过严
- `pre_filter.min_content_length` 是否过高
- 去重缓存中是否已存在同 URL（可检查 `cache/*.json`）

### 3) Weekly 期号不符合预期

- 实际以 `state.issue_file`（默认 `cache/weekly_state.json`）为准
- `weekly.current_issue` 只在状态文件不存在时作为初始值

## 安全检查

提交前建议执行：

```bash
git diff --cached
rg -n "sk-|api[_-]?key\\s*:\\s*[\"']?.+" config .env README.md
```

## 测试

```bash
source venv/bin/activate
python -m unittest discover -s tests -p "test_*.py" -v
```
