from __future__ import annotations

import argparse
import asyncio
import os
import tempfile
from pathlib import Path
from uuid import uuid4

from anyagent_agent_api.settings import Settings
from anyagent_agent_api.storage.migrate import apply_postgres_migrations
from anyagent_agent_api.storage.rollout_replay import ReplayFilters, _replay
from anyagent_agent_api.storage.runtime import create_storage_runtime


_EVENT_CHAIN_TEMPLATE: list[tuple[str | None, str]] = [
    ("response.created", '{"type":"response.created"}'),
    ("response.output_item.added", '{"type":"response.output_item.added","index":0}'),
    ("response.completed", '{"type":"response.completed"}'),
    (None, "[DONE]"),
]


def _assert(condition: bool, message: str) -> None:
    """Raise RuntimeError when acceptance assertion fails."""
    if not condition:
        raise RuntimeError(message)


def _build_base_settings(workspace_dir: str) -> dict[str, str]:
    """Build common settings payload for acceptance-only runtimes."""
    return {
        "WORKSPACE_DIR": workspace_dir,
        "AGENT_API_KEY": "acceptance-agent-api-key",
        "OPENAI_API_KEY": "acceptance-openai-api-key",
        "TOOL_RUNTIME_INTERNAL_KEY": "acceptance-tool-runtime-key",
    }


def _normalize_records(rows: list[tuple[int, str | None, str]]) -> list[tuple[int, str | None, str]]:
    """Normalize event tuples for deterministic comparisons."""
    return [(int(seq), event if isinstance(event, str) else None, str(data)) for seq, event, data in rows]


async def _write_and_read_event_chain(
    *,
    settings: Settings,
    session_partition_key: str,
    response_id: str,
    idempotency_key: str,
) -> list[tuple[int, str | None, str]]:
    """Write one deterministic event chain and read it back from Event Store."""
    runtime = await create_storage_runtime(settings)
    try:
        created, _ = await runtime.run_store.try_create_started(
            response_id=response_id,
            session_partition_key=session_partition_key,
            idempotency_key=idempotency_key,
            stream=True,
        )
        _assert(created is True, "run should be created on first idempotency key")

        expected_len = len(_EVENT_CHAIN_TEMPLATE)
        for event_name, data in _EVENT_CHAIN_TEMPLATE:
            await runtime.event_store.append(
                response_id=response_id,
                session_partition_key=session_partition_key,
                event=event_name,
                data=data,
            )

        rows = await runtime.event_store.list(response_id=response_id, after_seq=0, limit=200)
        chain = _normalize_records([(r.seq, r.event, r.data) for r in rows])
        _assert(len(chain) == expected_len, "event store should contain complete event chain")
        _assert([seq for seq, _, _ in chain] == list(range(1, expected_len + 1)), "event seq should be contiguous from 1")

        await runtime.run_store.set_final(
            response_id=response_id,
            status="completed",
            final_response_json={"id": response_id, "object": "response"},
            error_json=None,
        )
        return chain
    finally:
        await runtime.aclose()


def _extract_rollout_event_chain(*, root_dir: Path, session_partition_key: str, response_id: str) -> list[tuple[int, str | None, str]]:
    """Read persisted `event_appended` records from local rollout files."""
    replay = _replay(
        root_dir=root_dir,
        filters=ReplayFilters(
            session_partition_key=session_partition_key,
            response_id=response_id,
            kinds={"event_appended"},
            last_seq=0,
            limit=200,
        ),
        include_fingerprint=False,
    )
    rows: list[tuple[int, str | None, str]] = []
    for rec in replay.get("records", []):
        if not isinstance(rec, dict):
            continue
        seq = rec.get("seq")
        if not isinstance(seq, int):
            continue
        event = rec.get("event") if isinstance(rec.get("event"), str) else None
        data = rec.get("data")
        rows.append((seq, event, str(data) if data is not None else ""))
    return _normalize_records(rows)


def _strip_seq(rows: list[tuple[int, str | None, str]]) -> list[tuple[str | None, str]]:
    """Drop sequence number for cross-storage semantic comparisons."""
    return [(event, data) for _, event, data in rows]


