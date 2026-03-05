from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

from anyagent_agent_api.storage.rollout import RolloutFileWriter
from anyagent_agent_api.storage.rollout_replay import ReplayFilters, _replay


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


async def main() -> None:
    with tempfile.TemporaryDirectory(prefix="anyagent-rollout-rotation-") as td:
        root = Path(td) / "rollouts"
        writer = RolloutFileWriter(
            root_dir=root,
            max_file_bytes=320,
            max_file_age_seconds=0,
            max_rotated_files=16,
        )
        spk = "main::rotation-smoke"
        rid = "resp_rotation_smoke"

        for i in range(1, 12):
            await writer.append_event_appended(
                session_partition_key=spk,
                response_id=rid,
                seq=i,
                event="response.delta",
                data="x" * 120 + str(i),
            )

        session_dirs = [p for p in root.iterdir() if p.is_dir()]
        _assert(len(session_dirs) == 1, "expected exactly one session rollout directory")
        files = sorted([p.name for p in session_dirs[0].iterdir() if p.is_file() and p.name.startswith("rollout")])
        _assert("rollout.jsonl" in files, "current rollout.jsonl should exist")
        _assert(any(name.startswith("rollout-") for name in files), "rotation should create at least one archived rollout file")

        result = _replay(
            root_dir=root,
            filters=ReplayFilters(
                session_partition_key=spk,
                response_id=rid,
                kinds={"event_appended"},
                last_seq=0,
                limit=200,
            ),
            include_fingerprint=False,
        )
        _assert(int(result["summary"]["matched"]) == 11, "replay should read events from rotated and current files")

    print("ok: acceptance_rollout_rotation_smoke")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
