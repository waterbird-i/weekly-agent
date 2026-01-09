# RSS Agent 🤖📰

一个 Python RSS 订阅抓取与 AI 分析工具。自动抓取 RSS 订阅源、按时间过滤、调用 AI 进行内容分析，并输出 Markdown 报告。

## ✨ 功能特性

- **RSS 抓取**: 支持多个 RSS 订阅源同时抓取
- **时间过滤**: 按时间范围过滤文章（默认24小时）
- **AI 分析**: 调用 AI API 提取核心要点，判断 AI 行业相关性
- **Markdown 输出**: 生成美观的 Markdown 格式分析报告

## 📁 项目结构

```
rss-agent/
├── config.yaml          # 配置文件（所有参数外置）
├── requirements.txt     # Python 依赖
├── main.py             # 主入口
├── rss_fetcher.py      # RSS 抓取模块
├── content_filter.py   # 内容过滤模块
├── ai_processor.py     # AI 处理模块
├── output_formatter.py # Markdown 输出模块
├── utils.py            # 工具函数（去重等）
├── output/             # 输出目录
└── cache/              # 缓存目录
```

## 🚀 快速开始


### 1. 修改配置文件

编辑 `weekly_config.yaml` 文件，配置你的 RSS 源和 AI API：

```yaml
# RSS订阅源列表 或者 普通网页
rss_feeds:
  - name: "Hacker News"
    url: "https://hnrss.org/frontpage"
  # 添加更多源...

# AI处理配置
ai:
  api_base: ""
  model: ""
  api_key: "your-api-key"
```

### 2. 运行

```bash
bash scripts/generate_weekly.sh
```


# 存在的问题

1. 链接识别不准，会链向订阅地址
2. 普通网页图片爬取失败
