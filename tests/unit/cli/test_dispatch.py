from __future__ import annotations

import re
from pathlib import Path

import pytest

from anyagent.cli import main
from anyagent.cli.main import build_parser

_REPO_ROOT = Path(__file__).resolve().parents[3]


def _help_flags(argv: list[str], capsys: pytest.CaptureFixture[str]) -> set[str]:
    with pytest.raises(SystemExit) as caught:
        main(argv)
    assert caught.value.code == 0
    text = capsys.readouterr().out
    return set(re.findall(r"--[a-z0-9][a-z0-9-]*", text))


def test_dispatch_table_has_no_elif_chain() -> None:
    source = (_REPO_ROOT / "packages/anyagent/src/anyagent/cli/main.py").read_text(encoding="utf-8")
    assert "elif " not in source
    _parser, commands = build_parser()
    assert commands[("serve",)] is commands[("dev",)]
    assert ("storage-health",) not in commands
    assert ("storage-migrate",) not in commands
    assert ("storage-replay",) not in commands
    assert ("storage-retention",) not in commands
    assert ("config", "init") not in commands
    assert ("storage", "health") in commands
    assert ("db", "migrate") in commands
    assert ("init",) in commands
    assert ("add", "tool") in commands
    assert ("config", "show") in commands
    assert ("config", "schema") in commands


def test_serve_and_dev_share_flags(capsys: pytest.CaptureFixture[str]) -> None:
    assert _help_flags(["serve", "--help"], capsys) == _help_flags(["dev", "--help"], capsys)


@pytest.mark.parametrize(
    "argv",
    [
        ["storage-health"],
        ["storage-migrate"],
        ["storage-replay"],
        ["storage-retention"],
        ["config", "init"],
    ],
)
def test_removed_commands_are_rejected(argv: list[str]) -> None:
    with pytest.raises(SystemExit):
        main(argv)
