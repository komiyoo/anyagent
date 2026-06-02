from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from typing import Any

from anyagent.gateway.session import session_partition_key as build_session_partition_key
from anyagent.server.db.postgres_schema import PostgresSchemaPolicy
from anyagent.storage.settings import StorageSettings


@dataclass(slots=True)
class RunRecord:
    response_id: str
    agent_id: str
    session_key: str
    stream: bool
    idempotency_key: str | None
    status: str
    effective_status: str
    created_at_ms: int
    updated_at_ms: int
    ended_at_ms: int | None = None
    final_response_json: dict[str, Any] | None = None
    error_json: dict[str, Any] | None = None


class InMemoryRunStore:
    def __init__(self) -> None:
        self._runs: dict[str, RunRecord] = {}
        self._idempotency_index: dict[str, str] = {}
        self._lock = asyncio.Lock()

    async def get(self, response_id: str) -> RunRecord | None:
        async with self._lock:
            record = self._runs.get(response_id)
            return None if record is None else _clone_record(record)

    async def get_by_idempotency_key(self, idempotency_key: str) -> RunRecord | None:
        async with self._lock:
            response_id = self._idempotency_index.get(idempotency_key)
            if response_id is None:
                return None
            record = self._runs.get(response_id)
            return None if record is None else _clone_record(record)

    async def list(
        self,
        *,
        agent_id: str | None = None,
        session_key: str | None = None,
        response_id: str | None = None,
        limit: int = 100,
    ) -> list[RunRecord]:
        async with self._lock:
            records = list(self._runs.values())
        if response_id is not None and response_id.strip():
            records = [record for record in records if record.response_id == response_id]
        if agent_id is not None and agent_id.strip():
            records = [record for record in records if record.agent_id == agent_id]
        if session_key is not None and session_key.strip():
            records = [record for record in records if record.session_key == session_key]
        records.sort(key=lambda record: record.updated_at_ms, reverse=True)
        return [_clone_record(record) for record in records[: max(0, int(limit))]]

    async def create_started(
        self,
        *,
        response_id: str,
        agent_id: str,
        session_key: str,
        stream: bool,
        idempotency_key: str | None,
    ) -> RunRecord:
        now_ms = int(time.time() * 1000)
        record = RunRecord(
            response_id=response_id,
            agent_id=agent_id,
            session_key=session_key,
            stream=stream,
            idempotency_key=idempotency_key,
            status="started",
            effective_status="in_progress",
            created_at_ms=now_ms,
            updated_at_ms=now_ms,
        )
        async with self._lock:
            self._runs[response_id] = record
            if isinstance(idempotency_key, str) and idempotency_key.strip():
                self._idempotency_index[idempotency_key] = response_id
        return _clone_record(record)

    async def mark_cancel_requested(self, response_id: str) -> None:
        async with self._lock:
            record = self._runs.get(response_id)
            if record is None or record.ended_at_ms is not None:
                return
            record.status = "aborted"
            record.effective_status = "cancelled"
            record.updated_at_ms = int(time.time() * 1000)

    async def mark_final(
        self,
        *,
        response_id: str,
        status: str,
        effective_status: str,
        final_response_json: dict[str, Any] | None,
        error_json: dict[str, Any] | None = None,
    ) -> None:
        now_ms = int(time.time() * 1000)
        async with self._lock:
            record = self._runs.get(response_id)
            if record is None:
                return
            record.status = status
            record.effective_status = effective_status
            record.updated_at_ms = now_ms
            record.ended_at_ms = now_ms
            record.final_response_json = _clone_json(final_response_json)
            record.error_json = _clone_json(error_json)


class RedisRunStoreAdapter:
    async def hgetall(self, key: str) -> dict[str, str]: ...
    async def get(self, key: str) -> str | None: ...
    async def set(self, key: str, value: str) -> Any: ...
    async def eval(self, script: str, numkeys: int, *keys_and_args: Any) -> Any: ...
    async def pexpire(self, key: str, time_ms: int) -> Any: ...
    async def zadd(self, key: str, mapping: dict[str, float]) -> Any: ...
    async def zrevrange(self, key: str, start: int, stop: int) -> list[str]: ...



