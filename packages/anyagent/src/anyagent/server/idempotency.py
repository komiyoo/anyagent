from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any


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