async def _run_none_mode_case() -> tuple[list[tuple[int, str | None, str]], list[tuple[int, str | None, str]]]:
    """Run local `STORAGE_MODE=none` case and return in-memory/rollout chains."""
    with tempfile.TemporaryDirectory(prefix="anyagent-rollout-consistency-none-") as td:
        workspace_dir = Path(td).resolve()
        rollout_root = workspace_dir / "rollouts"

        raw = _build_base_settings(str(workspace_dir))
        raw["STORAGE_MODE"] = "none"
        raw["ROLLOUT_ROOT_DIR"] = str(rollout_root)
        settings = Settings.model_validate(raw)

        session_partition_key = "main::rollout-consistency-none"
        response_id = f"resp_none_{uuid4().hex[:12]}"
        idempotency_key = f"idem_none_{uuid4().hex[:12]}"

        chain_from_event_store = await _write_and_read_event_chain(
            settings=settings,
            session_partition_key=session_partition_key,
            response_id=response_id,
            idempotency_key=idempotency_key,
        )
        chain_from_rollout = _extract_rollout_event_chain(
            root_dir=rollout_root,
            session_partition_key=session_partition_key,
            response_id=response_id,
        )
        _assert(
            _strip_seq(chain_from_event_store) == _strip_seq(chain_from_rollout),
            "none mode rollout.jsonl chain should match in-memory event store chain",
        )
        return chain_from_event_store, chain_from_rollout


async def _run_external_mode_case(*, postgres_dsn: str, redis_dsn: str) -> list[tuple[int, str | None, str]]:
    """Run `STORAGE_MODE=external` case and return external event chain."""
    schema = f"acc_rollout_{uuid4().hex[:16]}"
    with tempfile.TemporaryDirectory(prefix="anyagent-rollout-consistency-ext-") as td:
        workspace_dir = Path(td).resolve()
        raw = _build_base_settings(str(workspace_dir))
        raw["STORAGE_MODE"] = "external"
        raw["POSTGRES_DSN"] = postgres_dsn
        raw["REDIS_DSN"] = redis_dsn
        raw["POSTGRES_SCHEMA"] = schema
        settings = Settings.model_validate(raw)

        apply_postgres_migrations(settings=settings)

        session_partition_key = "main::rollout-consistency-external"
        response_id = f"resp_ext_{uuid4().hex[:12]}"
        idempotency_key = f"idem_ext_{uuid4().hex[:12]}"
        return await _write_and_read_event_chain(
            settings=settings,
            session_partition_key=session_partition_key,
            response_id=response_id,
            idempotency_key=idempotency_key,
        )


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse script CLI options."""
    parser = argparse.ArgumentParser(
        description="Verify rollout.jsonl (none mode) and external storage event chains stay semantically consistent."
    )
    parser.add_argument(
        "--require-external",
        action="store_true",
        help="Fail when POSTGRES_DSN/REDIS_DSN are missing instead of skipping external comparison.",
    )
    return parser.parse_args(argv)


async def _main_async(*, require_external: bool) -> None:
    """Execute rollout consistency smoke checks."""
    chain_none_event_store, chain_none_rollout = await _run_none_mode_case()
    _assert(
        _strip_seq(chain_none_event_store) == _strip_seq(chain_none_rollout),
        "none mode event chain should be identical between event store and rollout replay",
    )

    postgres_dsn = (os.getenv("POSTGRES_DSN") or "").strip()
    redis_dsn = (os.getenv("REDIS_DSN") or "").strip()
    has_external_env = bool(postgres_dsn and redis_dsn)
    if not has_external_env:
        if require_external:
            raise RuntimeError("POSTGRES_DSN and REDIS_DSN are required when --require-external is set")
        print("skip: external consistency check (set POSTGRES_DSN + REDIS_DSN to enable)")
        print("ok: acceptance_rollout_storage_consistency_smoke (none mode)")
        return

    chain_external = await _run_external_mode_case(postgres_dsn=postgres_dsn, redis_dsn=redis_dsn)
    _assert(
        _strip_seq(chain_external) == _strip_seq(chain_none_rollout),
        "external mode event chain should match none mode rollout.jsonl event chain",
    )
    print("ok: acceptance_rollout_storage_consistency_smoke (none + external)")


def main() -> int:
    """Run rollout consistency smoke checks for none/external storage modes."""
    args = _parse_args()
    asyncio.run(_main_async(require_external=bool(args.require_external)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
