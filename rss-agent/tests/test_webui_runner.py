import unittest

from src.webui.runner import interpret_progress_line, parse_log_line


class WebUiRunnerTests(unittest.TestCase):
    def test_parse_log_line_with_python_logging_format(self):
        line = "2026-02-11 18:00:00,123 - src.core.rss_fetcher - INFO - 共获取 10 篇文章"
        parsed = parse_log_line(line)

        self.assertEqual(parsed["level"], "INFO")
        self.assertEqual(parsed["module"], "src.core.rss_fetcher")
        self.assertEqual(parsed["message"], "共获取 10 篇文章")

    def test_interpret_standard_steps(self):
        update = interpret_progress_line("standard", "📡 Step 2: 应用内容过滤...", 20)
        self.assertEqual(update.step, "内容过滤")
        self.assertEqual(update.progress, 40)

    def test_interpret_weekly_stats_and_output(self):
        update = interpret_progress_line("weekly", "分类 AI资讯 最终: 6 条", 45)
        self.assertEqual(update.step, "分类整理")
        self.assertEqual(update.progress, 70)
        self.assertEqual(update.stats["categories"]["AI资讯"], 6)

        output = interpret_progress_line(
            "weekly",
            "📄 文件已保存到: /tmp/output/NO1.前端Weekly(20260211).md",
            70,
        )
        self.assertEqual(output.output_path, "/tmp/output/NO1.前端Weekly(20260211).md")


if __name__ == "__main__":
    unittest.main()
