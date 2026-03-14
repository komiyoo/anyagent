from __future__ import annotations

import asyncio

from anyagent.storage.external import RedisLeaseLock


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


def test_redis_lease_lock_can_renew_and_release() -> None:
    async def _run() -> None:
        redis = _FakeRedis()
        lock = RedisLeaseLock(redis=redis, namespace="unit-test")

        handle = await lock.acquire(key="main::session-1", owner="owner-a", ttl_ms=1_000, wait_timeout_ms=10)
        assert handle is not None
        assert redis.values["unit-test:lease:main::session-1"] == "owner-a"

        renewed = await lock.renew(key=handle.key, owner=handle.owner, ttl_ms=5_000)
        assert renewed is True
        assert redis.expire_ms["unit-test:lease:main::session-1"] == 5_000

        released = await lock.release(key=handle.key, owner=handle.owner)
        assert released is True
        assert "unit-test:lease:main::session-1" not in redis.values

    asyncio.run(_run())
