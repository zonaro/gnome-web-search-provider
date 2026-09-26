#!/usr/bin/env python3
"""Tests for trilingual support (pt_BR / es / en) with en fallback."""

import os
import sys
import unittest
from unittest.mock import patch

SRC = os.path.join(os.path.dirname(__file__), "..", "src")
sys.path.insert(0, os.path.abspath(SRC))

from gnome_web_search_provider import RESULT_SEPARATOR, WebSearchProvider  # noqa: E402
from gnome_web_search_provider.i18n import (  # noqa: E402
    SUPPORTED_LANGUAGES,
    get_language,
    tr,
)
from test_web_search_provider import FakeConfig  # noqa: E402


class TestGetLanguage(unittest.TestCase):
    def test_supported_set(self):
        self.assertEqual(tuple(SUPPORTED_LANGUAGES), ("en", "pt_BR", "es"))

    def test_explicit_override(self):
        self.assertEqual(get_language("pt_BR"), "pt_BR")
        self.assertEqual(get_language("pt"), "pt_BR")
        self.assertEqual(get_language("es"), "es")
        self.assertEqual(get_language("en"), "en")

    def test_unknown_override_falls_back_to_english(self):
        self.assertEqual(get_language("fr"), "en")
        self.assertEqual(get_language("de_DE.UTF-8"), "en")
        self.assertEqual(get_language(""), "en")

    def test_lang_env_detection(self):
        with patch.dict(os.environ, {"GWSP_LANG": "", "LANGUAGE": "", "LC_ALL": "", "LANG": "pt_BR.UTF-8"}):
            self.assertEqual(get_language(), "pt_BR")
        with patch.dict(os.environ, {"GWSP_LANG": "", "LANGUAGE": "", "LC_ALL": "", "LANG": "es_ES.UTF-8"}):
            self.assertEqual(get_language(), "es")
        with patch.dict(os.environ, {"GWSP_LANG": "", "LANGUAGE": "", "LC_ALL": "", "LANG": "fr_FR.UTF-8"}):
            self.assertEqual(get_language(), "en")

    def test_gwsp_lang_wins_over_lang(self):
        env = {"GWSP_LANG": "es", "LANGUAGE": "", "LC_ALL": "", "LANG": "pt_BR.UTF-8"}
        with patch.dict(os.environ, env):
            self.assertEqual(get_language(), "es")


class TestTr(unittest.TestCase):
    def test_english_templates(self):
        self.assertEqual(
            tr("search_for", lang="en", provider="Bing", query="x"),
            "Search Bing for 'x'",
        )
        self.assertEqual(tr("press_enter", lang="en"), "Press Enter to open in browser")

    def test_portuguese_differs_from_english(self):
        pt = tr("search_for", lang="pt_BR", provider="Bing", query="x")
        self.assertNotEqual(pt, tr("search_for", lang="en", provider="Bing", query="x"))
        self.assertIn("Pesquisar", pt)

    def test_spanish_differs_from_english(self):
        es = tr("search_for", lang="es", provider="Bing", query="x")
        self.assertNotEqual(es, tr("search_for", lang="en", provider="Bing", query="x"))
        self.assertIn("Buscar", es)

    def test_unknown_lang_falls_back_to_english(self):
        self.assertEqual(
            tr("search_for", lang="fr", provider="Google", query="x"),
            tr("search_for", lang="en", provider="Google", query="x"),
        )

    def test_unknown_key_returns_key(self):
        self.assertEqual(tr("no-such-key", lang="en"), "no-such-key")


class TestTranslatedMetas(unittest.TestCase):
    def _name_for(self, lang):
        with patch.dict(os.environ, {"GWSP_LANG": lang, "LANGUAGE": "", "LC_ALL": "", "LANG": lang}):
            provider = WebSearchProvider(config=FakeConfig(["google"]))
            metas = provider.GetResultMetas([f"google{RESULT_SEPARATOR}linux"])
        return metas[0]["name"].unpack()

    def test_metas_portuguese(self):
        self.assertIn("Pesquisar", self._name_for("pt_BR"))

    def test_metas_spanish(self):
        self.assertIn("Buscar", self._name_for("es"))

    def test_metas_english_default(self):
        with patch.dict(os.environ, {"GWSP_LANG": "", "LANGUAGE": "", "LC_ALL": "", "LANG": "C"}):
            provider = WebSearchProvider(config=FakeConfig(["bing"]))
            metas = provider.GetResultMetas([f"bing{RESULT_SEPARATOR}test query"])
        self.assertEqual(metas[0]["name"].unpack(), "Search Bing for 'test query'")
        self.assertEqual(
            metas[0]["description"].unpack(), "Press Enter to open in browser"
        )


if __name__ == "__main__":
    unittest.main()
