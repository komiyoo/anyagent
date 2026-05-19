from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass
from typing import Any, TypeVar

from fastapi.responses import Response

from anyagent.gateway.sequencer import KeyedSequencer
from anyagent.storage import StorageRuntime

from .responses_optional import openai_error_response

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class DistributedSessionSerializationConfig:
    enable_keyed_serialization: bool = True
    lease_ttl_ms: int = 30_000
    lease_wait_timeout_ms: int = 30_000
    renew_interval_s: float = 10.0


def should_skip_external_session_lease(
    *,
    stream: bool,
    idempotency_key: str | None,
    idem_created: bool,
    idem_response_id: str | None,
) -> bool:
    return bool(
        stream
        and idempotency_key is not None
        and idem_created
        and isinstance(idem_response_id, str)
        and idem_response_id
    )


async def run_with_storage_session_lease(
    *,
    storage: StorageRuntime,
    session_partition_key: str,
    owner: str,
    fn: Callable[[], Awaitable[T]],
    config: DistributedSessionSerializationConfig | None = None,
) -> T:
    cfg = config or DistributedSessionSerializationConfig()
    if getattr(storage, "mode", "none") != "external":
        return await fn()

    handle = await storage.lease_lock.acquire(
        key=session_partition_key,
        owner=owner,
        ttl_ms=cfg.lease_ttl_ms,
        wait_timeout_ms=cfg.lease_wait_timeout_ms,
    )
    if handle is None:
        raise RuntimeError("lease_lock_unavailable")

    renew_task: asyncio.Task[object] | None = None

    async def _renew_loop() -> None:
        while True:
            await asyncio.sleep(cfg.renew_interval_s)
            ok = await storage.lease_lock.renew(
                key=session_partition_key,
                owner=owner,
                ttl_ms=cfg.lease_ttl_ms,
            )
            if not ok:
                raise RuntimeError("lease_lock_lost")

    try:
        renew_task = asyncio.create_task(_renew_loop())
        return await fn()
    finally:
        if renew_task is not None:
            renew_task.cancel()
            with suppress(asyncio.CancelledError):
                await renew_task
        await storage.lease_lock.release(key=session_partition_key, owner=owner)


async def run_distributed_response_with_session_serialization(
    *,
    storage: StorageRuntime,
    session_partition_key: str,
    owner: str,
    stream: bool,
    idempotency_key: str | None,
    idem_created: bool,
    idem_response_id: str | None,
    sequencer: KeyedSequencer,
    fn: Callable[[], Awaitable[Response]],
    config: DistributedSessionSerializationConfig | None = None,
) -> Response:
    cfg = config or DistributedSessionSerializationConfig()

    async def _run_with_local_serialization() -> Response:
        if cfg.enable_keyed_serialization:
            return await sequencer.run(session_partition_key, fn)
        return await fn()

    if getattr(storage, "mode", "none") != "external" or should_skip_external_session_lease(
        stream=stream,
        idempotency_key=idempotency_key,
        idem_created=idem_created,
        idem_response_id=idem_response_id,
    ):
        return await _run_with_local_serialization()

    try:
        return await run_with_storage_session_lease(
            storage=storage,
            session_partition_key=session_partition_key,
            owner=owner,
            fn=_run_with_local_serialization,
            config=cfg,
        )
    except RuntimeError as e:
        if str(e) == "lease_lock_unavailable":
            return openai_error_response(
                409,
                message="session busy (lease lock)",
                type_="rate_limit_error",
                code="lease_lock_unavailable",
                retryable=True,
            )
        raise