class RedisRunStore:
    _CREATE_STARTED_SCRIPT = """
redis.call('HSET', KEYS[1],
  'response_id', ARGV[1],
  'agent_id', ARGV[2],
  'session_key', ARGV[3],
  'stream', ARGV[4],
  'idempotency_key', ARGV[5],
  'status', 'started',
  'effective_status', 'in_progress',
  'created_at_ms', ARGV[6],
  'updated_at_ms', ARGV[6]
)
if ARGV[5] ~= '' then
  redis.call('SET', KEYS[2], ARGV[1])
end
return 1
""".strip()

    _MARK_CANCEL_SCRIPT = """
local ended_at_ms = redis.call('HGET', KEYS[1], 'ended_at_ms')
if ended_at_ms ~= false and tostring(ended_at_ms) ~= '' then
  return 0
end
if redis.call('EXISTS', KEYS[1]) == 0 then
  return 0
end
redis.call('HSET', KEYS[1],
  'status', 'aborted',
  'effective_status', 'cancelled',
  'updated_at_ms', ARGV[1]
)
return 1
""".strip()

    _MARK_FINAL_SCRIPT = """
if redis.call('EXISTS', KEYS[1]) == 0 then
  return 0
end
redis.call('HSET', KEYS[1],
  'status', ARGV[1],
  'effective_status', ARGV[2],
  'updated_at_ms', ARGV[3],
  'ended_at_ms', ARGV[3],
  'final_response_json', ARGV[4],
  'error_json', ARGV[5]
)
return 1
""".strip()

    def __init__(
        self,
        *,
        redis_dsn: str,
        namespace: str = "anyagent",
        adapter: RedisRunStoreAdapter | None = None,
        retention_s: int = 2 * 60 * 60,
    ) -> None:
        self._redis_dsn = redis_dsn
        self._namespace = namespace.strip() or "anyagent"
        self._adapter = adapter
        self._retention_ms = max(1, int(retention_s * 1000))

    async def get(self, response_id: str) -> RunRecord | None:
        adapter = await self._get_adapter()
        raw = await adapter.hgetall(build_redis_run_store_key(namespace=self._namespace, response_id=response_id))
        return _record_from_hash(raw)

    async def get_by_idempotency_key(self, idempotency_key: str) -> RunRecord | None:
        adapter = await self._get_adapter()
        response_id = await adapter.get(
            build_redis_run_store_idempotency_key(namespace=self._namespace, idempotency_key=idempotency_key)
        )
        if not isinstance(response_id, str) or not response_id.strip():
            return None
        return await self.get(response_id.strip())

    async def list(
        self,
        *,
        agent_id: str | None = None,
        session_key: str | None = None,
        response_id: str | None = None,
        limit: int = 100,
    ) -> list[RunRecord]:
        if isinstance(response_id, str) and response_id.strip():
            record = await self.get(response_id.strip())
            if record is None:
                return []
            if isinstance(agent_id, str) and agent_id.strip() and record.agent_id != agent_id.strip():
                return []
            if isinstance(session_key, str) and session_key.strip() and record.session_key != session_key.strip():
                return []
            return [record]
        adapter = await self._get_adapter()
        ids = await adapter.zrevrange(build_redis_run_store_history_key(namespace=self._namespace), 0, max(0, int(limit)) - 1)
        records: list[RunRecord] = []
        for rid in ids:
            record = await self.get(rid)
            if record is None:
                continue
            if isinstance(agent_id, str) and agent_id.strip() and record.agent_id != agent_id.strip():
                continue
            if isinstance(session_key, str) and session_key.strip() and record.session_key != session_key.strip():
                continue
            records.append(record)
            if len(records) >= max(0, int(limit)):
                break
        return records

    async def create_started(
        self,
        *,
        response_id: str,
        agent_id: str,
        session_key: str,
        stream: bool,
        idempotency_key: str | None,
    ) -> RunRecord:
        adapter = await self._get_adapter()
        now_ms = int(time.time() * 1000)
        idem = idempotency_key.strip() if isinstance(idempotency_key, str) and idempotency_key.strip() else ""
        await adapter.eval(
            self._CREATE_STARTED_SCRIPT,
            2,
            build_redis_run_store_key(namespace=self._namespace, response_id=response_id),
            build_redis_run_store_idempotency_key(namespace=self._namespace, idempotency_key=idem or response_id),
            response_id,
            agent_id,
            session_key,
            "1" if stream else "0",
            idem,
            str(now_ms),
        )
        await adapter.zadd(build_redis_run_store_history_key(namespace=self._namespace), {response_id: float(now_ms)})
        await adapter.pexpire(build_redis_run_store_history_key(namespace=self._namespace), self._retention_ms)
        await adapter.pexpire(
            build_redis_run_store_key(namespace=self._namespace, response_id=response_id),
            self._retention_ms,
        )
        if idem:
            await adapter.set(
                build_redis_run_store_idempotency_key(namespace=self._namespace, idempotency_key=idem),
                response_id,
            )
            await adapter.pexpire(
                build_redis_run_store_idempotency_key(namespace=self._namespace, idempotency_key=idem),
                self._retention_ms,
            )
        return RunRecord(
            response_id=response_id,
            agent_id=agent_id,
            session_key=session_key,
            stream=stream,
            idempotency_key=idem or None,
            status="started",
            effective_status="in_progress",
            created_at_ms=now_ms,
            updated_at_ms=now_ms,
        )

    async def mark_cancel_requested(self, response_id: str) -> None:
        adapter = await self._get_adapter()
        now_ms = int(time.time() * 1000)
        run_key = build_redis_run_store_key(namespace=self._namespace, response_id=response_id)
        await adapter.eval(
            self._MARK_CANCEL_SCRIPT,
            1,
            run_key,
            str(now_ms),
        )
        await adapter.pexpire(run_key, self._retention_ms)
        record = await self.get(response_id)
        if record is not None and isinstance(record.idempotency_key, str) and record.idempotency_key.strip():
            await adapter.pexpire(
                build_redis_run_store_idempotency_key(namespace=self._namespace, idempotency_key=record.idempotency_key),
                self._retention_ms,
            )

    async def mark_final(
        self,
        *,
        response_id: str,
        status: str,
        effective_status: str,
        final_response_json: dict[str, Any] | None,
        error_json: dict[str, Any] | None = None,
    ) -> None:
        adapter = await self._get_adapter()
        now_ms = int(time.time() * 1000)
        run_key = build_redis_run_store_key(namespace=self._namespace, response_id=response_id)
        await adapter.eval(
            self._MARK_FINAL_SCRIPT,
            1,
            run_key,
            status,
            effective_status,
            str(now_ms),
            json.dumps(final_response_json, ensure_ascii=False) if final_response_json is not None else "",
            json.dumps(error_json, ensure_ascii=False) if error_json is not None else "",
        )
        await adapter.zadd(build_redis_run_store_history_key(namespace=self._namespace), {response_id: float(now_ms)})
        await adapter.pexpire(build_redis_run_store_history_key(namespace=self._namespace), self._retention_ms)
        await adapter.pexpire(run_key, self._retention_ms)
        record = await self.get(response_id)
        if record is not None and isinstance(record.idempotency_key, str) and record.idempotency_key.strip():
            await adapter.pexpire(
                build_redis_run_store_idempotency_key(namespace=self._namespace, idempotency_key=record.idempotency_key),
                self._retention_ms,
            )

    async def write_record(self, record: RunRecord) -> RunRecord:
        adapter = await self._get_adapter()
        run_key = build_redis_run_store_key(namespace=self._namespace, response_id=record.response_id)
        await adapter.eval(
            self._MARK_FINAL_SCRIPT,
            1,
            run_key,
            record.status,
            record.effective_status,
            str(int(record.updated_at_ms)),
            json.dumps(record.final_response_json, ensure_ascii=False) if record.final_response_json is not None else "",
            json.dumps(record.error_json, ensure_ascii=False) if record.error_json is not None else "",
        )
        await adapter.eval(
            self._CREATE_STARTED_SCRIPT,
            2,
            run_key,
            build_redis_run_store_idempotency_key(
                namespace=self._namespace,
                idempotency_key=(record.idempotency_key or record.response_id),
            ),
            record.response_id,
            record.agent_id,
            record.session_key,
            "1" if record.stream else "0",
            record.idempotency_key or "",
            str(int(record.created_at_ms)),
        )
        await adapter.zadd(build_redis_run_store_history_key(namespace=self._namespace), {record.response_id: float(record.updated_at_ms)})
        await adapter.pexpire(build_redis_run_store_history_key(namespace=self._namespace), self._retention_ms)
        await adapter.pexpire(run_key, self._retention_ms)
        if isinstance(record.idempotency_key, str) and record.idempotency_key.strip():
            idem_key = build_redis_run_store_idempotency_key(namespace=self._namespace, idempotency_key=record.idempotency_key)
            await adapter.set(idem_key, record.response_id)
            await adapter.pexpire(idem_key, self._retention_ms)
        return _clone_record(record)

    async def _get_adapter(self) -> RedisRunStoreAdapter:
        if self._adapter is not None:
            return self._adapter
        try:
            from redis import asyncio as redis_asyncio  # type: ignore[import-not-found]
        except Exception as e:  # noqa: BLE001
            raise RuntimeError("redis run store requires `redis` package to be installed") from e
        client = redis_asyncio.from_url(self._redis_dsn, encoding="utf-8", decode_responses=True)
        self._adapter = client
        return client


