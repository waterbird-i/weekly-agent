"""
工具函数模块
包含URL去重、缓存管理等功能
"""

import json
import os
from datetime import datetime, timedelta
from typing import List, Optional, Tuple
from pathlib import Path
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


class URLDeduplicator:
    """URL去重器，使用本地JSON文件缓存已处理的URL"""
    
    def __init__(self, cache_file: str, expire_hours: int = 168):
        """
        初始化URL去重器
        
        Args:
            cache_file: 缓存文件路径
            expire_hours: 缓存过期时间（小时）
        """
        self.cache_file = cache_file
        self.expire_hours = expire_hours
        self.cache: dict = {}
        self._load_cache()
    
    def _load_cache(self):
        """从文件加载缓存"""
        if os.path.exists(self.cache_file):
            try:
                with open(self.cache_file, 'r', encoding='utf-8') as f:
                    self.cache = json.load(f)
            except (json.JSONDecodeError, IOError):
                self.cache = {}
        else:
            # 确保目录存在
            Path(self.cache_file).parent.mkdir(parents=True, exist_ok=True)
            self.cache = {}
    
    def _save_cache(self):
        """保存缓存到文件"""
        Path(self.cache_file).parent.mkdir(parents=True, exist_ok=True)
        with open(self.cache_file, 'w', encoding='utf-8') as f:
            json.dump(self.cache, f, ensure_ascii=False, indent=2)
    
    def _clean_expired(self):
        """清理过期的缓存条目"""
        now = datetime.now()
        expired_urls = []
        
        for url, timestamp_str in self.cache.items():
            try:
                cached_time = datetime.fromisoformat(timestamp_str)
                if now - cached_time > timedelta(hours=self.expire_hours):
                    expired_urls.append(url)
            except (ValueError, TypeError):
                expired_urls.append(url)
        
        for url in expired_urls:
            del self.cache[url]
        
        if expired_urls:
            self._save_cache()
    
    def is_duplicate(self, url: str) -> bool:
        """
        检查URL是否已处理过
        
        Args:
            url: 要检查的URL
            
        Returns:
            True如果是重复的，False否则
        """
        self._clean_expired()
        return url in self.cache
    
    def mark_processed(self, url: str):
        """
        标记URL为已处理
        
        Args:
            url: 要标记的URL
        """
        self.cache[url] = datetime.now().isoformat()
        self._save_cache()
    
    def mark_batch_processed(self, urls: List[str]):
        """
        批量标记URL为已处理
        
        Args:
            urls: URL列表
        """
        now = datetime.now().isoformat()
        for url in urls:
            self.cache[url] = now
        self._save_cache()
    
    def filter_new_urls(self, urls: List[str]) -> List[str]:
        """
        过滤出新的（未处理过的）URL
        
        Args:
            urls: URL列表
            
        Returns:
            未处理过的URL列表
        """
        self._clean_expired()
        return [url for url in urls if url not in self.cache]
    
    def get_processed_count(self) -> int:
        """获取已处理URL数量"""
        return len(self.cache)


def create_retry_session(
    total_retries: int = 3,
    backoff_factor: float = 0.8,
    status_forcelist: Optional[Tuple[int, ...]] = None
) -> requests.Session:
    """
    创建带重试机制的 requests Session

    Args:
        total_retries: 最大重试次数
        backoff_factor: 退避系数
        status_forcelist: 触发重试的状态码

    Returns:
        requests.Session
    """
    retry_codes = status_forcelist or (429, 500, 502, 503, 504)
    retry = Retry(
        total=total_retries,
        connect=total_retries,
        read=total_retries,
        status=total_retries,
        backoff_factor=backoff_factor,
        status_forcelist=retry_codes,
        allowed_methods=frozenset(["GET", "POST", "HEAD", "OPTIONS"]),
        raise_on_status=False
    )

    adapter = HTTPAdapter(max_retries=retry)
    session = requests.Session()
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


def clean_html(html_content: str) -> str:
    """
    清理HTML内容，提取纯文本
    
    Args:
        html_content: HTML内容
        
    Returns:
        清理后的纯文本
    """
    try:
        from bs4 import BeautifulSoup
        import html2text
        
        # 使用BeautifulSoup清理HTML
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # 移除script和style标签
        for script in soup(["script", "style"]):
            script.decompose()
        
        # 使用html2text转换为markdown/纯文本
        h = html2text.HTML2Text()
        h.ignore_links = False
        h.ignore_images = True
        h.ignore_emphasis = False
        
        text = h.handle(str(soup))
        return text.strip()
    except Exception:
        # 如果处理失败，返回原始内容（去掉标签）
        import re
        clean = re.compile('<.*?>')
        return re.sub(clean, '', html_content).strip()


def truncate_text(text: str, max_length: int = 5000) -> str:
    """
    截断文本到指定长度
    
    Args:
        text: 原始文本
        max_length: 最大长度
        
    Returns:
        截断后的文本
    """
    if len(text) <= max_length:
        return text
    return text[:max_length] + "..."


def format_datetime(dt: datetime) -> str:
    """
    格式化日期时间
    
    Args:
        dt: datetime对象
        
    Returns:
        格式化的字符串
    """
    return dt.strftime("%Y-%m-%d %H:%M:%S")
