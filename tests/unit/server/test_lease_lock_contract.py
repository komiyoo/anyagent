from __future__ import annotations

import asyncio

import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from anyagent.storage.external.redis_lock import RedisLeaseLock
from anyagent.storage.external.schema import build_storage_tables
from anyagent.storage.external.sqlalchemy_backend import SqlAlchemyLeaseLock
from anyagent.storage.inmemory import InMemoryLeaseLock


class _FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.expire_ms: dict[str, int] = {}

    async def set(self, key: str, value: str, *, nx: bool, px: int) -> bool:
        if nx and key in self.values:
            return False
        self.values[key] = value
        self.expire_ms[key] = int(px)
        return True

    async def eval(self, script: str, numkeys: int, *keys_and_args: str) -> int:
        assert numkeys == 1
        key = str(keys_and_args[0])
        args = tuple(str(item) for item in keys_and_args[1:])
        if "PEXPIRE" in script:
            owner, ttl_ms = args
            if self.values.get(key) != owner:
                return 0
            self.expire_ms[key] = int(ttl_ms)
            return 1
        if "DEL" in script:
            (owner,) = args
            if self.values.get(key) != owner:
                return 0
            self.values.pop(key, None)
            self.expire_ms.pop(key, None)
            return 1
        raise AssertionError(f"unexpected script: {script}")


def test_inmemory_lease_lock_contract() -> None:
    asyncio.run(_assert_lock_contract(InMemoryLeaseLock()))


def test_redis_lease_lock_contract() -> None:
    asyncio.run(_assert_lock_contract(RedisLeaseLock(redis=_FakeRedis(), namespace="unit-test")))  # type: ignore[arg-type]


def test_sqlalchemy_lease_lock_contract() -> None:
    pytest.importorskip("aiosqlite")

    async def _run() -> None:
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        try:
            tables = build_storage_tables(schema_name=None, dialect="sqlite")
            async with engine.begin() as conn:
                await conn.run_sync(tables.metadata.create_all)
            await _assert_lock_contract(SqlAlchemyLeaseLock(engine=engine, schema_name=None, dialect="sqlite"))
        finally:
            await engine.dispose()

    asyncio.run(_run())


async def _assert_lock_contract(lock) -> None:
    first = await lock.acquire(key="main::sess-a", owner="resp_a", ttl_ms=1_000, wait_timeout_ms=1)
    assert first is not None
    assert first.key == "main::sess-a"
    assert first.owner == "resp_a"

    conflict = await lock.acquire(key="main::sess-a", owner="resp_b", ttl_ms=1_000, wait_timeout_ms=1)
    assert conflict is None

    assert await lock.renew(key="main::sess-a", owner="resp_b", ttl_ms=1_000) is False
    assert await lock.renew(key="main::sess-a", owner="resp_a", ttl_ms=2_000) is True
    assert await lock.release(key="main::sess-a", owner="resp_b") is False
    assert await lock.release(key="main::sess-a", owner="resp_a") is True

    reacquired = await lock.acquire(key="main::sess-a", owner="resp_b", ttl_ms=1_000, wait_timeout_ms=1)
    assert reacquired is not None
    assert reacquired.owner == "resp_b"
