from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


class WorkspaceInitResult(BaseModel):
    """Result emitted by `anyagent init`."""

    model_config = ConfigDict(extra="forbid")

    ok: bool
    workspace: str
    agent_id: str
    created: list[str]
    skipped: list[str]
    next: str


class WorkspaceDoctorFinding(BaseModel):
    """One `anyagent doctor` finding."""

    model_config = ConfigDict(extra="forbid")

    level: Literal["info", "warning", "error"]
    code: str
    message: str


class WorkspaceDoctorReport(BaseModel):
    """Typed report emitted by `anyagent doctor`."""

    model_config = ConfigDict(extra="forbid")

    ok: bool
    workspace: str
    findings: list[WorkspaceDoctorFinding]

