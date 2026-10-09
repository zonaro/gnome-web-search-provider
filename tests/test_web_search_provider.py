#!/usr/bin/env python3
"""Tests for the multi-provider GNOME web search provider."""

import io
import os
import shutil
import socket
import struct
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

# Make the package importable from the source tree.
SRC = os.path.join(os.path.dirname(__file__), "..", "src")
sys.path.insert(0, os.path.abspath(SRC))

# Pin English: metas assertions below are written in English and must not
# depend on the machine language (see tests/test_i18n.py for locale coverage).
os.environ["GWSP_LANG"] = "en"

from gnome_web_search_provider import (  # noqa: E402
    BUS_NAME,
    OBJECT_PATH,
    RESULT_SEPARATOR,
    SERVICE_METHODS,
    WebSearchProvider,
)
from gnome_web_search_provider import cli  # noqa: E402
from gnome_web_search_provider import dbus as dbus_mod  # noqa: E402
from gnome_web_search_provider.config import (  # noqa: E402
    DEFAULT_BROWSER,
    DEFAULT_ENABLED_PROVIDERS,
    MAX_ENABLED_PROVIDERS,
    ConfigManager,
)
from gnome_web_search_provider.providers import PROVIDERS  # noqa: E402


def _provider(provider_id: str):
    return PROVIDERS[provider_id]


