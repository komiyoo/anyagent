from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest

from anyagent.agent_runtime.middleware import (
    MiddlewareLoadError,
    load_middleware_from_classpath,
)


def _write_module(tmp_path: Path, name: str, body: str) -> None:
    (tmp_path / f"{name}.py").write_text(textwrap.dedent(body), encoding="utf-8")


def test_loads_builtin_middleware_class() -> None:
    mw = load_middleware_from_classpath(
        "anyagent.agent_runtime.middlewares.loop_detection:LoopDetectionMiddleware"
    )
    from anyagent.agent_runtime.middlewares import LoopDetectionMiddleware

    assert isinstance(mw, LoopDetectionMiddleware)


def test_loads_custom_middleware_subclass(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_module(
        tmp_path,
        "custom_mw",
        """
        from anyagent.agent_runtime.middleware import BaseMiddleware

        class AuditMiddleware(BaseMiddleware):
            pass
        """,
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    sys.modules.pop("custom_mw", None)

    mw = load_middleware_from_classpath("custom_mw:AuditMiddleware")
    assert mw.__class__.__name__ == "AuditMiddleware"


def test_loads_duck_typed_middleware(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_module(
        tmp_path,
        "duck_mw",
        """
        class DuckMiddleware:
            async def before_model_call(self, context, body):
                return None
            async def after_model_call(self, context, response, calls):
                return None
            async def before_tool_execute(self, context, call):
                return None
            async def after_tool_execute(self, context, call, result):
                return None
        """,
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    sys.modules.pop("duck_mw", None)

    mw = load_middleware_from_classpath("duck_mw:DuckMiddleware")
    assert mw.__class__.__name__ == "DuckMiddleware"


def test_passes_kwargs_to_constructor() -> None:
    mw = load_middleware_from_classpath(
        "anyagent.agent_runtime.middlewares.loop_detection:LoopDetectionMiddleware",
        kwargs={"window_size": 7, "hard_limit": 9},
    )
    assert mw.window_size == 7  # type: ignore[attr-defined]
    assert mw.hard_limit == 9  # type: ignore[attr-defined]


@pytest.mark.parametrize("bad", ["NoColon", ":Missing", "mod:", "mod:1Class"])
def test_rejects_malformed_classpath(bad: str) -> None:
    with pytest.raises(MiddlewareLoadError, match="invalid middleware classpath"):
        load_middleware_from_classpath(bad)


def test_rejects_missing_module() -> None:
    with pytest.raises(MiddlewareLoadError, match="cannot import middleware module"):
        load_middleware_from_classpath("anyagent_no_such_module_xyz:Thing")


def test_rejects_missing_attribute() -> None:
    with pytest.raises(MiddlewareLoadError, match="not found in module"):
        load_middleware_from_classpath(
            "anyagent.agent_runtime.middlewares.loop_detection:NoSuchClass"
        )


def test_rejects_non_class_target(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_module(tmp_path, "not_a_class", "value = 123\n")
    monkeypatch.syspath_prepend(str(tmp_path))
    sys.modules.pop("not_a_class", None)

    with pytest.raises(MiddlewareLoadError, match="is not a class"):
        load_middleware_from_classpath("not_a_class:value")


def test_rejects_class_missing_middleware_hooks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_module(
        tmp_path,
        "incomplete_mw",
        """
        class NotAMiddleware:
            async def before_model_call(self, context, body):
                return None
        """,
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    sys.modules.pop("incomplete_mw", None)

    with pytest.raises(MiddlewareLoadError, match="does not implement the AgentMiddleware hooks"):
        load_middleware_from_classpath("incomplete_mw:NotAMiddleware")
