"""
内容过滤模块
在调用AI之前对文章进行预过滤
"""

from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any
import logging
import re

from .rss_fetcher import Article

logger = logging.getLogger(__name__)


class ContentFilter:
    """内容过滤器，在AI处理前进行预过滤"""
    
    def __init__(self, config: Dict[str, Any]):
        """
        初始化内容过滤器
        
        Args:
            config: 配置字典
        """
        self.config = config
        
        # 提取配置
        self.time_filter_hours = config.get('time_filter', {}).get('hours', 24)
        
        pre_filter = config.get('pre_filter', {})
        self.include_keywords = pre_filter.get('include_keywords', [])
        self.exclude_keywords = pre_filter.get('exclude_keywords', [])
        self.min_content_length = pre_filter.get('min_content_length', 100)
    
    def filter_by_time(self, articles: List[Article]) -> List[Article]:
        """
        按时间范围过滤文章
        
        Args:
            articles: 文章列表
            
        Returns:
            过滤后的文章列表
        """
        if not self.time_filter_hours:
            return articles
        
        now = datetime.now(timezone.utc)
        cutoff_time = now - timedelta(hours=self.time_filter_hours)
        
        filtered = []
        for article in articles:
            if article.published:
                # 确保时区一致性
                pub_time = article.published
                if pub_time.tzinfo is None:
                    pub_time = pub_time.replace(tzinfo=timezone.utc)
                
                if pub_time >= cutoff_time:
                    filtered.append(article)
            else:
                # 没有发布时间的文章，默认包含
                filtered.append(article)
        
        logger.info(f"时间过滤: {len(articles)} -> {len(filtered)} 篇文章")
        return filtered
    
    def filter_by_keywords(self, articles: List[Article]) -> List[Article]:
        """
        按关键词过滤文章
        
        Args:
            articles: 文章列表
            
        Returns:
            过滤后的文章列表
        """
        if not self.include_keywords and not self.exclude_keywords:
            return articles
        
        filtered = []
        for article in articles:
            # 合并标题、摘要和内容进行关键词匹配
            text = f"{article.title} {article.summary} {article.content}".lower()
            
            # 检查排除关键词
            should_exclude = False
            for keyword in self.exclude_keywords:
                if keyword.lower() in text:
                    should_exclude = True
                    break
            
            if should_exclude:
                continue
            
            # 如果有包含关键词列表，检查是否匹配
            if self.include_keywords:
                should_include = False
                for keyword in self.include_keywords:
                    # 使用正则进行更精确的匹配
                    pattern = re.compile(re.escape(keyword.lower()))
                    if pattern.search(text):
                        should_include = True
                        break
                
                if should_include:
                    filtered.append(article)
            else:
                # 没有包含关键词列表，默认包含
                filtered.append(article)
        
        logger.info(f"关键词过滤: {len(articles)} -> {len(filtered)} 篇文章")
        return filtered
    
    def filter_by_content_length(self, articles: List[Article]) -> List[Article]:
        """
        按内容长度过滤文章
        
        Args:
            articles: 文章列表
            
        Returns:
            过滤后的文章列表
        """
        if not self.min_content_length:
            return articles
        
        filtered = []
        for article in articles:
            content_length = len(article.content) + len(article.summary)
            if content_length >= self.min_content_length:
                filtered.append(article)
        
        logger.info(f"内容长度过滤: {len(articles)} -> {len(filtered)} 篇文章")
        return filtered
    
    def apply_all_filters(self, articles: List[Article]) -> List[Article]:
        """
        应用所有过滤器
        
        Args:
            articles: 文章列表
            
        Returns:
            过滤后的文章列表
        """
        logger.info(f"开始过滤，原始文章数: {len(articles)}")
        
        # 按顺序应用过滤器
        filtered = articles
        
        # 1. 时间过滤
        filtered = self.filter_by_time(filtered)
        
        # 2. 内容长度过滤
        filtered = self.filter_by_content_length(filtered)
        
        logger.info(f"过滤完成，剩余文章数: {len(filtered)}")
        return filtered
