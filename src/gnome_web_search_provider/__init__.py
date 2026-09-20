#!/usr/bin/env python3
"""GNOME Shell web search provider with multiple configurable engines.

Exposes the ``org.gnome.Shell.SearchProvider2`` D-Bus interface on
``org.gnome.WebSearch.SearchProvider``.  Each enabled search provider
(from GSettings/JSON config) produces one result entry per query; picking
an entry opens the matching search URL in the configured browser.

The D-Bus service is implemented with only the Python standard library
(``gnome_web_search_provider.dbus``), so the daemon runs on a bare
Python 3 install with no pip/OS dependencies (upstream issue #2).

Run directly to start the service::

    python -m gnome_web_search_provider
"""

import shlex
import subprocess
from typing import Dict, List, Tuple

from .config import DEFAULT_BROWSER, ConfigManager
from .dbus import DBusService, Variant
from .providers import PROVIDERS, SearchProvider

BUS_NAME = "org.gnome.WebSearch.SearchProvider"
OBJECT_PATH = "/org/gnome/WebSearch/SearchProvider"
INTERFACE_NAME = "org.gnome.Shell.SearchProvider2"

# Separator between provider id and query inside a result id.  The unit
# separator character is very unlikely to be typed by a user.
RESULT_SEPARATOR = "\u241f"

# Method name -> (input signature, output signature).  Output ``None``
# means a void reply.  This table drives the pure-stdlib D-Bus dispatch.
SERVICE_METHODS: Dict[str, Tuple[str, str]] = {
    "GetInitialResultSet": ("as", "as"),
    "GetSubsearchResultSet": ("asas", "as"),
    "GetResultMetas": ("as", "aa{sv}"),
    "ActivateResult": ("sasu", ""),
    "LaunchSearch": ("asu", ""),
}


class WebSearchProvider(object):
    # Raw XML documents the interface for maintainers; dispatch itself is
    # driven by SERVICE_METHODS above.
    __dbus_xml__ = """
    <node>
        <interface name="org.gnome.Shell.SearchProvider2">
            <method name="GetInitialResultSet">
                <arg direction="in" type="as" name="terms" />
                <arg direction="out" type="as" name="results" />
            </method>
            <method name="GetSubsearchResultSet">
                <arg direction="in" type="as" name="previous_results" />
                <arg direction="in" type="as" name="terms" />
                <arg direction="out" type="as" name="results" />
            </method>
            <method name="GetResultMetas">
                <arg direction="in" type="as" name="results" />
                <arg direction="out" type="aa{sv}" name="metas" />
            </method>
            <method name="ActivateResult">
                <arg direction="in" type="s" name="result" />
                <arg direction="in" type="as" name="terms" />
                <arg direction="in" type="u" name="timestamp" />
            </method>
            <method name="LaunchSearch">
                <arg direction="in" type="as" name="terms" />
                <arg direction="in" type="u" name="timestamp" />
            </method>
        </interface>
    </node>
    """

    def __init__(self, config=None, providers: Dict[str, SearchProvider] = None):
        self._config = config if config is not None else ConfigManager()
        self._providers = providers if providers is not None else PROVIDERS

    # ------------------------------------------------------------- helpers

    def _enabled_ids(self) -> List[str]:
        """Provider ids currently enabled, filtered to known providers."""
        enabled = self._config.get_enabled_providers()
        return [pid for pid in enabled if pid in self._providers]

    def _result_ids(self, query: str) -> List[str]:
        return [f"{pid}{RESULT_SEPARATOR}{query}" for pid in self._enabled_ids()]

    @staticmethod
    def _split_result(result: str) -> Tuple[str, str]:
        provider_id, sep, query = result.partition(RESULT_SEPARATOR)
        return (provider_id, query) if sep else ("", result)

    def _open_url(self, url: str) -> None:
        """Open ``url`` with the configured browser command."""
        browser = (self._config.get_browser() or DEFAULT_BROWSER).strip()
        argv = [DEFAULT_BROWSER] if not browser else shlex.split(browser)
        if not argv:
            argv = [DEFAULT_BROWSER]
        subprocess.Popen(argv + [url])

    # --------------------------------------------------------------- D-Bus

    def GetInitialResultSet(self, terms: List[str]) -> List[str]:
        # One result per enabled provider; the query itself is the payload.
        return self._result_ids(" ".join(terms))

    def GetSubsearchResultSet(self, previous_results: List[str], terms: List[str]) -> List[str]:
        return self._result_ids(" ".join(terms))

    def GetResultMetas(self, results: List[str]) -> List[Dict[str, Variant]]:
        metas = []
        for result in results:
            provider_id, query = self._split_result(result)
            provider = self._providers.get(provider_id)
            if provider is None:
                continue
            metas.append(
                {
                    "id": Variant("s", result),
                    "name": Variant("s", f"Search {provider.name} for '{query}'"),
                    "description": Variant("s", "Press Enter to open in browser"),
                    "icon": Variant("s", provider.icon),
                }
            )
        return metas

    def ActivateResult(self, result: str, terms: List[str], timestamp: int):
        provider_id, query = self._split_result(result)
        provider = self._providers.get(provider_id)
        if provider is None:
            return
        self._open_url(provider.build_url(query))

    def LaunchSearch(self, terms: List[str], timestamp: int):
        # "Search the web" from the overview: open the first enabled
        # provider with the typed query in the configured browser.
        ids = self._enabled_ids()
        if not ids:
            return
        provider = self._providers[ids[0]]
        self._open_url(provider.build_url(" ".join(terms)))


def main() -> int:
    """Start the D-Bus search provider service (blocking)."""
    try:
        service = DBusService(BUS_NAME).connect()
        provider = WebSearchProvider()
        service.export(
            OBJECT_PATH,
            INTERFACE_NAME,
            provider,
            {name: (in_sig, out_sig or None) for name, (in_sig, out_sig) in SERVICE_METHODS.items()},
            introspect_xml=provider.__dbus_xml__,
        )
        print(f"Service running at {BUS_NAME}...", flush=True)
        service.run()
    except Exception as exc:
        print(f"Error starting service: {exc}", flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())