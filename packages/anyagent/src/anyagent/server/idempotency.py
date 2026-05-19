from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from fastapi.responses import JSONResponse, Response, StreamingResponse

from anyagent.storage import StorageRuntime, resolve_nonstream_replay_payload

from .responses_optional import openai_error_response
from .streaming import build_external_response_stream_response


NewResponseIdFactory = Callable[[], str]
LookupExistingRun = Callable[[str], Awaitable[Any | None]]
CreateStartedRun = Callable[[str, str | None], Awaitable[Any]]
TryCreateStartedRun = Callable[[str, str], Awaitable[tuple[bool, Any]]]
ValidateReplayRun = Callable[[Any], Any | None]
BuildStreamReplayResponse = Callable[[str], Any]
BuildNonstreamReplayResponse = Callable[[Any, str], Awaitable[Any]]


@dataclass(slots=True)
class BeginOrReplayResponseRunResult:
    created: bool
    response_id: str
    run: Any | None = None
    response: Any | None = None


@dataclass(slots=True)
class DistributedResponseRunGate:
    created: bool
    response_id: str | None = None
    response: Response | None = None


def build_distributed_response_stream_response(*, storage: StorageRuntime, response_id: str) -> StreamingResponse:
    async def _iter_sse_from_store() -> Any:
        async for chunk in build_external_response_stream_response(
            run_store=storage.run_store,
            event_store=storage.event_store,
            response_id=response_id,
        ).body_iterator:
            yield chunk

    return StreamingResponse(_iter_sse_from_store(), media_type="text/event-stream")


async def begin_distributed_response_run(
    *,
    idempotency_key: str | None,
    stream: bool,
    session_partition_key: str,
    storage: StorageRuntime,
    new_response_id_factory: NewResponseIdFactory,
    nonstream_wait_timeout_s: float = 60.0,
) -> DistributedResponseRunGate:
    if idempotency_key is None:
        return DistributedResponseRunGate(created=False)

    def _validate_run(run: Any) -> Response | None:
        if getattr(run, "session_partition_key", None) != session_partition_key:
            return openai_error_response(
                409,
                message="Idempotency-Key conflict (session mismatch)",
                type_="invalid_request_error",
                code="idempotency_key_conflict",
            )
        return None

    gate = await begin_or_replay_response_run(
        idempotency_key=idempotency_key,
        stream=stream,
        new_response_id_factory=new_response_id_factory,
        try_create_started_run=lambda candidate_response_id, idem_value: storage.run_store.try_create_started(
            response_id=candidate_response_id,
            session_partition_key=session_partition_key,
            idempotency_key=idem_value,
            stream=stream,
        ),
        validate_run=_validate_run,
        build_stream_replay_response=lambda replay_response_id: build_distributed_response_stream_response(
            storage=storage,
            response_id=replay_response_id,
        ),
        build_nonstream_replay_response=lambda run, replay_response_id: resolve_nonstream_replay_payload(
            run_store=storage.run_store,
            run=run,
            response_id=replay_response_id,
            wait_timeout_s=nonstream_wait_timeout_s,
        ),
    )

    if gate.response is not None:
        if isinstance(gate.response, dict):
            return DistributedResponseRunGate(
                created=False,
                response_id=gate.response_id,
                response=JSONResponse(status_code=200, content=gate.response),
            )
        return DistributedResponseRunGate(
            created=False,
            response_id=gate.response_id,
            response=gate.response,
        )
    if not gate.created:
        return DistributedResponseRunGate(
            created=False,
            response_id=gate.response_id,
            response=openai_error_response(
                504,
                message="Idempotent request still in progress",
                type_="timeout_error",
            ),
        )

    return DistributedResponseRunGate(created=True, response_id=gate.response_id)


