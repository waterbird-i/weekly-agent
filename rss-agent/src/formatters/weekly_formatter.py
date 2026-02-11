"""
Weekly 格式化模块
将分析结果输出为前端 Weekly 格式的 Markdown
"""

from datetime import datetime
from typing import List, Dict, Any
from pathlib import Path
import logging

logger = logging.getLogger(__name__)


class WeeklyItem:
    """Weekly 条目"""
    
    def __init__(
        self,
        title: str,
        url: str,
        summary: str,
        is_english: bool = False,
        category: str = "",
        short_title: str = "",  # AI 生成的简短中文标题
        image_url: str = "",    # 文章配图 URL
        item_url: str = "",     # 条目级链接（优先使用）
        source_url: str = ""    # 来源文章链接
    ):
        self.title = title
        self.item_url = item_url or url
        self.source_url = source_url or url
        self.url = self.item_url  # 向后兼容
        self.summary = summary
        self.is_english = is_english
        self.category = category
        self.short_title = short_title or title  # 如果没有短标题，使用原标题
        self.image_url = image_url
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "url": self.url,
            "item_url": self.item_url,
            "source_url": self.source_url,
            "summary": self.summary,
            "is_english": self.is_english,
            "category": self.category,
            "short_title": self.short_title,
            "image_url": self.image_url
        }


class WeeklyFormatter:
    """Weekly Markdown 格式化器"""
    
    def __init__(self, output_path: str):
        """
        初始化格式化器
        
        Args:
            output_path: 输出文件路径
        """
        self.output_path = output_path
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    
    def _format_item(self, item: WeeklyItem) -> str:
        """
        格式化单个条目
        
        Args:
            item: Weekly 条目
            
        Returns:
            Markdown 格式字符串
        """
        # 使用 AI 生成的短标题，如果是英文内容，标题前加【英文】
        title_prefix = "【英文】" if item.is_english else ""
        display_title = item.short_title or item.title
        link_url = item.item_url or item.source_url or item.url
        
        # 构建基本内容
        markdown = f"""#### [{title_prefix}{display_title}]({link_url})

{item.summary}

"""
        
        # 如果有图片，添加图片
        if item.image_url:
            markdown += f"![{display_title}]({item.image_url})\n\n"
        
        return markdown
    
    def _format_category(self, name: str, items: List[WeeklyItem]) -> str:
        """
        格式化单个分类
        
        Args:
            name: 分类名称
            items: 分类下的条目列表
            
        Returns:
            Markdown 格式字符串
        """
        markdown = f"# {name}\n\n"
        if not items:
            markdown += "_本期暂无更新。_\n\n"
            return markdown

        for item in items:
            markdown += self._format_item(item)
        
        return markdown
    
    def format_weekly(
        self,
        issue: int,
        date: str,
        categories: Dict[str, List[WeeklyItem]]
    ) -> str:
        """
        格式化完整的 Weekly
        
        Args:
            issue: 期号
            date: 日期字符串 (如 20260108)
            categories: 分类数据 {分类名: [条目列表]}
            
        Returns:
            完整的 Markdown 字符串
        """
        # 标题
        title = f"# NO{issue}.前端Weekly({date})\n\n"
        
        # 按顺序输出各分类
        category_order = ["时事", "AI资讯", "教程", "训练", "工具"]
        
        content = title
        for cat_name in category_order:
            content += self._format_category(cat_name, categories.get(cat_name, []))

        # 兼容额外自定义分类
        for cat_name, items in categories.items():
            if cat_name not in category_order:
                content += self._format_category(cat_name, items)
        
        return content
    
    def save_weekly(
        self,
        issue: int,
        date: str,
        categories: Dict[str, List[WeeklyItem]]
    ) -> str:
        """
        保存 Weekly 到文件
        
        Args:
            issue: 期号
            date: 日期字符串
            categories: 分类数据
            
        Returns:
            保存的文件路径
        """
        content = self.format_weekly(issue, date, categories)
        
        with open(self.output_path, 'w', encoding='utf-8') as f:
            f.write(content)
        
        logger.info(f"Weekly 已保存到: {self.output_path}")
        return self.output_path
    
    def print_weekly(
        self,
        issue: int,
        date: str,
        categories: Dict[str, List[WeeklyItem]]
    ):
        """
        打印 Weekly 到控制台
        
        Args:
            issue: 期号
            date: 日期字符串
            categories: 分类数据
        """
        content = self.format_weekly(issue, date, categories)
        print(content)
