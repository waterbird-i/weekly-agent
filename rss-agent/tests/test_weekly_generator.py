import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import yaml

from src.core.rss_fetcher import Article
from src.generators.weekly_generator import WeeklyGenerator


class WeeklyGeneratorTests(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp_dir.name)
        self.config_path = self.root / "weekly_config.yaml"
        self.state_path = self.root / "cache" / "weekly_state.json"
        self.dedup_path = self.root / "cache" / "weekly_processed_urls.json"

        self.config = {
            "ai": {
                "api_base": "https://example.com/v1",
                "api_key": "",
                "api_key_env": "AI_API_KEY",
                "model": "test-model",
                "max_tokens": 1024,
            },
            "categories": {
                "news": {
                    "name": "时事",
                    "feeds": [],
                    "min_count": 0,
                    "max_count": 5,
                }
            },
            "dedup": {
                "cache_file": str(self.dedup_path),
                "cache_expire_hours": 720,
            },
            "weekly": {
                "current_issue": 10,
                "date_format": "%Y%m%d",
                "output_template": "output/NO{issue}.md",
                "title_template": "NO{issue}",
            },
            "state": {
                "issue_file": str(self.state_path),
            },
            "time_filter": {
                "hours": 168
            }
        }
        self.root.mkdir(parents=True, exist_ok=True)
        self.config_path.write_text(
            yaml.safe_dump(self.config, allow_unicode=True),
            encoding="utf-8"
        )

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_issue_state_file_does_not_modify_config(self):
        generator = WeeklyGenerator(str(self.config_path))
        self.assertEqual(generator.get_current_issue(), 10)

        generator._set_next_issue(10)
        self.assertTrue(self.state_path.exists())

        new_generator = WeeklyGenerator(str(self.config_path))
        self.assertEqual(new_generator.get_current_issue(), 11)

        config_after = yaml.safe_load(self.config_path.read_text(encoding="utf-8"))
        self.assertEqual(config_after["weekly"]["current_issue"], 10)

    def test_extract_candidate_links_prefers_title_match(self):
        generator = WeeklyGenerator(str(self.config_path))
        article = Article(
            title="2026-02-11日刊",
            url="https://daily.example.com/2026-02-11",
            content=(
                "[SeedFold超越AlphaFold3](https://news.example.com/seedfold)\n"
                "[OpenAI发布Gumdrop](https://news.example.com/gumdrop)"
            ),
            summary="",
            published=datetime.now(timezone.utc),
            source="daily"
        )

        candidates = generator._extract_candidate_links(article)
        used = set()
        selected = generator._select_item_link(
            "SeedFold超越AlphaFold3",
            candidates,
            used,
            article.url
        )
        self.assertEqual(selected, "https://news.example.com/seedfold")

    def test_select_item_link_uses_link_id_when_available(self):
        generator = WeeklyGenerator(str(self.config_path))
        candidates = [
            ("SeedFold超越AlphaFold3", "https://news.example.com/seedfold"),
            ("OpenAI发布Gumdrop", "https://news.example.com/gumdrop"),
        ]
        used = set()
        selected = generator._select_item_link(
            "任意标题",
            candidates,
            used,
            "https://fallback.example.com",
            preferred_link_id="L2",
            link_id_map={"L1": "https://news.example.com/seedfold", "L2": "https://news.example.com/gumdrop"},
        )
        self.assertEqual(selected, "https://news.example.com/gumdrop")

    def test_build_dedup_key_keeps_items_from_same_source(self):
        generator = WeeklyGenerator(str(self.config_path))
        source_url = "https://daily.example.com/2026-02-11"

        key1 = generator._build_dedup_key(source_url, source_url, "SeedFold超越AlphaFold3")
        key2 = generator._build_dedup_key(source_url, source_url, "OpenAI发布Gumdrop")

        self.assertNotEqual(key1, key2)
        self.assertTrue(key1.startswith(source_url))
        self.assertTrue(key2.startswith(source_url))

    def test_noise_link_filters_hubtoday_home(self):
        generator = WeeklyGenerator(str(self.config_path))
        self.assertTrue(
            generator._is_noise_source_link(
                "前往官网查看完整版 (ai.hubtoday.app)",
                "https://ai.hubtoday.app/"
            )
        )

    def test_editor_summary_adds_emoji(self):
        generator = WeeklyGenerator(str(self.config_path))
        summary = generator._format_editor_summary("这是一个没有表情的摘要，强调发布和性能改进。")
        self.assertNotEqual(summary, "暂无描述")
        self.assertIn("🔍", summary)

    def test_effective_min_count_enforces_news_and_ai_floor(self):
        generator = WeeklyGenerator(str(self.config_path))
        self.assertEqual(generator._get_effective_min_count("时事", 1), 5)
        self.assertEqual(generator._get_effective_min_count("AI资讯", 3), 5)
        self.assertEqual(generator._get_effective_min_count("教程", 2), 2)


if __name__ == "__main__":
    unittest.main()
