from __future__ import annotations

import asyncio
from dataclasses import dataclass
from time import monotonic

from redis.asyncio import Redis


@dataclass(frozen=True)
class LeaseLockHandle:
    key: str
    owner: str


_RENEW_LUA = """
if redis.call("GET", KEYS[1]) == ARGV[1] then
  return redis.call("PEXPIRE", KEYS[1], ARGV[2])
end
return 0
"""

_RELEASE_LUA = """
if redis.call("GET", KEYS[1]) == ARGV[1] then
  return redis.call("DEL", KEYS[1])
end
return 0
"""


class RedisLeaseLock:
    def __init__(self, *, redis: Redis, namespace: str) -> None:
        self._redis = redis
        self._ns = (namespace or "anyagent").strip() or "anyagent"

    def _k(self, key: str) -> str:
        return f"{self._ns}:lease:{key}"

    async def acquire(self, *, key: str, owner: str, ttl_ms: int, wait_timeout_ms: int) -> LeaseLockHandle | None:
        deadline = monotonic() + (wait_timeout_ms / 1000.0)
        k = self._k(key)
        while True:
            ok = await self._redis.set(k, owner, nx=True, px=ttl_ms)
            if ok:
                return LeaseLockHandle(key=key, owner=owner)
            if monotonic() >= deadline:
                return None
            await asyncio.sleep(0.05)

    async def renew(self, *, key: str, owner: str, ttl_ms: int) -> bool:
        k = self._k(key)
        try:
            r = await self._redis.eval(_RENEW_LUA, numkeys=1, keys=[k], args=[owner, str(ttl_ms)])
        except Exception:  # noqa: BLE001
            return False
        return bool(r)

    async def release(self, *, key: str, owner: str) -> bool:
        k = self._k(key)
        try:
            r = await self._redis.eval(_RELEASE_LUA, numkeys=1, keys=[k], args=[owner])
        except Exception:  # noqa: BLE001
            return False
        return bool(r)

