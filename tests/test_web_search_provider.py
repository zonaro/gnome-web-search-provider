#!/usr/bin/env python3
"""Tests for the multi-provider GNOME web search provider."""

import os
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

# Make the package importable from the source tree.
SRC = os.path.join(os.path.dirname(__file__), "..", "src")
sys.path.insert(0, os.path.abspath(SRC))

from gnome_web_search_provider import (  # noqa: E402
    BUS_NAME,
    OBJECT_PATH,
    RESULT_SEPARATOR,
    WebSearchProvider,
)
from gnome_web_search_provider.config import (  # noqa: E402
    DEFAULT_ENABLED_PROVIDERS,
    ConfigManager,
)
from gnome_web_search_provider.providers import PROVIDERS  # noqa: E402


class FakeConfig:
    """In-memory ConfigManager stand-in for provider tests."""

    def __init__(self, enabled=None):
        self._enabled = list(enabled) if enabled is not None else list(DEFAULT_ENABLED_PROVIDERS)

    def get_enabled_providers(self):
        return list(self._enabled)

    def set_enabled_providers(self, providers):
        self._enabled = list(providers)

    def toggle_provider(self, provider_id, enabled):
        if enabled and provider_id not in self._enabled:
            self._enabled.append(provider_id)
        elif not enabled and provider_id in self._enabled:
            self._enabled.remove(provider_id)


class TestWebSearchProvider(unittest.TestCase):
    def setUp(self):
        self.provider = WebSearchProvider(config=FakeConfig(["google"]))

    # ------------------------------------------------------------ basics

    def test_bus_name(self):
        self.assertEqual(BUS_NAME, "org.gnome.WebSearch.SearchProvider")

    def test_object_path(self):
        self.assertEqual(OBJECT_PATH, "/org/gnome/WebSearch/SearchProvider")

    def test_default_provider_list_includes_google(self):
        self.assertIn("google", PROVIDERS)

    # ------------------------------------------------------- result sets

    def test_initial_result_set_default_google(self):
        result = self.provider.GetInitialResultSet(["hello", "world"])
        self.assertEqual(result, [f"google{RESULT_SEPARATOR}hello world"])

    def test_initial_result_set_empty_terms(self):
        result = self.provider.GetInitialResultSet([])
        self.assertEqual(result, [f"google{RESULT_SEPARATOR}"])

    def test_subsearch_result_set(self):
        result = self.provider.GetSubsearchResultSet(["previous"], ["new"])
        self.assertEqual(result, [f"google{RESULT_SEPARATOR}new"])

    def test_multiple_enabled_providers(self):
        provider = WebSearchProvider(config=FakeConfig(["google", "bing", "duckduckgo"]))
        result = provider.GetInitialResultSet(["linux"])
        self.assertEqual(
            result,
            [
                f"google{RESULT_SEPARATOR}linux",
                f"bing{RESULT_SEPARATOR}linux",
                f"duckduckgo{RESULT_SEPARATOR}linux",
            ],
        )

    def test_empty_enabled_list_yields_no_results(self):
        provider = WebSearchProvider(config=FakeConfig([]))
        self.assertEqual(provider.GetInitialResultSet(["term"]), [])

    def test_unknown_provider_ids_are_filtered(self):
        provider = WebSearchProvider(config=FakeConfig(["google", "not-a-provider"]))
        result = provider.GetInitialResultSet(["term"])
        self.assertEqual(result, [f"google{RESULT_SEPARATOR}term"])

    # ------------------------------------------------------------ metas

    def test_get_result_metas_structure(self):
        result = self.provider.GetResultMetas([f"google{RESULT_SEPARATOR}test query"])
        self.assertEqual(len(result), 1)
        meta = result[0]
        self.assertIn("id", meta)
        self.assertIn("name", meta)
        self.assertIn("description", meta)
        self.assertIn("icon", meta)

    def test_get_result_metas_values(self):
        result = self.provider.GetResultMetas([f"bing{RESULT_SEPARATOR}test query"])
        meta = result[0]
        self.assertEqual(meta["id"].unpack(), f"bing{RESULT_SEPARATOR}test query")
        self.assertEqual(meta["name"].unpack(), "Search Bing for 'test query'")
        self.assertEqual(meta["description"].unpack(), "Press Enter to open in browser")
        self.assertEqual(meta["icon"].unpack(), "web-browser")

    def test_get_result_metas_skips_unknown_provider(self):
        result = self.provider.GetResultMetas(["nope-term"])
        self.assertEqual(result, [])

    def test_get_result_metas_multiple(self):
        result = self.provider.GetResultMetas(
            [f"google{RESULT_SEPARATOR}q1", f"google{RESULT_SEPARATOR}q2"]
        )
        self.assertEqual(len(result), 2)

    # ---------------------------------------------------------- activation

    @patch("gnome_web_search_provider.subprocess.Popen")
    def test_activate_result_google(self, mock_popen):
        self.provider.ActivateResult(f"google{RESULT_SEPARATOR}test query", ["test", "query"], 0)
        mock_popen.assert_called_once()
        call_args = mock_popen.call_args[0][0]
        self.assertEqual(call_args[0], "xdg-open")
        self.assertEqual(call_args[1], "https://www.google.com/search?q=test+query")

    @patch("gnome_web_search_provider.subprocess.Popen")
    def test_activate_result_bing(self, mock_popen):
        self.provider.ActivateResult(f"bing{RESULT_SEPARATOR}linux", ["linux"], 0)
        call_args = mock_popen.call_args[0][0]
        self.assertEqual(call_args[1], "https://www.bing.com/search?q=linux")

    @patch("gnome_web_search_provider.subprocess.Popen")
    def test_activate_result_encodes_special_chars(self, mock_popen):
        self.provider.ActivateResult(
            f"google{RESULT_SEPARATOR}<script> & \"x\"", ["<script> & \"x\""], 0
        )
        call_args = mock_popen.call_args[0][0]
        self.assertEqual(call_args[1], "https://www.google.com/search?q=%3Cscript%3E+%26+%22x%22")

    @patch("gnome_web_search_provider.subprocess.Popen")
    def test_activate_result_maps_uses_path_encoding(self, mock_popen):
        self.provider.ActivateResult(
            f"google-maps{RESULT_SEPARATOR}torre eiffel", ["torre", "eiffel"], 0
        )
        call_args = mock_popen.call_args[0][0]
        self.assertEqual(call_args[1], "https://www.google.com/maps/search/torre%20eiffel")

    @patch("gnome_web_search_provider.subprocess.Popen")
    def test_activate_result_spotify_uses_path_encoding(self, mock_popen):
        self.provider.ActivateResult(f"spotify{RESULT_SEPARATOR}daft punk", ["daft", "punk"], 0)
        call_args = mock_popen.call_args[0][0]
        self.assertEqual(call_args[1], "https://open.spotify.com/search/daft%20punk")

    @patch("gnome_web_search_provider.subprocess.Popen")
    def test_activate_unknown_provider_does_not_open(self, mock_popen):
        self.provider.ActivateResult("legacy-id-without-separator", ["term"], 0)
        mock_popen.assert_not_called()

    def test_launch_search_does_nothing(self):
        self.provider.LaunchSearch(["test"], 0)

    # -------------------------------------------------------- dbus xml

    def test_dbus_xml_interface(self):
        xml = self.provider.__dbus_xml__
        self.assertIn("org.gnome.Shell.SearchProvider2", xml)
        self.assertIn("GetInitialResultSet", xml)
        self.assertIn("GetSubsearchResultSet", xml)
        self.assertIn("GetResultMetas", xml)
        self.assertIn("ActivateResult", xml)
        self.assertIn("LaunchSearch", xml)


