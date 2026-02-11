import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class MainDryRunIntegrationTests(unittest.TestCase):
    def test_main_dry_run_with_local_feed(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            feed_path = tmp_path / "feed.xml"
            config_path = tmp_path / "config.yaml"
            output_path = tmp_path / "output.md"
            cache_path = tmp_path / "processed_urls.json"

            pub_date = format_datetime(datetime.now(timezone.utc))
            feed_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Test Feed</title>
    <link>https://example.com</link>
    <description>Test Description</description>
    <item>
      <title>AI News Today</title>
      <link>https://example.com/ai-news</link>
      <description><![CDATA[This article is about AI agents.]]></description>
      <pubDate>{pub_date}</pubDate>
    </item>
  </channel>
</rss>
"""
            feed_path.write_text(feed_xml, encoding="utf-8")

            config = {
                "rss_feeds": [
                    {"name": "LocalFeed", "url": str(feed_path)}
                ],
                "time_filter": {"hours": 24},
                "pre_filter": {
                    "include_keywords": ["AI"],
                    "exclude_keywords": [],
                    "min_content_length": 1,
                },
                "ai": {
                    "api_base": "https://example.com/v1",
                    "api_key_env": "AI_API_KEY",
                    "api_key": "",
                    "model": "test-model",
                    "max_tokens": 256,
                },
                "output": {
                    "file_path": str(output_path),
                    "max_articles": 5,
                },
                "dedup": {
                    "cache_file": str(cache_path),
                    "cache_expire_hours": 168,
                },
            }
            config_path.write_text(
                yaml.safe_dump(config, allow_unicode=True),
                encoding="utf-8"
            )

            result = subprocess.run(
                [sys.executable, "main.py", "--config", str(config_path), "--dry-run"],
                cwd=str(PROJECT_ROOT),
                capture_output=True,
                text=True
            )

            combined_output = f"{result.stdout}\n{result.stderr}"
            self.assertEqual(result.returncode, 0, msg=combined_output)
            self.assertIn("Dry-run模式", combined_output)
            self.assertIn("AI News Today", combined_output)


if __name__ == "__main__":
    unittest.main()
