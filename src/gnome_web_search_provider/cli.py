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
    gnome-web-search-provider-cli custom list
    gnome-web-search-provider-cli custom add --name "Meu Site" --url "https://exemplo.com/busca?q={query}"
    gnome-web-search-provider-cli custom remove custom-meu-site
"""

import argparse
import sys
from typing import List, Optional

from .config import ConfigManager
from .providers import CATEGORIES, PROVIDERS, all_providers, get_category_label

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


def _known_providers(config: ConfigManager):
    try:
        customs = config.get_custom_providers()
    except Exception:
        customs = []
    return all_providers(customs)


def _print_list(config: ConfigManager) -> None:
    known = _known_providers(config)
    enabled = set(config.get_enabled_providers())
    print(f"{tr('cli_backend')}: {config.backend}")
    print(f"{tr('cli_browser_label')}: {config.get_browser()}")
    print(f"{tr('cli_providers_label')}:")
    for category_id, category_label in CATEGORIES:
        rows = [p for p in known.values() if p.category == category_id]
        if not rows:
            continue
        print(f"  [{_category_label(category_id, category_label)}]")
        for provider in rows:
            marker = "*" if provider.provider_id in enabled else " "
            print(f"   {marker} {provider.provider_id:<20} {provider.name}")


def _validate_ids(config: ConfigManager, ids: List[str]) -> None:
    known = _known_providers(config)
    unknown = [pid for pid in ids if pid not in known]
    if unknown:
        print(
            tr("cli_unknown_providers", ids=", ".join(unknown)),
            file=sys.stderr,
        )
        print(tr("cli_run_list_hint"), file=sys.stderr)
        raise SystemExit(1)


def _enable(config: ConfigManager, ids: List[str]) -> int:
    _validate_ids(config, ids)
    current = config.get_enabled_providers()
    for pid in ids:
        if pid not in current:
            current.append(pid)
    config.set_enabled_providers(current)
    print(tr("cli_enabled", ids=", ".join(ids)))
    return 0


def _disable(config: ConfigManager, ids: List[str]) -> int:
    _validate_ids(config, ids)
    current = config.get_enabled_providers()
    config.set_enabled_providers([pid for pid in current if pid not in ids])
    print(tr("cli_disabled", ids=", ".join(ids)))
    return 0


def _set(config: ConfigManager, ids: List[str]) -> int:
    _validate_ids(config, ids)
    config.set_enabled_providers(ids)
    print(tr("cli_set_to", ids=", ".join(ids) if ids else tr("cli_set_to_none")))
    return 0


def _custom_list(config: ConfigManager) -> int:
    customs = config.get_custom_providers()
    if not customs:
        print(tr("cli_custom_empty"))
        return 0
    enabled = set(config.get_enabled_providers())
    for item in customs:
        pid = str(item.get("id", ""))
        marker = "*" if pid in enabled else " "
        print(f" {marker} {pid:<24} {item.get('name', '')}  {item.get('url', '')}")
    return 0


def _custom_add(config: ConfigManager, args) -> int:
    query_in_path = None
    if args.path_encoding:
        query_in_path = True
    elif args.query_encoding:
        query_in_path = False
    try:
        entry = config.add_custom_provider(
            name=args.name,
            url=args.url,
            icon=args.icon or "",
            query_in_path=query_in_path,
        )
    except ValueError as exc:
        detail = str(exc)
        if "name" in detail:
            print(tr("cli_custom_bad_name"), file=sys.stderr)
        elif "icon" in detail:
            print(tr("cli_custom_bad_icon"), file=sys.stderr)
        else:
            print(tr("cli_custom_bad_url"), file=sys.stderr)
        return 1
    print(tr("cli_custom_added", id=entry["id"], name=entry["name"]))
    return 0


def _custom_remove(config: ConfigManager, ids: List[str]) -> int:
    missing = []
    for pid in ids:
        if not config.remove_custom_provider(pid):
            missing.append(pid)
    if missing:
        print(tr("cli_custom_not_found", ids=", ".join(missing)), file=sys.stderr)
        return 1
    print(tr("cli_custom_removed", ids=", ".join(ids)))
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

    p_custom = sub.add_parser("custom", help=tr("cli_custom_help"))
    custom_sub = p_custom.add_subparsers(dest="custom_command")

    custom_sub.add_parser("list", help=tr("cli_custom_list_help"))

    p_add = custom_sub.add_parser("add", help=tr("cli_custom_add_help"))
    p_add.add_argument("--name", required=True, help=tr("cli_custom_name_help"))
    p_add.add_argument("--url", required=True, help=tr("cli_custom_url_help"))
    p_add.add_argument("--icon", default="", help=tr("cli_custom_icon_help"))
    enc = p_add.add_mutually_exclusive_group()
    enc.add_argument("--path", dest="path_encoding", action="store_true", help=tr("cli_custom_path_help"))
    enc.add_argument("--query", dest="query_encoding", action="store_true", help=tr("cli_custom_query_help"))

    p_rm = custom_sub.add_parser("remove", help=tr("cli_custom_remove_help"))
    p_rm.add_argument("ids", nargs="+", metavar="ID")

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
    if command == "custom":
        custom_command = getattr(args, "custom_command", None)
        if custom_command in (None, "list"):
            return _custom_list(config)
        if custom_command == "add":
            return _custom_add(config, args)
        if custom_command == "remove":
            return _custom_remove(config, args.ids)

    parser.error(f"unknown command: {command}")
    return 2  # pragma: no cover - argparse exits before this


if __name__ == "__main__":
    raise SystemExit(main())