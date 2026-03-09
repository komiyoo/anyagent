from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from anyagent.protocol.agent_api_internal import InternalEventItem, InternalEventsListResponse
from anyagent.protocol.responses_optional import AnyAgentResponseError
from anyagent.server.postgres_schema import PostgresSchemaPolicy, ensure_postgres_schema_objects
from anyagent.storage.settings import StorageSettings


@dataclass(slots=True)
class _ResponseRecord:
    response_id: str
    events: list[InternalEventItem] = field(default_factory=list)
    next_seq: int = 1
    done: bool = False
    run_status: str | None = None
    effective_run_status: str | None = None
    response_json: dict[str, Any] | None = None
    error: AnyAgentResponseError | None = None


class InMemoryEventStore:
    def __init__(self) -> None:
        self._records: dict[str, _ResponseRecord] = {}
        self._subscribers: dict[str, list[asyncio.Queue[InternalEventItem | None]]] = {}

    def _record(self, response_id: str) -> _ResponseRecord:
        record = self._records.get(response_id)
        if record is None:
            record = _ResponseRecord(response_id=response_id)
            self._records[response_id] = record
        return record

    async def append(self, *, response_id: str, event: str | None, data: str) -> int:
        record = self._record(response_id)
        seq = record.next_seq
        record.next_seq += 1
        item = InternalEventItem(seq=seq, event=event, data=data)
        record.events.append(item)
        for queue in list(self._subscribers.get(response_id, [])):
            await queue.put(item)
        return seq

    async def mark_started(self, *, response_id: str) -> None:
        record = self._record(response_id)
        record.done = False
        record.run_status = "started"
        record.effective_run_status = "in_progress"

    async def mark_cancel_requested(self, *, response_id: str) -> None:
        record = self._record(response_id)
        if record.done:
            return
        record.run_status = "aborted"
        record.effective_run_status = "cancelled"

    async def mark_final(
        self,
        *,
        response_id: str,
        run_status: str,
        effective_run_status: str | None = None,
        response_json: dict[str, Any] | None = None,
        error: AnyAgentResponseError | None = None,
    ) -> None:
        record = self._record(response_id)
        record.done = True
        record.run_status = run_status
        record.effective_run_status = effective_run_status or run_status
        record.response_json = response_json
        record.error = error
        for queue in list(self._subscribers.get(response_id, [])):
            await queue.put(None)

    async def get_response(self, response_id: str) -> dict[str, Any] | None:
        record = self._records.get(response_id)
        return None if record is None else record.response_json

    async def get_status(self, response_id: str) -> tuple[str | None, AnyAgentResponseError | None]:
        record = self._records.get(response_id)
        if record is None:
            return None, None
        return record.effective_run_status, record.error

    async def list_events(self, *, response_id: str, last_seq: int = 0, limit: int = 200) -> InternalEventsListResponse:
        record = self._record(response_id)
        items = [item for item in record.events if item.seq > last_seq][: max(limit, 0)]
        next_last_seq = last_seq
        if items:
            next_last_seq = items[-1].seq
        elif record.events:
            next_last_seq = record.events[-1].seq
        return InternalEventsListResponse(
            response_id=response_id,
            requested_last_seq=max(last_seq, 0),
            next_last_seq=max(next_last_seq, 0),
            events=items,
            done=record.done,
            run_status=record.run_status,
            effective_run_status=record.effective_run_status,
        )

    async def latest_seq(self, response_id: str) -> int:
        record = self._record(response_id)
        if not record.events:
            return 0
        return record.events[-1].seq

    async def stream_events(self, *, response_id: str, last_seq: int = 0) -> AsyncIterator[InternalEventItem]:
        record = self._record(response_id)
        next_seq = max(last_seq, 0)
        for item in record.events:
            if item.seq > next_seq:
                yield item
                next_seq = item.seq
        if record.done:
            return

        queue: asyncio.Queue[InternalEventItem | None] = asyncio.Queue()
        self._subscribers.setdefault(response_id, []).append(queue)
        try:
            while True:
                item = await queue.get()
                if item is None:
                    return
                if item.seq <= next_seq:
                    continue
                yield item
                next_seq = item.seq
        finally:
            queues = self._subscribers.get(response_id)
            if queues is not None:
                self._subscribers[response_id] = [q for q in queues if q is not queue]
                if not self._subscribers[response_id]:
                    self._subscribers.pop(response_id, None)


