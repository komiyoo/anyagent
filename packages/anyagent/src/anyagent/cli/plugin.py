"""`anyagent plugin` commands against the Admin API."""

from __future__ import annotations

import json
from typing import Any

from anyagent.cli.admin_client import admin_client_from_args, add_admin_flags


def register_plugin(subparsers: Any, bind: Any) -> None:
    """Register plugin inspection commands."""

    plugin = subparsers.add_parser("plugin", help="Inspect Tool Runtime plugins via the Admin API.")
    add_admin_flags(plugin)
    plugin_sub = plugin.add_subparsers(dest="plugin_command", required=True)
    catalog = plugin_sub.add_parser("catalog", help="List loaded plugins, registered tools, and cite refs.")
    add_admin_flags(catalog)
    catalog.add_argument("--json", action="store_true", help="Print JSON (default).")
    bind(catalog, ("plugin", "catalog"), cmd_plugin_catalog)


def cmd_plugin_catalog(args: Any) -> int:
    client = admin_client_from_args(args)
    print(json.dumps(client.plugin_catalog().model_dump(exclude_none=True), ensure_ascii=False))
    return 0
