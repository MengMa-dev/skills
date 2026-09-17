#!/usr/bin/env python3
"""Offline unit tests for discover_repos scoring and description helpers."""

from __future__ import annotations

import math
import unittest

import discover_repos as d


class ExcerptReadmeTests(unittest.TestCase):
    def test_strips_badges_and_keeps_prose(self) -> None:
        text = "\n".join(
            [
                "# Cool Agent",
                "[![CI](https://img.shields.io/badge/ci-ok)](https://example.com)",
                "![logo](logo.png)",
                "",
                "Cool Agent runs tools for LLM apps.",
                "Use it when you need MCP servers in production.",
            ]
        )
        excerpt = d.excerpt_readme(text)
        self.assertIn("Cool Agent", excerpt)
        self.assertIn("runs tools", excerpt)
        self.assertNotIn("shields.io", excerpt)
        self.assertNotIn("logo.png", excerpt)
        self.assertNotIn("<div", excerpt)

    def test_skips_html_blocks(self) -> None:
        text = "<div align=\"center\">badge soup</div>\n\nLangChain is a framework for LLM apps.\n"
        excerpt = d.excerpt_readme(text)
        self.assertIn("LangChain is a framework", excerpt)
        self.assertNotIn("<div", excerpt)


class ManifestParseTests(unittest.TestCase):
    def test_npm_skips_private(self) -> None:
        self.assertIsNone(d.parse_npm_name('{"name":"x","private":true}'))
        self.assertEqual(d.parse_npm_name('{"name":"@scope/pkg"}'), "@scope/pkg")

    def test_pyproject_prefers_project_table(self) -> None:
        text = "\n".join(
            [
                "[build-system]",
                'name = "should-ignore"',
                "[project]",
                'name = "real-pkg"',
                "[tool.poetry]",
                'name = "poetry-name"',
            ]
        )
        self.assertEqual(d.parse_python_package_name(text), "real-pkg")

    def test_js_repo_stem_guess(self) -> None:
        raw = {"nameWithOwner": "langchain-ai/langchainjs"}
        names = d.manifest_package_candidates(raw, "TypeScript")
        self.assertIn(("npm", "langchainjs"), names)
        self.assertIn(("npm", "langchain"), names)


class UsageScoreTests(unittest.TestCase):
    def test_log_cap_maps_to_100(self) -> None:
        self.assertAlmostEqual(d.score_usage(0), 0.0, places=4)
        self.assertAlmostEqual(d.score_usage(d.USAGE_LOG_CAP), 100.0, places=4)
        mid = d.score_usage(1_000)
        self.assertGreater(mid, 40)
        self.assertLess(mid, 60)

    def test_registry_downloads_outrank_stars(self) -> None:
        units, source = d.usage_units(downloads_30d=500_000, release_dl_12m=0, stars=2_000, forks=100)
        self.assertEqual(source, "registry-30d")
        self.assertEqual(units, 500_000)

    def test_falls_back_to_stars_forks(self) -> None:
        units, source = d.usage_units(downloads_30d=None, release_dl_12m=0, stars=1_000, forks=50)
        self.assertEqual(source, "stars+forks")
        self.assertEqual(units, 1_000 + 2 * 50)

    def test_release_downloads_can_win(self) -> None:
        units, source = d.usage_units(downloads_30d=10, release_dl_12m=120_000, stars=10, forks=0)
        self.assertEqual(source, "github-release-monthly")
        self.assertEqual(units, 10_000)

    def test_total_score_weights(self) -> None:
        score_pr, score_rel, score_use = 50.0, 80.0, 20.0
        total = d.WEIGHT_PR * score_pr + d.WEIGHT_RELEASE * score_rel + d.WEIGHT_USAGE * score_use
        self.assertAlmostEqual(total, 0.4 * 50 + 0.3 * 80 + 0.3 * 20)
        self.assertAlmostEqual(d.WEIGHT_PR + d.WEIGHT_RELEASE + d.WEIGHT_USAGE, 1.0)
        self.assertTrue(math.isclose(d.WEIGHT_USAGE, 0.3))


class TopicAndFormatTests(unittest.TestCase):
    def test_topic_names_merge_graphql_and_rest(self) -> None:
        raw = {
            "repositoryTopics": {"nodes": [{"topic": {"name": "mcp"}}, {"topic": {"name": "llm"}}]},
            "topics": ["mcp", "agents"],
        }
        self.assertEqual(d.topic_names(raw), ["mcp", "llm", "agents"])

    def test_format_count(self) -> None:
        self.assertEqual(d.format_count(None), "未取到")
        self.assertEqual(d.format_count(12345), "12,345")

    def test_invalid_pypi_name_skips_network(self) -> None:
        self.assertIsNone(d.pypi_downloads_clickhouse("foo;drop table"))
        self.assertIsNone(d.pypi_downloads_clickhouse(""))

    def test_render_includes_usage_and_description_source(self) -> None:
        md = d.render_markdown(
            [
                {
                    "full_name": "acme/agent",
                    "url": "https://github.com/acme/agent",
                    "description": "An agent runtime",
                    "topics": ["mcp"],
                    "readme_excerpt": "Run tools from an LLM.",
                    "stars": 2000,
                    "forks": 50,
                    "watchers": 10,
                    "language": "TypeScript",
                    "pushed_at": "2026-09-01",
                    "downloads_30d": 9000,
                    "download_source": "npm:agent",
                    "download_window": "近 30 天",
                    "release_downloads_12m": 120,
                    "usage_units": 9000,
                    "usage_source": "registry-30d",
                    "score_usage": 48.2,
                    "closed_issues": 10,
                    "open_issues": 2,
                    "issue_ratio_label": "5.00",
                    "median_merge_days": 1.5,
                    "score_pr": 40.0,
                    "releases_12m": 6,
                    "score_release": 50.0,
                    "score": 45.46,
                }
            ],
            1,
            filters_note="domain=agent",
            excluded_note="",
        )
        self.assertIn("使用分", md)
        self.assertIn("9,000", md)
        self.assertIn("做什么 / 解决的核心问题 / 适用场景", md)
        self.assertIn("README 摘要", md)
        self.assertIn("0.4 × PR", md)


if __name__ == "__main__":
    unittest.main()
