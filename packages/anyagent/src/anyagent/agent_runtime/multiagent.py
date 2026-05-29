from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass
from time import monotonic, time
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from anyagent.agent_packs import AgentCatalog, AgentPack
from anyagent.protocol.multi_agent import (
    AgentState,
    CloseAgentArgs,
    CloseAgentResult,
    ResumeAgentArgs,
    ResumeAgentResult,
    SendInputArgs,
    SendInputResult,
    SpawnAgentArgs,
    SpawnAgentResult,
    TaskArgs,
    TaskResult,
    WaitArgs,
    WaitResult,
)
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
    submission_seq: int = Field(default=0, ge=0)
    fork_context: bool = False
    explicit_skills: list[str] = Field(default_factory=list)


class SubmissionRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    submission_id: str
    thread_id: str
    created_at_ms: int
    message: str | None = None
    items_count: int = Field(default=0, ge=0)
    interrupt: bool | None = None


@dataclass
class MultiAgentLimitsResolved:
    max_depth: int
    max_threads: int
    run_timeout_seconds: int


def _now_ms() -> int:
    return int(time() * 1000)


def _normalize_skill_ids(values: list[object] | None, *, max_skills: int = 32) -> list[str]:
    if values is None:
        return []
    if not isinstance(values, list):
        raise ValueError("skills must be a list of strings")
    out: list[str] = []
    for v in values:
        if not isinstance(v, str):
            continue
        s = v.strip()
        if not s:
            continue
        if s not in out:
            out.append(s)
        if len(out) >= max_skills:
            break
    return out


def stable_root_thread_id(session_partition_key: str) -> str:
    h = hashlib.sha256(session_partition_key.encode("utf-8")).hexdigest()
    return f"thr_{h[:24]}"


def spawn_agent_tool_schema() -> FunctionToolParam:
    schema = SpawnAgentArgs.model_json_schema()
    # Keep schema constraints consistent with Tool Runtime registry style.
    schema.setdefault("required", [])
    return FunctionToolParam(
        name="spawn_agent",
        description="Spawn a child agent thread (anyagent system tool).",
        parameters=schema,
        strict=True,
    )


def task_tool_schema() -> FunctionToolParam:
    schema = TaskArgs.model_json_schema()
    return FunctionToolParam(
        name="task",
        description="Delegate a bounded task to an allowed child agent and return its final text output.",
        parameters=schema,
        strict=True,
    )


def send_input_tool_schema() -> FunctionToolParam:
    schema = SendInputArgs.model_json_schema()
    # Keep schema constraints consistent with Tool Runtime registry style.
    schema.setdefault("required", [])
    return FunctionToolParam(
        name="send_input",
        description="Send input to an existing child agent thread (anyagent system tool).",
        parameters=schema,
        strict=True,
    )


def wait_tool_schema() -> FunctionToolParam:
    schema = WaitArgs.model_json_schema()
    # Keep schema constraints consistent with Tool Runtime registry style.
    schema.setdefault("required", [])
    return FunctionToolParam(
        name="wait",
        description="Wait for one or more child agent threads to reach a terminal status (anyagent system tool).",
        parameters=schema,
        strict=True,
    )


def close_agent_tool_schema() -> FunctionToolParam:
    schema = CloseAgentArgs.model_json_schema()
    # Keep schema constraints consistent with Tool Runtime registry style.
    schema.setdefault("required", [])
    return FunctionToolParam(
        name="close_agent",
        description="Close a child agent thread and release resources (anyagent system tool).",
        parameters=schema,
        strict=True,
    )


def resume_agent_tool_schema() -> FunctionToolParam:
    schema = ResumeAgentArgs.model_json_schema()
    # Keep schema constraints consistent with Tool Runtime registry style.
    schema.setdefault("required", [])
    return FunctionToolParam(
        name="resume_agent",
        description="Resume a previously closed child agent thread (anyagent system tool).",
        parameters=schema,
        strict=True,
    )