def _clone_record(record: RunRecord) -> RunRecord:
    return RunRecord(
        response_id=record.response_id,
        agent_id=record.agent_id,
        session_key=record.session_key,
        stream=record.stream,
        idempotency_key=record.idempotency_key,
        status=record.status,
        effective_status=record.effective_status,
        created_at_ms=record.created_at_ms,
        updated_at_ms=record.updated_at_ms,
        ended_at_ms=record.ended_at_ms,
        final_response_json=_clone_json(record.final_response_json),
        error_json=_clone_json(record.error_json),
    )


def _clone_json(value: dict[str, Any] | None) -> dict[str, Any] | None:
    if value is None:
        return None
    return dict(value)


def _row_to_run_record(row: dict[str, Any]) -> RunRecord:
    return RunRecord(
        response_id=str(row.get("response_id") or ""),
        agent_id=str(row.get("agent_id") or ""),
        session_key=str(row.get("session_key") or ""),
        stream=bool(row.get("stream")),
        idempotency_key=str(row.get("idempotency_key") or "") or None,
        status=str(row.get("status") or ""),
        effective_status=str(row.get("effective_status") or ""),
        created_at_ms=int(row.get("created_at_ms") or 0),
        updated_at_ms=int(row.get("updated_at_ms") or 0),
        ended_at_ms=int(row["ended_at_ms"]) if row.get("ended_at_ms") is not None else None,
        final_response_json=row.get("final_response_json") if isinstance(row.get("final_response_json"), dict) else _loads_json(row.get("final_response_json")),
        error_json=row.get("error_json") if isinstance(row.get("error_json"), dict) else _loads_json(row.get("error_json")),
    )


