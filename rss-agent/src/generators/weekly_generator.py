"""
Weekly 生成器主模块
负责协调各模块生成前端 Weekly
"""

import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from urllib.parse import urljoin, urlparse

import yaml
from openai import OpenAI

from ..core.rss_fetcher import RSSFetcher, Article
from ..core.content_filter import ContentFilter
from ..fetchers.leetcode_fetcher import LeetCodeFetcher
from ..fetchers.web_fetcher import WebFetcher
from ..formatters.weekly_formatter import WeeklyFormatter, WeeklyItem
from ..utils import truncate_text, URLDeduplicator, create_retry_session

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
        self.state_file = self._get_state_file()
        self.deduplicator = self._init_deduplicator()
        self.http_session = create_retry_session(total_retries=2, backoff_factor=0.8)
        self._page_image_cache: Dict[str, str] = {}
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
    
    def _get_state_file(self) -> Path:
        """获取 issue 状态文件路径"""
        state_file = self.config.get('state', {}).get('issue_file', 'cache/weekly_state.json')
        path = Path(state_file)
        if not path.is_absolute():
            path = self.project_root / path
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def _load_state(self) -> Dict[str, Any]:
        """加载运行状态"""
        if not self.state_file.exists():
            return {}
        try:
            with open(self.state_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
        except Exception as e:
            logger.warning(f"读取状态文件失败，将回退默认配置: {self.state_file}, 错误: {e}")
        return {}

    def _save_state(self, state: Dict[str, Any]):
        """保存运行状态"""
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.state_file, 'w', encoding='utf-8') as f:
                json.dump(state, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存状态文件失败: {self.state_file}, 错误: {e}")

    def _init_deduplicator(self) -> Optional[URLDeduplicator]:
        """初始化 Weekly 去重器"""
        dedup_cfg = self.config.get('dedup', {})
        cache_file = dedup_cfg.get('cache_file')
        if not cache_file:
            return None
        cache_path = Path(cache_file)
        if not cache_path.is_absolute():
            cache_path = self.project_root / cache_path
        expire_hours = dedup_cfg.get('cache_expire_hours', 720)
        return URLDeduplicator(str(cache_path), expire_hours)
    
    def _init_ai_client(self):
        """初始化 AI 客户端"""
        ai_config = self.config.get('ai', {})
        api_key_env = ai_config.get('api_key_env', 'AI_API_KEY')
        api_key = os.getenv(api_key_env) or ai_config.get('api_key', '')
        if not api_key:
            logger.warning(f"未检测到 Weekly AI API Key，请设置环境变量 {api_key_env}")

        self.ai_client = OpenAI(
            api_key=api_key,
            base_url=ai_config.get('api_base', 'https://200.xstx.info/v1')
        )
        self.ai_model = ai_config.get('model', 'claude-opus-4-5-20251101-thinking')
        self.ai_max_tokens = ai_config.get('max_tokens', 4096)
        self.weekly_prompt = ai_config.get('weekly_prompt', '')
    

    
    def get_current_issue(self) -> int:
        """获取当前期号"""
        state = self._load_state()
        if isinstance(state.get('current_issue'), int):
            return state['current_issue']
        return self.config.get('weekly', {}).get('current_issue', 1)

    def _set_next_issue(self, issue: int):
        """更新下一期号到状态文件"""
        state = self._load_state()
        state['current_issue'] = issue + 1
        state['updated_at'] = datetime.now().isoformat()
        self._save_state(state)
    
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

    def _extract_candidate_links(self, article: Article) -> List[Tuple[str, str]]:
        """
        从聚合内容中提取候选链接（用于条目级链接分配）
        """
        text = f"{article.content or ''}\n{article.summary or ''}"
        candidates: List[Tuple[str, str]] = []
        seen_urls = set()

        # markdown 链接: [title](url)
        for match in re.finditer(r'\[([^\]]{2,200})\]\((https?://[^\s)]+)\)', text):
            anchor = match.group(1).strip()
            url = match.group(2).strip().rstrip(').,;')
            if not url or url == article.url or url in seen_urls:
                continue
            if self._is_noise_source_link(anchor, url):
                continue
            seen_urls.add(url)
            candidates.append((anchor, url))

        # 裸链接: https://...
        for match in re.finditer(r'(https?://[^\s<>()]+)', text):
            url = match.group(1).strip().rstrip(').,;')
            if not url or url == article.url or url in seen_urls:
                continue
            if self._is_noise_source_link("", url):
                continue
            seen_urls.add(url)
            candidates.append(("", url))

        # 如果正文里链接很少，尝试从来源网页抽取更多候选链接
        if len(candidates) <= 1 and article.url.startswith("http"):
            for anchor, url in self._extract_links_from_source_page(article.url):
                if url == article.url or url in seen_urls:
                    continue
                seen_urls.add(url)
                candidates.append((anchor, url))

        return candidates

    def _extract_links_from_source_page(self, source_url: str) -> List[Tuple[str, str]]:
        """
        从来源页面中提取正文锚点链接，补充条目级 URL 候选
        """
        try:
            response = self.http_session.get(source_url, timeout=15)
            response.raise_for_status()
            html = response.text
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, 'html.parser')

            root = None
            for selector in ['main', 'article', '.content', '#content', '.post-content', '.rich_media_content', 'body']:
                node = soup.select_one(selector)
                if node:
                    root = node
                    break

            if not root:
                return []

            result: List[Tuple[str, str]] = []
            seen = set()
            for anchor in root.select('a[href]'):
                href = (anchor.get('href') or '').strip()
                text = anchor.get_text(" ", strip=True)
                if not href:
                    continue
                if href.startswith('#') or href.startswith('javascript:'):
                    continue

                full_url = urljoin(source_url, href).strip()
                if not full_url.startswith('http'):
                    continue
                if full_url in seen:
                    continue
                if self._is_noise_source_link(text, full_url):
                    continue

                seen.add(full_url)
                result.append((text, full_url))
            return result
        except Exception as e:
            logger.debug(f"来源页链接补充失败: {source_url}, 错误: {e}")
            return []

    def _is_noise_source_link(self, text: str, url: str) -> bool:
        """过滤来源页中的导航/社交/素材链接"""
        lower_text = (text or "").lower()
        lower_url = url.lower()

        text_noise = (
            "关于我",
            "同性交友",
            "进群",
            "访问网页版",
            "小酒馆",
            "自媒体",
            "前往官网查看完整版",
            "阅读全文",
            "点击查看原文",
            "原文链接",
        )
        if any(keyword.lower() in lower_text for keyword in text_noise):
            return True

        url_noise = ("logo", "avatar", "favicon", ".jpg", ".jpeg", ".png", ".gif", ".svg")
        if any(keyword in lower_url for keyword in url_noise):
            return True

        parsed = urlparse(lower_url)
        if parsed.netloc == "ai.hubtoday.app" and parsed.path.strip("/") == "":
            return True

        if "github.com/justlovemaki" in lower_url:
            return True

        return False

    def _build_link_candidates_for_prompt(
        self,
        candidates: List[Tuple[str, str]],
        max_count: int = 40
    ) -> Tuple[List[str], Dict[str, str]]:
        """
        将候选链接编码为 link_id，供模型选择
        """
        lines: List[str] = []
        link_id_map: Dict[str, str] = {}

        for idx, (anchor, url) in enumerate(candidates[:max_count], start=1):
            link_id = f"L{idx}"
            clean_anchor = re.sub(r'\s+', ' ', (anchor or '').strip())
            label = clean_anchor[:80] if clean_anchor else "（无锚文本）"
            lines.append(f"- {link_id} | {label} | {url}")
            link_id_map[link_id] = url

        return lines, link_id_map

    def _normalize_link_id(self, raw_link_id: Any) -> str:
        """
        规范化 link_id（兼容 L1 / l1 / 1）
        """
        value = str(raw_link_id or '').strip().upper()
        if not value:
            return ""

        if value.isdigit():
            return f"L{int(value)}"

        match = re.match(r'^L(\d+)$', value)
        if not match:
            return ""
        return f"L{int(match.group(1))}"

    def _score_link_match(self, title: str, anchor: str, url: str) -> int:
        """根据标题与候选链接文本匹配程度打分"""
        title_tokens = set(re.findall(r'[\u4e00-\u9fa5]{2,}|[A-Za-z0-9]{3,}', title.lower()))
        if not title_tokens:
            return 0
        haystack = f"{anchor} {url}".lower()
        score = 0
        for token in title_tokens:
            if token in haystack:
                score += 1
        return score

    def _select_item_link(
        self,
        item_title: str,
        candidates: List[Tuple[str, str]],
        used_urls: set,
        fallback_url: str,
        preferred_link_id: str = "",
        link_id_map: Optional[Dict[str, str]] = None
    ) -> str:
        """为条目分配最合适的链接"""
        normalized_link_id = self._normalize_link_id(preferred_link_id)
        if normalized_link_id and link_id_map:
            preferred_url = link_id_map.get(normalized_link_id, "")
            if preferred_url and preferred_url not in used_urls:
                used_urls.add(preferred_url)
                return preferred_url

        best_url = ""
        best_score = 0
        for anchor, url in candidates:
            if url in used_urls:
                continue
            score = self._score_link_match(item_title, anchor, url)
            if score > best_score:
                best_score = score
                best_url = url

        if best_url:
            used_urls.add(best_url)
            return best_url

        for _, url in candidates:
            if url not in used_urls:
                used_urls.add(url)
                return url

        return fallback_url

    def _is_bad_image_url(self, image_url: str) -> bool:
        """判断图片 URL 是否为站点装饰图或无效图"""
        if not image_url:
            return True

        lower = image_url.lower()
        bad_keywords = (
            'logo',
            'avatar',
            'favicon',
            'icon',
            'sprite',
            'placeholder',
            'default',
            'wechat-qun',
            'qrcode',
            'qr-code',
        )
        if any(keyword in lower for keyword in bad_keywords):
            return True
        if lower.endswith('.svg') or lower.endswith('.ico'):
            return True
        return False

    def _fetch_page_preview_image(self, page_url: str) -> str:
        """
        从页面提取预览图（优先 og:image）
        """
        if not page_url or not page_url.startswith('http'):
            return ""

        if page_url in self._page_image_cache:
            return self._page_image_cache[page_url]

        image_url = ""
        try:
            response = self.http_session.get(page_url, timeout=12)
            response.raise_for_status()

            from bs4 import BeautifulSoup
            soup = BeautifulSoup(response.text, 'html.parser')

            meta_candidates = [
                ('meta', {'property': 'og:image'}, 'content'),
                ('meta', {'property': 'og:image:url'}, 'content'),
                ('meta', {'name': 'twitter:image'}, 'content'),
                ('meta', {'itemprop': 'image'}, 'content'),
            ]
            for tag_name, attrs, attr_name in meta_candidates:
                tag = soup.find(tag_name, attrs=attrs)
                value = (tag.get(attr_name, '') if tag else '').strip()
                if not value:
                    continue
                candidate = urljoin(page_url, value)
                if not self._is_bad_image_url(candidate):
                    image_url = candidate
                    break

            if not image_url:
                first_img = soup.select_one('article img, main img, .content img, #content img, body img')
                if first_img:
                    src = (first_img.get('src') or first_img.get('data-src') or '').strip()
                    if src:
                        candidate = urljoin(page_url, src)
                        if not self._is_bad_image_url(candidate):
                            image_url = candidate
        except Exception as e:
            logger.debug(f"图片回填失败: {page_url}, 错误: {e}")
            image_url = ""

        self._page_image_cache[page_url] = image_url
        return image_url

    def _resolve_item_image_url(self, item_url: str, source_url: str, fallback_image_url: str) -> str:
        """
        为条目选择图片：优先条目页图片，避免聚合源（如公众号封面）重复图
        """
        clean_item_url = (item_url or "").strip()
        clean_source_url = (source_url or "").strip()
        is_wechat_source = "mp.weixin.qq.com" in clean_source_url.lower()

        # 1. 优先使用条目链接对应的图片（避免公众号封面图复用）
        if clean_item_url and clean_item_url != clean_source_url:
            image_url = self._fetch_page_preview_image(clean_item_url)
            if image_url and not self._is_bad_image_url(image_url):
                return image_url
            if is_wechat_source:
                # 微信聚合文章常见封面重复，条目页拿不到图时宁缺毋滥
                return ""

        # 2. 对非微信来源，才考虑直接使用原始回退图
        if fallback_image_url and not self._is_bad_image_url(fallback_image_url):
            return fallback_image_url

        # 3. 最后兜底尝试 source 页
        for page_url in [clean_source_url]:
            if not page_url:
                continue
            image_url = self._fetch_page_preview_image(page_url)
            if image_url and not self._is_bad_image_url(image_url):
                return image_url
        return ""

    def _build_dedup_key(self, item_url: str, source_url: str, title: str) -> str:
        """
        构建条目级去重键：同源链接时追加标题，避免聚合页条目互相覆盖
        """
        dedup_key = (item_url or source_url or "").strip()
        if dedup_key and source_url and dedup_key == source_url:
            normalized_title = re.sub(r'\s+', '', str(title).lower())
            return f"{source_url}#{normalized_title[:80]}"
        return dedup_key

    def _parse_ai_items_response(self, response_text: str) -> List[Dict[str, Any]]:
        """
        解析 AI 返回的 JSON，支持 {"items": [...]} 和 [...] 两种格式
        """
        clean_text = response_text or ""
        clean_text = re.sub(r'```json\s*', '', clean_text, flags=re.IGNORECASE)
        clean_text = re.sub(r'```\s*', '', clean_text)
        clean_text = re.sub(r'<thinking>.*?</thinking>', '', clean_text, flags=re.DOTALL)
        clean_text = re.sub(r'<thinking>.*', '', clean_text, flags=re.DOTALL)
        clean_text = clean_text.strip()

        if not clean_text:
            return []

        payloads = [clean_text]
        object_match = re.search(r'\{.*\}', clean_text, re.DOTALL)
        array_match = re.search(r'\[.*\]', clean_text, re.DOTALL)
        if object_match:
            payloads.append(object_match.group())
        if array_match:
            payloads.append(array_match.group())

        for payload in payloads:
            try:
                parsed = json.loads(payload)
                if isinstance(parsed, dict):
                    items = parsed.get('items', [])
                    if isinstance(items, list):
                        return items
                if isinstance(parsed, list):
                    return parsed
            except (json.JSONDecodeError, TypeError):
                continue
        return []
    
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
            candidate_links = self._extract_candidate_links(article)
            candidate_link_lines, link_id_map = self._build_link_candidates_for_prompt(candidate_links)
            candidate_link_block = "\n".join(candidate_link_lines) if candidate_link_lines else "- 无可用候选链接（请返回空 link_id）"
            used_item_urls = set()
            
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
6. 每条资讯尽量选择最匹配的 link_id；如果无法匹配，link_id 返回空字符串
7. summary 必须用“编辑点评”语气写 2-3 句，避免照抄原文，包含 2-4 个 emoji