class InMemoryThreadStore:
    def __init__(self) -> None:
        self._threads: dict[str, ThreadRecord] = {}
        self._children_by_parent: dict[str, set[str]] = {}
        self._submissions_by_thread: dict[str, list[SubmissionRecord]] = {}

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

    def get_required(self, thread_id: str) -> ThreadRecord:
        rec = self.get(thread_id)
        if rec is None:
            raise ValueError(f"thread_not_found: {thread_id}")
        return rec

    def is_descendant_of(self, *, thread_id: str, ancestor_thread_id: str, max_hops: int = 32) -> bool:
        """
        Returns True if thread_id is a descendant of ancestor_thread_id (or equals it).
        """
        if thread_id == ancestor_thread_id:
            return True
        cur = self.get(thread_id)
        hops = 0
        while cur is not None and cur.parent_thread_id is not None and hops < max_hops:
            if cur.parent_thread_id == ancestor_thread_id:
                return True
            cur = self.get(cur.parent_thread_id)
            hops += 1
        return False

    def record_submission(self, rec: SubmissionRecord) -> None:
        self._submissions_by_thread.setdefault(rec.thread_id, []).append(rec)

    def set_status(self, *, thread_id: str, status: ThreadStatus, last_message: str | None = None) -> None:
        rec = self.get_required(thread_id)
        rec.status = status
        rec.updated_at_ms = _now_ms()
        if last_message is not None:
            rec.last_message = last_message


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
        return [
            task_tool_schema(),
            spawn_agent_tool_schema(),
            send_input_tool_schema(),
            wait_tool_schema(),
            close_agent_tool_schema(),
            resume_agent_tool_schema(),
        ]

    @staticmethod
    def _resolve_limits(pack: AgentPack) -> MultiAgentLimitsResolved:
        lim = pack.spec.multiagent.limits
        return MultiAgentLimitsResolved(
            max_depth=lim.max_depth if lim and lim.max_depth is not None else 2,
            max_threads=lim.max_threads if lim and lim.max_threads is not None else 8,
            run_timeout_seconds=lim.run_timeout_seconds if lim and lim.run_timeout_seconds is not None else 600,
        )

    def _validate_parent_thread_context(
        self,
        *,
        parent_thread_id: str,
        parent_depth: int,
        root_thread_id: str,
    ) -> None:
        """
        Parent thread metadata is untrusted input (comes from request.metadata).
        Validate it against our in-memory store to prevent spoofing.
        """
        if parent_thread_id == root_thread_id:
            if parent_depth != 0:
                raise ValueError("invalid_parent_depth")
            return

        parent = self._store.get(parent_thread_id)
        if parent is None:
            raise ValueError("unknown_parent_thread")
        if parent.root_thread_id != root_thread_id:
            raise ValueError("parent_thread_root_mismatch")
        if parent.depth != parent_depth:
            raise ValueError("parent_thread_depth_mismatch")
        if parent.status == "closed":
            raise ValueError("parent_thread_closed")

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

        self._validate_parent_thread_context(
            parent_thread_id=parent_thread_id,
            parent_depth=parent_depth,
            root_thread_id=root_thread_id,
        )

        # Isolation defaults (req-13-5): do not inherit parent's skills/tools.
        explicit_skills = _normalize_skill_ids(args.skills)
        fork_context = bool(args.fork_context is True)

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
            fork_context=fork_context,
            explicit_skills=explicit_skills,
        )
        self._store.create_thread(rec)

        out = SpawnAgentResult(thread_id=tid, agent_id=agent_id, nickname=None)
        return json.dumps(out.model_dump(exclude_none=True), ensure_ascii=False)

    def send_input(
        self,
        *,
        parent_thread_id: str,
        parent_depth: int,
        root_thread_id: str,
        arguments_json: object,
    ) -> str:
        """
        Execute `send_input` system tool. Returns string output for `function_call_output`.
        """
        try:
            if isinstance(arguments_json, str):
                obj = json.loads(arguments_json)
            else:
                obj = arguments_json
        except Exception as e:  # noqa: BLE001
            raise ValueError(f"invalid arguments_json: {e}") from e

        if not isinstance(obj, dict):
            raise ValueError("send_input arguments must be an object")

        args = SendInputArgs.model_validate(obj)

        self._validate_parent_thread_context(
            parent_thread_id=parent_thread_id,
            parent_depth=parent_depth,
            root_thread_id=root_thread_id,
        )

        child = self._store.get_required(args.id)
        if child.root_thread_id != root_thread_id:
            raise ValueError("thread_root_mismatch")
        if parent_thread_id != root_thread_id and not self._store.is_descendant_of(
            thread_id=child.thread_id, ancestor_thread_id=parent_thread_id
        ):
            raise ValueError("thread_not_child")
        if child.status in {"completed", "failed", "closed"}:
            raise ValueError(f"thread_not_accepting_input: {child.status}")

        child.submission_seq += 1
        now = _now_ms()
        child.updated_at_ms = now
        if isinstance(args.message, str) and args.message.strip():
            child.last_message = args.message.strip()
        elif isinstance(args.items, list) and args.items:
            child.last_message = child.last_message or "input_items"

        submission_id = f"sub_{child.thread_id}_{child.submission_seq}"
        self._store.record_submission(
            SubmissionRecord(
                submission_id=submission_id,
                thread_id=child.thread_id,
                created_at_ms=now,
                message=(args.message.strip() if isinstance(args.message, str) and args.message.strip() else None),
                items_count=(len(args.items) if isinstance(args.items, list) else 0),
                interrupt=args.interrupt,
            )
        )

        out = SendInputResult(submission_id=submission_id)
        return json.dumps(out.model_dump(exclude_none=True), ensure_ascii=False)

    async def wait(
        self,
        *,
        parent_thread_id: str,
        parent_depth: int,
        root_thread_id: str,
        arguments_json: object,
    ) -> str:
        """
        Execute `wait` system tool. Returns string output for `function_call_output`.
        """
        try:
            if isinstance(arguments_json, str):
                obj = json.loads(arguments_json)
            else:
                obj = arguments_json
        except Exception as e:  # noqa: BLE001
            raise ValueError(f"invalid arguments_json: {e}") from e

        if not isinstance(obj, dict):
            raise ValueError("wait arguments must be an object")

        args = WaitArgs.model_validate(obj)

        self._validate_parent_thread_context(
            parent_thread_id=parent_thread_id,
            parent_depth=parent_depth,
            root_thread_id=root_thread_id,
        )

        ids = [s.strip() for s in args.ids if isinstance(s, str) and s.strip()]
        if not ids:
            raise ValueError("wait requires non-empty ids")

        terminal_statuses: set[ThreadStatus] = {"completed", "failed", "closed"}
        deadline = monotonic() + (args.timeout_ms / 1000.0)

        def _snapshot() -> tuple[dict[str, AgentState], set[str]]:
            states: dict[str, AgentState] = {}
            pending: set[str] = set()
            for tid in ids:
                if tid == root_thread_id:
                    states[tid] = AgentState(status="failed", message="root_thread_not_waitable")
                    continue

                rec = self._store.get(tid)
                if rec is None:
                    states[tid] = AgentState(status="failed", message="thread_not_found")
                    continue
                if rec.root_thread_id != root_thread_id:
                    states[tid] = AgentState(status="failed", message="thread_root_mismatch")
                    continue
                if parent_thread_id != root_thread_id and not self._store.is_descendant_of(
                    thread_id=rec.thread_id, ancestor_thread_id=parent_thread_id
                ):
                    states[tid] = AgentState(status="failed", message="thread_not_child")
                    continue

                states[tid] = AgentState(status=rec.status, message=rec.last_message)
                if rec.status not in terminal_statuses:
                    pending.add(tid)
            return states, pending

        states, pending = _snapshot()
        while pending and monotonic() < deadline:
            remaining = deadline - monotonic()
            await asyncio.sleep(min(0.25, max(0.0, remaining)))
            states, pending = _snapshot()

        out = WaitResult(agents_states=states, timed_out=bool(pending))
        return json.dumps(out.model_dump(exclude_none=True), ensure_ascii=False)

    def close_agent(
        self,
        *,
        parent_thread_id: str,
        parent_depth: int,
        root_thread_id: str,
        arguments_json: object,
    ) -> str:
        """
        Execute `close_agent` system tool. Returns string output for `function_call_output`.
        """
        try:
            if isinstance(arguments_json, str):
                obj = json.loads(arguments_json)
            else:
                obj = arguments_json
        except Exception as e:  # noqa: BLE001
            raise ValueError(f"invalid arguments_json: {e}") from e

        if not isinstance(obj, dict):
            raise ValueError("close_agent arguments must be an object")

        args = CloseAgentArgs.model_validate(obj)

        self._validate_parent_thread_context(
            parent_thread_id=parent_thread_id,
            parent_depth=parent_depth,
            root_thread_id=root_thread_id,
        )

        if args.id == root_thread_id:
            out = CloseAgentResult(ok=False)
            return json.dumps(out.model_dump(exclude_none=True), ensure_ascii=False)

        rec = self._store.get(args.id)
        if rec is None:
            out = CloseAgentResult(ok=False)
            return json.dumps(out.model_dump(exclude_none=True), ensure_ascii=False)

        if rec.root_thread_id != root_thread_id:
            out = CloseAgentResult(ok=False)
            return json.dumps(out.model_dump(exclude_none=True), ensure_ascii=False)

        if parent_thread_id != root_thread_id and not self._store.is_descendant_of(
            thread_id=rec.thread_id, ancestor_thread_id=parent_thread_id
        ):
            out = CloseAgentResult(ok=False)
            return json.dumps(out.model_dump(exclude_none=True), ensure_ascii=False)

        self._store.set_status(thread_id=rec.thread_id, status="closed")
        out = CloseAgentResult(ok=True)
        return json.dumps(out.model_dump(exclude_none=True), ensure_ascii=False)

    def resume_agent(
        self,
        *,
        parent_thread_id: str,
        parent_depth: int,
        root_thread_id: str,
        arguments_json: object,
    ) -> str:
        """
        Execute `resume_agent` system tool. Returns string output for `function_call_output`.
        """
        try:
            if isinstance(arguments_json, str):
                obj = json.loads(arguments_json)
            else:
                obj = arguments_json
        except Exception as e:  # noqa: BLE001
            raise ValueError(f"invalid arguments_json: {e}") from e

        if not isinstance(obj, dict):
            raise ValueError("resume_agent arguments must be an object")

        args = ResumeAgentArgs.model_validate(obj)

        self._validate_parent_thread_context(
            parent_thread_id=parent_thread_id,
            parent_depth=parent_depth,
            root_thread_id=root_thread_id,
        )

        if args.id == root_thread_id:
            out = ResumeAgentResult(ok=False)
            return json.dumps(out.model_dump(exclude_none=True), ensure_ascii=False)

        rec = self._store.get(args.id)
        if rec is None:
            out = ResumeAgentResult(ok=False)
            return json.dumps(out.model_dump(exclude_none=True), ensure_ascii=False)

        if rec.root_thread_id != root_thread_id:
            out = ResumeAgentResult(ok=False)
            return json.dumps(out.model_dump(exclude_none=True), ensure_ascii=False)

        if parent_thread_id != root_thread_id and not self._store.is_descendant_of(
            thread_id=rec.thread_id, ancestor_thread_id=parent_thread_id
        ):
            out = ResumeAgentResult(ok=False)
            return json.dumps(out.model_dump(exclude_none=True), ensure_ascii=False)

        if rec.status == "closed":
            self._store.set_status(thread_id=rec.thread_id, status="queued")
            out = ResumeAgentResult(ok=True)
            return json.dumps(out.model_dump(exclude_none=True), ensure_ascii=False)

        if rec.status in {"completed", "failed"}:
            out = ResumeAgentResult(ok=False)
            return json.dumps(out.model_dump(exclude_none=True), ensure_ascii=False)

        out = ResumeAgentResult(ok=True)
        return json.dumps(out.model_dump(exclude_none=True), ensure_ascii=False)


