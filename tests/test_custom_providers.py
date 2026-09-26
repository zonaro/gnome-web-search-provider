#!/usr/bin/env python3
"""Tests for user-defined (custom) search providers."""

import os
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

SRC = os.path.join(os.path.dirname(__file__), "..", "src")
sys.path.insert(0, os.path.abspath(SRC))

os.environ["GWSP_LANG"] = "en"

from gnome_web_search_provider import RESULT_SEPARATOR, WebSearchProvider  # noqa: E402
from gnome_web_search_provider import cli  # noqa: E402
from gnome_web_search_provider.config import ConfigManager  # noqa: E402
from gnome_web_search_provider.providers import (  # noqa: E402
    PROVIDERS,
    all_providers,
    custom_providers_from_list,
    detect_query_in_path,
    slugify_provider_id,
    validate_custom_provider,
)


class TestCustomHelpers(unittest.TestCase):
    def test_slugify(self):
        self.assertEqual(slugify_provider_id("Meu Fórum!"), "meu-fórum")
        self.assertEqual(slugify_provider_id("  a  b  "), "a-b")
        self.assertEqual(slugify_provider_id("!!!"), "site")

    def test_validate_ok(self):
        self.assertEqual(validate_custom_provider("Forum", "https://x.com/s?q={query}"), [])

    def test_validate_bad_name(self):
        self.assertIn("name", validate_custom_provider("", "https://x.com/?q={query}"))
        self.assertIn("name", validate_custom_provider("x" * 61, "https://x.com/?q={query}"))

    def test_validate_bad_url(self):
        self.assertIn("url", validate_custom_provider("Ok", "not a url"))
        self.assertIn("url", validate_custom_provider("Ok", "https://x.com/search?q=term"))

    def test_detect_query_in_path(self):
        self.assertTrue(detect_query_in_path("https://x.com/busca/{query}"))
        self.assertFalse(detect_query_in_path("https://x.com/?q={query}"))
        self.assertFalse(detect_query_in_path("https://x.com/?q={query}#{query}"))

    def test_merge_ignores_bad_and_builtin_collisions(self):
        merged = custom_providers_from_list(
            [
                {"id": "custom-ok", "name": "Ok", "url": "https://ok.com/?q={query}"},
                {"id": "google", "name": "Fake", "url": "https://evil.com/?q={query}"},
                {"id": "custom-bad", "name": "Bad", "url": "https://bad.com/nope"},
                "not-a-dict",
            ]
        )
        self.assertIn("custom-ok", merged)
        self.assertEqual(PROVIDERS["google"].url, "https://www.google.com/search?q={query}")
        self.assertNotIn("custom-bad", merged)

    def test_custom_build_url_encodings(self):
        merged = all_providers(
            [
                {"id": "custom-q", "name": "Q", "url": "https://q.com/?q={query}"},
                {"id": "custom-p", "name": "P", "url": "https://p.com/s/{query}", "query_in_path": True},
            ]
        )
        self.assertEqual(merged["custom-q"].build_url("a b"), "https://q.com/?q=a+b")
        self.assertEqual(merged["custom-p"].build_url("a b"), "https://p.com/s/a%20b")


class _TempXdgMixin:
    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="gwsp-custom-test-")
        self._old_xdg = os.environ.get("XDG_CONFIG_HOME")
        os.environ["XDG_CONFIG_HOME"] = self._tmp

    def tearDown(self):
        if self._old_xdg is None:
            os.environ.pop("XDG_CONFIG_HOME", None)
        else:
            os.environ["XDG_CONFIG_HOME"] = self._old_xdg
        shutil.rmtree(self._tmp, ignore_errors=True)


