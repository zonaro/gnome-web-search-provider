#!/usr/bin/env python3
"""GTK4 preferences window to enable/disable web search providers.

Providers are shown as an icon grid grouped by category: each card shows
the provider icon, its name and a switch underneath. The browser command
used to open results can be customized at the top. Changes are written
immediately to the shared configuration (GSettings or the JSON fallback),
so the running search provider picks them up on the next search.

This window is the optional GUI part; PyGObject/GTK4 are only needed here,
not for the provider daemon. Without them, use ``gnome-web-search-provider-cli``.

Run directly, or launch via the installed desktop entry::

    gnome-web-search-provider-config
"""

import subprocess
import sys
import threading

try:
    import gi

    gi.require_version("Gtk", "4.0")
    gi.require_version("Gdk", "4.0")

    from gi.repository import Gdk, Gio, GLib, Gtk  # noqa: E402

    try:
        gi.require_version("Adw", "1")
        from gi.repository import Adw  # noqa: E402

        _HAS_ADW = True
    except Exception:
        Adw = None  # type: ignore[assignment]
        _HAS_ADW = False
except Exception:  # pragma: no cover - depends on optional PyGObject
    Gdk = None
    Gio = None
    GLib = None
    Gtk = None
    Adw = None
    _HAS_ADW = False

from . import favicons as _favicons  # noqa: E402
from .config import ConfigManager  # noqa: E402
from .providers import CATEGORIES, PROVIDERS, fallback_icon_name, get_category_label  # noqa: E402

try:
    from .i18n import tr  # noqa: E402
except Exception:  # pragma: no cover - GUI must open even without i18n

    def tr(key: str, lang=None, **kwargs: object) -> str:  # type: ignore[no-redef]
        try:
            return str(key.format(**kwargs)) if kwargs else str(key)
        except Exception:
            return str(key)

_APP_ID = "org.gnome.WebSearch.SearchProviderConfig"

# Theme-aware CSS only: no hardcoded background/foreground colors, so both
# Adwaita light and dark variants render correctly. `.card` already ships
# light/dark styles; we only add spacing and a dimmed state for disabled
# providers using `currentColor` alpha.
_CSS = """
.category-header {
    font-weight: bold;
    padding: 14px 12px 2px 12px;
    color: alpha(currentColor, 0.85);
}
.provider-card {
    padding: 12px 8px 10px 8px;
}
.provider-card.disabled .provider-icon,
.provider-card.disabled .provider-name {
    opacity: 0.55;
}
.provider-name {
    font-size: 0.95em;
}
.provider-icon {
    border-radius: 10px;
}
.footer {
    padding: 8px 12px;
    color: alpha(currentColor, 0.75);
}
.flat-button {
    background: transparent;
    box-shadow: none;
}
.flat-button:hover {
    background: alpha(currentColor, 0.07);
}
"""

_SEARCH_SETTINGS_BIN = "gnome-control-center"

def _icon_for(provider) -> str:
    """Return a themed icon name for ``provider`` (always theme-aware)."""
    return fallback_icon_name(provider.provider_id)


def _apply_gtk_dark_mode() -> None:
    """Mirror the GNOME `color-scheme` setting into pure-GTK apps.

    Plain GTK4 (without libadwaita) does not follow
    ``org.gnome.desktop.interface color-scheme`` on its own and stays on
    the light variant. Copy the desktop preference into
    ``gtk-application-prefer-dark-theme`` so the window respects dark mode.
    No-op when Adw handles theming.
    """
    if _HAS_ADW or Gtk is None or Gio is None:
        return
    try:
        gtk_settings = Gtk.Settings.get_default()
        if gtk_settings is None:
            return
        try:
            iface = Gio.Settings.new("org.gnome.desktop.interface")
            prefer_dark = iface.get_string("color-scheme") == "prefer-dark"
        except Exception:
            prefer_dark = False
        gtk_settings.set_property("gtk-application-prefer-dark-theme", prefer_dark)
    except Exception:
        pass


