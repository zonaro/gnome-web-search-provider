"""Configuration manager for the GNOME web search provider.

Uses GSettings when PyGObject is installed AND the schema is available
(the native GNOME way), falling back to a JSON file in
``$XDG_CONFIG_HOME`` otherwise (e.g. on a minimal system without PyGObject,
when run from a checkout or inside a sandbox).

The ``gi`` import is lazy on purpose so that the core provider daemon
works with **zero external dependencies** (upstream issue #2); the backend
is chosen once at instantiation time, so reads and writes always hit the
same storage.
"""

import json
import os
from typing import Any, Dict, List, Optional

SCHEMA_ID = "org.gnome.WebSearch.SearchProvider"
KEY_ENABLED_PROVIDERS = "enabled-providers"
DEFAULT_ENABLED_PROVIDERS = ["google"]
KEY_BROWSER = "browser"
DEFAULT_BROWSER = "xdg-open"

CONFIG_DIR_NAME = "gnome-web-search-provider"
CONFIG_FILE_NAME = "config.json"


def _config_file_path() -> str:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, CONFIG_DIR_NAME, CONFIG_FILE_NAME)


def _schema_available(schema_id: str = SCHEMA_ID) -> bool:
    """True when PyGObject is importable and the schema is installed."""
    try:
        from gi.repository import Gio
    except Exception:
        return False
    try:
        source = Gio.SettingsSchemaSource.get_default()
        return source is not None and source.lookup(schema_id, True) is not None
    except Exception:
        return False


class ConfigManager:
    """Reads and writes the enabled search providers list and the browser."""

    def __init__(self, use_gsettings: Optional[bool] = None) -> None:
        # True -> always GSettings; False -> always JSON file;
        # None -> auto-detect (GSettings only when gi + schema are available).
        if use_gsettings is None:
            use_gsettings = _schema_available()
        self._use_gsettings = use_gsettings
        self._settings: Optional[Any] = None
        if use_gsettings:
            try:
                from gi.repository import Gio
            except Exception as exc:  # pragma: no cover - explicit misuse
                raise RuntimeError(
                    "GSettings backend requested but PyGObject (gi) is not installed; "
                    "use ConfigManager(use_gsettings=False) for the JSON backend"
                ) from exc
            self._settings = Gio.Settings.new(SCHEMA_ID)

    @property
    def backend(self) -> str:
        return "gsettings" if self._use_gsettings else "file"

    # ------------------------------------------------------- enabled list

    def get_enabled_providers(self) -> List[str]:
        if self._settings is not None:
            return list(self._settings.get_strv(KEY_ENABLED_PROVIDERS))
        data = self._read_data()
        providers = data.get("enabled_providers", list(DEFAULT_ENABLED_PROVIDERS))
        if not isinstance(providers, list):
            return list(DEFAULT_ENABLED_PROVIDERS)
        return [str(p) for p in providers]

    def set_enabled_providers(self, providers: List[str]) -> None:
        # Keep the list stable and free of duplicates/empty ids.
        seen: List[str] = []
        for pid in providers:
            pid = str(pid).strip()
            if pid and pid not in seen:
                seen.append(pid)
        if self._settings is not None:
            self._settings.set_strv(KEY_ENABLED_PROVIDERS, seen)
            self._settings.sync()
            return
        data = self._read_data()
        data["enabled_providers"] = seen
        self._write_data(data)

    def is_provider_enabled(self, provider_id: str) -> bool:
        return provider_id in self.get_enabled_providers()

    def toggle_provider(self, provider_id: str, enabled: bool) -> None:
        current = self.get_enabled_providers()
        if enabled and provider_id not in current:
            current.append(provider_id)
        elif not enabled and provider_id in current:
            current.remove(provider_id)
        self.set_enabled_providers(current)

    # ---------------------------------------------------------- browser

    def get_browser(self) -> str:
        if self._settings is not None:
            try:
                return self._settings.get_string(KEY_BROWSER) or DEFAULT_BROWSER
            except Exception:
                return DEFAULT_BROWSER
        data = self._read_data()
        browser = data.get("browser")
        return str(browser) if browser else DEFAULT_BROWSER

    def set_browser(self, command: str) -> None:
        command = str(command).strip()
        if not command:
            return  # refuse to store an empty browser command
        if self._settings is not None:
            self._settings.set_string(KEY_BROWSER, command)
            self._settings.sync()
            return
        data = self._read_data()
        data["browser"] = command
        self._write_data(data)

    # ------------------------------------------------------------------
    # JSON file backend helpers
    # ------------------------------------------------------------------

    def _read_data(self) -> Dict[str, Any]:
        try:
            with open(_config_file_path(), encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def _write_data(self, data: Dict[str, Any]) -> None:
        path = _config_file_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = f"{path}.tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
        os.replace(tmp, path)