from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, AsyncIterator, Literal, Protocol

from anyagent.storage.settings import StorageSettings, active_storage_settings


@dataclass(slots=True, frozen=True)
class SessionLeaseRecord:
    session_partition_key: str
    owner_id: str
    expires_at_ms: int


class SessionLeaseConflict(Exception):
    def __init__(self, *, session_partition_key: str, owner_id: str, current_owner_id: str | None) -> None:
        self.session_partition_key = session_partition_key
        self.owner_id = owner_id
        self.current_owner_id = current_owner_id
        super().__init__(
            "session lease conflict"
            f" (session_partition_key={session_partition_key!r},"
            f" owner_id={owner_id!r}, current_owner_id={current_owner_id!r})"
        )


class SessionLeaseLost(Exception):
    def __init__(self, *, session_partition_key: str, owner_id: str) -> None:
        self.session_partition_key = session_partition_key
        self.owner_id = owner_id
        super().__init__(
            "session lease lost"
            f" (session_partition_key={session_partition_key!r}, owner_id={owner_id!r})"
        )


class SessionLockService(Protocol):
    async def get(self, *, session_partition_key: str) -> SessionLeaseRecord | None: ...

    async def acquire(
        self,
        *,
        session_partition_key: str,
        owner_id: str,
        ttl_s: float,
    ) -> SessionLeaseRecord: ...

    async def renew(
        self,
        *,
        session_partition_key: str,
        owner_id: str,
        ttl_s: float,
    ) -> SessionLeaseRecord: ...

    async def release(self, *, session_partition_key: str, owner_id: str) -> None: ...


class SessionLockBackendClient(Protocol):
    async def get_lease(self, *, session_partition_key: str) -> SessionLeaseRecord | None: ...

    async def acquire_lease(
        self,
        *,
        session_partition_key: str,
        owner_id: str,
        ttl_s: float,
    ) -> SessionLeaseRecord: ...

    async def renew_lease(
        self,
        *,
        session_partition_key: str,
        owner_id: str,
        ttl_s: float,
    ) -> SessionLeaseRecord: ...

    async def release_lease(self, *, session_partition_key: str, owner_id: str) -> None: ...


class RedisSessionLockAdapter(Protocol):
    async def get(self, key: str) -> str | None: ...

    async def pttl(self, key: str) -> int: ...

    async def set(self, key: str, value: str, *, nx: bool = False, px: int | None = None) -> bool | None: ...

    async def eval(self, script: str, numkeys: int, *keys_and_args: Any) -> Any: ...


class InMemorySessionLockService:
    """
    单进程 lease lock。

    语义上对齐未来外置 Lock Service：
    - acquire: 同 key 仅允许一个 owner
    - renew: 仅当前 owner 可续租，且 lease 未过期
    - release: 仅当前 owner 可释放
    """

    def __init__(self) -> None:
        self._leases: dict[str, SessionLeaseRecord] = {}
        self._lock = asyncio.Lock()

    async def get(self, *, session_partition_key: str) -> SessionLeaseRecord | None:
        async with self._lock:
            self._purge_expired_locked(now_ms=_now_ms())
            record = self._leases.get(session_partition_key)
            return None if record is None else _clone_record(record)

    async def acquire(
        self,
        *,
        session_partition_key: str,
        owner_id: str,
        ttl_s: float,
    ) -> SessionLeaseRecord:
        now_ms = _now_ms()
        expires_at_ms = now_ms + _ttl_to_ms(ttl_s)
        async with self._lock:
            self._purge_expired_locked(now_ms=now_ms)
            current = self._leases.get(session_partition_key)
            if current is not None and current.owner_id != owner_id:
                raise SessionLeaseConflict(
                    session_partition_key=session_partition_key,
                    owner_id=owner_id,
                    current_owner_id=current.owner_id,
                )
            record = SessionLeaseRecord(
                session_partition_key=session_partition_key,
                owner_id=owner_id,
                expires_at_ms=expires_at_ms,
            )
            self._leases[session_partition_key] = record
            return _clone_record(record)

    async def renew(
        self,
        *,
        session_partition_key: str,
        owner_id: str,
        ttl_s: float,
    ) -> SessionLeaseRecord:
        now_ms = _now_ms()
        expires_at_ms = now_ms + _ttl_to_ms(ttl_s)
        async with self._lock:
            self._purge_expired_locked(now_ms=now_ms)
            current = self._leases.get(session_partition_key)
            if current is None or current.owner_id != owner_id:
                raise SessionLeaseLost(session_partition_key=session_partition_key, owner_id=owner_id)
            record = SessionLeaseRecord(
                session_partition_key=session_partition_key,
                owner_id=owner_id,
                expires_at_ms=expires_at_ms,
            )
            self._leases[session_partition_key] = record
            return _clone_record(record)

    async def release(self, *, session_partition_key: str, owner_id: str) -> None:
        async with self._lock:
            self._purge_expired_locked(now_ms=_now_ms())
            current = self._leases.get(session_partition_key)
            if current is None:
                return
            if current.owner_id != owner_id:
                raise SessionLeaseConflict(
                    session_partition_key=session_partition_key,
                    owner_id=owner_id,
                    current_owner_id=current.owner_id,
                )
            del self._leases[session_partition_key]

    def _purge_expired_locked(self, *, now_ms: int) -> None:
        expired_keys = [
            key for key, record in self._leases.items() if record.expires_at_ms <= now_ms
        ]
        for key in expired_keys:
            self._leases.pop(key, None)


