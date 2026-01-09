"""
Weekly 生成器主模块
负责协调各模块生成前端 Weekly
"""

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional

import yaml
from openai import OpenAI

from ..core.rss_fetcher import RSSFetcher, Article
from ..core.content_filter import ContentFilter
from ..fetchers.leetcode_fetcher import LeetCodeFetcher, LeetCodeProblem
from ..fetchers.web_fetcher import WebFetcher
from ..formatters.weekly_formatter import WeeklyFormatter, WeeklyItem
from ..utils import truncate_text

logger = logging.getLogger(__name__)


class WeeklyGenerator:
    """前端 Weekly 生成器"""
    
    def __init__(self, config_path: str = "weekly_config.yaml"):
        """
        初始化生成器
        
        Args:
            config_path: 配置文件路径
        """
        self.config_path = Path(config_path)
        # 项目根目录 (src/generators -> src -> project_root)
        self.project_root = Path(__file__).parent.parent.parent
        if not self.config_path.is_absolute():
            self.config_path = self.project_root / config_path
        
        self.config = self._load_config()
        self._init_ai_client()
    
    def _load_config(self) -> Dict[str, Any]:
        """加载配置文件"""
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
            logger.info(f"配置文件加载成功: {self.config_path}")
            return config
        except Exception as e:
            logger.error(f"加载配置文件失败: {e}")
            raise
    
    def _save_config(self):
        """保存配置文件（用于更新期号）"""
        try:
            with open(self.config_path, 'w', encoding='utf-8') as f:
                yaml.dump(self.config, f, allow_unicode=True, default_flow_style=False)
            logger.info(f"配置文件已更新: {self.config_path}")
        except Exception as e:
            logger.error(f"保存配置文件失败: {e}")
    
    def _init_ai_client(self):
        """初始化 AI 客户端"""
        ai_config = self.config.get('ai', {})
        self.ai_client = OpenAI(
            api_key=ai_config.get('api_key', ''),
            base_url=ai_config.get('api_base', 'https://200.xstx.info/v1')
        )
        self.ai_model = ai_config.get('model', 'claude-opus-4-5-20251101-thinking')
        self.ai_max_tokens = ai_config.get('max_tokens', 4096)
        self.weekly_prompt = ai_config.get('weekly_prompt', '')
    

    
    def get_current_issue(self) -> int:
        """获取当前期号"""
        return self.config.get('weekly', {}).get('current_issue', 1)
    
    def get_current_date(self) -> str:
        """获取当前日期字符串"""
        date_format = self.config.get('weekly', {}).get('date_format', '%Y%m%d')
        return datetime.now().strftime(date_format)
    
    def get_output_path(self, issue: int, date: str) -> str:
        """获取输出文件路径"""
        template = self.config.get('weekly', {}).get(
            'output_template', 
            'output/NO{issue}.前端Weekly({date}).md'
        )
        path = template.format(issue=issue, date=date)
        if not Path(path).is_absolute():
            path = str(self.project_root / path)
        return path
    
    def _fetch_category_articles(
        self, 
        category_config: Dict[str, Any]
    ) -> List[Article]:
        """
        获取某个分类的文章
        
        Args:
            category_config: 分类配置
            
        Returns:
            文章列表
        """
        feeds = category_config.get('feeds', [])
        if not feeds:
            return []
        
        # 分离 RSS 和 普通网页
        rss_feeds = []
        web_urls = []
        
        for feed in feeds:
            url = feed.get('url', '')
            # 简单判断是否为 RSS，微信公众号文章链接肯定不是 RSS
            if 'mp.weixin.qq.com' in url or not (url.endswith('.xml') or url.endswith('.rss') or url.endswith('.atom') or 'rss' in url.lower() or 'feed' in url.lower()):
                web_urls.append(feed)
            else:
                rss_feeds.append(feed)
        
        articles = []
        
        # 1. 抓取 RSS
        if rss_feeds:
            fetcher = RSSFetcher(rss_feeds)
            articles.extend(fetcher.fetch_all())
        
        # 2. 抓取普通网页
        if web_urls:
            web_fetcher = WebFetcher()
            articles.extend(web_fetcher.fetch_all(web_urls))
        
        if not articles:
            return []
        
        # 时间和长度过滤配置
        time_hours = self.config.get('time_filter', {}).get('hours', 168)
        pre_filter_config = self.config.get('pre_filter', {})
        min_length = pre_filter_config.get('min_content_length', 50)
        
        filter_config = {
            'time_filter': {'hours': time_hours},
            'pre_filter': {
                'include_keywords': category_config.get('keywords', []),
                'exclude_keywords': [],
                'min_content_length': min_length
            }
        }
        
        content_filter = ContentFilter(filter_config)
        filtered = content_filter.apply_all_filters(articles)
        
        return filtered
    
    def _extract_items(self, article: Article) -> List[Dict[str, Any]]:
        """
        使用 AI 从文章中提取多个条目
        
        Args:
            article: 文章对象
            
        Returns:
            包含多个条目的列表，每个条目有 title, summary, category, is_english
        """
        try:
            content = article.content or article.summary
            content = truncate_text(content, 8000)  # 增加内容长度以获取更多信息
            
            # 获取所有可用分类
            categories = self.config.get('categories', {})
            category_names = [cat.get('name', key) for key, cat in categories.items() if key != 'training']
            
            # 检测是否为日刊/聚合类内容
            is_daily_digest = any(kw in article.title.lower() or kw in content[:500].lower() 
                                  for kw in ['日刊', '日报', '今日摘要', '每日', 'daily', '周刊'])
            
            if is_daily_digest:
                extract_prompt = f"""你是一个技术资讯编辑助手。

这是一篇日刊/日报内容，包含多条独立的资讯。请从中提取每一条独立的新闻/资讯。

【可选分类】
{', '.join(category_names)}

【分类指南】
- 时事：行业动态、政策新闻、公司融资、市场趋势、产业规划等综合资讯
- AI资讯：AI模型发布、AI产品更新、AI技术突破等与AI直接相关的资讯
- 教程：技术教程、工作流分享、学习资源、最佳实践等
- 工具：开源项目、开发工具、实用软件等

【重要】这是聚合类日刊内容，你必须：
1. 将日刊拆分成独立的资讯条目，每条资讯单独提取
2. 不要把多条资讯合并成一个条目
3. 日刊中通常有"产品与功能更新"、"前沿研究"、"行业展望"等分类，每个分类下的每一条都是独立资讯
4. 提取数量：5-10条最重要的资讯
5. 务必根据内容合理分配到不同分类，不要都放到同一分类

【输出格式】
直接输出 JSON 数组，不要任何markdown标记或其他文字：
[
  {{"title": "北京AI产业两年冲万亿", "summary": "北京发布九大行动计划，核心产业规模预计从4500亿冲刺万亿。", "category": "时事", "is_english": false}},
  {{"title": "SeedFold超越AlphaFold3", "summary": "字节Seed团队发布分子结构预测新模型，表现优于AlphaFold3。", "category": "AI资讯", "is_english": false}},
  {{"title": "开源笔记Memos获4万星", "summary": "轻量级开源笔记服务，支持自托管，用户数据完全自主掌控。", "category": "工具", "is_english": false}}
]

如果无法提取，返回空数组 []"""
            else:
                extract_prompt = f"""你是一个前端技术周刊编辑助手。

从以下文章内容中提取所有有价值的独立资讯条目。

【可选分类】
{', '.join(category_names)}

【提取规则】
1. 每个条目只描述一件具体的事，不要聚合
2. 为每个条目选择最合适的分类
3. 如果文章是日刊/周刊合集，提取其中所有重要的独立资讯（最多10条）
4. 如果文章只包含单一主题，只返回1条
5. 过滤掉广告、招聘等无关内容

【输出格式】
直接输出 JSON 数组，不要任何markdown标记或其他文字：
[{{"title": "15字以内的中文标题", "summary": "约100字的中文简介", "category": "从可选分类中选择一个", "is_english": true或false}}]

如果没有可提取的内容，返回空数组 []"""
            
            user_prompt = f"""标题：{article.title}
来源：{article.source}
URL：{article.url}

内容：
{content}"""
            
            # 日刊类内容需要更多token来输出多个条目
            max_tokens = 4000 if is_daily_digest else 2000
            logger.info(f"  日刊检测: {is_daily_digest}, 文章: {article.title[:30]}...")
            
            response = self.ai_client.chat.completions.create(
                model=self.ai_model,
                messages=[
                    {"role": "system", "content": extract_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                max_tokens=max_tokens,
                temperature=0.7
            )
            
            response_text = response.choices[0].message.content
            logger.debug(f"  AI原始响应(前300字): {response_text[:300] if response_text else 'None'}...")
            
            # 解析 JSON 数组
            try:
                # 移除可能的 markdown 代码块标记
                clean_text = response_text or ""
                if '```json' in clean_text:
                    clean_text = re.sub(r'```json\s*', '', clean_text)
                    clean_text = re.sub(r'```\s*$', '', clean_text)
                elif '```' in clean_text:
                    clean_text = re.sub(r'```\s*', '', clean_text)
                
                # 移除 thinking 标签（Claude模型可能返回）
                clean_text = re.sub(r'<thinking>.*?</thinking>', '', clean_text, flags=re.DOTALL)
                clean_text = re.sub(r'<thinking>.*', '', clean_text, flags=re.DOTALL)
                
                # 提取 JSON 数组
                json_match = re.search(r'\[.*\]', clean_text, re.DOTALL)
                if json_match:
                    json_str = json_match.group()
                    items = json.loads(json_str)
                    
                    # 清理并返回条目
                    result = []
                    for idx, item in enumerate(items):
                        if isinstance(item, dict) and item.get('title') and item.get('summary'):
                            item['summary'] = self._clean_summary(item.get('summary', ''))
                            item['source_url'] = article.url
                            result.append(item)
                    
                    # 图片分配策略：每条提取的新闻都保留原文章的图片
                    for item in result:
                        item['image_url'] = article.image_url
                    
                    if result:
                        logger.info(f"  成功提取 {len(result)} 个条目")
                        return result
                    else:
                        logger.warning(f"  JSON解析成功但无有效条目")
                else:
                    logger.warning(f"  未找到JSON数组")
            except (json.JSONDecodeError, AttributeError) as parse_err:
                logger.warning(f"  JSON解析失败: {parse_err}")
            
            # 解析失败，返回单条目（兼容原逻辑）
            # 对于日刊类内容，尝试从内容中提取有意义的标题和简介
            fallback_title = self._extract_fallback_title(article)
            fallback_summary = self._extract_fallback_summary(article, fallback_title)
            return [{
                "title": fallback_title,
                "summary": fallback_summary,
                "category": "AI资讯" if is_daily_digest else "时事",
                "is_english": self._detect_english(article.title),
                "source_url": article.url,
                "image_url": article.image_url
            }]
            
        except Exception as e:
            logger.error(f"提取条目失败: {article.title}, 错误: {e}")
            fallback_title = self._extract_fallback_title(article)
            fallback_summary = self._extract_fallback_summary(article, fallback_title)
            return [{
                "title": fallback_title,
                "summary": fallback_summary,
                "category": "AI资讯",
                "is_english": self._detect_english(article.title),
                "source_url": article.url,
                "image_url": article.image_url
            }]
    
    def _clean_summary(self, summary: str) -> str:
        """
        清理摘要内容，移除无效信息
        
        Args:
            summary: 原始摘要
            
        Returns:
            清理后的摘要
        """
        if not summary:
            return "暂无描述"
        
        # 需要过滤的无效内容模式
        invalid_patterns = [
            r'Article URL:\s*<[^>]+>',
            r'Comments URL:\s*<[^>]+>',
            r'Points:\s*\d+',
            r'# Comments:\s*\d+',
            r'Comments:\s*\d+',
            r'<https?://[^>]+>',  # 尖括号包裹的 URL
            r'Article URL:.*',
            r'Comments URL:.*',
            r'<thinking>.*?</thinking>',  # 移除 thinking 标签及其内容
            r'<thinking>.*',  # 移除未闭合的 thinking 标签
        ]
        
        clean_text = summary
        for pattern in invalid_patterns:
            clean_text = re.sub(pattern, '', clean_text, flags=re.IGNORECASE | re.MULTILINE | re.DOTALL)
        
        # 移除多余的空行和空格
        clean_text = re.sub(r'\n\s*\n', '\n', clean_text)
        clean_text = clean_text.strip()
        
        # 如果清理后内容太短或为空，返回默认值
        if not clean_text or len(clean_text) < 10:
            return "暂无描述"
        
        return clean_text
    
    def _extract_fallback_title(self, article: Article) -> str:
        """
        从日刊类文章内容中提取有意义的标题
        
        当AI提取失败时，如果原始标题是日期格式（如"2026-01-01日刊"），
        尝试从内容中提取第一条有价值的资讯标题。
        
        Args:
            article: 文章对象
            
        Returns:
            提取的标题（15字以内）
        """
        original_title = article.title.strip()
        
        # 检测是否为日期格式的日刊/日报标题
        date_pattern = r'^\d{4}-?\d{2}-?\d{2}.*?(日刊|日报|Daily)'
        is_date_title = re.match(date_pattern, original_title, re.IGNORECASE)
        
        if not is_date_title:
            # 不是日期格式，直接返回原标题（截断到15字）
            return original_title[:15]
        
        # 尝试从内容中提取有意义的标题
        content = article.content or article.summary or ""
        
        # 优先从"今日摘要"后提取第一条有意义的资讯
        # 格式通常是：今日摘要 豆包眼镜2000内售腾讯ima一键生成PPT SeedFold超...
        summary_match = re.search(r'今日摘要\s*([^\n]{5,80})', content)
        if summary_match:
            summary_text = summary_match.group(1).strip()
            # 提取第一个有意义的短语（通常以中文名词/产品开头）
            # 匹配模式：产品名+动作，或者公司名+产品
            news_patterns = [
                # 公司/产品名 + 动作（如：豆包眼镜开售、腾讯ima一键生成PPT）
                r'([A-Za-z\u4e00-\u9fa5]{2,8}(?:眼镜|模型|平台|工具|框架|系统)?(?:开售|发布|上线|开源|推出|获得|完成|融资|突破|超越|冲刺)[^\s]*)',
                # 产品版本格式（如：SeedFold超AlphaFold3）
                r'([A-Za-z][A-Za-z0-9]{1,10}超[A-Za-z0-9]{2,12})',
                # 通用的"XX+动词"格式
                r'([\u4e00-\u9fa5A-Za-z]{2,6}(?:AI|眼镜|模型|芯片|平台)?[\u4e00-\u9fa5]{2,8})',
            ]
            
            for pattern in news_patterns:
                match = re.search(pattern, summary_text)
                if match:
                    extracted = match.group(1).strip()
                    if 4 <= len(extracted) <= 15:
                        return extracted
            
            # 如果没有匹配到，取摘要的前15字
            return summary_text[:15]
        
        # 备用：从内容中匹配常见的资讯模式
        patterns = [
            # 中文产品/公司名 + 动作
            r'([\u4e00-\u9fa5A-Za-z]{2,8}(?:公测|发布|开源|上线|推出|开售|开放|获得|完成|宣布|融资|突破)[^\n。！]{0,8})',
            # 公司名 + 产品动作
            r'((?:小米|字节|腾讯|阿里|百度|华为|OpenAI|Meta|Google|微软|Apple|北京|上海)[A-Za-z\u4e00-\u9fa5]{2,12})',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, content[:2000])
            if match:
                extracted = match.group(1).strip()
                extracted = re.sub(r'\s+', '', extracted)
                if 4 <= len(extracted) <= 15:
                    return extracted
        
        # 最后回退：使用原标题
        return original_title[:15]
    
    def _extract_fallback_summary(self, article: Article, title: str) -> str:
        """
        从日刊类文章内容中提取与标题相关的简介
        
        当AI提取失败时，尝试从内容中找到与标题相关的描述。
        
        Args:
            article: 文章对象
            title: 已提取的标题
            
        Returns:
            提取的简介（约100字）
        """
        content = article.content or article.summary or ""
        
        # 尝试从内容中查找与标题相关的段落
        # 查找标题附近的内容
        title_keywords = list(filter(lambda x: len(x) >= 2, 
                                     re.findall(r'[A-Za-z]+|\u4e00-\u9fa5{2,}', title)))
        
        if title_keywords:
            # 尝试找到包含标题关键词的句子
            for keyword in title_keywords[:3]:
                # 查找关键词所在的句子
                pattern = rf'[^。！？\n]*{re.escape(keyword)}[^。！？\n]*[。！？]?'
                match = re.search(pattern, content)
                if match:
                    sentence = match.group().strip()
                    # 限制长度并清理
                    if 20 <= len(sentence) <= 150:
                        return self._clean_summary(sentence)
        
        # 如果找不到相关内容，提取"今日摘要"后的一段内容
        summary_pattern = r'今日摘要\s*(.{20,200})'
        summary_match = re.search(summary_pattern, content)
        if summary_match:
            return self._clean_summary(summary_match.group(1)[:150])
        
        # 最后回退：使用原始简介的前150字
        if article.summary:
            return self._clean_summary(article.summary[:150])
        
        return "暂无描述"
    
    def _detect_english(self, text: str) -> bool:
        """
        检测文本是否为英文
        
        Args:
            text: 待检测文本
            
        Returns:
            是否为英文
        """
        if not text:
            return False
        # 计算英文字符占比
        english_chars = sum(1 for c in text if c.isalpha() and ord(c) < 128)
        total_chars = sum(1 for c in text if c.isalpha())
        if total_chars == 0:
            return False
        return english_chars / total_chars > 0.7
    
    def _process_all_articles(self) -> Dict[str, List[WeeklyItem]]:
        """
        处理所有文章，统一提取并按分类归类
        
        Returns:
            按分类名分组的 WeeklyItem 字典
        """
        categories_config = self.config.get('categories', {})
        all_items: Dict[str, List[WeeklyItem]] = {}
        processed_urls = set()
        
        # 收集所有唯一的文章
        all_articles = []
        for cat_key, cat_config in categories_config.items():
            if cat_key == 'training':
                continue
            articles = self._fetch_category_articles(cat_config)
            for article in articles:
                if article.url not in processed_urls:
                    all_articles.append(article)
                    processed_urls.add(article.url)
        
        logger.info(f"共收集 {len(all_articles)} 篇唯一文章")
        
        # 处理每篇文章，提取多条目
        for article in all_articles:
            logger.info(f"  处理文章: {article.title[:40]}...")
            
            extracted_items = self._extract_items(article)
            logger.info(f"    提取到 {len(extracted_items)} 个条目")
            
            for item_data in extracted_items:
                category = item_data.get('category', '时事')
                
                # 确保分类存在
                if category not in all_items:
                    all_items[category] = []
                
                item = WeeklyItem(
                    title=item_data.get('title', article.title),
                    url=item_data.get('source_url', article.url),
                    summary=item_data.get('summary', '暂无描述'),
                    is_english=item_data.get('is_english', False),
                    category=category,
                    short_title=item_data.get('title', ''),
                    image_url=item_data.get('image_url', '')
                )
                all_items[category].append(item)
        
        # 按配置的 max_count 限制每个分类的数量
        for cat_key, cat_config in categories_config.items():
            cat_name = cat_config.get('name', cat_key)
            max_count = cat_config.get('max_count', 5)
            min_count = cat_config.get('min_count', 1)
            
            if cat_name in all_items:
                if len(all_items[cat_name]) > max_count:
                    all_items[cat_name] = all_items[cat_name][:max_count]
                
                if len(all_items[cat_name]) < min_count:
                    logger.warning(f"分类 {cat_name} 内容不足: {len(all_items[cat_name])}/{min_count}")
                
                logger.info(f"分类 {cat_name} 最终: {len(all_items[cat_name])} 条")
        
        return all_items
    
    def _process_training(self, category_config: Dict[str, Any]) -> List[WeeklyItem]:
        """
        处理训练分类（LeetCode 题目）
        
        Args:
            category_config: 分类配置
            
        Returns:
            WeeklyItem 列表
        """
        leetcode_config = category_config.get('leetcode', {})
        if not leetcode_config.get('enabled', True):
            return []
        
        count = leetcode_config.get('count', 2)
        difficulties = leetcode_config.get('difficulties', [])
        
        logger.info(f"获取 LeetCode 题目: {count} 道")
        
        fetcher = LeetCodeFetcher(difficulties)
        problems = fetcher.get_random_problems(count)
        
        items = []
        for problem in problems:
            # 使用中文标题
            title = problem.title_cn or problem.title
            
            summary = f"难度：{problem.difficulty}。这是一道经典的算法题目，建议尝试多种解法，理解其背后的算法思想。"
            
            item = WeeklyItem(
                title=title,
                url=problem.url,
                summary=summary,
                is_english=False,
                category="训练"
            )
            items.append(item)
        
        logger.info(f"LeetCode 题目处理完成: {len(items)} 道")
        return items
    
    def generate(self, dry_run: bool = False) -> Optional[str]:
        """
        生成 Weekly
        
        Args:
            dry_run: 是否仅模拟运行
            
        Returns:
            生成的文件路径，或 None
        """
        issue = self.get_current_issue()
        date = self.get_current_date()
        output_path = self.get_output_path(issue, date)
        
        logger.info("=" * 50)
        logger.info(f"开始生成 Weekly NO{issue} ({date})")
        logger.info("=" * 50)
        
        # 统一处理所有文章，AI 自动分类
        categories_data = self._process_all_articles()
        
        # 处理训练分类
        categories_config = self.config.get('categories', {})
        if 'training' in categories_config:
            training_items = self._process_training(categories_config['training'])
            if training_items:
                categories_data['训练'] = training_items
        
        if dry_run:
            logger.info("Dry-run 模式，跳过保存")
            for cat_name, items in categories_data.items():
                logger.info(f"\n{cat_name}:")
                for item in items:
                    logger.info(f"  - {item.title}")
            return None
        
        # 格式化并保存
        formatter = WeeklyFormatter(output_path)
        saved_path = formatter.save_weekly(issue, date, categories_data)
        
        # 打印到控制台
        formatter.print_weekly(issue, date, categories_data)
        
        # 更新期号
        self.config['weekly']['current_issue'] = issue + 1
        self._save_config()
        
        logger.info("=" * 50)
        logger.info(f"✅ Weekly NO{issue} 生成完成")
        logger.info(f"📄 文件已保存到: {saved_path}")
        logger.info("=" * 50)
        
        return saved_path
