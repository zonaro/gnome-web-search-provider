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
from .providers import CATEGORIES, PROVIDERS


def _print_list(config: ConfigManager) -> None:
    enabled = set(config.get_enabled_providers())
    print(f"Backend: {config.backend}")
    print(f"Browser: {config.get_browser()}")
    print("Providers:")
    for category_id, category_label in CATEGORIES:
        rows = [p for p in PROVIDERS.values() if p.category == category_id]
        if not rows:
            continue
        print(f"  [{category_label}]")
        for provider in rows:
            marker = "*" if provider.provider_id in enabled else " "
            print(f"   {marker} {provider.provider_id:<20} {provider.name}")


def _validate_ids(ids: List[str]) -> None:
    unknown = [pid for pid in ids if pid not in PROVIDERS]
    if unknown:
        print(
            f"Unknown provider(s): {', '.join(unknown)}",
            file=sys.stderr,
        )
        print("Run 'gnome-web-search-provider-cli list' for valid ids.", file=sys.stderr)
        raise SystemExit(1)


def _enable(config: ConfigManager, ids: List[str]) -> int:
    _validate_ids(ids)
    current = config.get_enabled_providers()
    for pid in ids:
        if pid not in current:
            current.append(pid)
    config.set_enabled_providers(current)
    print(f"Enabled: {', '.join(ids)}")
    return 0


def _disable(config: ConfigManager, ids: List[str]) -> int:
    _validate_ids(ids)
    current = config.get_enabled_providers()
    config.set_enabled_providers([pid for pid in current if pid not in ids])
    print(f"Disabled: {', '.join(ids)}")
    return 0


def _set(config: ConfigManager, ids: List[str]) -> int:
    _validate_ids(ids)
    config.set_enabled_providers(ids)
    print(f"Enabled providers set to: {', '.join(ids) if ids else '(none)'}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gnome-web-search-provider-cli",
        description="Configure the GNOME web search provider (no GUI required).",
    )
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("list", help="show providers and their enabled status")
    sub.add_parser("status", help="alias for 'list'")

    p_enable = sub.add_parser("enable", help="enable one or more providers")
    p_enable.add_argument("ids", nargs="+", metavar="ID")

    p_disable = sub.add_parser("disable", help="disable one or more providers")
    p_disable.add_argument("ids", nargs="+", metavar="ID")

    p_set = sub.add_parser("set", help="replace the enabled providers list")
    p_set.add_argument("ids", nargs="*", metavar="ID")

    p_browser = sub.add_parser("browser", help="get or set the browser command")
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
            print(f"Browser set to: {args.value}")
        return 0

    parser.error(f"unknown command: {command}")
    return 2  # pragma: no cover - argparse exits before this


if __name__ == "__main__":
    raise SystemExit(main())