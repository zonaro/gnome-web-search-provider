"""Configuration manager for the GNOME web search provider.

Uses GSettings when the schema is installed (the native GNOME way),
falling back to a JSON file in $XDG_CONFIG_HOME when it is not (e.g. when
the provider is run from a checkout or inside a sandbox).

The backend is chosen once at instantiation time, so reads and writes
always hit the same storage.
"""

import json
import os
from typing import List, Optional

from gi.repository import Gio

SCHEMA_ID = "org.gnome.WebSearch.SearchProvider"
KEY_ENABLED_PROVIDERS = "enabled-providers"
DEFAULT_ENABLED_PROVIDERS = ["google"]

CONFIG_DIR_NAME = "gnome-web-search-provider"
CONFIG_FILE_NAME = "config.json"


def _config_file_path() -> str:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, CONFIG_DIR_NAME, CONFIG_FILE_NAME)


def _schema_available(schema_id: str = SCHEMA_ID) -> bool:
    source = Gio.SettingsSchemaSource.get_default()
    return source is not None and source.lookup(schema_id, True) is not None


class ConfigManager:
    """Reads and writes the enabled search providers list."""

    def __init__(self, use_gsettings: Optional[bool] = None) -> None:
        # True -> always GSettings; False -> always JSON file;
        # None -> auto-detect (GSettings when the schema is installed).
        if use_gsettings is None:
            use_gsettings = _schema_available()
        self._use_gsettings = use_gsettings
        self._settings: Optional[Gio.Settings] = None
        if use_gsettings:
            self._settings = Gio.Settings.new(SCHEMA_ID)

    @property
    def backend(self) -> str:
        return "gsettings" if self._use_gsettings else "file"

    def get_enabled_providers(self) -> List[str]:
        if self._settings is not None:
            return list(self._settings.get_strv(KEY_ENABLED_PROVIDERS))
        return self._read_file()

    def set_enabled_providers(self, providers: List[str]) -> None:
        # Keep the list stable and free of duplicates/empty ids.
        seen: List[str] = []
        for pid in providers:
            pid = pid.strip()
            if pid and pid not in seen:
                seen.append(pid)
        if self._settings is not None:
            self._settings.set_strv(KEY_ENABLED_PROVIDERS, seen)
            self._settings.sync()
            return
        self._write_file(seen)

    def is_provider_enabled(self, provider_id: str) -> bool:
        return provider_id in self.get_enabled_providers()

    def toggle_provider(self, provider_id: str, enabled: bool) -> None:
        current = self.get_enabled_providers()
        if enabled and provider_id not in current:
            current.append(provider_id)
        elif not enabled and provider_id in current:
            current.remove(provider_id)
        self.set_enabled_providers(current)

    # ------------------------------------------------------------------
    # JSON file backend helpers
    # ------------------------------------------------------------------

    def _read_file(self) -> List[str]:
        try:
            with open(_config_file_path(), encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            return list(DEFAULT_ENABLED_PROVIDERS)
        providers = data.get("enabled_providers", [])
        if not isinstance(providers, list):
            return list(DEFAULT_ENABLED_PROVIDERS)
        return [str(p) for p in providers]

    def _write_file(self, providers: List[str]) -> None:
        path = _config_file_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = f"{path}.tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({"enabled_providers": providers}, fh, indent=2)
        os.replace(tmp, path)