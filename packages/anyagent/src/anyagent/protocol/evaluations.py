from __future__ import annotations

import time
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


EvalRunStatus = Literal["queued", "running", "completed", "failed"]
EvalCaseStatus = Literal["passed", "failed", "unscored", "error"]


class EvalCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    input: str
    expected_output: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class EvalDataset(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset_id: str
    name: str
    agent_id: str | None = None
    description: str | None = None
    cases: list[EvalCase] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at_ms: int = Field(default_factory=lambda: int(time.time() * 1000), ge=0)
    updated_at_ms: int = Field(default_factory=lambda: int(time.time() * 1000), ge=0)


class EvalDatasetUpsertRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset_id: str | None = None
    name: str
    agent_id: str | None = None
    description: str | None = None
    cases: list[EvalCase] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class EvalDatasetsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    datasets: list[EvalDataset] = Field(default_factory=list)


class EvalDatasetResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset: EvalDataset


class EvalCaseResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    status: EvalCaseStatus
    score: float | None = Field(default=None, ge=0, le=1)
    response_id: str | None = None
    expected_output: str | None = None
    actual_output: str | None = None
    error: str | None = None


class EvalRun(BaseModel):
    model_config = ConfigDict(extra="forbid")

    eval_run_id: str
    dataset_id: str
    agent_id: str
    status: EvalRunStatus
    created_at_ms: int = Field(default_factory=lambda: int(time.time() * 1000), ge=0)
    completed_at_ms: int | None = Field(default=None, ge=0)
    total_cases: int = Field(default=0, ge=0)
    passed_cases: int = Field(default=0, ge=0)
    failed_cases: int = Field(default=0, ge=0)
    unscored_cases: int = Field(default=0, ge=0)
    error_cases: int = Field(default=0, ge=0)
    results: list[EvalCaseResult] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class EvalRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset_id: str
    agent_id: str | None = None
    session_key_prefix: str = "eval"
    max_cases: int | None = Field(default=None, ge=1)
    model: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class EvalRunsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset_id: str | None = None
    runs: list[EvalRun] = Field(default_factory=list)


class EvalRunResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run: EvalRun
