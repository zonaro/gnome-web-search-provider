#!/usr/bin/env python3
"""GNOME Shell web search provider with multiple configurable engines.

Exposes the ``org.gnome.Shell.SearchProvider2`` D-Bus interface on
``org.gnome.WebSearch.SearchProvider``.  Each enabled search provider
(from GSettings/JSON config) produces one result entry per query; picking
an entry opens the matching search URL in the default browser.

Run directly to start the service::

    python -m gnome_web_search_provider
"""

import subprocess
from typing import Dict, List, Tuple

from dasbus.connection import SessionMessageBus
from dasbus.loop import EventLoop
from dasbus.typing import Variant

from .config import ConfigManager
from .providers import PROVIDERS, SearchProvider

BUS_NAME = "org.gnome.WebSearch.SearchProvider"
OBJECT_PATH = "/org/gnome/WebSearch/SearchProvider"

# Separator between provider id and query inside a result id.  The unit
# separator character is very unlikely to be typed by a user.
RESULT_SEPARATOR = "\u241f"


class WebSearchProvider(object):
    # Raw XML guarantees strict compatibility with GNOME Shell's interface.
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
        subprocess.Popen(["xdg-open", provider.build_url(query)])

    def LaunchSearch(self, terms: List[str], timestamp: int):
        pass


def main() -> int:
    """Start the D-Bus search provider service (blocking)."""
    try:
        bus = SessionMessageBus()
        provider = WebSearchProvider()
        bus.publish_object(OBJECT_PATH, provider)
        # Register the name LAST, after the object is ready.
        bus.register_service(BUS_NAME)
        print(f"Service running at {BUS_NAME}...", flush=True)
        EventLoop().run()
    except Exception as exc:
        print(f"Error starting service: {exc}", flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())