class RedisEventStoreAdapter:
    async def hgetall(self, key: str) -> dict[str, str]: ...
    async def llen(self, key: str) -> int: ...
    async def lrange(self, key: str, start: int, stop: int) -> list[str]: ...
    async def eval(self, script: str, numkeys: int, *keys_and_args: Any) -> Any: ...
    async def pexpire(self, key: str, time_ms: int) -> Any: ...


class PostgresEventStore:
    def __init__(
        self,
        *,
        postgres_dsn: str,
        postgres_schema: str = "public",
        poll_interval_s: float = 0.05,
        schema_policy: PostgresSchemaPolicy = "migrate",
    ) -> None:
        self._postgres_dsn = postgres_dsn
        self._postgres_schema = postgres_schema.strip() or "public"
        self._poll_interval_s = max(poll_interval_s, 0.01)
        self._schema_policy = schema_policy
        self._init_lock = asyncio.Lock()
        self._initialized = False

    async def append(self, *, response_id: str, event: str | None, data: str) -> int:
        await self._ensure_tables()
        from psycopg import AsyncConnection
        from psycopg.rows import dict_row

        async with await AsyncConnection.connect(self._postgres_dsn) as conn:
            conn.row_factory = dict_row
            async with conn.cursor() as cur:
                await cur.execute(
                    f"""
                    INSERT INTO {self._meta_table()}(response_id, next_seq, done)
                    VALUES (%s, 0, false)
                    ON CONFLICT (response_id) DO NOTHING
                    """,
                    (response_id,),
                )
                await cur.execute(
                    f"""
                    UPDATE {self._meta_table()}
                       SET next_seq = next_seq + 1
                     WHERE response_id = %s
                 RETURNING next_seq
                    """,
                    (response_id,),
                )
                row = await cur.fetchone()
                if row is None:
                    raise RuntimeError("failed to allocate event seq")
                seq = int(row["next_seq"])
                await cur.execute(
                    f"""
                    INSERT INTO {self._events_table()}(response_id, seq, event_type, payload_json)
                    VALUES (%s, %s, %s, %s::jsonb)
                    """,
                    (response_id, seq, event, json.dumps({"seq": seq, "event": event, "data": data}, ensure_ascii=False)),
                )
            await conn.commit()
        return seq

    async def mark_started(self, *, response_id: str) -> None:
        await self._ensure_tables()
        from psycopg import AsyncConnection

        async with await AsyncConnection.connect(self._postgres_dsn) as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    f"""
                    INSERT INTO {self._meta_table()}(response_id, next_seq, done, run_status, effective_run_status)
                    VALUES (%s, 0, false, 'started', 'in_progress')
                    ON CONFLICT (response_id) DO UPDATE
                       SET done = false,
                           run_status = EXCLUDED.run_status,
                           effective_run_status = EXCLUDED.effective_run_status
                    """,
                    (response_id,),
                )
            await conn.commit()

    async def mark_cancel_requested(self, *, response_id: str) -> None:
        await self._ensure_tables()
        from psycopg import AsyncConnection

        async with await AsyncConnection.connect(self._postgres_dsn) as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    f"""
                    UPDATE {self._meta_table()}
                       SET run_status = 'aborted',
                           effective_run_status = 'cancelled'
                     WHERE response_id = %s
                       AND done = false
                    """,
                    (response_id,),
                )
            await conn.commit()

    async def mark_final(
        self,
        *,
        response_id: str,
        run_status: str,
        effective_run_status: str | None = None,
        response_json: dict[str, Any] | None = None,
        error: AnyAgentResponseError | None = None,
    ) -> None:
        await self._ensure_tables()
        from psycopg import AsyncConnection

        async with await AsyncConnection.connect(self._postgres_dsn) as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    f"""
                    INSERT INTO {self._meta_table()}(response_id, next_seq, done, run_status, effective_run_status, response_json, error_json)
                    VALUES (%s, 0, true, %s, %s, %s::jsonb, %s::jsonb)
                    ON CONFLICT (response_id) DO UPDATE
                       SET done = true,
                           run_status = EXCLUDED.run_status,
                           effective_run_status = EXCLUDED.effective_run_status,
                           response_json = EXCLUDED.response_json,
                           error_json = EXCLUDED.error_json
                    """,
                    (
                        response_id,
                        run_status,
                        effective_run_status or run_status,
                        json.dumps(response_json, ensure_ascii=False) if response_json is not None else None,
                        error.model_dump_json(exclude_none=True) if error is not None else None,
                    ),
                )
            await conn.commit()

    async def get_response(self, response_id: str) -> dict[str, Any] | None:
        meta = await self._get_meta_row(response_id)
        return _loads_json_dict(meta.get("response_json")) if meta else None

    async def get_status(self, response_id: str) -> tuple[str | None, AnyAgentResponseError | None]:
        meta = await self._get_meta_row(response_id)
        if not meta:
            return None, None
        error = None
        error_raw = meta.get("error_json")
        if isinstance(error_raw, str) and error_raw.strip():
            try:
                error = AnyAgentResponseError.model_validate_json(error_raw)
            except Exception:  # noqa: BLE001
                error = None
        return str(meta.get("effective_run_status") or "") or None, error

    async def list_events(self, *, response_id: str, last_seq: int = 0, limit: int = 200) -> InternalEventsListResponse:
        await self._ensure_tables()
        from psycopg import AsyncConnection
        from psycopg.rows import dict_row

        meta = await self._get_meta_row(response_id)
        items: list[InternalEventItem] = []
        async with await AsyncConnection.connect(self._postgres_dsn) as conn:
            conn.row_factory = dict_row
            async with conn.cursor() as cur:
                await cur.execute(
                    f"""
                    SELECT seq, event_type, payload_json
                      FROM {self._events_table()}
                     WHERE response_id = %s
                       AND seq > %s
                     ORDER BY seq ASC
                     LIMIT %s
                    """,
                    (response_id, max(last_seq, 0), max(limit, 0)),
                )
                rows = await cur.fetchall()
        for row in rows or []:
            payload = row.get("payload_json")
            if isinstance(payload, dict):
                try:
                    items.append(InternalEventItem.model_validate(payload))
                    continue
                except Exception:  # noqa: BLE001
                    pass
            items.append(
                InternalEventItem(
                    seq=int(row.get("seq") or 0),
                    event=row.get("event_type"),
                    data=json.dumps(payload, ensure_ascii=False) if isinstance(payload, dict) else "",
                )
            )
        latest = await self.latest_seq(response_id)
        next_last_seq = last_seq
        if items:
            next_last_seq = items[-1].seq
        elif latest > 0:
            next_last_seq = latest
        return InternalEventsListResponse(
            response_id=response_id,
            requested_last_seq=max(last_seq, 0),
            next_last_seq=max(next_last_seq, 0),
            events=items,
            done=bool(meta and meta.get("done")),
            run_status=None if meta is None else meta.get("run_status"),
            effective_run_status=None if meta is None else meta.get("effective_run_status"),
        )

    async def latest_seq(self, response_id: str) -> int:
        await self._ensure_tables()
        from psycopg import AsyncConnection

        async with await AsyncConnection.connect(self._postgres_dsn) as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    f"SELECT COALESCE(MAX(seq), 0) FROM {self._events_table()} WHERE response_id = %s",
                    (response_id,),
                )
                row = await cur.fetchone()
        return int(row[0] if row else 0)

    async def stream_events(self, *, response_id: str, last_seq: int = 0) -> AsyncIterator[InternalEventItem]:
        next_seq = max(last_seq, 0)
        while True:
            resp = await self.list_events(response_id=response_id, last_seq=next_seq, limit=200)
            for item in resp.events:
                if item.seq <= next_seq:
                    continue
                yield item
                next_seq = item.seq
            if resp.done:
                return
            await asyncio.sleep(self._poll_interval_s)

    async def _get_meta_row(self, response_id: str) -> dict[str, Any] | None:
        await self._ensure_tables()
        from psycopg import AsyncConnection
        from psycopg.rows import dict_row

        async with await AsyncConnection.connect(self._postgres_dsn) as conn:
            conn.row_factory = dict_row
            async with conn.cursor() as cur:
                await cur.execute(
                    f"""
                    SELECT response_id, next_seq, done, run_status, effective_run_status, response_json, error_json
                      FROM {self._meta_table()}
                     WHERE response_id = %s
                     LIMIT 1
                    """,
                    (response_id,),
                )
                return await cur.fetchone()

    async def _ensure_tables(self) -> None:
        if self._initialized:
            return
        async with self._init_lock:
            if self._initialized:
                return
            await ensure_postgres_schema_objects(
                postgres_dsn=self._postgres_dsn,
                postgres_schema=self._postgres_schema,
                required_tables=["event_runs", "events"],
                create_statements=[
                    f"""
                    CREATE TABLE IF NOT EXISTS {self._meta_table()} (
                      response_id TEXT PRIMARY KEY,
                      next_seq BIGINT NOT NULL DEFAULT 0,
                      done BOOLEAN NOT NULL DEFAULT FALSE,
                      run_status TEXT NULL,
                      effective_run_status TEXT NULL,
                      response_json JSONB NULL,
                      error_json JSONB NULL
                    )
                    """,
                    f"""
                    CREATE TABLE IF NOT EXISTS {self._events_table()} (
                      response_id TEXT NOT NULL,
                      seq BIGINT NOT NULL,
                      event_type TEXT NULL,
                      payload_json JSONB NOT NULL,
                      PRIMARY KEY (response_id, seq)
                    )
                    """,
                ],
                policy=self._schema_policy,
            )
            self._initialized = True

    def _meta_table(self) -> str:
        return f"{self._postgres_schema}.event_runs"

    def _events_table(self) -> str:
        return f"{self._postgres_schema}.events"


