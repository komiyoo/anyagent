from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from time import time
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from anyagent.agent_packs import AgentCatalog, AgentPack
from anyagent.protocol.multi_agent import SpawnAgentArgs, SpawnAgentResult
from anyagent.protocol.openai_responses import FunctionToolParam


ThreadStatus = Literal["queued", "running", "completed", "failed", "closed"]


class ThreadRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    thread_id: str
    parent_thread_id: str | None = None
    root_thread_id: str
    agent_id: str
    depth: int = Field(ge=0)
    status: ThreadStatus
    created_at_ms: int
    updated_at_ms: int
    nickname: str | None = None
    last_message: str | None = None


@dataclass
class MultiAgentLimitsResolved:
    max_depth: int
    max_threads: int
    run_timeout_seconds: int


def _now_ms() -> int:
    return int(time() * 1000)


def stable_root_thread_id(session_partition_key: str) -> str:
    h = hashlib.sha256(session_partition_key.encode("utf-8")).hexdigest()
    return f"thr_{h[:24]}"


def spawn_agent_tool_schema() -> FunctionToolParam:
    schema = SpawnAgentArgs.model_json_schema()
    # Keep schema constraints consistent with Tool Runtime registry style.
    schema.setdefault("required", [])
    return FunctionToolParam(
        name="spawn_agent",
        description="Spawn a child agent thread (AnyAgent system tool).",
        parameters=schema,
        strict=True,
    )


class InMemoryThreadStore:
    def __init__(self) -> None:
        self._threads: dict[str, ThreadRecord] = {}
        self._children_by_parent: dict[str, set[str]] = {}

    def count_children(self, parent_thread_id: str) -> int:
        return len(self._children_by_parent.get(parent_thread_id, set()))

    def create_thread(self, rec: ThreadRecord) -> None:
        if rec.thread_id in self._threads:
            raise ValueError(f"duplicate thread_id: {rec.thread_id}")
        self._threads[rec.thread_id] = rec
        if rec.parent_thread_id is not None:
            self._children_by_parent.setdefault(rec.parent_thread_id, set()).add(rec.thread_id)

    def get(self, thread_id: str) -> ThreadRecord | None:
        return self._threads.get(thread_id)


class MultiAgentManager:
    """
    v0 Multi-Agent manager (in-memory, single instance).
    System tools are executed in Agent API (not Tool Runtime).
    """

    def __init__(self) -> None:
        self._store = InMemoryThreadStore()

    @staticmethod
    def system_tools_for_pack(pack: AgentPack) -> list[FunctionToolParam]:
        allow = [s for s in (pack.spec.multiagent.spawn_allow_agent_ids or []) if isinstance(s, str) and s.strip()]
        if not allow:
            return []
        return [spawn_agent_tool_schema()]

    @staticmethod
    def _resolve_limits(pack: AgentPack) -> MultiAgentLimitsResolved:
        lim = pack.spec.multiagent.limits
        return MultiAgentLimitsResolved(
            max_depth=lim.max_depth if lim and lim.max_depth is not None else 2,
            max_threads=lim.max_threads if lim and lim.max_threads is not None else 8,
            run_timeout_seconds=lim.run_timeout_seconds if lim and lim.run_timeout_seconds is not None else 600,
        )

    def spawn_agent(
        self,
        *,
        catalog: AgentCatalog,
        parent_pack: AgentPack,
        parent_thread_id: str,
        parent_depth: int,
        root_thread_id: str,
        arguments_json: object,
    ) -> str:
        """
        Execute `spawn_agent` system tool. Returns string output for `function_call_output`.
        """
        try:
            if isinstance(arguments_json, str):
                obj = json.loads(arguments_json)
            else:
                obj = arguments_json
        except Exception as e:  # noqa: BLE001
            raise ValueError(f"invalid arguments_json: {e}") from e

        if not isinstance(obj, dict):
            raise ValueError("spawn_agent arguments must be an object")

        args = SpawnAgentArgs.model_validate(obj)

        agent_id = (args.agent_id or args.agent_type or "").strip()
        allow = set(s.strip() for s in (parent_pack.spec.multiagent.spawn_allow_agent_ids or []) if isinstance(s, str) and s.strip())
        if agent_id not in allow:
            raise ValueError(f"spawn_agent agent_id not allowed: {agent_id}")

        child_pack = catalog.get(agent_id)
        if child_pack is None:
            raise ValueError(f"unknown agent_id: {agent_id}")
        if not child_pack.spec.exposed:
            raise ValueError(f"agent_id not exposed: {agent_id}")

        limits = self._resolve_limits(parent_pack)
        child_depth = parent_depth + 1
        if child_depth > limits.max_depth:
            raise ValueError("depth_limit_reached")

        if self._store.count_children(parent_thread_id) >= limits.max_threads:
            raise ValueError("threads_limit_reached")

        tid = f"thr_{uuid4().hex}"
        now = _now_ms()
        rec = ThreadRecord(
            thread_id=tid,
            parent_thread_id=parent_thread_id,
            root_thread_id=root_thread_id,
            agent_id=agent_id,
            depth=child_depth,
            status="queued",
            created_at_ms=now,
            updated_at_ms=now,
            nickname=None,
            last_message=(args.message or None),
        )
        self._store.create_thread(rec)

        out = SpawnAgentResult(thread_id=tid, agent_id=agent_id, nickname=None)
        return json.dumps(out.model_dump(exclude_none=True), ensure_ascii=False)