def _record_from_hash(raw: dict[str, str] | None) -> RunRecord | None:
    if not isinstance(raw, dict) or not raw:
        return None
    return RunRecord(
        response_id=str(raw.get("response_id") or ""),
        agent_id=str(raw.get("agent_id") or ""),
        session_key=str(raw.get("session_key") or ""),
        stream=str(raw.get("stream") or "0") == "1",
        idempotency_key=str(raw.get("idempotency_key") or "") or None,
        status=str(raw.get("status") or ""),
        effective_status=str(raw.get("effective_status") or ""),
        created_at_ms=int(raw.get("created_at_ms") or 0),
        updated_at_ms=int(raw.get("updated_at_ms") or 0),
        ended_at_ms=int(raw["ended_at_ms"]) if str(raw.get("ended_at_ms") or "").strip() else None,
        final_response_json=_loads_json(raw.get("final_response_json")),
        error_json=_loads_json(raw.get("error_json")),
    )


def _loads_json(value: str | None) -> dict[str, Any] | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        obj = json.loads(value)
    except Exception:  # noqa: BLE001
        return None
    return obj if isinstance(obj, dict) else None


def build_redis_run_store(*, namespace: str | None = None, redis_dsn: str | None = None) -> RedisRunStore:
    settings = StorageSettings()
    effective_dsn = redis_dsn or (str(settings.redis_dsn) if settings.redis_dsn is not None else None)
    if effective_dsn is None:
        raise RuntimeError("redis run store requires REDIS_DSN")
    effective_namespace = namespace or settings.redis_namespace
    return RedisRunStore(
        redis_dsn=effective_dsn,
        namespace=effective_namespace,
        retention_s=settings.run_store_retention_s,
    )


