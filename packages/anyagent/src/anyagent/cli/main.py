"""Parser assembly and the command dispatch table."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from typing import Any

from anyagent.cli.credential import register_credential
from anyagent.cli.plugin import register_plugin
from anyagent.cli.serve import register_serve
from anyagent.cli.services import register_services
from anyagent.cli.storage import register_storage
from anyagent.cli.workspace import register_workspace

Handler = Callable[[argparse.Namespace], int]
CommandPath = tuple[str, ...]


def build_parser() -> tuple[argparse.ArgumentParser, dict[CommandPath, Handler]]:
    """Build the CLI parser and the path-to-handler table."""

    parser = argparse.ArgumentParser(prog="anyagent")
    parser.set_defaults(command_path=())
    subparsers = parser.add_subparsers(dest="command", required=True)
    commands: dict[CommandPath, Handler] = {}

    def bind(target: argparse.ArgumentParser, path: CommandPath, handler: Handler) -> argparse.ArgumentParser:
        target.set_defaults(command_path=path)
        commands[path] = handler
        return target

    register_workspace(subparsers, bind)
    register_serve(subparsers, bind)
    register_services(subparsers, bind)
    register_storage(subparsers, bind)
    register_credential(subparsers, bind)
    register_plugin(subparsers, bind)
    return parser, commands


def main(argv: list[str] | None = None) -> int:
    """Parse ``argv`` and dispatch through the command table."""

    parser, commands = build_parser()
    args = parser.parse_args(argv)
    path = tuple(getattr(args, "command_path", ()) or ())
    try:
        handler: Any = commands[path]
    except KeyError:
        parser.error("unsupported command")
    return int(handler(args))
