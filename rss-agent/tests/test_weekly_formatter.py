import tempfile
import unittest
from pathlib import Path

from src.formatters.weekly_formatter import WeeklyFormatter, WeeklyItem


class WeeklyFormatterTests(unittest.TestCase):
    def test_format_weekly_keeps_all_core_sections(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "weekly.md"
            formatter = WeeklyFormatter(str(output_path))

            categories = {
                "AI资讯": [
                    WeeklyItem(
                        title="测试标题",
                        url="https://example.com/item",
                        summary="测试摘要",
                        category="AI资讯",
                    )
                ]
            }

            content = formatter.format_weekly(1, "20260211", categories)

            self.assertIn("# 时事", content)
            self.assertIn("# AI资讯", content)
            self.assertIn("# 教程", content)
            self.assertIn("# 训练", content)
            self.assertIn("# 工具", content)
            self.assertIn("_本期暂无更新。_", content)
            self.assertNotIn("来源页:", content)


if __name__ == "__main__":
    unittest.main()
