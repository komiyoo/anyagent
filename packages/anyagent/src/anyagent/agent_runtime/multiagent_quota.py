from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import AsyncIterator

from anyagent.storage.contracts import LeaseLock
from anyagent.storage.models import LeaseLockHandle


@dataclass(frozen=True, slots=True)
class MultiAgentQuotaSpec:
    """Cross-node quota contract for sub-agent execution slots."""

    root_response_id: str
    max_concurrent_children: int
    ttl_ms: int = 60_000
    wait_timeout_ms: int = 0
    namespace: str = "multiagent"

    def __post_init__(self) -> None:
        if not self.root_response_id.strip():
            raise ValueError("root_response_id must be non-empty")
        if self.max_concurrent_children < 1:
            raise ValueError("max_concurrent_children must be >= 1")
        if self.ttl_ms < 1:
            raise ValueError("ttl_ms must be >= 1")
        if self.wait_timeout_ms < 0:
            raise ValueError("wait_timeout_ms must be >= 0")


class MultiAgentQuotaExceeded(RuntimeError):
    def __init__(self, *, root_response_id: str, max_concurrent_children: int) -> None:
        self.root_response_id = root_response_id
        self.max_concurrent_children = max_concurrent_children
        super().__init__(
            "multi-agent quota exceeded"
            f" (root_response_id={root_response_id!r}, max_concurrent_children={max_concurrent_children})"
        )


class MultiAgentQuota:
    """LeaseLock-backed quota primitive shared by all runtime nodes."""

    def __init__(self, *, lease_lock: LeaseLock, spec: MultiAgentQuotaSpec) -> None:
        self._lease_lock = lease_lock
        self._spec = spec

    async def acquire(self, *, owner: str) -> LeaseLockHandle:
        normalized_owner = owner.strip()
        if not normalized_owner:
            raise ValueError("owner must be non-empty")
        for slot in range(self._spec.max_concurrent_children):
            handle = await self._lease_lock.acquire(
                key=self._slot_key(slot),
                owner=normalized_owner,
                ttl_ms=self._spec.ttl_ms,
                wait_timeout_ms=self._spec.wait_timeout_ms,
            )
            if handle is not None:
                return handle
        raise MultiAgentQuotaExceeded(
            root_response_id=self._spec.root_response_id,
            max_concurrent_children=self._spec.max_concurrent_children,
        )

    async def release(self, handle: LeaseLockHandle) -> bool:
        return await self._lease_lock.release(key=handle.key, owner=handle.owner)

    @asynccontextmanager
    async def hold(self, *, owner: str) -> AsyncIterator[LeaseLockHandle]:
        handle = await self.acquire(owner=owner)
        try:
            yield handle
        finally:
            await self.release(handle)

    def _slot_key(self, slot: int) -> str:
        return f"{self._spec.namespace}:root:{self._spec.root_response_id}:slot:{slot}"