class ExternalSessionLockService:
    """外置锁服务包装层；底层可接 Redis/HTTP/RPC client。"""

    def __init__(self, *, client: SessionLockBackendClient) -> None:
        self._client = client

    async def get(self, *, session_partition_key: str) -> SessionLeaseRecord | None:
        return await self._client.get_lease(session_partition_key=session_partition_key)

    async def acquire(
        self,
        *,
        session_partition_key: str,
        owner_id: str,
        ttl_s: float,
    ) -> SessionLeaseRecord:
        return await self._client.acquire_lease(
            session_partition_key=session_partition_key,
            owner_id=owner_id,
            ttl_s=ttl_s,
        )

    async def renew(
        self,
        *,
        session_partition_key: str,
        owner_id: str,
        ttl_s: float,
    ) -> SessionLeaseRecord:
        return await self._client.renew_lease(
            session_partition_key=session_partition_key,
            owner_id=owner_id,
            ttl_s=ttl_s,
        )

    async def release(self, *, session_partition_key: str, owner_id: str) -> None:
        await self._client.release_lease(session_partition_key=session_partition_key, owner_id=owner_id)


class UnsupportedExternalSessionLockClient:
    """
    占位 stub：用于显式表达“已切到 external 模式，但本仓库构建未提供 backend client”。
    """

    def __init__(self, *, backend_name: str = "external") -> None:
        self.backend_name = backend_name

    async def get_lease(self, *, session_partition_key: str) -> SessionLeaseRecord | None:
        raise RuntimeError(f"session lock backend not configured: {self.backend_name}")

    async def acquire_lease(
        self,
        *,
        session_partition_key: str,
        owner_id: str,
        ttl_s: float,
    ) -> SessionLeaseRecord:
        _ = session_partition_key, owner_id, ttl_s
        raise RuntimeError(f"session lock backend not configured: {self.backend_name}")

    async def renew_lease(
        self,
        *,
        session_partition_key: str,
        owner_id: str,
        ttl_s: float,
    ) -> SessionLeaseRecord:
        _ = session_partition_key, owner_id, ttl_s
        raise RuntimeError(f"session lock backend not configured: {self.backend_name}")

    async def release_lease(self, *, session_partition_key: str, owner_id: str) -> None:
        _ = session_partition_key, owner_id
        raise RuntimeError(f"session lock backend not configured: {self.backend_name}")


class RedisSessionLockClient:
    """
    最小 Redis lease lock client。

    运行时优先复用显式传入的 adapter；若未提供，则尝试动态导入 `redis.asyncio`
    并基于 `StorageSettings.REDIS_DSN` 建立连接。
    """

    _RENEW_SCRIPT = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
  return redis.call('PEXPIRE', KEYS[1], ARGV[2])
