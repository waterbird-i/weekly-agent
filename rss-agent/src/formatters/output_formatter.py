"""
输出格式化模块
将分析结果输出为Markdown格式
"""

from datetime import datetime
from typing import List
from pathlib import Path
import logging

from ..core.ai_processor import AnalysisResult
from ..utils import format_datetime

logger = logging.getLogger(__name__)


class OutputFormatter:
    """Markdown输出格式化器"""
    
    def __init__(self, output_path: str):
        """
        初始化输出格式化器
        
        Args:
            output_path: 输出文件路径
        """
        self.output_path = output_path
        # 确保输出目录存在
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    
    def _format_single_result(self, result: AnalysisResult, index: int) -> str:
        """
        格式化单个分析结果
        
        Args:
            result: 分析结果
            index: 序号
            
        Returns:
            Markdown格式的字符串
        """
        article = result.article
        
        # 发布时间格式化
        pub_time = format_datetime(article.published) if article.published else "未知"
        
        # AI相关性标记
        ai_badge = "🤖 **AI相关**" if result.is_ai_related else "📰 一般新闻"
        
        # 成功/失败状态
        status = "✅" if result.success else "❌ 分析失败"
        
        markdown = f"""
---

### {index}. {article.title}

{status} | {ai_badge} | 📅 {pub_time} | 📍 {article.source}

🔗 [原文链接]({article.url})

#### 📌 核心要点

1. {result.key_points[0]}
2. {result.key_points[1]}
3. {result.key_points[2]}

#### 🎯 AI行业相关性分析

- **判断**: {"是" if result.is_ai_related else "否"}
- **理由**: {result.ai_relevance_reason}

"""
        return markdown
    
    def format_report(self, results: List[AnalysisResult]) -> str:
        """
        格式化完整报告
        
        Args:
            results: 分析结果列表
            
        Returns:
            完整的Markdown报告
        """
        now = datetime.now()
        
        # 统计信息
        total = len(results)
        successful = sum(1 for r in results if r.success)
        ai_related = sum(1 for r in results if r.is_ai_related)
        
        # 报告头部
        header = f"""# 📰 RSS新闻分析报告

> 生成时间: {format_datetime(now)}

## 📊 统计概览

| 指标 | 数值 |
|------|------|
| 总文章数 | {total} |
| 分析成功 | {successful} |
| AI相关文章 | {ai_related} |
| 分析失败 | {total - successful} |

---

## 🤖 AI相关文章

"""
        
        # 先输出AI相关的文章
        ai_related_results = [r for r in results if r.is_ai_related and r.success]
        if ai_related_results:
            for i, result in enumerate(ai_related_results, 1):
                header += self._format_single_result(result, i)
        else:
            header += "\n*暂无AI相关文章*\n"
        
        # 再输出其他文章
        header += "\n---\n\n## 📰 其他新闻\n"
        
        other_results = [r for r in results if not r.is_ai_related and r.success]
        if other_results:
            for i, result in enumerate(other_results, 1):
                header += self._format_single_result(result, i)
        else:
            header += "\n*暂无其他新闻*\n"
        
        # 失败的文章
        failed_results = [r for r in results if not r.success]
        if failed_results:
            header += "\n---\n\n## ❌ 分析失败的文章\n"
            for i, result in enumerate(failed_results, 1):
                header += f"\n{i}. [{result.article.title}]({result.article.url})\n   - 错误: {result.error_message}\n"
        
        # 报告尾部
        footer = f"""

---

*此报告由 RSS Agent 自动生成*
*生成时间: {format_datetime(now)}*
"""
        
        return header + footer
    
    def save_report(self, results: List[AnalysisResult]) -> str:
        """
        保存报告到文件
        
        Args:
            results: 分析结果列表
            
        Returns:
            保存的文件路径
        """
        report = self.format_report(results)
        
        with open(self.output_path, 'w', encoding='utf-8') as f:
            f.write(report)
        
        logger.info(f"报告已保存到: {self.output_path}")
        return self.output_path
    
    def print_report(self, results: List[AnalysisResult]):
        """
        打印报告到控制台
        
        Args:
            results: 分析结果列表
        """
        report = self.format_report(results)
        print(report)