class RedisEventStore:
    _APPEND_SCRIPT = """
local seq = redis.call('HINCRBY', KEYS[1], 'next_seq', 1)
local item = cjson.encode({ seq = seq, event = ARGV[1], data = ARGV[2] })
redis.call('RPUSH', KEYS[2], item)
if redis.call('HEXISTS', KEYS[1], 'done') == 0 then
  redis.call('HSET', KEYS[1], 'done', '0')
end
return seq
""".strip()

    _MARK_STARTED_SCRIPT = """
redis.call('HSET', KEYS[1], 'done', '0', 'run_status', 'started', 'effective_run_status', 'in_progress')
if redis.call('HEXISTS', KEYS[1], 'next_seq') == 0 then
  redis.call('HSET', KEYS[1], 'next_seq', '0')
end
return 1
""".strip()

    _MARK_CANCEL_SCRIPT = """
if redis.call('HGET', KEYS[1], 'done') == '1' then
  return 0
end
redis.call('HSET', KEYS[1], 'run_status', 'aborted', 'effective_run_status', 'cancelled')
return 1
""".strip()

    _MARK_FINAL_SCRIPT = """
redis.call('HSET', KEYS[1],
  'done', '1',
  'run_status', ARGV[1],
  'effective_run_status', ARGV[2],
  'response_json', ARGV[3],
  'error', ARGV[4]
)
if redis.call('HEXISTS', KEYS[1], 'next_seq') == 0 then
  redis.call('HSET', KEYS[1], 'next_seq', '0')
end
return 1
""".strip()
    _WRITE_META_SCRIPT = """
redis.call('HSET', KEYS[1],
  'done', ARGV[1],
  'run_status', ARGV[2],
  'effective_run_status', ARGV[3],
  'response_json', ARGV[4],
  'error', ARGV[5]
)
if redis.call('HEXISTS', KEYS[1], 'next_seq') == 0 then
  redis.call('HSET', KEYS[1], 'next_seq', '0')
end
return 1
""".strip()

    def __init__(
        self,
        *,
        redis_dsn: str,
        namespace: str = "anyagent",
        adapter: RedisEventStoreAdapter | None = None,
        poll_interval_s: float = 0.05,
        retention_s: int = 2 * 60 * 60,
    ) -> None:
        self._redis_dsn = redis_dsn
        self._namespace = namespace.strip() or "anyagent"
        self._adapter = adapter
        self._poll_interval_s = max(poll_interval_s, 0.01)
        self._retention_ms = max(1, int(retention_s * 1000))

    async def append(self, *, response_id: str, event: str | None, data: str) -> int:
        adapter = await self._get_adapter()
        meta_key = build_redis_event_meta_key(namespace=self._namespace, response_id=response_id)
        list_key = build_redis_event_list_key(namespace=self._namespace, response_id=response_id)
        seq = await adapter.eval(self._APPEND_SCRIPT, 2, meta_key, list_key, "" if event is None else event, data)
        await self._touch(adapter=adapter, response_id=response_id)
        return int(seq or 0)

    async def mark_started(self, *, response_id: str) -> None:
        adapter = await self._get_adapter()
        await adapter.eval(
            self._MARK_STARTED_SCRIPT,
            1,
            build_redis_event_meta_key(namespace=self._namespace, response_id=response_id),
        )
        await self._touch(adapter=adapter, response_id=response_id)

    async def mark_cancel_requested(self, *, response_id: str) -> None:
        adapter = await self._get_adapter()
        await adapter.eval(
            self._MARK_CANCEL_SCRIPT,
            1,
            build_redis_event_meta_key(namespace=self._namespace, response_id=response_id),
        )
        await self._touch(adapter=adapter, response_id=response_id)

    async def mark_final(
        self,
        *,
        response_id: str,
        run_status: str,
        effective_run_status: str | None = None,
        response_json: dict[str, Any] | None = None,
        error: AnyAgentResponseError | None = None,
    ) -> None:
        adapter = await self._get_adapter()
        await adapter.eval(
            self._MARK_FINAL_SCRIPT,
            1,
            build_redis_event_meta_key(namespace=self._namespace, response_id=response_id),
            run_status,
            effective_run_status or run_status,
            json.dumps(response_json, ensure_ascii=False) if response_json is not None else "",
            error.model_dump_json(exclude_none=True) if error is not None else "",
        )
        await self._touch(adapter=adapter, response_id=response_id)

    async def get_response(self, response_id: str) -> dict[str, Any] | None:
        meta = await self._get_meta(response_id)
        return _loads_json_dict(meta.get("response_json"))

    async def get_status(self, response_id: str) -> tuple[str | None, AnyAgentResponseError | None]:
        meta = await self._get_meta(response_id)
        error = None
        error_raw = meta.get("error")
        if isinstance(error_raw, str) and error_raw.strip():
            try:
                error = AnyAgentResponseError.model_validate_json(error_raw)
            except Exception:  # noqa: BLE001
                error = None
        return meta.get("effective_run_status"), error

    async def list_events(self, *, response_id: str, last_seq: int = 0, limit: int = 200) -> InternalEventsListResponse:
        adapter = await self._get_adapter()
        meta = await self._get_meta(response_id)
        items: list[InternalEventItem] = []
        if limit > 0:
            start = max(last_seq, 0)
            stop = start + max(limit, 0) - 1
            raw_items = await adapter.lrange(
                build_redis_event_list_key(namespace=self._namespace, response_id=response_id),
                start,
                stop,
            )
            items = _decode_internal_event_items(raw_items)
        latest_seq = await self.latest_seq(response_id)
        next_last_seq = last_seq
        if items:
            next_last_seq = items[-1].seq
        elif latest_seq > 0:
            next_last_seq = latest_seq
        return InternalEventsListResponse(
            response_id=response_id,
            requested_last_seq=max(last_seq, 0),
            next_last_seq=max(next_last_seq, 0),
            events=items,
            done=str(meta.get("done") or "0") == "1",
            run_status=meta.get("run_status"),
            effective_run_status=meta.get("effective_run_status"),
        )

    async def latest_seq(self, response_id: str) -> int:
        adapter = await self._get_adapter()
        length = await adapter.llen(build_redis_event_list_key(namespace=self._namespace, response_id=response_id))
        return int(length or 0)

    async def stream_events(self, *, response_id: str, last_seq: int = 0) -> AsyncIterator[InternalEventItem]:
        next_seq = max(last_seq, 0)
        while True:
            resp = await self.list_events(response_id=response_id, last_seq=next_seq, limit=200)
            for item in resp.events:
                if item.seq <= next_seq:
                    continue
                yield item
                next_seq = item.seq
            if resp.done:
                return
            await asyncio.sleep(self._poll_interval_s)

    async def _get_meta(self, response_id: str) -> dict[str, str]:
        adapter = await self._get_adapter()
        raw = await adapter.hgetall(build_redis_event_meta_key(namespace=self._namespace, response_id=response_id))
        return raw if isinstance(raw, dict) else {}

    async def _touch(self, *, adapter: RedisEventStoreAdapter, response_id: str) -> None:
        await adapter.pexpire(
            build_redis_event_meta_key(namespace=self._namespace, response_id=response_id),
            self._retention_ms,
        )
        await adapter.pexpire(
            build_redis_event_list_key(namespace=self._namespace, response_id=response_id),
            self._retention_ms,
        )

    async def _get_adapter(self) -> RedisEventStoreAdapter:
        if self._adapter is not None:
            return self._adapter
        try:
            from redis import asyncio as redis_asyncio  # type: ignore[import-not-found]
        except Exception as e:  # noqa: BLE001
            raise RuntimeError("redis event store requires `redis` package to be installed") from e
        client = redis_asyncio.from_url(self._redis_dsn, encoding="utf-8", decode_responses=True)
        self._adapter = client
        return client

    async def warm_response(
        self,
        *,
        response_id: str,
        events: list[InternalEventItem],
        done: bool,
        run_status: str | None,
        effective_run_status: str | None,
        response_json: dict[str, Any] | None,
        error: AnyAgentResponseError | None,
    ) -> None:
        adapter = await self._get_adapter()
        meta_key = build_redis_event_meta_key(namespace=self._namespace, response_id=response_id)
        list_key = build_redis_event_list_key(namespace=self._namespace, response_id=response_id)
        await adapter.eval(
            self._WRITE_META_SCRIPT,
            1,
            meta_key,
            "1" if done else "0",
            run_status or ("completed" if done else "started"),
            effective_run_status or run_status or ("completed" if done else "in_progress"),
            json.dumps(response_json, ensure_ascii=False) if response_json is not None else "",
            error.model_dump_json(exclude_none=True) if error is not None else "",
        )
        if events:
            for item in events:
                await adapter.eval(
                    self._APPEND_SCRIPT,
                    2,
                    meta_key,
                    list_key,
                    "" if item.event is None else item.event,
                    item.data,
                )
        await self._touch(adapter=adapter, response_id=response_id)