end
return 0
""".strip()

    _RELEASE_SCRIPT = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
  return redis.call('DEL', KEYS[1])
end
return 0
""".strip()

    def __init__(
        self,
        *,
        redis_dsn: str,
        namespace: str = "anyagent",
        adapter: RedisSessionLockAdapter | None = None,
    ) -> None:
        self._redis_dsn = redis_dsn
        self._namespace = namespace.strip() or "anyagent"
        self._adapter = adapter

    async def get_lease(self, *, session_partition_key: str) -> SessionLeaseRecord | None:
        adapter = await self._get_adapter()
        key = build_redis_session_lock_key(namespace=self._namespace, session_partition_key=session_partition_key)
        owner_id = await adapter.get(key)
        if not isinstance(owner_id, str) or not owner_id:
            return None
        ttl_ms = int(await adapter.pttl(key))
        if ttl_ms <= 0:
            return None
        return SessionLeaseRecord(
            session_partition_key=session_partition_key,
            owner_id=owner_id,
            expires_at_ms=_now_ms() + ttl_ms,
        )

    async def acquire_lease(
        self,
        *,
        session_partition_key: str,
        owner_id: str,
        ttl_s: float,
    ) -> SessionLeaseRecord:
        adapter = await self._get_adapter()
        key = build_redis_session_lock_key(namespace=self._namespace, session_partition_key=session_partition_key)
        ttl_ms = _ttl_to_ms(ttl_s)
        ok = await adapter.set(key, owner_id, nx=True, px=ttl_ms)
        if ok:
            return SessionLeaseRecord(
                session_partition_key=session_partition_key,
                owner_id=owner_id,
                expires_at_ms=_now_ms() + ttl_ms,
            )
        current_owner_id = await adapter.get(key)
        raise SessionLeaseConflict(
            session_partition_key=session_partition_key,
            owner_id=owner_id,
            current_owner_id=current_owner_id if isinstance(current_owner_id, str) else None,
        )

    async def renew_lease(
        self,
        *,
        session_partition_key: str,
        owner_id: str,
        ttl_s: float,
    ) -> SessionLeaseRecord:
        adapter = await self._get_adapter()
        key = build_redis_session_lock_key(namespace=self._namespace, session_partition_key=session_partition_key)
        ttl_ms = _ttl_to_ms(ttl_s)
        result = await adapter.eval(self._RENEW_SCRIPT, 1, key, owner_id, str(ttl_ms))
        if int(result or 0) <= 0:
            raise SessionLeaseLost(session_partition_key=session_partition_key, owner_id=owner_id)
        return SessionLeaseRecord(
            session_partition_key=session_partition_key,
            owner_id=owner_id,
            expires_at_ms=_now_ms() + ttl_ms,
        )

    async def release_lease(self, *, session_partition_key: str, owner_id: str) -> None:
        adapter = await self._get_adapter()
        key = build_redis_session_lock_key(namespace=self._namespace, session_partition_key=session_partition_key)
        result = await adapter.eval(self._RELEASE_SCRIPT, 1, key, owner_id)
        if int(result or 0) > 0:
            return
        current_owner_id = await adapter.get(key)
        if current_owner_id is None:
            return
        raise SessionLeaseConflict(
            session_partition_key=session_partition_key,
            owner_id=owner_id,
            current_owner_id=current_owner_id if isinstance(current_owner_id, str) else None,
        )

    async def _get_adapter(self) -> RedisSessionLockAdapter:
        if self._adapter is not None:
            return self._adapter
        try:
            from redis import asyncio as redis_asyncio  # type: ignore[import-not-found]
        except Exception as e:  # noqa: BLE001
            raise RuntimeError("redis lock backend requires `redis` package to be installed") from e
        client = redis_asyncio.from_url(self._redis_dsn, encoding="utf-8", decode_responses=True)
        self._adapter = client
        return client


def build_session_lock_service(
    *,
    backend: Literal["inmemory", "external", "redis"] = "inmemory",
    client: SessionLockBackendClient | None = None,
) -> SessionLockService:
    if backend == "inmemory":
        return InMemorySessionLockService()
    if backend == "redis":
        if client is not None:
            return ExternalSessionLockService(client=client)
        settings = active_storage_settings()
        if settings.redis_dsn is None:
            raise RuntimeError("redis lock backend requires REDIS_DSN")
        redis_client = RedisSessionLockClient(
            redis_dsn=str(settings.redis_dsn),
            namespace=settings.redis_namespace,
        )
        return ExternalSessionLockService(client=redis_client)
    return ExternalSessionLockService(client=client or UnsupportedExternalSessionLockClient(backend_name=backend))


@asynccontextmanager
async def hold_session_lease(
    *,
    service: SessionLockService,
    session_partition_key: str,
    owner_id: str,
    ttl_s: float,
) -> AsyncIterator[SessionLeaseRecord]:
    owner_task = asyncio.current_task()
    if owner_task is None:
        raise RuntimeError("hold_session_lease must run inside a task")

    lease = await service.acquire(
        session_partition_key=session_partition_key,
        owner_id=owner_id,
        ttl_s=ttl_s,
    )

    stop = asyncio.Event()
    renew_task = asyncio.create_task(
        _renew_loop(
            service=service,
            session_partition_key=session_partition_key,
            owner_id=owner_id,
            ttl_s=ttl_s,
            stop=stop,
            owner_task=owner_task,
        ),
        name=f"anyagent-lease-renew-{owner_id}",
    )
    try:
        yield lease
    finally:
        stop.set()
        renew_task.cancel()
        try:
            await renew_task
        except asyncio.CancelledError:
            pass
        await service.release(session_partition_key=session_partition_key, owner_id=owner_id)


async def _renew_loop(
    *,
    service: SessionLockService,
    session_partition_key: str,
    owner_id: str,
    ttl_s: float,
    stop: asyncio.Event,
    owner_task: asyncio.Task[object],
) -> None:
    renew_interval_s = max(ttl_s / 3.0, 0.05)
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=renew_interval_s)
            return
        except asyncio.TimeoutError:
            pass
        try:
            await service.renew(
                session_partition_key=session_partition_key,
                owner_id=owner_id,
                ttl_s=ttl_s,
            )
        except SessionLeaseLost:
            owner_task.cancel()
            return


def _clone_record(record: SessionLeaseRecord) -> SessionLeaseRecord:
    return SessionLeaseRecord(
        session_partition_key=record.session_partition_key,
        owner_id=record.owner_id,
        expires_at_ms=record.expires_at_ms,
    )


def _ttl_to_ms(ttl_s: float) -> int:
    return max(1, int(float(ttl_s) * 1000))


def _now_ms() -> int:
    return int(time.time() * 1000)


def build_redis_session_lock_key(*, namespace: str, session_partition_key: str) -> str:
    ns = namespace.strip() or "anyagent"
    return f"{ns}:lease:{session_partition_key}"
