import unittest
from datetime import datetime, timezone

from src.core.content_filter import ContentFilter
from src.core.rss_fetcher import Article


class DummyDeduplicator:
    def __init__(self, duplicated_urls):
        self.duplicated_urls = set(duplicated_urls)

    def is_duplicate(self, url):
        return url in self.duplicated_urls


class ContentFilterTests(unittest.TestCase):
    def make_article(self, title, url, content):
        return Article(
            title=title,
            url=url,
            content=content,
            summary="summary",
            published=datetime.now(timezone.utc),
            source="test"
        )

    def test_apply_all_filters_includes_keyword_and_dedup(self):
        config = {
            "time_filter": {"hours": 0},
            "pre_filter": {
                "include_keywords": ["AI"],
                "exclude_keywords": [],
                "min_content_length": 1
            }
        }
        deduplicator = DummyDeduplicator({"https://example.com/dup"})
        content_filter = ContentFilter(config, deduplicator)

        articles = [
            self.make_article("AI News", "https://example.com/ok", "This is AI news"),
            self.make_article("Other News", "https://example.com/other", "No keyword"),
            self.make_article("AI Dup", "https://example.com/dup", "AI duplicated"),
        ]

        filtered = content_filter.apply_all_filters(articles)

        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0].url, "https://example.com/ok")


if __name__ == "__main__":
    unittest.main()