class TestCustomConfig(_TempXdgMixin, unittest.TestCase):
    def test_add_roundtrip_and_auto_enable(self):
        config = ConfigManager(use_gsettings=False)
        entry = config.add_custom_provider("Meu Forum", "https://forum.com/busca?q={query}")
        self.assertEqual(entry["id"], "custom-meu-forum")
        self.assertIn("custom-meu-forum", config.get_enabled_providers())
        again = ConfigManager(use_gsettings=False)
        self.assertEqual(len(again.get_custom_providers()), 1)

    def test_add_rejects_invalid(self):
        config = ConfigManager(use_gsettings=False)
        with self.assertRaises(ValueError):
            config.add_custom_provider("", "https://x.com/?q={query}")
        with self.assertRaises(ValueError):
            config.add_custom_provider("Ok", "https://x.com/no-placeholder")

    def test_add_rejects_missing_icon(self):
        config = ConfigManager(use_gsettings=False)
        with self.assertRaises(ValueError):
            config.add_custom_provider("Ok", "https://x.com/?q={query}", icon="/nope/missing.png")

    def test_add_with_icon_file(self):
        fd, path = tempfile.mkstemp(suffix=".png")
        os.close(fd)
        try:
            config = ConfigManager(use_gsettings=False)
            entry = config.add_custom_provider("Ok", "https://x.com/?q={query}", icon=path)
            self.assertEqual(entry["icon"], path)
        finally:
            os.remove(path)

    def test_slug_collision_gets_suffix(self):
        config = ConfigManager(use_gsettings=False)
        first = config.add_custom_provider("Forum", "https://a.com/?q={query}")
        second = config.add_custom_provider("Forum", "https://b.com/?q={query}")
        self.assertNotEqual(first["id"], second["id"])
        self.assertTrue(second["id"].startswith(first["id"]))

    def test_update_and_remove(self):
        config = ConfigManager(use_gsettings=False)
        entry = config.add_custom_provider("Forum", "https://a.com/?q={query}")
        updated = config.update_custom_provider(entry["id"], name="Forum Novo")
        self.assertEqual(updated["name"], "Forum Novo")
        with self.assertRaises(ValueError):
            config.update_custom_provider(entry["id"], url="https://a.com/sem-placeholder")
        self.assertTrue(config.remove_custom_provider(entry["id"]))
        self.assertNotIn(entry["id"], config.get_enabled_providers())
        self.assertFalse(config.remove_custom_provider(entry["id"]))
        with self.assertRaises(KeyError):
            config.update_custom_provider(entry["id"], name="x")


class FakeConfigWithCustoms:
    def __init__(self, enabled, customs):
        self._enabled = list(enabled)
        self._customs = list(customs)

    def get_enabled_providers(self):
        return list(self._enabled)

    def get_custom_providers(self):
        return list(self._customs)

    def get_browser(self):
        return "xdg-open"


class TestCustomDaemon(unittest.TestCase):
    def test_custom_search_flows_through_daemon(self):
        customs = [{"id": "custom-forum", "name": "Forum", "url": "https://forum.com/busca?q={query}"}]
        provider = WebSearchProvider(config=FakeConfigWithCustoms(["custom-forum"], customs))
        results = provider.GetInitialResultSet(["hello"])
        self.assertEqual(results, [f"custom-forum{RESULT_SEPARATOR}hello"])
        metas = provider.GetResultMetas(results)
        self.assertEqual(len(metas), 1)
        with patch("gnome_web_search_provider.subprocess.Popen") as mock_popen:
            provider.ActivateResult(f"custom-forum{RESULT_SEPARATOR}hello world", ["hello", "world"], 0)
            opened = mock_popen.call_args[0][0]
            self.assertEqual(opened[-1], "https://forum.com/busca?q=hello+world")

    def test_legacy_config_without_customs_still_works(self):
        from test_web_search_provider import FakeConfig

        provider = WebSearchProvider(config=FakeConfig(["google"]))
        self.assertEqual(provider.GetInitialResultSet(["hi"]), [f"google{RESULT_SEPARATOR}hi"])

    def test_result_icon_prefers_custom_icon_file(self):
        from gnome_web_search_provider import _result_icon
        from gnome_web_search_provider.providers import SearchProvider

        fd, path = tempfile.mkstemp(suffix=".png")
        os.close(fd)
        try:
            provider = SearchProvider(
                provider_id="custom-x",
                name="X",
                url="https://x.com/?q={query}",
                category="custom",
                icon_path=path,
            )
            self.assertEqual(_result_icon(provider), path)
        finally:
            os.remove(path)


class TestCustomCli(_TempXdgMixin, unittest.TestCase):
    def _run_cli(self, argv):
        from gnome_web_search_provider.config import ConfigManager as RealConfigManager

        class FileConfigManager(RealConfigManager):
            def __init__(self):
                super().__init__(use_gsettings=False)

        with patch.object(cli, "ConfigManager", FileConfigManager):
            return cli.main(argv)

    def test_cli_add_list_remove(self):
        self.assertEqual(self._run_cli(["custom", "add", "--name", "Forum", "--url", "https://f.com/?q={query}"]), 0)
        self.assertEqual(self._run_cli(["custom", "list"]), 0)
        self.assertEqual(self._run_cli(["custom", "remove", "custom-forum"]), 0)
        self.assertEqual(self._run_cli(["custom", "remove", "custom-missing"]), 1)

    def test_cli_add_rejects_bad_url(self):
        self.assertEqual(self._run_cli(["custom", "add", "--name", "X", "--url", "https://x.com/nope"]), 1)


if __name__ == "__main__":
    unittest.main()