def build_redis_event_store(*, namespace: str | None = None, redis_dsn: str | None = None) -> RedisEventStore:
    settings = StorageSettings()
    effective_dsn = redis_dsn or (str(settings.redis_dsn) if settings.redis_dsn is not None else None)
    if effective_dsn is None:
        raise RuntimeError("redis event store requires REDIS_DSN")
    effective_namespace = namespace or settings.redis_namespace
    return RedisEventStore(
        redis_dsn=effective_dsn,
        namespace=effective_namespace,
        retention_s=settings.event_store_retention_s,
    )


class CachedEventStore:
    def __init__(self, *, primary: PostgresEventStore, cache: RedisEventStore) -> None:
        self._primary = primary
        self._cache = cache

    async def append(self, *, response_id: str, event: str | None, data: str) -> int:
        seq = await self._primary.append(response_id=response_id, event=event, data=data)
        await self._cache.append(response_id=response_id, event=event, data=data)
        return seq

    async def mark_started(self, *, response_id: str) -> None:
        await self._primary.mark_started(response_id=response_id)
        await self._cache.mark_started(response_id=response_id)

    async def mark_cancel_requested(self, *, response_id: str) -> None:
        await self._primary.mark_cancel_requested(response_id=response_id)
        await self._cache.mark_cancel_requested(response_id=response_id)

    async def mark_final(
        self,
        *,
        response_id: str,
        run_status: str,
        effective_run_status: str | None = None,
        response_json: dict[str, Any] | None = None,
        error: AnyAgentResponseError | None = None,
    ) -> None:
        await self._primary.mark_final(
            response_id=response_id,
            run_status=run_status,
            effective_run_status=effective_run_status,
            response_json=response_json,
            error=error,
        )
        await self._cache.mark_final(
            response_id=response_id,
            run_status=run_status,
            effective_run_status=effective_run_status,
            response_json=response_json,
            error=error,
        )

    async def get_response(self, response_id: str) -> dict[str, Any] | None:
        cached = await self._cache.get_response(response_id)
        if cached is not None:
            return cached
        payload = await self._primary.get_response(response_id)
        if payload is not None:
            await self._warm(response_id=response_id)
        return payload

    async def get_status(self, response_id: str) -> tuple[str | None, AnyAgentResponseError | None]:
        cached = await self._cache.get_status(response_id)
        if cached[0] is not None:
            return cached
        status = await self._primary.get_status(response_id)
        if status[0] is not None:
            await self._warm(response_id=response_id)
        return status

    async def list_events(self, *, response_id: str, last_seq: int = 0, limit: int = 200) -> InternalEventsListResponse:
        cached = await self._cache.list_events(response_id=response_id, last_seq=last_seq, limit=limit)
        if cached.events or cached.done:
            return cached
        resp = await self._primary.list_events(response_id=response_id, last_seq=last_seq, limit=limit)
        if resp.events or resp.done:
            await self._warm(response_id=response_id)
        return resp

    async def latest_seq(self, response_id: str) -> int:
        cached = await self._cache.latest_seq(response_id)
        if cached > 0:
            return cached
        latest = await self._primary.latest_seq(response_id)
        if latest > 0:
            await self._warm(response_id=response_id)
        return latest

    async def stream_events(self, *, response_id: str, last_seq: int = 0) -> AsyncIterator[InternalEventItem]:
        next_seq = max(last_seq, 0)
        while True:
            resp = await self.list_events(response_id=response_id, last_seq=next_seq, limit=200)
            for item in resp.events:
                if item.seq <= next_seq:
                    continue
                yield item
                next_seq = item.seq
            if resp.done:
                return
            await asyncio.sleep(0.05)

    async def _warm(self, *, response_id: str) -> None:
        resp = await self._primary.list_events(response_id=response_id, last_seq=0, limit=10000)
        _, error = await self._primary.get_status(response_id)
        payload = await self._primary.get_response(response_id)
        await self._cache.warm_response(
            response_id=response_id,
            events=resp.events,
            done=resp.done,
            run_status=resp.run_status,
            effective_run_status=resp.effective_run_status,
            response_json=payload,
            error=error,
        )


