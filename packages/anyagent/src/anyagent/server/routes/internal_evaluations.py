from __future__ import annotations

import time
import uuid
from typing import Any

import httpx
from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from anyagent.protocol.evaluations import (
    EvalCase,
    EvalCaseResult,
    EvalDatasetResponse,
    EvalDatasetsResponse,
    EvalDatasetUpsertRequest,
    EvalRun,
    EvalRunRequest,
    EvalRunResponse,
    EvalRunsResponse,
)
from anyagent.server.handlers.auth import _require_user_auth


def create_internal_evaluations_router() -> APIRouter:
    router = APIRouter()

    @router.get("/internal/evaluations/datasets")
    async def internal_eval_datasets(
        req: Request,
        agent_id: str | None = None,
        authorization: str | None = Header(default=None),
    ) -> JSONResponse:
        state = req.app.state.anyagent
        _require_user_auth(state, authorization)
        datasets = await state.evaluation_store.list_datasets(agent_id=agent_id)
        return JSONResponse(EvalDatasetsResponse(datasets=datasets).model_dump(exclude_none=True))

    @router.post("/internal/evaluations/datasets")
    async def internal_eval_dataset_upsert(
        req: Request,
        authorization: str | None = Header(default=None),
    ) -> JSONResponse:
        state = req.app.state.anyagent
        _require_user_auth(state, authorization)
        dataset = await state.evaluation_store.upsert_dataset(EvalDatasetUpsertRequest.model_validate(await req.json()))
        return JSONResponse(EvalDatasetResponse(dataset=dataset).model_dump(exclude_none=True))

    @router.get("/internal/evaluations/datasets/{dataset_id}")
    async def internal_eval_dataset_get(
        req: Request,
        dataset_id: str,
        authorization: str | None = Header(default=None),
    ) -> JSONResponse:
        state = req.app.state.anyagent
        _require_user_auth(state, authorization)
        dataset = await state.evaluation_store.get_dataset(dataset_id)
        if dataset is None:
            raise HTTPException(status_code=404, detail=f"unknown dataset_id: {dataset_id}")
        return JSONResponse(EvalDatasetResponse(dataset=dataset).model_dump(exclude_none=True))

    @router.delete("/internal/evaluations/datasets/{dataset_id}")
    async def internal_eval_dataset_delete(
        req: Request,
        dataset_id: str,
        authorization: str | None = Header(default=None),
    ) -> JSONResponse:
        state = req.app.state.anyagent
        _require_user_auth(state, authorization)
        deleted = await state.evaluation_store.delete_dataset(dataset_id)
        return JSONResponse({"ok": True, "deleted": deleted, "dataset_id": dataset_id})

    @router.post("/internal/evaluations/run")
    async def internal_eval_run(
        req: Request,
        authorization: str | None = Header(default=None),
    ) -> JSONResponse:
        state = req.app.state.anyagent
        _require_user_auth(state, authorization)
        run_request = EvalRunRequest.model_validate(await req.json())
        dataset = await state.evaluation_store.get_dataset(run_request.dataset_id)
        if dataset is None:
            raise HTTPException(status_code=404, detail=f"unknown dataset_id: {run_request.dataset_id}")
        agent_id = run_request.agent_id or dataset.agent_id
        if not agent_id:
            raise HTTPException(status_code=400, detail="agent_id is required when dataset has no agent_id")
        state.require_pack(agent_id, external=False)

        eval_run = EvalRun(
            eval_run_id=f"eval_{uuid.uuid4().hex[:16]}",
            dataset_id=dataset.dataset_id,
            agent_id=agent_id,
            status="running",
            total_cases=len(dataset.cases if run_request.max_cases is None else dataset.cases[: run_request.max_cases]),
            metadata=run_request.metadata,
        )
        await state.evaluation_store.upsert_run(eval_run)
        results = await _run_eval_cases(req=req, run_request=run_request, run=eval_run, cases=dataset.cases[: eval_run.total_cases])
        completed = eval_run.model_copy(
            update={
                "status": "completed",
                "completed_at_ms": int(time.time() * 1000),
                "results": results,
                "passed_cases": sum(1 for item in results if item.status == "passed"),
                "failed_cases": sum(1 for item in results if item.status == "failed"),
                "unscored_cases": sum(1 for item in results if item.status == "unscored"),
                "error_cases": sum(1 for item in results if item.status == "error"),
            }
        )
        await state.evaluation_store.upsert_run(completed)
        return JSONResponse(EvalRunResponse(run=completed).model_dump(exclude_none=True))

    @router.get("/internal/evaluations/runs")
    async def internal_eval_runs(
        req: Request,
        dataset_id: str | None = None,
        limit: int = 100,
        authorization: str | None = Header(default=None),
    ) -> JSONResponse:
        state = req.app.state.anyagent
        _require_user_auth(state, authorization)
        runs = await state.evaluation_store.list_runs(dataset_id=dataset_id, limit=limit)
        return JSONResponse(EvalRunsResponse(dataset_id=dataset_id, runs=runs).model_dump(exclude_none=True))

    @router.get("/internal/evaluations/runs/{eval_run_id}")
    async def internal_eval_run_get(
        req: Request,
        eval_run_id: str,
        authorization: str | None = Header(default=None),
    ) -> JSONResponse:
        state = req.app.state.anyagent
        _require_user_auth(state, authorization)
        run = await state.evaluation_store.get_run(eval_run_id)
        if run is None:
            raise HTTPException(status_code=404, detail=f"unknown eval_run_id: {eval_run_id}")
        return JSONResponse(EvalRunResponse(run=run).model_dump(exclude_none=True))

    return router