class CachedRunStore:
    def __init__(self, *, primary: PostgresRunStore, cache: RedisRunStore) -> None:
        self._primary = primary
        self._cache = cache

    async def get(self, response_id: str) -> RunRecord | None:
        cached = await self._cache.get(response_id)
        if cached is not None:
            return cached
        record = await self._primary.get(response_id)
        if record is not None:
            await self._cache.write_record(record)
        return record

    async def get_by_idempotency_key(self, idempotency_key: str) -> RunRecord | None:
        cached = await self._cache.get_by_idempotency_key(idempotency_key)
        if cached is not None:
            return cached
        record = await self._primary.get_by_idempotency_key(idempotency_key)
        if record is not None:
            await self._cache.write_record(record)
        return record

    async def list(
        self,
        *,
        agent_id: str | None = None,
        session_key: str | None = None,
        response_id: str | None = None,
        limit: int = 100,
    ) -> list[RunRecord]:
        return await self._primary.list(
            agent_id=agent_id,
            session_key=session_key,
            response_id=response_id,
            limit=limit,
        )

    async def create_started(
        self,
        *,
        response_id: str,
        agent_id: str,
        session_key: str,
        stream: bool,
        idempotency_key: str | None,
    ) -> RunRecord:
        record = await self._primary.create_started(
            response_id=response_id,
            agent_id=agent_id,
            session_key=session_key,
            stream=stream,
            idempotency_key=idempotency_key,
        )
        await self._cache.write_record(record)
        return record

    async def mark_cancel_requested(self, response_id: str) -> None:
        await self._primary.mark_cancel_requested(response_id)
        record = await self._primary.get(response_id)
        if record is not None:
            await self._cache.write_record(record)

    async def mark_final(
        self,
        *,
        response_id: str,
        status: str,
        effective_status: str,
        final_response_json: dict[str, Any] | None,
        error_json: dict[str, Any] | None = None,
    ) -> None:
        await self._primary.mark_final(
            response_id=response_id,
            status=status,
            effective_status=effective_status,
            final_response_json=final_response_json,
            error_json=error_json,
        )
        record = await self._primary.get(response_id)
        if record is not None:
            await self._cache.write_record(record)


class PostgresRunStore:
    def __init__(
        self,
        *,
        postgres_dsn: str,
        postgres_schema: str = "public",
        schema_policy: PostgresSchemaPolicy = "migrate",
    ) -> None:
        try:
            from anyagent.storage.external import PostgresRunStore as ExternalPostgresRunStore
            from anyagent.storage.external import create_external_sql_engine, resolve_external_sql_backend_config
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(
                "postgres run store requires installing anyagent[postgres]"
                " (and anyagent[redis] when using the cached external store)"
            ) from e

        _ = schema_policy
        config = resolve_external_sql_backend_config(
            postgres_dsn=postgres_dsn,
            mysql_dsn=None,
            redis_dsn=None,
            schema_name=postgres_schema,
            namespace="anyagent",
            dialect="postgresql",
        )
        self._engine = create_external_sql_engine(config)
        self._store = ExternalPostgresRunStore(engine=self._engine, schema_name=postgres_schema)

    async def get(self, response_id: str) -> RunRecord | None:
        record = await self._store.get(response_id)
        return None if record is None else _local_run_record(record)

    async def get_by_idempotency_key(self, idempotency_key: str) -> RunRecord | None:
        record = await self._store.get_by_idempotency_key(idempotency_key)
        return None if record is None else _local_run_record(record)

    async def list(
        self,
        *,
        agent_id: str | None = None,
        session_key: str | None = None,
        response_id: str | None = None,
        limit: int = 100,
    ) -> list[RunRecord]:
        records = await self._store.list(
            agent_id=agent_id,
            session_key=session_key,
            response_id=response_id,
            limit=limit,
        )
        return [_local_run_record(record) for record in records]

    async def create_started(
        self,
        *,
        response_id: str,
        agent_id: str,
        session_key: str,
        stream: bool,
        idempotency_key: str | None,
    ) -> RunRecord:
        record = await self._store.create_started(
            response_id=response_id,
            session_partition_key=build_session_partition_key(agent_id=agent_id, session_key=session_key),
            stream=stream,
            idempotency_key=idempotency_key,
        )
        return _local_run_record(record, agent_id=agent_id, session_key=session_key)

    async def mark_cancel_requested(self, response_id: str) -> None:
        await self._store.mark_cancel_requested(response_id)

    async def mark_final(
        self,
        *,
        response_id: str,
        status: str,
        effective_status: str,
        final_response_json: dict[str, Any] | None,
        error_json: dict[str, Any] | None = None,
    ) -> None:
        _ = effective_status
        await self._store.set_final(
            response_id=response_id,
            status=status,
            final_response_json=final_response_json,
            error_json=error_json,
        )


