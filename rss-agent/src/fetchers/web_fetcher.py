"""
网页抓取模块
负责从普通网页获取文章内容
"""

import requests
import logging
from typing import Optional, List
from datetime import datetime, timezone
from urllib.parse import urljoin
from ..core.rss_fetcher import Article
from ..utils import clean_html, create_retry_session

logger = logging.getLogger(__name__)


class WebFetcher:
    """普通网页抓取器"""

    def __init__(self, timeout: int = 15):
        """
        初始化网页抓取器
        
        Args:
            timeout: 请求超时时间（秒）
        """
        self.timeout = timeout
        self.session = create_retry_session(total_retries=3, backoff_factor=0.8)
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
        }
        self.session.headers.update(self.headers)

    def _is_likely_logo(self, image_url: str) -> bool:
        """判断图片 URL 是否疑似站点 logo/icon"""
        lower = image_url.lower()
        bad_keywords = (
            'logo', 'icon', 'avatar', 'favicon', 'sprite', 'brand', 'header', 'footer'
        )
        return any(keyword in lower for keyword in bad_keywords)

    def _is_small_image(self, img) -> bool:
        """判断图片元素是否过小（通常是 icon）"""
        width = img.get('width', '')
        height = img.get('height', '')
        if str(width).isdigit() and int(width) < 120:
            return True
        if str(height).isdigit() and int(height) < 120:
            return True
        return False

    def _extract_main_content(self, soup, html_content: str) -> str:
        """
        从页面中提取正文区域，减少导航和页面噪音
        """
        selectors = [
            'article',
            '.rich_media_content',  # 微信公众号
            '#js_content',          # 微信公众号正文 ID
            '.post-content',
            '.entry-content',
            '.article-content',
            'main',
            '#content',
            '.content'
        ]

        best_node = None
        best_text_len = 0
        for selector in selectors:
            for node in soup.select(selector):
                text_len = len(node.get_text(" ", strip=True))
                if text_len > best_text_len:
                    best_text_len = text_len
                    best_node = node

        if best_node and best_text_len >= 120:
            return clean_html(str(best_node))

        return clean_html(html_content)

    def _extract_image(self, soup, url: str) -> str:
        """
        从网页中提取首张图片
        
        Args:
            soup: BeautifulSoup对象
            url: 网页URL（用于处理相对路径）
            
        Returns:
            图片URL或空字符串
        """
        def normalize_image_url(img_url: str) -> str:
            if not img_url or img_url.startswith('data:'):
                return ""
            full_url = urljoin(url, img_url)
            if self._is_likely_logo(full_url):
                return ""
            return full_url

        # 1. 优先尝试 og:image (社交媒体分享图)
        og_image = soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            normalized = normalize_image_url(og_image['content'])
            if normalized:
                return normalized

        # 2. 尝试 twitter:image
        twitter_image = soup.find('meta', attrs={'name': 'twitter:image'})
        if twitter_image and twitter_image.get('content'):
            normalized = normalize_image_url(twitter_image['content'])
            if normalized:
                return normalized

        # 3. 微信公众号特殊处理
        if "mp.weixin.qq.com" in url:
            # 微信文章封面图
            cover_img = soup.find('meta', property='og:image') or soup.find('img', id='js_cover')
            if cover_img:
                img_url = cover_img.get('content') or cover_img.get('src')
                normalized = normalize_image_url(img_url)
                if normalized:
                    return normalized

        # 4. 正文中的第一张有效图片（优先正文区域，最后再尝试 body）
        content_selectors = [
            '.rich_media_content img',  # 微信公众号
            '#js_content img',
            'article img',
            '.post-content img',
            '.entry-content img',
            '.article-content img',
            'main img',
            '#content img',
            '.content img',
            'body img'
        ]

        for selector in content_selectors:
            imgs = soup.select(selector)
            for img in imgs:
                src = img.get('src') or img.get('data-src')
                if not src or len(src) < 10:
                    continue
                if self._is_small_image(img):
                    continue
                normalized = normalize_image_url(src)
                if normalized:
                    return normalized

        return ""

    def fetch_url(self, url: str, name: str = "网页内容") -> Optional[Article]:
        """
        抓取单个网页并转换为 Article 对象
        
        Args:
            url: 网页 URL
            name: 来源名称
            
        Returns:
            Article 对象或 None
        """
        try:
            logger.info(f"正在抓取网页内容: {url}")
            response = self.session.get(url, timeout=self.timeout)
            response.raise_for_status()

            # 处理编码
            if response.encoding == 'ISO-8859-1':
                response.encoding = response.apparent_encoding

            html_content = response.text

            # 提取标题
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html_content, 'html.parser')
            title = soup.title.get_text(strip=True) if soup.title else "无标题"

            # 微信公众号特殊处理标题
            if "mp.weixin.qq.com" in url:
                wechat_title = soup.find('meta', property='og:title')
                if wechat_title:
                    title = wechat_title.get('content', title)
                else:
                    h1_title = soup.find('h1', class_='rich_media_title')
                    if h1_title:
                        title = h1_title.get_text(strip=True)

            content = self._extract_main_content(soup, html_content)

            # 提取图片
            image_url = self._extract_image(soup, url)
            if image_url:
                logger.info(f"  提取到图片: {image_url[:80]}...")

            # 简单生成摘要（前500字）
            summary = content[:500] + "..." if len(content) > 500 else content

            article = Article(
                title=title or name,
                url=url,
                content=content,
                summary=summary,
                published=datetime.now(timezone.utc),  # 网页爬取通常没有明确发布日期，默认现在
                source=name,
                image_url=image_url
            )

            return article

        except requests.exceptions.RequestException as e:
            logger.error(f"抓取网页网络错误: {url}, 错误类型: {type(e).__name__}, 错误: {e}")
            return None
        except Exception as e:
            logger.error(f"抓取网页失败: {url}, 错误类型: {type(e).__name__}, 错误: {e}")
            return None

    def fetch_all(self, urls: List[dict]) -> List[Article]:
        """
        抓取多个网页
        
        Args:
            urls: 包含 name 和 url 的字典列表
            
        Returns:
            Article 列表
        """
        articles = []
        for item in urls:
            url = item.get('url')
            name = item.get('name', '网页内容')
            if url:
                article = self.fetch_url(url, name)
                if article:
                    articles.append(article)
        return articles