async def begin_or_replay_response_run(
    *,
    idempotency_key: str | None,
    stream: bool,
    new_response_id_factory: NewResponseIdFactory,
    lookup_existing_run: LookupExistingRun | None = None,
    create_started_run: CreateStartedRun | None = None,
    try_create_started_run: TryCreateStartedRun | None = None,
    validate_run: ValidateReplayRun | None = None,
    build_stream_replay_response: BuildStreamReplayResponse | None = None,
    build_nonstream_replay_response: BuildNonstreamReplayResponse | None = None,
) -> BeginOrReplayResponseRunResult:
    idem = idempotency_key.strip() if isinstance(idempotency_key, str) and idempotency_key.strip() else None

    if idem is None:
        response_id = new_response_id_factory()
        run = await _create_started(
            response_id=response_id,
            idempotency_key=None,
            create_started_run=create_started_run,
            try_create_started_run=try_create_started_run,
        )
        return BeginOrReplayResponseRunResult(created=True, response_id=response_id, run=run)

    if try_create_started_run is not None:
        candidate_response_id = new_response_id_factory()
        created, run = await try_create_started_run(candidate_response_id, idem)
        response_id = _resolve_response_id(run=run, fallback=candidate_response_id)
        immediate = validate_run(run) if validate_run is not None else None
        if immediate is not None:
            return BeginOrReplayResponseRunResult(created=False, response_id=response_id, run=run, response=immediate)
        if created:
            return BeginOrReplayResponseRunResult(created=True, response_id=response_id, run=run)
        return BeginOrReplayResponseRunResult(
            created=False,
            response_id=response_id,
            run=run,
            response=await _build_replay_response(
                stream=stream,
                response_id=response_id,
                run=run,
                build_stream_replay_response=build_stream_replay_response,
                build_nonstream_replay_response=build_nonstream_replay_response,
            ),
        )

    if lookup_existing_run is not None:
        run = await lookup_existing_run(idem)
        if run is not None:
            response_id = _resolve_response_id(run=run, fallback=new_response_id_factory())
            immediate = validate_run(run) if validate_run is not None else None
            if immediate is not None:
                return BeginOrReplayResponseRunResult(created=False, response_id=response_id, run=run, response=immediate)
            return BeginOrReplayResponseRunResult(
                created=False,
                response_id=response_id,
                run=run,
                response=await _build_replay_response(
                    stream=stream,
                    response_id=response_id,
                    run=run,
                    build_stream_replay_response=build_stream_replay_response,
                    build_nonstream_replay_response=build_nonstream_replay_response,
                ),
            )

    response_id = new_response_id_factory()
    run = await _create_started(
        response_id=response_id,
        idempotency_key=idem,
        create_started_run=create_started_run,
        try_create_started_run=try_create_started_run,
    )
    return BeginOrReplayResponseRunResult(created=True, response_id=response_id, run=run)


async def _create_started(
    *,
    response_id: str,
    idempotency_key: str | None,
    create_started_run: CreateStartedRun | None,
    try_create_started_run: TryCreateStartedRun | None,
) -> Any:
    if create_started_run is not None:
        return await create_started_run(response_id, idempotency_key)
    if try_create_started_run is not None and idempotency_key is not None:
        _created, run = await try_create_started_run(response_id, idempotency_key)
        return run
    return None


def _resolve_response_id(*, run: Any, fallback: str) -> str:
    response_id = getattr(run, "response_id", None)
    return response_id.strip() if isinstance(response_id, str) and response_id.strip() else fallback


async def _build_replay_response(
    *,
    stream: bool,
    response_id: str,
    run: Any,
    build_stream_replay_response: BuildStreamReplayResponse | None,
    build_nonstream_replay_response: BuildNonstreamReplayResponse | None,
) -> Any:
    if stream:
        if build_stream_replay_response is None:
            raise RuntimeError("build_stream_replay_response is required for stream replay")
        return build_stream_replay_response(response_id)
    if build_nonstream_replay_response is None:
        raise RuntimeError("build_nonstream_replay_response is required for non-stream replay")
    return await build_nonstream_replay_response(run, response_id)