async def _run_eval_cases(
    *,
    req: Request,
    run_request: EvalRunRequest,
    run: EvalRun,
    cases: list[EvalCase],
) -> list[EvalCaseResult]:
    state = req.app.state.anyagent
    headers = {"authorization": f"Bearer {state.api_key}"} if state.api_key else {}
    results: list[EvalCaseResult] = []
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=req.app), base_url="http://anyagent.local") as client:
        for case in cases:
            body: dict[str, Any] = {
                "input": case.input,
                "metadata": {
                    "agent_id": run.agent_id,
                    "session_key": f"{run_request.session_key_prefix}:{run.eval_run_id}:{case.case_id}",
                },
            }
            if run_request.model:
                body["model"] = run_request.model
            try:
                response = await client.post("/v1/responses", headers=headers, json=body)
                response.raise_for_status()
                payload = response.json()
                actual = _response_text(payload)
                results.append(_score_case(case=case, response_id=str(payload.get("id") or ""), actual=actual))
            except Exception as e:  # noqa: BLE001
                results.append(EvalCaseResult(case_id=case.case_id, status="error", expected_output=case.expected_output, error=str(e)))
    return results


def _score_case(*, case: EvalCase, response_id: str, actual: str | None) -> EvalCaseResult:
    if case.expected_output is None:
        return EvalCaseResult(
            case_id=case.case_id,
            status="unscored",
            response_id=response_id,
            expected_output=None,
            actual_output=actual,
        )
    passed = (actual or "").strip() == case.expected_output.strip()
    return EvalCaseResult(
        case_id=case.case_id,
        status="passed" if passed else "failed",
        score=1.0 if passed else 0.0,
        response_id=response_id,
        expected_output=case.expected_output,
        actual_output=actual,
    )


def _response_text(payload: dict[str, Any]) -> str | None:
    chunks: list[str] = []
    for item in payload.get("output") or []:
        if not isinstance(item, dict):
            continue
        for part in item.get("content") or []:
            if isinstance(part, dict) and isinstance(part.get("text"), str):
                chunks.append(part["text"])
    return "".join(chunks) if chunks else None