class FakeConfig:
    """In-memory ConfigManager stand-in for provider tests."""

    def __init__(self, enabled=None, browser=DEFAULT_BROWSER):
        self._enabled = list(enabled) if enabled is not None else list(DEFAULT_ENABLED_PROVIDERS)
        self._browser = browser

    def get_enabled_providers(self):
        return list(self._enabled)

    def set_enabled_providers(self, providers):
        self._enabled = list(providers)

    def toggle_provider(self, provider_id, enabled):
        if enabled and provider_id not in self._enabled:
            self._enabled.append(provider_id)
        elif not enabled and provider_id in self._enabled:
            self._enabled.remove(provider_id)

    def get_browser(self):
        return self._browser

    def set_browser(self, command):
        self._browser = command


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

    def test_service_methods_match_interface(self):
        expected = {"GetInitialResultSet", "GetSubsearchResultSet", "GetResultMetas", "ActivateResult", "LaunchSearch"}
        self.assertEqual(set(SERVICE_METHODS), expected)

    # ------------------------------------------------------- result sets

    def test_initial_result_set_default_google(self):
        result = self.provider.GetInitialResultSet(["hello", "world"])
        self.assertEqual(result, [f"google{RESULT_SEPARATOR}hello world"])

    def test_initial_result_set_empty_terms(self):
        result = self.provider.GetInitialResultSet([])
        self.assertEqual(result, [])

    def test_initial_result_set_blank_terms(self):
        result = self.provider.GetInitialResultSet(["   "])
        self.assertEqual(result, [])

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

    def test_daemon_caps_enabled_providers_at_max(self):
        ids = ["google", "bing", "duckduckgo", "brave", "startpage", "ecosia", "qwant"]
        provider = WebSearchProvider(config=FakeConfig(ids))
        result = provider.GetInitialResultSet(["term"])
        self.assertEqual(len(result), MAX_ENABLED_PROVIDERS)
        self.assertEqual(
            result,
            [f"{pid}{RESULT_SEPARATOR}term" for pid in ids[:MAX_ENABLED_PROVIDERS]],
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
        self.assertIn("gicon", meta)

    def test_get_result_metas_values(self):
        result = self.provider.GetResultMetas([f"bing{RESULT_SEPARATOR}test query"])
        meta = result[0]
        self.assertEqual(meta["id"].unpack(), f"bing{RESULT_SEPARATOR}test query")
        self.assertEqual(meta["name"].unpack(), "Search Bing for 'test query'")
        self.assertEqual(meta["description"].unpack(), "Press Enter to open in browser")
        gicon = meta["gicon"].unpack()
        if os.path.isabs(gicon):
            self.assertTrue(os.path.isfile(gicon), gicon)
        else:
            self.assertTrue(gicon.endswith("-symbolic") or gicon == "web-browser", gicon)

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

    # ----------------------------------------------------------- browser

    @patch("gnome_web_search_provider.subprocess.Popen")
    def test_activate_result_uses_configured_browser(self, mock_popen):
        provider = WebSearchProvider(config=FakeConfig(["google"], browser="firefox"))
        provider.ActivateResult(f"google{RESULT_SEPARATOR}linux", ["linux"], 0)
        call_args = mock_popen.call_args[0][0]
        self.assertEqual(call_args[0], "firefox")
        self.assertEqual(call_args[1], "https://www.google.com/search?q=linux")

    @patch("gnome_web_search_provider.subprocess.Popen")
    def test_activate_result_browser_with_args(self, mock_popen):
        provider = WebSearchProvider(
            config=FakeConfig(["google"], browser="flatpak run org.mozilla.firefox")
        )
        provider.ActivateResult(f"google{RESULT_SEPARATOR}linux", ["linux"], 0)
        call_args = mock_popen.call_args[0][0]
        self.assertEqual(
            call_args,
            ["flatpak", "run", "org.mozilla.firefox", "https://www.google.com/search?q=linux"],
        )

    @patch("gnome_web_search_provider.subprocess.Popen")
    def test_launch_search_opens_first_enabled_provider(self, mock_popen):
        provider = WebSearchProvider(config=FakeConfig(["bing", "google"]))
        provider.LaunchSearch(["hello", "world"], 0)
        mock_popen.assert_called_once()
        call_args = mock_popen.call_args[0][0]
        self.assertEqual(call_args[0], "xdg-open")
        self.assertEqual(call_args[1], "https://www.bing.com/search?q=hello+world")

    @patch("gnome_web_search_provider.subprocess.Popen")
    def test_launch_search_with_no_enabled_providers_does_nothing(self, mock_popen):
        provider = WebSearchProvider(config=FakeConfig([]))
        provider.LaunchSearch(["hello"], 0)
        mock_popen.assert_not_called()

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

    def test_kagi_and_you_are_back(self):
        self.assertIn("kagi", PROVIDERS)
        self.assertIn("you", PROVIDERS)
        self.assertTrue(PROVIDERS["kagi"].build_url("t").startswith("https://kagi.com/"))
        self.assertTrue(PROVIDERS["you"].build_url("t").startswith("https://you.com/"))


class _TempXdgMixin:
    """Isolate the JSON file backend under a temporary XDG_CONFIG_HOME."""

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

    def make_config(self):
        return ConfigManager(use_gsettings=False)


class TestConfigManager(_TempXdgMixin, unittest.TestCase):
    """JSON file backend, isolated under a temporary XDG_CONFIG_HOME."""

    def test_default_is_google(self):
        config = self.make_config()
        self.assertEqual(config.get_enabled_providers(), ["google"])
        self.assertEqual(config.backend, "file")

    def test_set_and_persist(self):
        config = self.make_config()
        config.set_enabled_providers(["google", "bing"])
        again = self.make_config()
        self.assertEqual(again.get_enabled_providers(), ["google", "bing"])

    def test_set_dedupes_and_strips(self):
        config = self.make_config()
        config.set_enabled_providers(["  google ", "google", "", "bing", "bing"])
        self.assertEqual(config.get_enabled_providers(), ["google", "bing"])

    def test_set_enabled_providers_caps_at_max(self):
        config = self.make_config()
        ids = ["google", "bing", "duckduckgo", "brave", "startpage", "ecosia", "qwant"]
        config.set_enabled_providers(ids)
        self.assertEqual(config.get_enabled_providers(), ids[:MAX_ENABLED_PROVIDERS])

    def test_get_enabled_providers_caps_at_max(self):
        config = self.make_config()
        ids = ["google", "bing", "duckduckgo", "brave", "startpage", "ecosia", "qwant"]
        config._write_data({"enabled_providers": ids})
        self.assertEqual(config.get_enabled_providers(), ids[:MAX_ENABLED_PROVIDERS])
        self.assertEqual(self.make_config().get_enabled_providers(), ids[:MAX_ENABLED_PROVIDERS])

    def test_toggle_refuses_sixth_provider(self):
        config = self.make_config()
        config.set_enabled_providers(["google", "bing", "duckduckgo", "brave", "startpage"])
        config.toggle_provider("ecosia", True)
        self.assertEqual(len(config.get_enabled_providers()), MAX_ENABLED_PROVIDERS)
        self.assertNotIn("ecosia", config.get_enabled_providers())

    def test_toggle(self):
        config = self.make_config()
        config.toggle_provider("duckduckgo", True)
        self.assertEqual(config.get_enabled_providers(), ["google", "duckduckgo"])
        config.toggle_provider("google", False)
        self.assertEqual(config.get_enabled_providers(), ["duckduckgo"])

    def test_is_provider_enabled(self):
        config = self.make_config()
        self.assertTrue(config.is_provider_enabled("google"))
        self.assertFalse(config.is_provider_enabled("bing"))

    def test_corrupt_file_falls_back_to_default(self):
        config_dir = os.path.join(self._tmp, "gnome-web-search-provider")
        os.makedirs(config_dir, exist_ok=True)
        with open(os.path.join(config_dir, "config.json"), "w", encoding="utf-8") as fh:
            fh.write("{not valid json")
        config = self.make_config()
        self.assertEqual(config.get_enabled_providers(), ["google"])

    # ---------------------------------------------------------- browser

    def test_browser_default_is_xdg_open(self):
        config = self.make_config()
        self.assertEqual(config.get_browser(), DEFAULT_BROWSER)

    def test_browser_set_and_persist(self):
        config = self.make_config()
        config.set_browser("firefox")
        again = self.make_config()
        self.assertEqual(again.get_browser(), "firefox")

    def test_browser_set_ignores_empty(self):
        config = self.make_config()
        config.set_browser("   ")
        self.assertEqual(config.get_browser(), DEFAULT_BROWSER)

    def test_browser_survives_provider_update(self):
        config = self.make_config()
        config.set_browser("google-chrome")
        config.set_enabled_providers(["bing"])
        again = self.make_config()
        self.assertEqual(again.get_browser(), "google-chrome")
        self.assertEqual(again.get_enabled_providers(), ["bing"])


class TestCli(_TempXdgMixin, unittest.TestCase):
    """CLI commands, forced onto the isolated JSON backend."""

    def setUp(self):
        super().setUp()
        self._def = patch.object(cli, "ConfigManager", self.make_config)
        self._def.start()

    def tearDown(self):
        self._def.stop()
        super().tearDown()

    def run_cli(self, *argv):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = cli.main(list(argv))
        return code, buf.getvalue()

    def test_list_returns_zero_and_shows_backend(self):
        code, out = self.run_cli("list")
        self.assertEqual(code, 0)
        self.assertIn("Backend: file", out)
        self.assertIn("google", out)

    def test_status_aliases_list(self):
        code, out = self.run_cli("status")
        self.assertEqual(code, 0)
        self.assertIn("google", out)

    def test_enable_adds_provider(self):
        code, _ = self.run_cli("enable", "bing", "duckduckgo")
        self.assertEqual(code, 0)
        self.assertEqual(self.make_config().get_enabled_providers(), ["google", "bing", "duckduckgo"])

    def test_disable_removes_provider(self):
        self.make_config().set_enabled_providers(["google", "bing"])
        code, _ = self.run_cli("disable", "bing")
        self.assertEqual(code, 0)
        self.assertEqual(self.make_config().get_enabled_providers(), ["google"])

    def test_set_replaces_list(self):
        code, _ = self.run_cli("set", "brave")
        self.assertEqual(code, 0)
        self.assertEqual(self.make_config().get_enabled_providers(), ["brave"])

    def test_set_accepts_empty_list(self):
        code, _ = self.run_cli("set")
        self.assertEqual(code, 0)
        self.assertEqual(self.make_config().get_enabled_providers(), [])

    def test_unknown_provider_rejected(self):
        with self.assertRaises(SystemExit) as ctx:
            self.run_cli("enable", "does-not-exist")
        self.assertEqual(ctx.exception.code, 1)
        self.assertEqual(self.make_config().get_enabled_providers(), ["google"])

    def test_browser_get_and_set(self):
        code, out = self.run_cli("browser")
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), DEFAULT_BROWSER)
        code, _ = self.run_cli("browser", "firefox")
        self.assertEqual(code, 0)
        self.assertEqual(self.make_config().get_browser(), "firefox")