_NO_GTK_MESSAGE = tr("no_gtk_message")


if Gtk is None:  # pragma: no cover - depends on optional PyGObject

    def main() -> int:
        print(_NO_GTK_MESSAGE, file=sys.stderr)
        return 1


else:

    class ConfigWindow(Gtk.ApplicationWindow):
        def __init__(self, application: Gtk.Application, config: ConfigManager):
            super().__init__(application=application)
            self._config = config
            self._switches: dict = {}
            self._images: dict = {}
            self._cards: list = []  # (provider_id, card, name_lower)
            self._sections: list = []  # (category_id, header, flowbox)
            self._updating = False
            self._favicons_started = False

            self.set_title(tr("window_title"))
            self.set_default_size(680, 640)

            toolbar = Gtk.HeaderBar()
            self.set_titlebar(toolbar)

            select_all = Gtk.Button(label=tr("btn_all"))
            select_all.set_tooltip_text(tr("btn_all_tooltip"))
            select_all.connect("clicked", self._on_select_all)
            toolbar.pack_start(select_all)

            select_none = Gtk.Button(label=tr("btn_none"))
            select_none.set_tooltip_text(tr("btn_none_tooltip"))
            select_none.connect("clicked", self._on_select_none)
            toolbar.pack_start(select_none)

            search_settings = Gtk.Button(label=tr("btn_search_settings"))
            search_settings.connect("clicked", self._on_open_search_settings)
            toolbar.pack_end(search_settings)

            root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
            self.set_child(root)

            # Search filter for the 49-provider grid.
            search_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            search_row.set_margin_top(8)
            search_row.set_margin_start(12)
            search_row.set_margin_end(12)
            self._search_entry = Gtk.SearchEntry()
            self._search_entry.set_placeholder_text(tr("search_placeholder"))
            self._search_entry.set_hexpand(True)
            self._search_entry.connect("search-changed", self._on_search_changed)
            search_row.append(self._search_entry)

            refresh_icons = Gtk.Button.new_from_icon_name("view-refresh-symbolic")
            refresh_icons.set_tooltip_text(tr("refresh_tooltip"))
            refresh_icons.connect("clicked", self._on_refresh_icons)
            search_row.append(refresh_icons)
            root.append(search_row)

            scrolled = Gtk.ScrolledWindow()
            scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
            scrolled.set_vexpand(True)
            root.append(scrolled)

            main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
            main_box.set_margin_bottom(8)
            scrolled.set_child(main_box)
            self._main_box = main_box

            browser_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            browser_box.set_margin_top(8)
            browser_box.set_margin_bottom(4)
            browser_box.set_margin_start(12)
            browser_box.set_margin_end(12)

            browser_label = Gtk.Label(label=tr("browser_label"))
            browser_label.set_halign(Gtk.Align.START)
            browser_box.append(browser_label)

            self._browser_entry = Gtk.Entry()
            self._browser_entry.set_text(config.get_browser())
            self._browser_entry.set_placeholder_text(tr("browser_placeholder"))
            self._browser_entry.set_hexpand(True)
            self._browser_entry.set_tooltip_text(tr("browser_tooltip"))
            self._browser_entry.connect("activate", self._on_browser_apply)
            browser_box.append(self._browser_entry)
            root.append(browser_box)

            footer = Gtk.Label(
                label=tr("footer_text"),
                wrap=True,
            )
            footer.set_halign(Gtk.Align.START)
            footer.get_style_context().add_class("footer")
            root.append(footer)

            self._populate()
            self._refresh_favicons(force=False)

        # ------------------------------------------------------ building

        def _populate(self) -> None:
            enabled = set(self._config.get_enabled_providers())
            for category_id, category_label in CATEGORIES:
                rows = [p for p in PROVIDERS.values() if p.category == category_id]
                if not rows:
                    continue

                header = Gtk.Label(label=get_category_label(category_id) or category_label)
                header.set_halign(Gtk.Align.START)
                header.get_style_context().add_class("category-header")
                self._main_box.append(header)

                flow = Gtk.FlowBox()
                flow.set_selection_mode(Gtk.SelectionMode.NONE)
                flow.set_homogeneous(True)
                flow.set_column_spacing(12)
                flow.set_row_spacing(12)
                flow.set_margin_start(12)
                flow.set_margin_end(12)
                flow.set_margin_top(4)
                flow.set_margin_bottom(4)
                flow.set_min_children_per_line(2)
                flow.set_max_children_per_line(6)
                self._main_box.append(flow)

                self._sections.append((category_id, header, flow))

                for provider in rows:
                    card = self._build_card(provider, provider.provider_id in enabled)
                    flow.append(card)

        def _build_card(self, provider, active: bool) -> Gtk.Widget:
            card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            card.get_style_context().add_class("card")
            card.get_style_context().add_class("provider-card")
            card.set_size_request(140, 0)

            # Icon + name inside a flat button so the whole upper area is
            # clickable (keyboard accessible too); the switch below toggles.
            press = Gtk.Button()
            press.get_style_context().add_class("flat")
            press.get_style_context().add_class("flat-button")
            press.set_tooltip_text(tr("toggle_tooltip", name=provider.name))
            inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            press.set_child(inner)

            icon = Gtk.Image.new_from_icon_name(_icon_for(provider))
            icon.set_pixel_size(48)
            icon.set_halign(Gtk.Align.CENTER)
            icon.get_style_context().add_class("provider-icon")
            inner.append(icon)
            self._images[provider.provider_id] = icon
            try:
                cached = _favicons.cached_icon_path(provider.provider_id)
            except Exception:
                cached = None
            if cached:
                self._apply_favicon_image(icon, cached)

            name = Gtk.Label(label=provider.name)
            name.set_wrap(True)
            name.set_lines(2)
            name.set_justify(Gtk.Justification.CENTER)
            name.set_halign(Gtk.Align.CENTER)
            name.set_ellipsize(3)  # Pango.EllipsizeMode.END without importing Pango
            name.get_style_context().add_class("provider-name")
            inner.append(name)

            card.append(press)

            switch = Gtk.Switch()
            switch.set_halign(Gtk.Align.CENTER)
            switch.set_valign(Gtk.Align.CENTER)
            switch.set_tooltip_text(tr("switch_tooltip", name=provider.name))
            switch.set_active(active)
            card.append(switch)

            self._switches[provider.provider_id] = switch
            self._cards.append((provider.provider_id, card, provider.name.lower()))
            self._update_card_style(card, active)

            switch.connect("notify::active", self._on_switch_toggled, provider.provider_id, card)
            press.connect("clicked", self._on_card_pressed, provider.provider_id)
            return card

        @staticmethod
        def _update_card_style(card: Gtk.Widget, active: bool) -> None:
            ctx = card.get_style_context()
            if active:
                ctx.remove_class("disabled")
            elif not ctx.has_class("disabled"):
                ctx.add_class("disabled")

        @staticmethod
        def _apply_favicon_image(image: Gtk.Image, path: str) -> None:
            try:
                from gi.repository import GdkPixbuf

                if GdkPixbuf.Pixbuf.new_from_file(path) is None:
                    return
            except Exception:
                try:
                    image.set_from_file(path)
                except Exception:
                    return
                return
            try:
                image.set_from_file(path)
            except Exception:
                pass

        def _refresh_favicons(self, force: bool = False) -> None:
            if self._favicons_started and not force:
                return
            self._favicons_started = True

            def _work():
                try:
                    results = _favicons.ensure_favicons(
                        {pid: p.url for pid, p in PROVIDERS.items()},
                        force=force,
                    )
                except Exception:
                    return
                if GLib is None:
                    return
                GLib.idle_add(self._apply_favicon_results, results)

            threading.Thread(target=_work, name="favicon-fetch", daemon=True).start()

        def _apply_favicon_results(self, results: dict) -> bool:
            for provider_id, path in results.items():
                if not path:
                    continue
                image = self._images.get(provider_id)
                if image is not None:
                    self._apply_favicon_image(image, path)
            return False

        def _on_refresh_icons(self, _button: Gtk.Button) -> None:
            self._refresh_favicons(force=True)

        def _on_browser_apply(self, entry: Gtk.Entry) -> None:
            self._config.set_browser(entry.get_text().strip())

        # ------------------------------------------------------- actions

        def _on_switch_toggled(self, switch: Gtk.Switch, _pspec, provider_id: str, card: Gtk.Widget) -> None:
            if self._updating:
                return
            active = switch.get_active()
            self._config.toggle_provider(provider_id, active)
            self._update_card_style(card, active)

        def _on_card_pressed(self, _button: Gtk.Button, provider_id: str) -> None:
            switch = self._switches.get(provider_id)
            if switch is not None:
                switch.set_active(not switch.get_active())

        def _on_search_changed(self, entry: Gtk.SearchEntry) -> None:
            query = entry.get_text().strip().lower()
            visible_per_flow: dict = {}
            for provider_id, card, name_lower in self._cards:
                visible = not query or query in name_lower or query in provider_id
                card.set_visible(visible)
                # FlowBox wraps each child in a FlowBoxChild; hide that too.
                parent = card.get_parent()
                if parent is not None:
                    parent.set_visible(visible)
                    flow = parent.get_parent()
                    if flow is not None:
                        visible_per_flow.setdefault(flow, False)
                        if visible:
                            visible_per_flow[flow] = True
            for _cat_id, header, flow in self._sections:
                any_visible = visible_per_flow.get(flow, False)
                header.set_visible(any_visible)
                flow.set_visible(any_visible)

        def _set_all(self, enabled: bool) -> None:
            if enabled:
                self._config.set_enabled_providers(list(PROVIDERS.keys()))
            else:
                self._config.set_enabled_providers([])
            self._updating = True
            try:
                for provider_id, switch in self._switches.items():
                    switch.set_active(enabled)
                    parent = switch.get_parent()
                    if parent is not None:
                        self._update_card_style(parent, enabled)
            finally:
                self._updating = False

        def _on_select_all(self, *_args) -> None:
            self._set_all(True)

        def _on_select_none(self, *_args) -> None:
            self._set_all(False)

        def _on_open_search_settings(self, *_args) -> None:
            try:
                subprocess.Popen([_SEARCH_SETTINGS_BIN, "search"])
            except OSError:
                pass

    _BaseApp = Adw.Application if _HAS_ADW else Gtk.Application

    class ConfigApp(_BaseApp):
        def __init__(self):
            super().__init__(application_id=_APP_ID)
            self._window: ConfigWindow | None = None
            self._config: ConfigManager | None = None

        def do_startup(self) -> None:
            # libadwaita apps follow the system color-scheme automatically;
            # pin the style manager to PREFER so dark mode is always honored.
            if _HAS_ADW:
                try:
                    Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.PREFER)
                except Exception:
                    pass
            _BaseApp.do_startup(self)
            provider = Gtk.CssProvider()
            provider.load_from_string(_CSS)
            Gtk.StyleContext.add_provider_for_display(
                Gdk.Display.get_default(),
                provider,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
            )
            if not _HAS_ADW:
                _apply_gtk_dark_mode()
                # Keep following the desktop if the user flips light/dark
                # while the window is open.
                try:
                    iface = Gio.Settings.new("org.gnome.desktop.interface")
                    iface.connect(
                        "changed::color-scheme", lambda *_a: _apply_gtk_dark_mode()
                    )
                    self._iface_settings = iface  # keep a reference alive
                except Exception:
                    pass

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
