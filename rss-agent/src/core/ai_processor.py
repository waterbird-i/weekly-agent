"""
AI处理模块
调用AI API分析文章内容
"""

from typing import List, Dict, Any, Optional
from dataclasses import dataclass
import logging
from openai import OpenAI

from .rss_fetcher import Article
from ..utils import truncate_text

logger = logging.getLogger(__name__)


@dataclass
class AnalysisResult:
    """AI分析结果"""
    article: Article
    key_points: List[str]  # 3条核心要点
    is_ai_related: bool    # 是否与AI行业高度相关
    ai_relevance_reason: str  # AI相关性判断理由
    raw_response: str      # 原始AI响应
    success: bool = True
    error_message: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "article": self.article.to_dict(),
            "key_points": self.key_points,
            "is_ai_related": self.is_ai_related,
            "ai_relevance_reason": self.ai_relevance_reason,
            "raw_response": self.raw_response,
            "success": self.success,
            "error_message": self.error_message
        }


class AIProcessor:
    """AI处理器，调用AI API分析文章"""
    
    # 系统提示词
    SYSTEM_PROMPT = """你是一个 AI 时事分析助手。

请根据以下新闻内容，完成以下任务：
1. 提炼 3 条核心要点
2. 判断是否与 AI 行业高度相关
3. 用中文输出

请严格按照以下格式输出：

## 核心要点
1. [要点1]
2. [要点2]
3. [要点3]

## AI行业相关性
- 判断：[是/否]
- 理由：[简要说明为什么相关或不相关]"""
    
    def __init__(self, config: Dict[str, Any]):
        """
        初始化AI处理器
        
        Args:
            config: AI配置字典
        """
        ai_config = config.get('ai', {})
        
        self.api_base = ai_config.get('api_base', 'https://200.xstx.info/v1')
        self.model = ai_config.get('model', 'claude-opus-4-5-20251101-thinking')
        self.api_key = ai_config.get('api_key', '')
        self.max_tokens = ai_config.get('max_tokens', 4096)
        self.temperature = ai_config.get('temperature', 0.7)
        
        # 初始化OpenAI客户端（兼容API）
        self.client = OpenAI(
            api_key=self.api_key,
            base_url=self.api_base
        )
    
    def _build_user_prompt(self, article: Article) -> str:
        """
        构建用户提示词
        
        Args:
            article: 文章对象
            
        Returns:
            用户提示词
        """
        content = article.content or article.summary
        content = truncate_text(content, 4000)  # 限制内容长度
        
        return f"""新闻内容：

标题：{article.title}
来源：{article.source}
发布时间：{article.published.isoformat() if article.published else '未知'}

正文：
{content}"""
    
    def _parse_response(self, response_text: str) -> Dict[str, Any]:
        """
        解析AI响应
        
        Args:
            response_text: AI响应文本
            
        Returns:
            解析后的结构化数据
        """
        result = {
            "key_points": [],
            "is_ai_related": False,
            "ai_relevance_reason": ""
        }
        
        lines = response_text.strip().split('\n')
        current_section = None
        
        for line in lines:
            line = line.strip()
            
            if '核心要点' in line:
                current_section = 'key_points'
                continue
            elif 'AI行业相关性' in line or 'AI 行业相关性' in line:
                current_section = 'ai_related'
                continue
            
            if current_section == 'key_points':
                # 解析要点
                if line.startswith(('1.', '2.', '3.', '- ', '* ')):
                    point = line.lstrip('0123456789.-* ').strip()
                    if point:
                        result["key_points"].append(point)
            
            elif current_section == 'ai_related':
                # 解析AI相关性判断
                if '判断' in line:
                    result["is_ai_related"] = '是' in line and '否' not in line.split('是')[0]
                elif '理由' in line:
                    reason = line.split('理由')[-1].strip().lstrip('：:').strip()
                    result["ai_relevance_reason"] = reason
        
        # 确保有3个要点
        while len(result["key_points"]) < 3:
            result["key_points"].append("（无更多要点）")
        result["key_points"] = result["key_points"][:3]  # 只保留前3个
        
        return result
    
    def analyze_article(self, article: Article) -> AnalysisResult:
        """
        分析单篇文章
        
        Args:
            article: 文章对象
            
        Returns:
            分析结果
        """
        try:
            logger.info(f"正在分析文章: {article.title[:50]}...")
            
            user_prompt = self._build_user_prompt(article)
            
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": self.SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt}
                ],
                max_tokens=self.max_tokens,
                temperature=self.temperature
            )
            
            response_text = response.choices[0].message.content
            parsed = self._parse_response(response_text)
            
            return AnalysisResult(
                article=article,
                key_points=parsed["key_points"],
                is_ai_related=parsed["is_ai_related"],
                ai_relevance_reason=parsed["ai_relevance_reason"],
                raw_response=response_text,
                success=True
            )
            
        except Exception as e:
            logger.error(f"分析文章失败: {article.title}, 错误: {e}")
            return AnalysisResult(
                article=article,
                key_points=["分析失败", "分析失败", "分析失败"],
                is_ai_related=False,
                ai_relevance_reason="分析过程中发生错误",
                raw_response="",
                success=False,
                error_message=str(e)
            )
    
    def analyze_batch(self, articles: List[Article], max_articles: int = 20) -> List[AnalysisResult]:
        """
        批量分析文章
        
        Args:
            articles: 文章列表
            max_articles: 最大处理数量
            
        Returns:
            分析结果列表
        """
        # 限制处理数量
        articles_to_process = articles[:max_articles]
        
        logger.info(f"开始批量分析 {len(articles_to_process)} 篇文章")
        
        results = []
        for i, article in enumerate(articles_to_process, 1):
            logger.info(f"处理进度: {i}/{len(articles_to_process)}")
            result = self.analyze_article(article)
            results.append(result)
        
        successful = sum(1 for r in results if r.success)
        logger.info(f"分析完成: 成功 {successful}/{len(results)}")
        
        return results