class TestResultIcons(_TempXdgMixin, unittest.TestCase):
    """Metas carry the cached favicon or the themed fallback (config parity)."""

    def setUp(self):
        super().setUp()
        from gnome_web_search_provider import _result_icon  # noqa: E402
        from gnome_web_search_provider.providers import fallback_icon_name  # noqa: E402

        self._result_icon = _result_icon
        self._fallback_icon_name = fallback_icon_name
        self._old_cache = os.environ.get("XDG_CACHE_HOME")
        os.environ["XDG_CACHE_HOME"] = self._tmp

    def tearDown(self):
        if self._old_cache is None:
            os.environ.pop("XDG_CACHE_HOME", None)
        else:
            os.environ["XDG_CACHE_HOME"] = self._old_cache
        super().tearDown()

    def _write_cached(self, provider_id, ext, size=200):
        directory = os.path.join(self._tmp, "gnome-web-search-provider", "favicons")
        os.makedirs(directory, exist_ok=True)
        path = os.path.join(directory, f"{provider_id}{ext}")
        with open(path, "wb") as fh:
            fh.write(b"x" * size)
        return path

    def test_fallback_names(self):
        self.assertEqual(self._fallback_icon_name("youtube"), "video-x-generic-symbolic")
        self.assertEqual(self._fallback_icon_name("google-maps"), "find-location-symbolic")
        self.assertEqual(self._fallback_icon_name("google"), "web-browser-symbolic")
        self.assertEqual(self._fallback_icon_name("no-such-provider"), "web-browser-symbolic")

    def test_result_icon_uses_cached_favicon(self):
        path = self._write_cached("google", ".png")
        self.assertEqual(self._result_icon(_provider("google")), path)

    def test_result_icon_falls_back_without_cache(self):
        self.assertEqual(self._result_icon(_provider("google")), "web-browser-symbolic")

    def test_result_icon_skips_unloadable_format(self):
        self._write_cached("google", ".webp")
        self.assertEqual(self._result_icon(_provider("google")), "web-browser-symbolic")