def build_postgres_event_store(*, postgres_dsn: str | None = None, postgres_schema: str | None = None) -> PostgresEventStore:
    settings = StorageSettings()
    effective_dsn = postgres_dsn or (str(settings.postgres_dsn) if settings.postgres_dsn is not None else None)
    if effective_dsn is None:
        raise RuntimeError("postgres event store requires POSTGRES_DSN")
    effective_schema = postgres_schema or settings.postgres_schema
    return PostgresEventStore(
        postgres_dsn=effective_dsn,
        postgres_schema=effective_schema,
        schema_policy=settings.postgres_schema_policy,
    )


def build_cached_event_store() -> CachedEventStore:
    return CachedEventStore(
        primary=build_postgres_event_store(),
        cache=build_redis_event_store(),
    )


def build_redis_event_meta_key(*, namespace: str, response_id: str) -> str:
    ns = namespace.strip() or "anyagent"
    return f"{ns}:events:meta:{response_id}"


def build_redis_event_list_key(*, namespace: str, response_id: str) -> str:
    ns = namespace.strip() or "anyagent"
    return f"{ns}:events:list:{response_id}"


def _decode_internal_event_items(raw_items: list[str]) -> list[InternalEventItem]:
    out: list[InternalEventItem] = []
    for raw in raw_items:
        try:
            payload = json.loads(raw)
            out.append(InternalEventItem.model_validate(payload))
        except Exception:  # noqa: BLE001
            continue
    return out


def _loads_json_dict(value: str | None) -> dict[str, Any] | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        payload = json.loads(value)
    except Exception:  # noqa: BLE001
        return None
    return payload if isinstance(payload, dict) else None
