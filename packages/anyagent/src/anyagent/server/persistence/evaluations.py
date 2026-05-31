from __future__ import annotations

import json
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from anyagent.protocol.evaluations import EvalDataset, EvalDatasetUpsertRequest, EvalRun


class JsonEvaluationStore:
    def __init__(self, *, path: str | Path) -> None:
        self._path = Path(path).expanduser().resolve()
        self._lock = threading.Lock()

    async def list_datasets(self, *, agent_id: str | None = None) -> list[EvalDataset]:
        payload = self._read()
        datasets = [EvalDataset.model_validate(item) for item in payload.get("datasets", {}).values()]
        if agent_id is not None:
            datasets = [item for item in datasets if item.agent_id in {None, agent_id}]
        return sorted(datasets, key=lambda item: (item.updated_at_ms, item.dataset_id), reverse=True)

    async def get_dataset(self, dataset_id: str) -> EvalDataset | None:
        payload = self._read()
        raw = payload.get("datasets", {}).get(dataset_id)
        return None if raw is None else EvalDataset.model_validate(raw)

    async def upsert_dataset(self, request: EvalDatasetUpsertRequest) -> EvalDataset:
        now_ms = int(time.time() * 1000)
        dataset_id = request.dataset_id or f"ds_{uuid.uuid4().hex[:16]}"
        with self._lock:
            payload = self._read_unlocked()
            datasets: dict[str, Any] = payload.setdefault("datasets", {})
            previous = datasets.get(dataset_id)
            created_at_ms = now_ms
            if isinstance(previous, dict):
                created_at_ms = int(previous.get("created_at_ms") or now_ms)
            dataset = EvalDataset(
                dataset_id=dataset_id,
                name=request.name,
                agent_id=request.agent_id,
                description=request.description,
                cases=request.cases,
                metadata=request.metadata,
                created_at_ms=created_at_ms,
                updated_at_ms=now_ms,
            )
            datasets[dataset_id] = dataset.model_dump(mode="json", exclude_none=True)
            self._write_unlocked(payload)
            return dataset

    async def delete_dataset(self, dataset_id: str) -> bool:
        with self._lock:
            payload = self._read_unlocked()
            existed = payload.setdefault("datasets", {}).pop(dataset_id, None) is not None
            if existed:
                payload["runs"] = {
                    run_id: run
                    for run_id, run in payload.setdefault("runs", {}).items()
                    if not isinstance(run, dict) or run.get("dataset_id") != dataset_id
                }
                self._write_unlocked(payload)
            return existed

    async def upsert_run(self, run: EvalRun) -> EvalRun:
        with self._lock:
            payload = self._read_unlocked()
            payload.setdefault("runs", {})[run.eval_run_id] = run.model_dump(mode="json", exclude_none=True)
            self._write_unlocked(payload)
        return run

    async def get_run(self, eval_run_id: str) -> EvalRun | None:
        payload = self._read()
        raw = payload.get("runs", {}).get(eval_run_id)
        return None if raw is None else EvalRun.model_validate(raw)

    async def list_runs(self, *, dataset_id: str | None = None, limit: int = 100) -> list[EvalRun]:
        payload = self._read()
        runs = [EvalRun.model_validate(item) for item in payload.get("runs", {}).values()]
        if dataset_id is not None:
            runs = [item for item in runs if item.dataset_id == dataset_id]
        runs.sort(key=lambda item: (item.created_at_ms, item.eval_run_id), reverse=True)
        return runs[: max(1, min(int(limit), 500))]

    def _read(self) -> dict[str, Any]:
        with self._lock:
            return self._read_unlocked()

    def _read_unlocked(self) -> dict[str, Any]:
        if not self._path.is_file():
            return {"datasets": {}, "runs": {}}
        try:
            loaded = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"datasets": {}, "runs": {}}
        if not isinstance(loaded, dict):
            return {"datasets": {}, "runs": {}}
        loaded.setdefault("datasets", {})
        loaded.setdefault("runs", {})
        return loaded

    def _write_unlocked(self, payload: dict[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
