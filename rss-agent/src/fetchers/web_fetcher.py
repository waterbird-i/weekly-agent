"""
网页抓取模块
负责从普通网页获取文章内容
"""

import requests
import logging
from typing import Optional, List
from datetime import datetime, timezone
from ..core.rss_fetcher import Article
from ..utils import clean_html

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
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
        }

    def _extract_image(self, soup, url: str) -> str:
        """
        从网页中提取首张图片
        
        Args:
            soup: BeautifulSoup对象
            url: 网页URL（用于处理相对路径）
            
        Returns:
            图片URL或空字符串
        """
        from urllib.parse import urljoin
        
        # 1. 优先尝试 og:image (社交媒体分享图)
        og_image = soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            img_url = og_image['content']
            if img_url and not img_url.startswith('data:'):
                return urljoin(url, img_url)
        
        # 2. 尝试 twitter:image
        twitter_image = soup.find('meta', attrs={'name': 'twitter:image'})
        if twitter_image and twitter_image.get('content'):
            img_url = twitter_image['content']
            if img_url and not img_url.startswith('data:'):
                return urljoin(url, img_url)
        
        # 3. 微信公众号特殊处理
        if "mp.weixin.qq.com" in url:
            # 微信文章封面图
            cover_img = soup.find('meta', property='og:image') or soup.find('img', id='js_cover')
            if cover_img:
                img_url = cover_img.get('content') or cover_img.get('src')
                if img_url and not img_url.startswith('data:'):
                    return img_url
        
        # 4. 正文中的第一张有效图片
        content_selectors = [
            'article img',
            '.content img',
            '.post-content img',
            'main img',
            '#content img',
            '.rich_media_content img',  # 微信公众号
            'body img'
        ]
        
        for selector in content_selectors:
            imgs = soup.select(selector)
            for img in imgs:
                src = img.get('src') or img.get('data-src')
                if src and not src.startswith('data:') and len(src) > 10:
                    # 过滤logo、icon等小图片
                    width = img.get('width', '')
                    height = img.get('height', '')
                    if width and str(width).isdigit() and int(width) < 50:
                        continue
                    if height and str(height).isdigit() and int(height) < 50:
                        continue
                    return urljoin(url, src)
        
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
            response = requests.get(url, headers=self.headers, timeout=self.timeout)
            response.raise_for_status()
            
            # 处理编码
            if response.encoding == 'ISO-8859-1':
                response.encoding = response.apparent_encoding
            
            html_content = response.text
            
            # 提取标题 (简单提取)
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html_content, 'html.parser')
            # 使用 get_text() 更安全地提取标题，避免 soup.title.string 为 None 时报错
            title = soup.title.get_text(strip=True) if soup.title else "无标题"
            
            # 微信公众号特殊处理标题
            if "mp.weixin.qq.com" in url:
                # 微信公众号标题通常在 meta 标签或特定 id 的元素中
                wechat_title = soup.find('meta', property='og:title')
                if wechat_title:
                    title = wechat_title.get('content', title)
                else:
                    h1_title = soup.find('h1', class_='rich_media_title')
                    if h1_title:
                        title = h1_title.get_text(strip=True)

            content = clean_html(html_content)
            
            # 提取图片
            image_url = self._extract_image(soup, url)
            if image_url:
                logger.info(f"  提取到图片: {image_url[:80]}...")
            
            # 简单生成摘要 (前500字)
            summary = content[:500] + "..." if len(content) > 500 else content
            
            article = Article(
                title=title or name,
                url=url,
                content=content,
                summary=summary,
                published=datetime.now(timezone.utc), # 网页爬取通常没有明确发布日期，默认现在
                source=name,
                image_url=image_url
            )
            
            return article
            
        except Exception as e:
            logger.error(f"抓取网页失败: {url}, 错误: {e}")
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