class SubAgentExecutor:
    """In-process `task()` executor for the Phase 1.8 multi-agent MVP."""

    async def execute_task(
        self,
        *,
        catalog: AgentCatalog,
        parent_pack: AgentPack,
        model_provider: Any,
        tool_runtime: Any,
        session_key: str | None,
        parent_body: dict[str, Any],
        arguments_json: object,
        max_iters: int = 4,
    ) -> str:
        obj = _coerce_arguments_object(arguments_json=arguments_json, tool_name="task")
        args = TaskArgs.model_validate(obj)
        child_agent_id = args.agent_id.strip()
        allow = {
            item.strip()
            for item in (parent_pack.spec.multiagent.spawn_allow_agent_ids or [])
            if isinstance(item, str) and item.strip()
        }
        if child_agent_id not in allow:
            raise ValueError(f"task agent_id not allowed: {child_agent_id}")

        child_pack = catalog.get(child_agent_id)
        if child_pack is None:
            raise ValueError(f"unknown agent_id: {child_agent_id}")
        if not child_pack.spec.exposed:
            raise ValueError(f"agent_id not exposed: {child_agent_id}")

        from anyagent.protocol.tool_runtime import ToolContext

        from .prompt_envelope import build_default_environment_context_values, build_prompt_envelope
        from .tool_loop import run_tool_loop_nonstream

        model = child_pack.spec.model.default or parent_body.get("model")
        child_session_key = _task_session_key(parent_session_key=session_key, agent_id=child_agent_id)
        child_body: dict[str, Any] = {
            "input": args.prompt,
            "metadata": {
                "agent_id": child_agent_id,
                "session_key": child_session_key,
                "parent_session_key": session_key,
                "task_description": args.description,
            },
        }
        if isinstance(model, str) and model.strip():
            child_body["model"] = model.strip()

        prompt_envelope = build_prompt_envelope(
            pack=child_pack,
            selected_skills=[],
            tool_context=ToolContext(),
            model=child_body.get("model") if isinstance(child_body.get("model"), str) else None,
            environment_values=build_default_environment_context_values(
                cwd=child_pack.root_dir,
                sandbox_mode=child_pack.spec.sandbox.mode,
            ),
        )
        child_body = prompt_envelope.apply_to_body(body=child_body)

        status_code, payload = await run_tool_loop_nonstream(
            model_provider=model_provider,
            tool_runtime=tool_runtime,
            agent_id=child_agent_id,
            session_key=child_session_key,
            body=child_body,
            idempotency_key=None,
            tool_context=ToolContext(),
            selected_skills=[],
            max_iters=max_iters,
            prompt_envelope_applied=True,
        )
        if status_code >= 400:
            raise RuntimeError(_extract_error_message(payload))

        result = TaskResult(agent_id=child_agent_id, output_text=_extract_response_output_text(payload))
        return json.dumps(result.model_dump(), ensure_ascii=False)


