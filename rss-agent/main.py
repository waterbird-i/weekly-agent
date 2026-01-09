#!/usr/bin/env python3
"""
RSS Agent 主入口
用于RSS订阅抓取、过滤和AI分析
"""

import argparse
import logging
import sys
from pathlib import Path

import yaml

from src.core.rss_fetcher import RSSFetcher
from src.core.content_filter import ContentFilter
from src.core.ai_processor import AIProcessor
from src.formatters.output_formatter import OutputFormatter
from src.utils import URLDeduplicator

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def load_config(config_path: str) -> dict:
    """
    加载配置文件
    
    Args:
        config_path: 配置文件路径
        
    Returns:
        配置字典
    """
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
        logger.info(f"配置文件加载成功: {config_path}")
        return config
    except Exception as e:
        logger.error(f"加载配置文件失败: {e}")
        sys.exit(1)


def main():
    """主函数"""
    # 解析命令行参数
    parser = argparse.ArgumentParser(description='RSS Agent - RSS订阅抓取与AI分析')
    parser.add_argument(
        '-c', '--config',
        default='config/config.yaml',
        help='配置文件路径 (默认: config/config.yaml)'
    )
    parser.add_argument(
        '-o', '--output',
        default=None,
        help='输出文件路径 (覆盖配置文件中的设置)'
    )
    parser.add_argument(
        '-n', '--max-articles',
        type=int,
        default=None,
        help='最大处理文章数 (覆盖配置文件中的设置)'
    )
    parser.add_argument(
        '--hours',
        type=int,
        default=None,
        help='时间过滤范围(小时) (覆盖配置文件中的设置)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='仅抓取和过滤，不调用AI分析'
    )
    parser.add_argument(
        '--weekly',
        action='store_true',
        help='生成前端 Weekly 报告'
    )
    parser.add_argument(
        '--weekly-config',
        default='config/weekly_config.yaml',
        help='Weekly 配置文件路径 (默认: config/weekly_config.yaml)'
    )
    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='显示详细日志'
    )
    
    args = parser.parse_args()
    
    # 设置日志级别
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    # Weekly 模式
    if args.weekly:
        from src.generators.weekly_generator import WeeklyGenerator
        
        weekly_config_path = args.weekly_config
        if not Path(weekly_config_path).is_absolute():
            weekly_config_path = Path(__file__).parent / weekly_config_path
        
        generator = WeeklyGenerator(str(weekly_config_path))
        generator.generate(dry_run=args.dry_run)
        return
    
    # 确定配置文件路径
    config_path = args.config
    if not Path(config_path).is_absolute():
        config_path = Path(__file__).parent / config_path
    
    # 加载配置
    config = load_config(str(config_path))
    
    # 命令行参数覆盖配置文件
    if args.hours:
        config.setdefault('time_filter', {})['hours'] = args.hours
    
    if args.max_articles:
        config.setdefault('output', {})['max_articles'] = args.max_articles
    
    output_path = args.output or config.get('output', {}).get('file_path', 'output/rss_analysis.md')
    if not Path(output_path).is_absolute():
        output_path = Path(__file__).parent / output_path
    
    max_articles = config.get('output', {}).get('max_articles', 20)
    
    # 初始化去重器
    cache_file = config.get('dedup', {}).get('cache_file', 'cache/processed_urls.json')
    if not Path(cache_file).is_absolute():
        cache_file = Path(__file__).parent / cache_file
    
    cache_expire_hours = config.get('dedup', {}).get('cache_expire_hours', 168)
    deduplicator = URLDeduplicator(str(cache_file), cache_expire_hours)
    
    logger.info("=" * 50)
    logger.info("RSS Agent 启动")
    logger.info("=" * 50)
    
    # 1. 抓取RSS
    logger.info("\n📡 Step 1: 抓取RSS订阅...")
    feeds = config.get('rss_feeds', [])
    if not feeds:
        logger.error("配置文件中没有RSS订阅源")
        sys.exit(1)
    
    fetcher = RSSFetcher(feeds)
    articles = fetcher.fetch_all()
    
    if not articles:
        logger.warning("未获取到任何文章")
        sys.exit(0)
    
    # 2. 内容过滤
    logger.info("\n🔍 Step 2: 应用内容过滤...")
    content_filter = ContentFilter(config, deduplicator)
    filtered_articles = content_filter.apply_all_filters(articles)
    
    if not filtered_articles:
        logger.warning("过滤后没有剩余文章")
        sys.exit(0)
    
    logger.info(f"过滤后剩余 {len(filtered_articles)} 篇文章待处理")
    
    # 3. AI分析 (如果不是dry-run)
    if args.dry_run:
        logger.info("\n⏭️ Dry-run模式，跳过AI分析")
        logger.info("过滤后的文章列表:")
        for i, article in enumerate(filtered_articles[:max_articles], 1):
            logger.info(f"  {i}. {article.title}")
            logger.info(f"     URL: {article.url}")
        sys.exit(0)
    
    logger.info("\n🤖 Step 3: 调用AI进行分析...")
    ai_processor = AIProcessor(config)
    results = ai_processor.analyze_batch(filtered_articles, max_articles)
    
    # 4. 标记已处理的URL
    logger.info("\n📝 Step 4: 更新URL缓存...")
    processed_urls = [r.article.url for r in results]
    deduplicator.mark_batch_processed(processed_urls)
    
    # 5. 输出报告
    logger.info("\n📄 Step 5: 生成Markdown报告...")
    formatter = OutputFormatter(str(output_path))
    saved_path = formatter.save_report(results)
    
    # 打印报告到控制台
    formatter.print_report(results)
    
    logger.info("=" * 50)
    logger.info("✅ RSS Agent 执行完成")
    logger.info(f"📄 报告已保存到: {saved_path}")
    logger.info("=" * 50)


if __name__ == '__main__':
    main()