class TestProviderUrls(unittest.TestCase):
    """Every configured provider must build a URL with its id."""

    def test_all_providers_build_urls(self):
        for provider in PROVIDERS.values():
            url = provider.build_url("hello world & more")
            self.assertTrue(url.startswith("https://"), provider.provider_id)
            self.assertNotIn("{query}", url, provider.provider_id)
            self.assertNotIn(" ", url, provider.provider_id)

    def test_all_providers_have_valid_categories(self):
        from gnome_web_search_provider.providers import CATEGORIES

        category_ids = {cid for cid, _ in CATEGORIES}
        for provider in PROVIDERS.values():
            self.assertIn(provider.category, category_ids, provider.provider_id)


class TestConfigManager(unittest.TestCase):
    """JSON file backend, isolated under a temporary XDG_CONFIG_HOME."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="gwsp-test-")
        self._old_xdg = os.environ.get("XDG_CONFIG_HOME")
        os.environ["XDG_CONFIG_HOME"] = self._tmp

    def tearDown(self):
        if self._old_xdg is None:
            os.environ.pop("XDG_CONFIG_HOME", None)
        else:
            os.environ["XDG_CONFIG_HOME"] = self._old_xdg
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_default_is_google(self):
        config = ConfigManager(use_gsettings=False)
        self.assertEqual(config.get_enabled_providers(), ["google"])
        self.assertEqual(config.backend, "file")

    def test_set_and_persist(self):
        config = ConfigManager(use_gsettings=False)
        config.set_enabled_providers(["google", "bing"])
        # A brand new instance reads the same file.
        again = ConfigManager(use_gsettings=False)
        self.assertEqual(again.get_enabled_providers(), ["google", "bing"])

    def test_set_dedupes_and_strips(self):
        config = ConfigManager(use_gsettings=False)
        config.set_enabled_providers(["  google ", "google", "", "bing", "bing"])
        self.assertEqual(config.get_enabled_providers(), ["google", "bing"])

    def test_toggle(self):
        config = ConfigManager(use_gsettings=False)
        config.toggle_provider("duckduckgo", True)
        self.assertEqual(config.get_enabled_providers(), ["google", "duckduckgo"])
        config.toggle_provider("google", False)
        self.assertEqual(config.get_enabled_providers(), ["duckduckgo"])

    def test_is_provider_enabled(self):
        config = ConfigManager(use_gsettings=False)
        self.assertTrue(config.is_provider_enabled("google"))
        self.assertFalse(config.is_provider_enabled("bing"))

    def test_corrupt_file_falls_back_to_default(self):
        config_dir = os.path.join(self._tmp, "gnome-web-search-provider")
        os.makedirs(config_dir, exist_ok=True)
        with open(os.path.join(config_dir, "config.json"), "w", encoding="utf-8") as fh:
            fh.write("{not valid json")
        config = ConfigManager(use_gsettings=False)
        self.assertEqual(config.get_enabled_providers(), ["google"])


if __name__ == "__main__":
    unittest.main()