def build_postgres_run_store(*, postgres_dsn: str | None = None, postgres_schema: str | None = None) -> PostgresRunStore:
    settings = StorageSettings()
    effective_dsn = postgres_dsn or (str(settings.effective_postgres_dsn) if settings.effective_postgres_dsn is not None else None)
    if effective_dsn is None:
        raise RuntimeError("postgres run store requires POSTGRES_DSN or DATABASE_URL")
    effective_schema = postgres_schema or settings.postgres_schema
    return PostgresRunStore(
        postgres_dsn=effective_dsn,
        postgres_schema=effective_schema,
        schema_policy=settings.postgres_schema_policy,
    )


def build_cached_run_store() -> CachedRunStore:
    return CachedRunStore(
        primary=build_postgres_run_store(),
        cache=build_redis_run_store(),
    )


def build_redis_run_store_key(*, namespace: str, response_id: str) -> str:
    ns = namespace.strip() or "anyagent"
    return f"{ns}:run:{response_id}"


def build_redis_run_store_idempotency_key(*, namespace: str, idempotency_key: str) -> str:
    ns = namespace.strip() or "anyagent"
    return f"{ns}:run-idem:{idempotency_key}"


def build_redis_run_store_history_key(*, namespace: str) -> str:
    ns = namespace.strip() or "anyagent"
    return f"{ns}:runs:history"


def _local_run_record(record: Any, *, agent_id: str | None = None, session_key: str | None = None) -> RunRecord:
    partition = str(getattr(record, "session_partition_key", "") or "")
    agent, session = _split_session_partition_key(partition)
    status = str(getattr(record, "status", "") or "")
    error_json = getattr(record, "error_json", None) if isinstance(getattr(record, "error_json", None), dict) else None
    return RunRecord(
        response_id=str(getattr(record, "response_id", "") or ""),
        agent_id=agent_id or agent,
        session_key=session_key or session,
        stream=bool(getattr(record, "stream", False)),
        idempotency_key=getattr(record, "idempotency_key", None),
        status=status,
        effective_status=_effective_status_from_status(status=status, error_json=error_json),
        created_at_ms=int(float(getattr(record, "created_at_s", 0.0) or 0.0) * 1000),
        updated_at_ms=int(time.time() * 1000),
        final_response_json=getattr(record, "final_response_json", None),
        error_json=error_json,
    )


def _split_session_partition_key(value: str) -> tuple[str, str]:
    if "::" not in value:
        return "", value
    return value.split("::", 1)


def _effective_status_from_status(*, status: str, error_json: dict[str, Any] | None) -> str:
    if status == "started":
        return "in_progress"
    if status == "aborted":
        return "cancelled"
    if status == "errored" and isinstance(error_json, dict) and str(error_json.get("code") or "").strip() == "response_cancelled":
        return "cancelled"
    return status
