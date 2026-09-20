#!/usr/bin/env python3
"""GTK4 preferences window to enable/disable web search providers.

Each provider is a checkable row grouped by category, and the browser
command used to open results can be customized at the top. Changes are
written immediately to the shared configuration (GSettings or the JSON
fallback), so the running search provider picks them up on the next search.

This window is the optional GUI part; PyGObject/GTK4 are only needed here,
not for the provider daemon. Without them, use ``gnome-web-search-provider-cli``.

Run directly, or launch via the installed desktop entry::

    gnome-web-search-provider-config
"""

import subprocess
import sys

try:
    import gi

    gi.require_version("Gtk", "4.0")
    gi.require_version("Gdk", "4.0")

    from gi.repository import Gdk, Gtk  # noqa: E402
except Exception:  # pragma: no cover - depends on optional PyGObject
    Gdk = None
    Gtk = None

from .config import ConfigManager  # noqa: E402
from .providers import CATEGORIES, PROVIDERS  # noqa: E402

_APP_ID = "org.gnome.WebSearch.SearchProviderConfig"

_CSS = """
.category-header {
    font-weight: bold;
    padding: 10px 12px 2px 12px;
    color: alpha(currentColor, 0.85);
}
.provider-row {
    padding: 2px 12px 2px 12px;
}
.footer {
    padding: 8px 12px;
    color: alpha(currentColor, 0.75);
}
"""

_SEARCH_SETTINGS_BIN = "gnome-control-center"

_NO_GTK_MESSAGE = (
    "The GNOME web search provider config window needs PyGObject and GTK4. "
    "Install python3-gobject / python3-gi with GTK4, or configure providers "
    "from the terminal instead: gnome-web-search-provider-cli"
)


if Gtk is None:  # pragma: no cover - depends on optional PyGObject

    def main() -> int:
        print(_NO_GTK_MESSAGE, file=sys.stderr)
        return 1


else:

    class ConfigWindow(Gtk.ApplicationWindow):
        def __init__(self, application: Gtk.Application, config: ConfigManager):
            super().__init__(application=application)
            self._config = config
            self._checks: dict = {}

            self.set_title("Web Search Providers")
            self.set_default_size(480, 640)

            toolbar = Gtk.HeaderBar()
            self.set_titlebar(toolbar)

            select_all = Gtk.Button(label="All")
            select_all.set_tooltip_text("Enable every search provider")
            select_all.connect("clicked", self._on_select_all)
            toolbar.pack_start(select_all)

            select_none = Gtk.Button(label="None")
            select_none.set_tooltip_text("Disable every search provider")
            select_none.connect("clicked", self._on_select_none)
            toolbar.pack_start(select_none)

            search_settings = Gtk.Button(label="GNOME Search Settings")
            search_settings.connect("clicked", self._on_open_search_settings)
            toolbar.pack_end(search_settings)

            root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
            self.set_child(root)

            scrolled = Gtk.ScrolledWindow()
            scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
            scrolled.set_vexpand(True)
            root.append(scrolled)

            self._listbox = Gtk.ListBox()
            self._listbox.set_selection_mode(Gtk.SelectionMode.NONE)
            scrolled.set_child(self._listbox)

            browser_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            browser_box.set_margin_top(8)
            browser_box.set_margin_bottom(4)
            browser_box.set_margin_start(12)
            browser_box.set_margin_end(12)

            browser_label = Gtk.Label(label="Browser command")
            browser_label.set_halign(Gtk.Align.START)
            browser_box.append(browser_label)

            self._browser_entry = Gtk.Entry()
            self._browser_entry.set_text(config.get_browser())
            self._browser_entry.set_placeholder_text("xdg-open")
            self._browser_entry.set_tooltip_text(
                "Command used to open search results, e.g. xdg-open (default), "
                "firefox, google-chrome, or 'flatpak run org.mozilla.firefox'. "
                "Press Enter to apply."
            )
            self._browser_entry.connect("activate", self._on_browser_apply)
            browser_box.append(self._browser_entry)
            root.append(browser_box)

            footer = Gtk.Label(
                label=(
                    "Each enabled provider adds an entry to the GNOME Shell "
                    "search results in the Activities overview.\n"
                    "Changes are saved and applied immediately."
                ),
                wrap=True,
            )
            footer.set_halign(Gtk.Align.START)
            footer.get_style_context().add_class("footer")
            root.append(footer)

            self._populate()

        # ------------------------------------------------------ building

        def _populate(self) -> None:
            enabled = set(self._config.get_enabled_providers())
            for category_id, category_label in CATEGORIES:
                rows = [p for p in PROVIDERS.values() if p.category == category_id]
                if not rows:
                    continue

                header = Gtk.Label(label=category_label)
                header.set_halign(Gtk.Align.START)
                header.get_style_context().add_class("category-header")
                header_row = Gtk.ListBoxRow()
                header_row.set_child(header)
                self._listbox.append(header_row)

                for provider in rows:
                    check = Gtk.CheckButton(label=provider.name)
                    check.set_active(provider.provider_id in enabled)
                    check.connect("toggled", self._on_toggled, provider.provider_id)
                    row = Gtk.ListBoxRow()
                    row.get_style_context().add_class("provider-row")
                    row.set_child(check)
                    self._listbox.append(row)
                    self._checks[provider.provider_id] = check

        def _on_browser_apply(self, entry: Gtk.Entry) -> None:
            self._config.set_browser(entry.get_text().strip())

        # ------------------------------------------------------- actions

        def _on_toggled(self, check: Gtk.CheckButton, provider_id: str) -> None:
            self._config.toggle_provider(provider_id, check.get_active())

        def _set_all(self, enabled: bool) -> None:
            if enabled:
                self._config.set_enabled_providers(list(PROVIDERS.keys()))
            else:
                self._config.set_enabled_providers([])
            for check in self._checks.values():
                check.set_active(enabled)

        def _on_select_all(self, *_args) -> None:
            self._set_all(True)

        def _on_select_none(self, *_args) -> None:
            self._set_all(False)

        def _on_open_search_settings(self, *_args) -> None:
            try:
                subprocess.Popen([_SEARCH_SETTINGS_BIN, "search"])
            except OSError:
                pass

    class ConfigApp(Gtk.Application):
        def __init__(self):
            super().__init__(application_id=_APP_ID)
            self._window: ConfigWindow | None = None
            self._config: ConfigManager | None = None

        def do_startup(self) -> None:
            Gtk.Application.do_startup(self)
            provider = Gtk.CssProvider()
            provider.load_from_string(_CSS)
            Gtk.StyleContext.add_provider_for_display(
                Gdk.Display.get_default(),
                provider,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
            )

        def do_activate(self) -> None:
            if self._config is None:
                self._config = ConfigManager()
            if self._window is None:
                self._window = ConfigWindow(self, self._config)
            self._window.present()

    def main() -> int:
        app = ConfigApp()
        return app.run(sys.argv)


if __name__ == "__main__":
    raise SystemExit(main())