def _coerce_arguments_object(*, arguments_json: object, tool_name: str) -> dict[str, Any]:
    try:
        obj = json.loads(arguments_json) if isinstance(arguments_json, str) else arguments_json
    except Exception as e:  # noqa: BLE001
        raise ValueError(f"invalid {tool_name} arguments_json: {e}") from e
    if not isinstance(obj, dict):
        raise ValueError(f"{tool_name} arguments must be an object")
    return obj


def _task_session_key(*, parent_session_key: str | None, agent_id: str) -> str:
    parent = (parent_session_key or "ephemeral").strip() or "ephemeral"
    suffix = uuid4().hex[:12]
    return f"{parent}:task:{agent_id}:{suffix}"


def _extract_response_output_text(payload: dict[str, Any]) -> str:
    output_text = payload.get("output_text")
    if isinstance(output_text, str):
        return output_text
    chunks: list[str] = []
    output = payload.get("output")
    if isinstance(output, list):
        for item in output:
            if not isinstance(item, dict):
                continue
            content = item.get("content")
            if not isinstance(content, list):
                continue
            for part in content:
                if isinstance(part, dict) and isinstance(part.get("text"), str):
                    chunks.append(part["text"])
    if chunks:
        return "".join(chunks)
    return json.dumps(payload, ensure_ascii=False)


def _extract_error_message(payload: dict[str, Any]) -> str:
    error = payload.get("error")
    if isinstance(error, dict) and isinstance(error.get("message"), str):
        return error["message"]
    return "subagent task failed"
