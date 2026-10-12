from __future__ import annotations

import logging
from typing import Any

from anyagent.config.agents import AgentPack
from anyagent.agent_runtime.middleware import MiddlewareChain, MiddlewareLoadError, load_middleware_from_classpath
from anyagent.agent_runtime.middlewares import ContextCompactionMiddleware, LoopDetectionMiddleware


_LOGGER = logging.getLogger(__name__)

_BUILTIN_MIDDLEWARE_ALIASES = {
    "loop_detection": "loop_detection",
    "loopdetectionmiddleware": "loop_detection",
    "context_compaction": "context_compaction",
    "contextcompactionmiddleware": "context_compaction",
    "compaction": "context_compaction",
}


def _build_agent_middleware_chain(pack: AgentPack) -> MiddlewareChain | None:
    configured_order = [item.strip() for item in (pack.spec.runtime.middlewares or []) if isinstance(item, str) and item.strip()]
    order = configured_order or ["loop_detection", "context_compaction"]
    middlewares: list[Any] = []
    loop_cfg = pack.spec.runtime.loop_detection
    compaction_cfg = pack.spec.runtime.context_compaction

    def _append(name: str) -> None:
        normalized = name.rsplit(":", 1)[-1].rsplit(".", 1)[-1].lower().replace("-", "_")
        builtin = _BUILTIN_MIDDLEWARE_ALIASES.get(normalized)
        if builtin == "loop_detection" and loop_cfg.enabled:
            middlewares.append(
                LoopDetectionMiddleware(
                    window_size=loop_cfg.window_size,
                    warn_threshold=loop_cfg.warn_threshold,
                    hard_limit=loop_cfg.hard_limit,
                )
            )
            return
        if builtin == "context_compaction" and compaction_cfg.enabled:
            middlewares.append(
                ContextCompactionMiddleware(
                    max_context_tokens=compaction_cfg.max_context_tokens,
                    trigger_ratio=compaction_cfg.trigger_ratio,
                    keep_recent_tokens=compaction_cfg.keep_recent_tokens,
                )
            )
            return
        if builtin is not None:
            return
        try:
            middlewares.append(load_middleware_from_classpath(name))
        except MiddlewareLoadError as e:
            _LOGGER.warning("skipping middleware %r for agent %r: %s", name, pack.agent_id, e)

    for name in order:
        _append(name)
    if not configured_order and loop_cfg.enabled and not any(isinstance(m, LoopDetectionMiddleware) for m in middlewares):
        middlewares.append(
            LoopDetectionMiddleware(
                window_size=loop_cfg.window_size,
                warn_threshold=loop_cfg.warn_threshold,
                hard_limit=loop_cfg.hard_limit,
            )
        )
    if not configured_order and compaction_cfg.enabled and not any(isinstance(m, ContextCompactionMiddleware) for m in middlewares):
        middlewares.append(
            ContextCompactionMiddleware(
                max_context_tokens=compaction_cfg.max_context_tokens,
                trigger_ratio=compaction_cfg.trigger_ratio,
                keep_recent_tokens=compaction_cfg.keep_recent_tokens,
            )
        )
    return MiddlewareChain(middlewares) if middlewares else None
