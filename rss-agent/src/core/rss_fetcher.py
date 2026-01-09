"""
RSS订阅抓取模块
负责从RSS源获取文章列表
"""

import re
import feedparser
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field
from dateutil import parser as date_parser
import logging

from ..utils import clean_html

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class Article:
    """文章数据类"""
    title: str
    url: str
    content: str
    summary: str
    published: Optional[datetime]
    source: str
    author: str = ""
    tags: List[str] = field(default_factory=list)
    image_url: str = ""  # 文章配图 URL
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "title": self.title,
            "url": self.url,
            "content": self.content,
            "summary": self.summary,
            "published": self.published.isoformat() if self.published else None,
            "source": self.source,
            "author": self.author,
            "tags": self.tags,
            "image_url": self.image_url
        }


class RSSFetcher:
    """RSS订阅抓取器"""
    
    def __init__(self, feeds: List[Dict[str, str]]):
        """
        初始化RSS抓取器
        
        Args:
            feeds: RSS源列表，每个元素包含name和url
        """
        self.feeds = feeds
    
    def _parse_date(self, entry: Any) -> Optional[datetime]:
        """
        解析文章发布日期
        
        Args:
            entry: feedparser的entry对象
            
        Returns:
            datetime对象或None
        """
        # 尝试多个日期字段
        date_fields = ['published', 'updated', 'created']
        
        for field in date_fields:
            date_str = getattr(entry, field, None)
            if date_str:
                try:
                    # 使用dateutil解析各种格式的日期
                    dt = date_parser.parse(date_str)
                    # 确保有时区信息，如果没有则假定为UTC
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    return dt
                except (ValueError, TypeError):
                    continue
        
        # 尝试使用time_struct
        for field in ['published_parsed', 'updated_parsed', 'created_parsed']:
            time_struct = getattr(entry, field, None)
            if time_struct:
                try:
                    dt = datetime(*time_struct[:6], tzinfo=timezone.utc)
                    return dt
                except (TypeError, ValueError):
                    continue
        
        return None
    
    def _extract_content(self, entry: Any) -> str:
        """
        提取文章内容
        
        Args:
            entry: feedparser的entry对象
            
        Returns:
            清理后的文章内容
        """
        content = ""
        
        # 尝试从content字段获取
        if hasattr(entry, 'content') and entry.content:
            content = entry.content[0].get('value', '')
        
        # 如果没有content，尝试description
        if not content and hasattr(entry, 'description'):
            content = entry.description or ""
        
        # 如果还是没有，尝试summary
        if not content and hasattr(entry, 'summary'):
            content = entry.summary or ""
        
        return clean_html(content)
    
    def _extract_summary(self, entry: Any) -> str:
        """
        提取文章摘要
        
        Args:
            entry: feedparser的entry对象
            
        Returns:
            文章摘要
        """
        summary = ""
        
        if hasattr(entry, 'summary'):
            summary = entry.summary or ""
        elif hasattr(entry, 'description'):
            summary = entry.description or ""
        
        return clean_html(summary)[:500]  # 限制摘要长度
    
    def _extract_tags(self, entry: Any) -> List[str]:
        """
        提取文章标签
        
        Args:
            entry: feedparser的entry对象
            
        Returns:
            标签列表
        """
        tags = []
        
        if hasattr(entry, 'tags'):
            for tag in entry.tags:
                if hasattr(tag, 'term') and tag.term:
                    tags.append(tag.term)
        
        return tags
    
    def _extract_image(self, entry: Any, content: str) -> str:
        """
        提取文章配图
        
        Args:
            entry: feedparser的entry对象
            content: 文章内容
            
        Returns:
            图片URL或空字符串
        """
        # 1. 尝试从 media_content 获取
        if hasattr(entry, 'media_content') and entry.media_content:
            for media in entry.media_content:
                url = media.get('url', '')
                media_type = media.get('type', '')
                if url and ('image' in media_type or url.endswith(('.jpg', '.jpeg', '.png', '.gif', '.webp'))):
                    return url
        
        # 2. 尝试从 media_thumbnail 获取
        if hasattr(entry, 'media_thumbnail') and entry.media_thumbnail:
            for thumb in entry.media_thumbnail:
                url = thumb.get('url', '')
                if url:
                    return url
        
        # 3. 尝试从 enclosures 获取
        if hasattr(entry, 'enclosures') and entry.enclosures:
            for enclosure in entry.enclosures:
                url = enclosure.get('url', '') or enclosure.get('href', '')
                enc_type = enclosure.get('type', '')
                if url and 'image' in enc_type:
                    return url
        
        # 4. 尝试从 links 获取
        if hasattr(entry, 'links'):
            for link in entry.links:
                if link.get('type', '').startswith('image/'):
                    return link.get('href', '')
        
        # 5. 尝试从原始内容中提取第一个 img 标签
        if content:
            # 从原始 HTML 内容提取
            raw_content = ""
            if hasattr(entry, 'content') and entry.content:
                raw_content = entry.content[0].get('value', '')
            elif hasattr(entry, 'description'):
                raw_content = entry.description or ""
            elif hasattr(entry, 'summary'):
                raw_content = entry.summary or ""
            
            if raw_content:
                img_match = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', raw_content, re.IGNORECASE)
                if img_match:
                    img_url = img_match.group(1)
                    # 过滤掉 base64 图片和太短的 URL
                    if not img_url.startswith('data:') and len(img_url) > 10:
                        return img_url
        
        return ""
    
    def fetch_feed(self, feed_name: str, feed_url: str) -> List[Article]:
        """
        获取单个RSS源的文章
        
        Args:
            feed_name: RSS源名称
            feed_url: RSS源URL
            
        Returns:
            文章列表
        """
        articles = []
        
        try:
            logger.info(f"正在抓取RSS源: {feed_name} ({feed_url})")
            parsed = feedparser.parse(feed_url)
            
            if parsed.bozo and parsed.bozo_exception:
                logger.warning(f"解析RSS源时出现问题: {feed_name}, 错误: {parsed.bozo_exception}")
            
            for entry in parsed.entries:
                try:
                    content = self._extract_content(entry)
                    article = Article(
                        title=getattr(entry, 'title', '无标题'),
                        url=getattr(entry, 'link', ''),
                        content=content,
                        summary=self._extract_summary(entry),
                        published=self._parse_date(entry),
                        source=feed_name,
                        author=getattr(entry, 'author', ''),
                        tags=self._extract_tags(entry),
                        image_url=self._extract_image(entry, content)
                    )
                    
                    if article.url:  # 只添加有URL的文章
                        articles.append(article)
                        
                except Exception as e:
                    logger.error(f"处理文章时出错: {e}")
                    continue
            
            logger.info(f"从 {feed_name} 获取了 {len(articles)} 篇文章")
            
        except Exception as e:
            logger.error(f"获取RSS源失败: {feed_name}, 错误: {e}")
        
        return articles
    
    def fetch_all(self) -> List[Article]:
        """
        获取所有RSS源的文章
        
        Returns:
            所有文章列表
        """
        all_articles = []
        
        for feed in self.feeds:
            name = feed.get('name', 'Unknown')
            url = feed.get('url', '')
            
            if url:
                articles = self.fetch_feed(name, url)
                all_articles.extend(articles)
        
        logger.info(f"共获取 {len(all_articles)} 篇文章")
        return all_articles
