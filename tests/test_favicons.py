#!/usr/bin/env python3
"""Tests for the favicon fetching + cache module (no network used)."""

import io
import os
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

SRC = os.path.join(os.path.dirname(__file__), "..", "src")
sys.path.insert(0, os.path.abspath(SRC))

from gnome_web_search_provider import favicons  # noqa: E402
from gnome_web_search_provider.providers import PROVIDERS  # noqa: E402


class _FakeHeaders:
    def __init__(self, content_type):
        self._content_type = content_type

    def get_content_type(self):
        return self._content_type


class _FakeResponse:
    def __init__(self, body, content_type="image/png", status=200):
        self._body = body
        self.headers = _FakeHeaders(content_type)
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, limit=None):
        return self._body


class TestFavicons(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="gwsp-favicon-test-")
        self._old_cache = os.environ.get("XDG_CACHE_HOME")
        os.environ["XDG_CACHE_HOME"] = self._tmp

    def tearDown(self):
        if self._old_cache is None:
            os.environ.pop("XDG_CACHE_HOME", None)
        else:
            os.environ["XDG_CACHE_HOME"] = self._old_cache
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_domain_extraction(self):
        self.assertEqual(
            favicons.domain_for_provider("https://www.google.com/search?q={query}"),
            "www.google.com",
        )
        self.assertEqual(
            favicons.domain_for_provider("https://open.spotify.com/search/{query}"),
            "open.spotify.com",
        )

    def test_candidates_order_crisp_first(self):
        urls = favicons.favicon_candidates("www.google.com")
        self.assertTrue(urls[0].endswith("apple-touch-icon.png"))
        self.assertTrue(urls[-1].endswith("favicon.ico"))
        self.assertTrue(all("www.google.com" in u for u in urls))

    def test_candidates_empty_domain(self):
        self.assertEqual(favicons.favicon_candidates(""), [])

    def test_extension_mapping(self):
        self.assertEqual(favicons.extension_for("image/png", "http://x/favicon.ico"), ".png")
        self.assertEqual(favicons.extension_for("image/x-icon", "http://x/y"), ".ico")
        self.assertEqual(favicons.extension_for("image/svg+xml", "http://x/y"), ".svg")
        self.assertEqual(favicons.extension_for("", "http://x/icon.svg"), ".svg")

    def test_cache_miss_returns_none(self):
        self.assertIsNone(favicons.cached_icon_path("google"))

    def test_fetch_saves_file(self):
        body = b"\x89PNG\r\n" + b"x" * 500
        with patch.object(
            favicons.urllib.request,
            "urlopen",
            return_value=_FakeResponse(body, "image/png"),
        ):
            path = favicons.fetch_favicon("google", "https://www.google.com/search?q={query}")
        self.assertIsNotNone(path)
        self.assertTrue(path.endswith(".png"))
        self.assertEqual(favicons.cached_icon_path("google"), path)

    def test_fetch_rejects_non_image(self):
        body = b"<html>nope</html>" + b"x" * 500
        with patch.object(
            favicons.urllib.request,
            "urlopen",
            return_value=_FakeResponse(body, "text/html"),
        ):
            path = favicons.fetch_favicon("google", "https://www.google.com/search?q={query}")
        self.assertIsNone(path)

    def test_fetch_offline_keeps_cache(self):
        cached = os.path.join(favicons.cache_dir(), "google.png")
        with open(cached, "wb") as fh:
            fh.write(b"\x89PNG\r\n" + b"x" * 500)
        with patch.object(
            favicons.urllib.request, "urlopen", side_effect=OSError("offline")
        ):
            path = favicons.fetch_favicon("google", "https://www.google.com/search?q={query}")
        self.assertEqual(path, cached)

    def test_ensure_skips_cached_without_network(self):
        cached = os.path.join(favicons.cache_dir(), "google.png")
        with open(cached, "wb") as fh:
            fh.write(b"\x89PNG\r\n" + b"x" * 500)
        with patch.object(
            favicons.urllib.request, "urlopen", side_effect=AssertionError("must not fetch")
        ):
            results = favicons.ensure_favicons({"google": "https://www.google.com/"})
        self.assertEqual(results, {"google": cached})

    def test_every_provider_has_domain(self):
        for provider in PROVIDERS.values():
            self.assertTrue(favicons.domain_for_provider(provider.url), provider.provider_id)

    def test_icon_domain_overrides(self):
        self.assertEqual(favicons.icon_domain("brave", "https://search.brave.com/x"), "brave.com")
        self.assertEqual(
            favicons.icon_domain("hackernews", "https://hn.algolia.com/?q=x"),
            "news.ycombinator.com",
        )
        self.assertEqual(
            favicons.icon_domain("google", "https://www.google.com/search?q=x"),
            "www.google.com",
        )

    def test_icon_domains_tries_search_domain_first(self):
        domains = favicons.icon_domains("hackernews", "https://hn.algolia.com/?q=x")
        self.assertEqual(domains[0], "hn.algolia.com")
        self.assertIn("news.ycombinator.com", domains)

    def test_parse_icon_links_prefers_biggest(self):
        html = (
            '<link rel="icon" href="/icon16.png" sizes="16x16">'
            '<link rel="icon" href="/icon128.png" sizes="128x128">'
            '<link rel="shortcut icon" href="/favicon.ico">'
        )
        links = favicons.parse_icon_links(html, "https://example.com/")
        self.assertEqual(links[0], "https://example.com/icon128.png")
        self.assertIn("https://example.com/favicon.ico", links)

    def test_octet_stream_icon_accepted_by_magic(self):
        body = b"\x00\x00\x01\x00" + b"x" * 500
        with patch.object(
            favicons.urllib.request,
            "urlopen",
            return_value=_FakeResponse(body, "application/octet-stream"),
        ):
            path = favicons.fetch_favicon("kagi", "https://kagi.com/search?q={query}")
        self.assertIsNotNone(path)

    def test_external_fallback_used_when_direct_fails(self):
        png = b"\x89PNG\r\n" + b"x" * 500
        calls = []

        def _fake(urlopen_request, timeout=None):
            url = urlopen_request.full_url
            calls.append(url)
            if "google.com/s2/favicons" in url or "icons.duckduckgo.com" in url:
                return _FakeResponse(png, "image/png")
            raise OSError("blocked")

        with patch.object(favicons.urllib.request, "urlopen", side_effect=_fake):
            with patch.object(favicons, "discover_icon_links", return_value=[]):
                path = favicons.fetch_favicon("yep", "https://yep.com/search?q={query}")
        self.assertIsNotNone(path)
        self.assertTrue(any("google.com/s2/favicons" in url for url in calls))


if __name__ == "__main__":
    unittest.main()