class TestDbusWire(unittest.TestCase):
    """Round-trips of the pure-stdlib D-Bus marshalling."""

    def roundtrip(self, signature, values):
        tokens = dbus_mod.split_types(signature)
        raw = dbus_mod.pack_types(tokens, values)
        return dbus_mod.unpack_types(tokens, raw)

    def test_array_length_excludes_leading_padding(self):
        # dbus-broker disconnects peers whose array length covers the
        # alignment padding before the first element (live "invalid body"
        # kills once 3+ result metas were returned). Canonical form counts
        # the elements only: meta1 payload starts at 36 (needs 4 pad bytes
        # to reach the 8-aligned entry at 40), so its length is 18, not 22.
        body = dbus_mod.pack_types(
            ["aa{sv}"],
            [[{"k": dbus_mod.Variant("s", "XXXX")}, {"k": dbus_mod.Variant("s", "Y")}]],
        )
        (outer,) = struct.unpack_from("<I", body, 0)
        self.assertEqual(outer, len(body) - 4)
        (inner1,) = struct.unpack_from("<I", body, 32)
        self.assertEqual(inner1, 18)
        self.assertEqual(body[32:36], b"\x12\x00\x00\x00")
        # The canonical bytes still round-trip through our own parser.
        back = dbus_mod.unpack_types(["aa{sv}"], body)
        self.assertEqual(len(back[0]), 2)

    def test_split_types(self):
        self.assertEqual(dbus_mod.split_types("as"), ["as"])
        self.assertEqual(dbus_mod.split_types("aas"), ["aas"])
        self.assertEqual(dbus_mod.split_types("sasu"), ["s", "as", "u"])
        self.assertEqual(dbus_mod.split_types("aa{sv}"), ["aa{sv}"])
        self.assertEqual(dbus_mod.split_types("suv"), ["s", "u", "v"])
        self.assertEqual(dbus_mod.split_types("(yv)"), ["(yv)"])

    def test_roundtrip_as(self):
        self.assertEqual(self.roundtrip("as", [["a", "b c", ""]]), [["a", "b c", ""]])

    def test_roundtrip_aas(self):
        self.assertEqual(self.roundtrip("aas", [[["x", "y"], []]]), [[["x", "y"], []]])

    def test_roundtrip_sasu(self):
        value = ["result-id", ["hello", "world"], 123]
        self.assertEqual(self.roundtrip("sasu", value), value)

    def test_roundtrip_asu(self):
        value = [["hello"], 7]
        self.assertEqual(self.roundtrip("asu", value), value)

    def test_roundtrip_u(self):
        self.assertEqual(self.roundtrip("u", [42]), [42])

    def test_roundtrip_s(self):
        self.assertEqual(self.roundtrip("s", ["unicode ✓ é"]), ["unicode ✓ é"])

    def test_roundtrip_aa_sv(self):
        packed = self.roundtrip(
            "aa{sv}",
            [
                [
                    {"id": dbus_mod.Variant("s", "r1"), "name": dbus_mod.Variant("s", "N1")},
                    {"id": dbus_mod.Variant("s", "r2")},
                ],
            ],
        )
        # D-Bus dicts are arrays of {key, value} structs, so each entry of the
        # outer array comes back as a list of single-entry dicts.
        self.assertEqual(
            packed,
            [
                [
                    [{"id": dbus_mod.Variant("s", "r1")}, {"name": dbus_mod.Variant("s", "N1")}],
                    [{"id": dbus_mod.Variant("s", "r2")}],
                ],
            ],
        )

    def test_roundtrip_sv_variant(self):
        packed = self.roundtrip("a{sv}", [{"k": dbus_mod.Variant("s", "v")}])
        self.assertEqual(packed, [[{"k": dbus_mod.Variant("s", "v")}]])

    def test_build_and_parse_message(self):
        fields = {
            dbus_mod.FIELD_PATH: dbus_mod.Variant("o", "/org/gnome/WebSearch/SearchProvider"),
            dbus_mod.FIELD_INTERFACE: dbus_mod.Variant("s", "org.gnome.Shell.SearchProvider2"),
            dbus_mod.FIELD_MEMBER: dbus_mod.Variant("s", "GetInitialResultSet"),
            dbus_mod.FIELD_SIGNATURE: dbus_mod.Variant("g", "as"),
        }
        body = dbus_mod.pack_types(["as"], [["hello", "world"]])
        raw = dbus_mod.build_message(dbus_mod.MESSAGE_METHOD_CALL, 17, fields, body)
        mtype, serial, parsed_fields, parsed_body = dbus_mod.parse_message(raw)
        self.assertEqual(mtype, dbus_mod.MESSAGE_METHOD_CALL)
        self.assertEqual(serial, 17)
        self.assertEqual(parsed_fields[dbus_mod.FIELD_MEMBER], "GetInitialResultSet")
        self.assertEqual(parsed_fields[dbus_mod.FIELD_SIGNATURE], "as")
        self.assertEqual(dbus_mod.unpack_types(["as"], parsed_body), [["hello", "world"]])

    def test_variant_equality(self):
        self.assertEqual(dbus_mod.Variant("s", "x"), dbus_mod.Variant("s", "x"))
        self.assertNotEqual(dbus_mod.Variant("s", "x"), dbus_mod.Variant("u", 1))

    def test_call_stashes_method_call_during_handshake(self):
        # dbus-broker forwards a queued activation call before answering
        # RequestName; _call must stash it instead of raising
        # "unexpected reply of type 1" (which killed on-demand activation).
        service = dbus_mod.DBusService("org.test.Service")
        handler = type("H", (), {"Echo": lambda self, arg: arg})()
        service.export(
            "/org/test/Path",
            "org.test.Interface",
            handler,
            {"Echo": ("s", "s")},
            introspect_xml="<node/>",
        )
        client, server = socket.socketpair()
        try:
            service._sock = server
            incoming = dbus_mod.build_message(
                dbus_mod.MESSAGE_METHOD_CALL,
                99,
                {
                    dbus_mod.FIELD_PATH: dbus_mod.Variant("o", "/org/test/Path"),
                    dbus_mod.FIELD_INTERFACE: dbus_mod.Variant("s", "org.test.Interface"),
                    dbus_mod.FIELD_MEMBER: dbus_mod.Variant("s", "Echo"),
                    dbus_mod.FIELD_SIGNATURE: dbus_mod.Variant("g", "s"),
                },
                dbus_mod.pack_types(["s"], ["ping"]),
            )
            reply = dbus_mod.build_message(
                dbus_mod.MESSAGE_METHOD_RETURN,
                50,
                {
                    dbus_mod.FIELD_REPLY_SERIAL: dbus_mod.Variant("u", 2),
                    dbus_mod.FIELD_SIGNATURE: dbus_mod.Variant("g", "s"),
                },
                dbus_mod.pack_types(["s"], ["hello"]),
            )
            client.sendall(incoming + reply)
            result = service._call(
                "org.freedesktop.DBus",
                "/org/freedesktop/DBus",
                "org.freedesktop.DBus",
                "Hello",
                "",
                [],
            )
            self.assertEqual(result, ["hello"])
            self.assertEqual(len(service._pending_calls), 1)
            call_serial, _fields, pending_body = service._pending_calls[0]
            self.assertEqual(call_serial, 99)
            self.assertEqual(dbus_mod.unpack_types(["s"], pending_body), ["ping"])
        finally:
            client.close()
            server.close()

    def test_run_answers_pending_calls(self):
        service = dbus_mod.DBusService("org.test.Service")
        handler = type("H", (), {"Echo": lambda self, arg: arg})()
        service.export(
            "/org/test/Path",
            "org.test.Interface",
            handler,
            {"Echo": ("s", "s")},
            introspect_xml="<node/>",
        )
        client, server = socket.socketpair()
        try:
            service._sock = server
            service._stop.set()
            service._pending_calls = [
                (
                    99,
                    {
                        dbus_mod.FIELD_PATH: "/org/test/Path",
                        dbus_mod.FIELD_INTERFACE: "org.test.Interface",
                        dbus_mod.FIELD_MEMBER: "Echo",
                    },
                    dbus_mod.pack_types(["s"], ["ping"]),
                )
            ]
            service.run()
            incoming = dbus_mod.read_message(client)
            self.assertIsNotNone(incoming)
            mtype, _serial, reply_fields, reply_body = incoming
            self.assertEqual(mtype, dbus_mod.MESSAGE_METHOD_RETURN)
            self.assertEqual(reply_fields[dbus_mod.FIELD_REPLY_SERIAL], 99)
            self.assertEqual(dbus_mod.unpack_types(["s"], reply_body), ["ping"])
        finally:
            client.close()
            try:
                server.close()
            except OSError:
                pass

    def test_dispatch_replies_with_call_serial(self):
        service = dbus_mod.DBusService("org.test.Service")
        handler = type("H", (), {"Echo": lambda self, arg: arg})()
        service.export(
            "/org/test/Path",
            "org.test.Interface",
            handler,
            {"Echo": ("s", "s")},
        )
        fields = {
            dbus_mod.FIELD_PATH: "/org/test/Path",
            dbus_mod.FIELD_INTERFACE: "org.test.Interface",
            dbus_mod.FIELD_MEMBER: "Echo",
            dbus_mod.FIELD_SENDER: ":1.42",
            dbus_mod.FIELD_SIGNATURE: "s",
        }
        body = dbus_mod.pack_types(["s"], ["ping"])
        raw = service._dispatch(fields, body, 99)
        mtype, _serial, reply_fields, reply_body = dbus_mod.parse_message(raw)
        self.assertEqual(mtype, dbus_mod.MESSAGE_METHOD_RETURN)
        self.assertEqual(reply_fields[dbus_mod.FIELD_REPLY_SERIAL], 99)
        self.assertEqual(reply_fields[dbus_mod.FIELD_DESTINATION], ":1.42")
        self.assertEqual(dbus_mod.unpack_types(["s"], reply_body), ["ping"])

    def test_dispatch_error_replies_with_call_serial(self):
        service = dbus_mod.DBusService("org.test.Service")
        fields = {
            dbus_mod.FIELD_PATH: "/org/test/Missing",
            dbus_mod.FIELD_SENDER: ":1.42",
        }
        raw = service._dispatch(fields, b"", 7)
        mtype, _serial, reply_fields, _reply_body = dbus_mod.parse_message(raw)
        self.assertEqual(mtype, dbus_mod.MESSAGE_ERROR)
        self.assertEqual(reply_fields[dbus_mod.FIELD_REPLY_SERIAL], 7)

    def test_error_reply_includes_signature(self):
        # A reply with a body but no SIGNATURE header field is dropped by
        # dbus-broker as "invalid body"; the error text is sent as "s".
        service = dbus_mod.DBusService("org.test.Service")
        fields = {dbus_mod.FIELD_SENDER: ":1.42"}
        raw = service._reply_error(fields, 3, "org.freedesktop.DBus.Error.Failed", "boom")
        mtype, _serial, reply_fields, reply_body = dbus_mod.parse_message(raw)
        self.assertEqual(mtype, dbus_mod.MESSAGE_ERROR)
        self.assertEqual(reply_fields[dbus_mod.FIELD_SIGNATURE], "s")
        self.assertEqual(dbus_mod.unpack_types(["s"], reply_body), ["boom"])

    def test_dispatch_introspect_returns_xml(self):
        # Clients introspect (interface org.freedesktop.DBus.Introspectable)
        # before calling a typed method; the export must match by path alone.
        service = dbus_mod.DBusService("org.test.Service")
        handler = type("H", (), {"Echo": lambda self, arg: arg})()
        service.export(
            "/org/test/Path",
            "org.test.Interface",
            handler,
            {"Echo": ("s", "s")},
            introspect_xml="<node/>",
        )
        fields = {
            dbus_mod.FIELD_PATH: "/org/test/Path",
            dbus_mod.FIELD_INTERFACE: "org.freedesktop.DBus.Introspectable",
            dbus_mod.FIELD_MEMBER: "Introspect",
        }
        raw = service._dispatch(fields, b"", 5)
        mtype, _serial, reply_fields, reply_body = dbus_mod.parse_message(raw)
        self.assertEqual(mtype, dbus_mod.MESSAGE_METHOD_RETURN)
        self.assertEqual(reply_fields[dbus_mod.FIELD_SIGNATURE], "s")
        self.assertEqual(dbus_mod.unpack_types(["s"], reply_body), ["<node/>"])

    def test_service_methods_match_declared_xml(self):
        # SERVICE_METHODS drives the wire dispatch, so its signatures must
        # match the introspection XML that clients actually read.  A drift
        # here (e.g. "aas" vs "as as") only shows up as a runtime Failure.
        import xml.etree.ElementTree as ET

        root = ET.fromstring(WebSearchProvider.__dbus_xml__)
        iface = root.find("./interface")
        self.assertIsNotNone(iface)
        for method in iface.findall("method"):
            name = method.get("name")
            self.assertIn(name, SERVICE_METHODS, f"XML declares undeclared method {name}")
            declared = SERVICE_METHODS[name][0]
            in_args = [a.get("type") for a in method.findall("arg") if a.get("direction") == "in"]
            self.assertEqual(
                declared,
                "".join(in_args),
                f"{name}: SERVICE_METHODS {declared!r} != XML inputs {in_args!r}",
            )


if __name__ == "__main__":
    unittest.main()