【输出格式】
必须输出 JSON 对象，不要任何 markdown 标记或额外文本：
{{
  "items": [
    {{"title": "北京AI产业两年冲万亿", "summary": "北京发布九大行动计划，核心产业规模预计从4500亿冲刺万亿，信号很强。对区域产业链是明显利好，值得持续跟踪。📈🏙️", "category": "时事", "is_english": false, "link_id": "L3"}}
  ]
}}

如果无法提取，返回 {{"items": []}}"""
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
6. 每条资讯尽量选择最匹配的 link_id；如果无法匹配，link_id 返回空字符串
7. summary 必须用“编辑点评”语气写 2-3 句，避免照抄原文，包含 2-4 个 emoji

【输出格式】
必须输出 JSON 对象，不要任何 markdown 标记或额外文本：
{{
  "items": [
    {{"title": "15字以内的中文标题", "summary": "先说清事件，再补一两句点评，包含emoji。🚀✨", "category": "从可选分类中选择一个", "is_english": false, "link_id": "L1"}}
  ]
}}

如果没有可提取的内容，返回 {{"items": []}}"""
            
            user_prompt = f"""标题：{article.title}
来源：{article.source}
URL：{article.url}

候选链接（只能返回 link_id，不要返回 URL）：
{candidate_link_block}

内容：
{content}"""
            
            # 日刊类内容需要更多 token 来输出多个条目
            max_tokens = 4000 if is_daily_digest else 2000
            if self.ai_max_tokens:
                max_tokens = min(max_tokens, self.ai_max_tokens)
            logger.info(f"  日刊检测: {is_daily_digest}, 文章: {article.title[:30]}...")
            
            response = self.ai_client.chat.completions.create(
                model=self.ai_model,
                messages=[
                    {"role": "system", "content": extract_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                max_tokens=max_tokens,
                temperature=0.2
            )
            
            response_text = response.choices[0].message.content
            logger.debug(f"  AI原始响应(前300字): {response_text[:300] if response_text else 'None'}...")
            
            items = self._parse_ai_items_response(response_text)

            # 清理并返回条目
            result = []
            for item in items:
                if not isinstance(item, dict):
                    continue
                title = str(item.get('title', '')).strip()
                summary = self._format_editor_summary(str(item.get('summary', '')))
                if not title or summary == "暂无描述":
                    continue

                preferred_link_id = self._normalize_link_id(item.get('link_id', ''))
                model_item_url = str(item.get('item_url', '') or item.get('url', '')).strip()
                if model_item_url.startswith('http') and model_item_url not in used_item_urls:
                    item_url = model_item_url
                    used_item_urls.add(model_item_url)
                else:
                    item_url = self._select_item_link(
                        title,
                        candidate_links,
                        used_item_urls,
                        article.url,
                        preferred_link_id=preferred_link_id,
                        link_id_map=link_id_map
                    )

                result.append({
                    "title": title,
                    "summary": summary,
                    "category": str(item.get('category', '时事')).strip() or "时事",
                    "is_english": bool(item.get('is_english', self._detect_english(title))),
                    "source_url": article.url,
                    "item_url": item_url,
                    "image_url": article.image_url
                })

            if result:
                logger.info(f"  成功提取 {len(result)} 个条目")
                return result

            logger.warning("  AI 结果解析后没有有效条目，使用回退模式")
            
            # 解析失败，返回单条目（兼容原逻辑）
            # 对于日刊类内容，尝试从内容中提取有意义的标题和简介
            fallback_title = self._extract_fallback_title(article)
            fallback_summary = self._format_editor_summary(
                self._extract_fallback_summary(article, fallback_title)
            )
            return [{
                "title": fallback_title,
                "summary": fallback_summary,
                "category": "AI资讯" if is_daily_digest else "时事",
                "is_english": self._detect_english(article.title),
                "source_url": article.url,
                "item_url": self._select_item_link(
                    fallback_title,
                    candidate_links,
                    used_item_urls,
                    article.url,
                    link_id_map=link_id_map
                ),
                "image_url": article.image_url
            }]
            
        except Exception as e:
            logger.error(f"提取条目失败: {article.title}, 错误: {e}")
            fallback_title = self._extract_fallback_title(article)
            fallback_summary = self._format_editor_summary(
                self._extract_fallback_summary(article, fallback_title)
            )
            return [{
                "title": fallback_title,
                "summary": fallback_summary,
                "category": "AI资讯",
                "is_english": self._detect_english(article.title),
                "source_url": article.url,
                "item_url": article.url,
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

    def _format_editor_summary(self, summary: str) -> str:
        """
        将摘要整理为带轻点评的编辑口吻，并补充 emoji 风格
        """
        clean_text = self._clean_summary(summary)
        if clean_text == "暂无描述":
            return clean_text

        clean_text = re.sub(r'^\s*\d+\.\s*', '', clean_text)
        clean_text = re.sub(r'\s+', ' ', clean_text).strip()

        if len(clean_text) > 180:
            clean_text = clean_text[:180].rstrip('，,；;。.!?！？')

        emoji_pattern = r'[\U0001F300-\U0001FAFF\u2600-\u27BF]'
        emoji_count = len(re.findall(emoji_pattern, clean_text))
        if emoji_count == 0:
            if not clean_text.endswith(('。', '！', '？', '.', '!', '?')):
                clean_text += '。'
            clean_text += ' 🔍✨'
        elif emoji_count == 1:
            clean_text += ' 🚀'

        return clean_text

    def _fetch_github_trending_tools(self, limit: int = 20) -> List[Dict[str, str]]:
        """
        抓取 GitHub Trending，用于工具分类兜底补全
        """
        try:
            response = self.http_session.get("https://github.com/trending?since=daily", timeout=15)
            response.raise_for_status()

            from bs4 import BeautifulSoup
            soup = BeautifulSoup(response.text, 'html.parser')
            repos: List[Dict[str, str]] = []

            for row in soup.select('article.Box-row'):
                repo_link = row.select_one('h2 a[href]')
                if not repo_link:
                    continue

                href = (repo_link.get('href') or '').strip()
                if not href:
                    continue
                repo_url = urljoin("https://github.com", href)
                repo_name = re.sub(r'\s+', '', repo_link.get_text(" ", strip=True)).strip('/')
                if not repo_name:
                    continue

                desc_node = row.select_one('p')
                desc = desc_node.get_text(" ", strip=True) if desc_node else ""
                star_node = row.select_one('a[href$="/stargazers"]')
                stars = star_node.get_text(" ", strip=True) if star_node else ""

                repos.append({
                    "name": repo_name,
                    "url": repo_url,
                    "description": desc,
                    "stars": stars,
                })
                if len(repos) >= limit:
                    break
            return repos
        except Exception as e:
            logger.warning(f"抓取 GitHub Trending 失败: {e}")
            return []

    def _build_tool_fallback_summary(self, name: str, description: str, stars: str) -> str:
        """
        生成工具补全项的编辑点评摘要
        """
        desc = re.sub(r'\s+', ' ', (description or "").strip())
        if len(desc) > 100:
            desc = desc[:100].rstrip('，,；;。.!?！？:：') + "..."
        stars_text = f"，当前热度 {stars}" if stars else ""
        if desc:
            summary = f"🚀 GitHub 热门项目 {name}{stars_text}：{desc}。建议先看 README 与最近提交，再评估是否引入到你的工作流。⭐🛠️"
        else:
            summary = f"🚀 GitHub 热门项目 {name}{stars_text}，近期关注度很高。建议快速浏览 README、Issue 与示例，判断是否适合当前业务。⭐🛠️"
        return self._format_editor_summary(summary)

    def _compose_editor_commentary(self, title: str, raw_summary: str, category_name: str) -> str:
        """
        用模型生成简短点评，失败时退回本地摘要格式化
        """
        base_summary = self._clean_summary(raw_summary) if raw_summary else "暂无描述"
        if base_summary == "暂无描述":
            return base_summary

        prompt = f"""你是技术周刊编辑。请基于给定标题和素材，写一段中文点评。

要求：
1. 2-3句，总长度约70-130字
2. 不要照抄素材原句，要有编辑视角
3. 包含2-4个emoji
4. 不要输出标题，不要markdown，仅输出一段正文

分类：{category_name}
标题：{title}
素材：{truncate_text(base_summary, 320)}"""
        try:
            response = self.ai_client.chat.completions.create(
                model=self.ai_model,
                messages=[
                    {"role": "system", "content": "你是专业的技术编辑。"},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=220,
                temperature=0.5
            )
            content = response.choices[0].message.content if response.choices else ""
            if content:
                return self._format_editor_summary(content)
        except Exception as e:
            logger.debug(f"编辑点评生成失败，使用本地回退: {title[:40]}..., 错误: {e}")

        return self._format_editor_summary(base_summary)

    def _get_fallback_feeds_for_category(self, category_name: str) -> List[Dict[str, str]]:
        """
        分类兜底的联网来源（RSS）
        """
        if category_name == "AI资讯":
            return [
                {"name": "OpenAI News", "url": "https://openai.com/news/rss.xml"},
                {"name": "Hugging Face Blog", "url": "https://huggingface.co/blog/feed.xml"},
                {"name": "Google AI Blog", "url": "https://blog.google/technology/ai/rss/"},
                {"name": "VentureBeat AI", "url": "https://venturebeat.com/category/ai/feed/"},
                {"name": "AI News", "url": "https://www.artificialintelligence-news.com/feed/"},
                {"name": "MIT AI Topic", "url": "https://www.technologyreview.com/topic/artificial-intelligence/feed"},
            ]

        if category_name == "时事":
            return [
                {"name": "TechCrunch", "url": "https://techcrunch.com/feed/"},
                {"name": "The Verge", "url": "https://www.theverge.com/rss/index.xml"},
                {"name": "InfoQ", "url": "https://www.infoq.com/feed/"},
                {"name": "36Kr", "url": "https://www.36kr.com/feed"},
            ]

        if category_name == "教程":
            return [
                {"name": "Frontend Masters Blog", "url": "https://frontendmasters.com/blog/feed/"},
                {"name": "CSS-Tricks", "url": "https://css-tricks.com/feed/"},
                {"name": "Smashing Magazine", "url": "https://www.smashingmagazine.com/feed/"},
                {"name": "web.dev", "url": "https://web.dev/feed.xml"},
            ]

        return []

    def _article_timestamp(self, article: Article) -> float:
        """
        统一文章时间戳，便于排序
        """
        if not article.published:
            return 0.0
        dt = article.published
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()

    def _collect_fallback_articles(
        self,
        feeds: List[Dict[str, str]],
        max_articles: int = 120
    ) -> List[Article]:
        """
        从兜底 RSS 源抓取并按时间排序
        """
        if not feeds:
            return []

        fetcher = RSSFetcher(feeds)
        articles = fetcher.fetch_all()
        if not articles:
            return []

        # 兜底阶段适当放宽时间窗口，保证最小数量目标
        fallback_hours = max(self.config.get('time_filter', {}).get('hours', 168), 336)
        now = datetime.now(timezone.utc).timestamp()
        cutoff = now - fallback_hours * 3600

        filtered = []
        for article in articles:
            ts = self._article_timestamp(article)
            if ts == 0 or ts >= cutoff:
                filtered.append(article)

        filtered.sort(key=self._article_timestamp, reverse=True)
        return filtered[:max_articles]

    def _supplement_category_with_feeds(
        self,
        category_name: str,
        needed_count: int,
        run_dedup_urls: set,
        used_image_urls: set
    ) -> List[WeeklyItem]:
        """
        通过联网 RSS 兜底补齐指定分类
        """
        if needed_count <= 0:
            return []

        feeds = self._get_fallback_feeds_for_category(category_name)
        fallback_articles = self._collect_fallback_articles(feeds, max_articles=max(needed_count * 20, 80))
        if not fallback_articles:
            return []

        items: List[WeeklyItem] = []
        for article in fallback_articles:
            title = (article.title or "").strip()
            item_url = (article.url or "").strip()
            if not title or not item_url:
                continue

            dedup_key = self._build_dedup_key(item_url, item_url, title)
            if dedup_key in run_dedup_urls:
                continue
            if self.deduplicator and self.deduplicator.is_duplicate(dedup_key):
                continue

            raw_summary = article.summary or article.content or title
            summary = self._compose_editor_commentary(title, raw_summary, category_name)
            if not summary or summary == "暂无描述":
                continue

            image_url = self._resolve_item_image_url(item_url, item_url, article.image_url)
            if image_url and image_url in used_image_urls:
                image_url = ""
            if image_url:
                used_image_urls.add(image_url)

            run_dedup_urls.add(dedup_key)
            items.append(WeeklyItem(
                title=title,
                url=item_url,
                summary=summary,
                is_english=self._detect_english(title),
                category=category_name,
                short_title=title,
                image_url=image_url,
                item_url=item_url,
                source_url=item_url
            ))

            if len(items) >= needed_count:
                break

        if items:
            logger.info(f"{category_name} 分类已通过联网兜底补齐 {len(items)} 条")
        return items

    def _get_effective_min_count(self, category_name: str, config_min_count: int) -> int:
        """
        计算分类最小数量约束（时事/AI资讯强制至少5）
        """
        min_count = max(0, int(config_min_count or 0))
        if category_name in ("时事", "AI资讯"):
            min_count = max(min_count, 5)
        return min_count

    def _supplement_tools_with_github(
        self,
        needed_count: int,
        run_dedup_urls: set
    ) -> List[WeeklyItem]:
        """
        当工具数量不足时，使用 GitHub Trending 自动补齐
        """
        if needed_count <= 0:
            return []

        repos = self._fetch_github_trending_tools(limit=max(needed_count * 4, 20))
        if not repos:
            return []

        items: List[WeeklyItem] = []
        for repo in repos:
            title = repo.get("name", "").strip()
            item_url = repo.get("url", "").strip()
            if not title or not item_url:
                continue

            dedup_key = self._build_dedup_key(item_url, item_url, title)
            if dedup_key in run_dedup_urls:
                continue
            if self.deduplicator and self.deduplicator.is_duplicate(dedup_key):
                continue

            run_dedup_urls.add(dedup_key)
            item = WeeklyItem(
                title=title,
                url=item_url,
                summary=self._build_tool_fallback_summary(
                    title,
                    repo.get("description", ""),
                    repo.get("stars", "")
                ),
                is_english=self._detect_english(title),
                category="工具",
                short_title=title,
                image_url="",
                item_url=item_url,
                source_url=item_url
            )
            items.append(item)
            if len(items) >= needed_count:
                break

        if items:
            logger.info(f"工具分类已由 GitHub Trending 补齐 {len(items)} 条")
        return items
    
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
        run_dedup_urls = set()
        used_image_urls = set()
        allowed_category_names = {
            cat_config.get('name', cat_key)
            for cat_key, cat_config in categories_config.items()
            if cat_key != 'training'
        }
        
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
                if category not in allowed_category_names:
                    category = "时事"

                title = item_data.get('title', article.title)
                item_url = item_data.get('item_url') or article.url
                source_url = item_data.get('source_url') or article.url
                dedup_key = self._build_dedup_key(item_url, source_url, title)

                # 确保分类存在
                if category not in all_items:
                    all_items[category] = []

                if dedup_key in run_dedup_urls:
                    continue
                if self.deduplicator and self.deduplicator.is_duplicate(dedup_key):
                    logger.info(f"    跳过已处理条目: {item_data.get('title', '')[:40]}")
                    continue
                run_dedup_urls.add(dedup_key)

                image_url = self._resolve_item_image_url(
                    item_url,
                    source_url,
                    item_data.get('image_url', '')
                )
                if image_url and image_url in used_image_urls:
                    # 避免周刊中大面积复用同一封面图
                    if item_url and item_url != source_url:
                        alt_image = self._fetch_page_preview_image(item_url)
                        if alt_image and not self._is_bad_image_url(alt_image) and alt_image not in used_image_urls:
                            image_url = alt_image
                        else:
                            image_url = ""
                    else:
                        image_url = ""
                if image_url:
                    used_image_urls.add(image_url)
                
                item = WeeklyItem(
                    title=title,
                    url=item_url,
                    summary=item_data.get('summary', '暂无描述'),
                    is_english=item_data.get('is_english', False),
                    category=category,
                    short_title=item_data.get('title', ''),
                    image_url=image_url,
                    item_url=item_url,
                    source_url=source_url
                )
                all_items[category].append(item)

        # 联网兜底：确保分类达到最小数量
        for cat_key, cat_config in categories_config.items():
            if cat_key == 'training':
                continue
            cat_name = cat_config.get('name', cat_key)
            min_count = self._get_effective_min_count(cat_name, cat_config.get('min_count', 0))
            current_count = len(all_items.get(cat_name, []))
            if current_count >= min_count:
                continue

            needed_count = min_count - current_count
            if cat_name == "工具":
                fallback_items = self._supplement_tools_with_github(needed_count, run_dedup_urls)
            else:
                fallback_items = self._supplement_category_with_feeds(
                    cat_name,
                    needed_count,
                    run_dedup_urls,
                    used_image_urls
                )

            if fallback_items:
                if cat_name not in all_items:
                    all_items[cat_name] = []
                all_items[cat_name].extend(fallback_items)
        
        # 按配置的 max_count 限制每个分类的数量
        for cat_key, cat_config in categories_config.items():
            cat_name = cat_config.get('name', cat_key)
            max_count = cat_config.get('max_count', 5)
            min_count = self._get_effective_min_count(cat_name, cat_config.get('min_count', 1))
            
            if cat_name in all_items:
                if len(all_items[cat_name]) > max_count:
                    all_items[cat_name] = all_items[cat_name][:max_count]
                
                if len(all_items[cat_name]) < min_count:
                    logger.warning(f"分类 {cat_name} 内容不足: {len(all_items[cat_name])}/{min_count}")
                
                logger.info(f"分类 {cat_name} 最终: {len(all_items[cat_name])} 条")

        self._latest_dedup_urls = run_dedup_urls
        
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
                category="训练",
                item_url=problem.url,
                source_url=problem.url
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

        # 更新去重缓存（仅记录非训练项）
        if self.deduplicator:
            dedup_urls = []
            for category_name, items in categories_data.items():
                if category_name == "训练":
                    continue
                for item in items:
                    dedup_url = self._build_dedup_key(item.item_url, item.source_url, item.title)
                    if dedup_url:
                        dedup_urls.append(dedup_url)
            if dedup_urls:
                self.deduplicator.mark_batch_processed(dedup_urls)
                logger.info(f"已写入 Weekly 去重缓存: {len(dedup_urls)} 条")

        # 更新期号状态文件
        self._set_next_issue(issue)
        
        logger.info("=" * 50)
        logger.info(f"✅ Weekly NO{issue} 生成完成")
        logger.info(f"📄 文件已保存到: {saved_path}")
        logger.info("=" * 50)
        
        return saved_path
