#!/usr/bin/env python3
"""Command-line configuration for the GNOME web search provider.

Pure standard library (no PyGObject/GTK needed), so providers can be
configured from a terminal or script even on minimal systems.

Examples::

    gnome-web-search-provider-cli list
    gnome-web-search-provider-cli enable bing duckduckgo
    gnome-web-search-provider-cli disable bing
    gnome-web-search-provider-cli set google brave startpage
    gnome-web-search-provider-cli browser              # print current
    gnome-web-search-provider-cli browser firefox      # set browser
"""

import argparse
import sys
from typing import List, Optional

from .config import ConfigManager
from .providers import CATEGORIES, PROVIDERS, get_category_label

try:
    from .i18n import tr
except Exception:  # pragma: no cover - i18n must never break the CLI

    def tr(key: str, lang=None, **kwargs: object) -> str:  # type: ignore[no-redef]
        try:
            return str(key.format(**kwargs)) if kwargs else str(key)
        except Exception:
            return str(key)


def _category_label(category_id: str, fallback: str) -> str:
    label = get_category_label(category_id)
    return label if label else fallback


def _print_list(config: ConfigManager) -> None:
    enabled = set(config.get_enabled_providers())
    print(f"{tr('cli_backend')}: {config.backend}")
    print(f"{tr('cli_browser_label')}: {config.get_browser()}")
    print(f"{tr('cli_providers_label')}:")
    for category_id, category_label in CATEGORIES:
        rows = [p for p in PROVIDERS.values() if p.category == category_id]
        if not rows:
            continue
        print(f"  [{_category_label(category_id, category_label)}]")
        for provider in rows:
            marker = "*" if provider.provider_id in enabled else " "
            print(f"   {marker} {provider.provider_id:<20} {provider.name}")


def _validate_ids(ids: List[str]) -> None:
    unknown = [pid for pid in ids if pid not in PROVIDERS]
    if unknown:
        print(
            tr("cli_unknown_providers", ids=", ".join(unknown)),
            file=sys.stderr,
        )
        print(tr("cli_run_list_hint"), file=sys.stderr)
        raise SystemExit(1)


def _enable(config: ConfigManager, ids: List[str]) -> int:
    _validate_ids(ids)
    current = config.get_enabled_providers()
    for pid in ids:
        if pid not in current:
            current.append(pid)
    config.set_enabled_providers(current)
    print(tr("cli_enabled", ids=", ".join(ids)))
    return 0


def _disable(config: ConfigManager, ids: List[str]) -> int:
    _validate_ids(ids)
    current = config.get_enabled_providers()
    config.set_enabled_providers([pid for pid in current if pid not in ids])
    print(tr("cli_disabled", ids=", ".join(ids)))
    return 0


def _set(config: ConfigManager, ids: List[str]) -> int:
    _validate_ids(ids)
    config.set_enabled_providers(ids)
    print(tr("cli_set_to", ids=", ".join(ids) if ids else tr("cli_set_to_none")))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gnome-web-search-provider-cli",
        description=tr("cli_description"),
    )
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("list", help=tr("cli_list_help"))
    sub.add_parser("status", help=tr("cli_status_help"))

    p_enable = sub.add_parser("enable", help=tr("cli_enable_help"))
    p_enable.add_argument("ids", nargs="+", metavar="ID")

    p_disable = sub.add_parser("disable", help=tr("cli_disable_help"))
    p_disable.add_argument("ids", nargs="+", metavar="ID")

    p_set = sub.add_parser("set", help=tr("cli_set_help"))
    p_set.add_argument("ids", nargs="*", metavar="ID")

    p_browser = sub.add_parser("browser", help=tr("cli_browser_help"))
    p_browser.add_argument("value", nargs="?", metavar="CMD")

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    config = ConfigManager()

    command = args.command
    if command in (None, "list", "status"):
        _print_list(config)
        return 0
    if command == "enable":
        return _enable(config, args.ids)
    if command == "disable":
        return _disable(config, args.ids)
    if command == "set":
        return _set(config, args.ids)
    if command == "browser":
        if args.value is None:
            print(config.get_browser())
        else:
            config.set_browser(args.value)
            print(tr("cli_browser_set_to", value=args.value))
        return 0

    parser.error(f"unknown command: {command}")
    return 2  # pragma: no cover - argparse exits before this


if __name__ == "__main__":
    raise SystemExit(main())