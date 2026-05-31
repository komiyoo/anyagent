from __future__ import annotations

import asyncio
import os
import hashlib
import json
import posixpath
import re
import shlex
import tarfile
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import httpx
from pydantic import BaseModel, ConfigDict, Field

from anyagent.gateway.session import session_partition_key
from anyagent.protocol.admin_storage import AdminSandboxRuntimeDiagnostics
from anyagent.protocol.sandbox import SandboxPolicy
from anyagent.server.sandbox.backends import CommandExecutionResult, CommandStagedFile
from anyagent.storage import SessionWorkspaceRecord


def _now_ms() -> int:
    return int(time.time() * 1000)


def _extract_exit_code(error_text: str | None) -> int:
    """尽量从 OpenSandbox/execd 的错误文本里恢复 exit code。"""

    if not error_text:
        return 1
    match = re.search(r"exit status (\d+)", error_text)
    if match is not None:
        return int(match.group(1))
    if "timed out" in error_text.lower() or "timeout" in error_text.lower():
        return 124
    return 1


def _as_proxy_base_url(endpoint: str) -> str:
    if endpoint.startswith(("http://", "https://")):
        return endpoint.rstrip("/")
    return f"http://{endpoint.rstrip('/')}"


def _safe_label_value(value: str) -> str:
    """
    OpenSandbox docker runtime 会把 metadata 下沉为容器 label。

    这里把 session key 收敛成稳定、可追踪、且满足 label 约束的短值。
    """

    digest = hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()[:24]
    return f"ws-{digest}"


def _resolve_workdir(*, workspace_root: str, workdir: str | None) -> str:
    if not isinstance(workdir, str) or not workdir.strip():
        return workspace_root
    normalized = workdir.strip()
    if normalized.startswith("/"):
        return normalized
    return posixpath.normpath(posixpath.join(workspace_root, normalized))


class OpenSandboxImageSpec(BaseModel):
    """Lifecycle API 里的镜像描述。"""

    model_config = ConfigDict(extra="forbid")

    uri: str


class OpenSandboxSandboxStatus(BaseModel):
    """Lifecycle API 的最小状态视图。"""

    model_config = ConfigDict(extra="ignore")

    state: str
    reason: str | None = None
    message: str | None = None
    last_transition_at: datetime | None = Field(default=None, alias="lastTransitionAt")


class OpenSandboxCreateSandboxRequest(BaseModel):
    """创建 sandbox 所需的最小请求体。"""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    image: OpenSandboxImageSpec
    timeout: int = Field(ge=60, le=86400)
    resource_limits: dict[str, str] = Field(alias="resourceLimits")
    env: dict[str, str] | None = None
    metadata: dict[str, str] | None = None
    entrypoint: list[str]


class OpenSandboxCreateSandboxResponse(BaseModel):
    """Lifecycle API 的创建响应。"""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    id: str
    status: OpenSandboxSandboxStatus


class OpenSandboxSandboxRef(BaseModel):
    """`GET /sandboxes/{id}` 的最小运行时快照。"""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    id: str
    image: OpenSandboxImageSpec
    status: OpenSandboxSandboxStatus
    created_at: datetime | None = Field(default=None, alias="createdAt")
    expires_at: datetime | None = Field(default=None, alias="expiresAt")


class OpenSandboxEndpointRef(BaseModel):
    """`GET /sandboxes/{id}/endpoints/{port}` 返回的 endpoint。"""

    model_config = ConfigDict(extra="ignore")

    endpoint: str


class OpenSandboxCommandRequest(BaseModel):
    """execd `/command` 请求体。"""

    model_config = ConfigDict(extra="forbid")

    command: str
    cwd: str | None = None
    background: bool = False
    timeout: int | None = Field(default=None, ge=1)
    env: dict[str, str] | None = None


class OpenSandboxCommandError(BaseModel):
    """execd SSE error payload。"""

    model_config = ConfigDict(extra="ignore")

    ename: str | None = None
    evalue: str | None = None


class OpenSandboxCommandEvent(BaseModel):
    """execd `/command` 返回的单条 SSE JSON event。"""

    model_config = ConfigDict(extra="ignore")

    type: str | None = None
    text: str | None = None
    execution_time: int | None = None
    error: OpenSandboxCommandError | None = None


class OpenSandboxCommandStatus(BaseModel):
    """execd `/command/status/{id}` 返回的状态。"""

    model_config = ConfigDict(extra="ignore")

    id: str
    running: bool
    exit_code: int | None = None
    error: str | None = None
    content: str | None = None


@dataclass(slots=True)
class OpenSandboxWorkspaceBackend:
    """
    基于官方 OpenSandbox Lifecycle API + execd 代理的 workspace backend。

    关键点：
    - lifecycle 管理走 `/sandboxes`
    - 命令执行走 `/sandboxes/{id}/proxy/44772/command`
    - 文件导入导出走 execd `/files/upload` / `/files/download`
    - 冷热切换通过“tar 打包 + 上传/下载 + 解压”实现，而不是依赖我们此前猜测的 import/export 端点
    """

    base_url: str
    api_key: str | None
    workspace_root: str
    image: str
    sandbox_timeout_s: int
    cpu_limit: str
    memory_limit: str
    proxy_port: int = 44772
    _client: httpx.AsyncClient = field(init=False)
    _records: dict[str, SessionWorkspaceRecord] = field(default_factory=dict)
    _runtime_diagnostics: dict[str, AdminSandboxRuntimeDiagnostics] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.base_url, str) or not self.base_url.strip():
            raise RuntimeError("opensandbox backend requires OPENSANDBOX_BASE_URL")
        headers: dict[str, str] = {}
        if self.api_key:
            headers["OPEN-SANDBOX-API-KEY"] = self.api_key
        self._client = httpx.AsyncClient(
            base_url=self.base_url.rstrip("/"),
            timeout=120.0,
            headers=headers,
        )

    async def execute_command(
        self,
        *,
        policy: SandboxPolicy,
        agent_id: str,
        session_key: str,
        cmd: str,
        workdir: str | None,
        timeout_seconds: int,
        env: dict[str, str] | None = None,
        staged_files: list[CommandStagedFile] | None = None,
    ) -> CommandExecutionResult:
        record = await self._ensure_sandbox(policy=policy, agent_id=agent_id, session_key=session_key)
        cwd = _resolve_workdir(workspace_root=_workspace_root_for_policy(policy, default=self.workspace_root), workdir=workdir)
        if staged_files:
            await self._stage_remote_files(sandbox_id=str(record.sandbox_id), cwd=cwd, staged_files=staged_files)
        result = await self._run_command(
            sandbox_id=str(record.sandbox_id),
            cmd=cmd,
            cwd=cwd,
            timeout_seconds=timeout_seconds,
            env=env,
        )
        self._records[record.session_partition_key] = record.model_copy(
            update={"last_accessed_at_ms": _now_ms(), "state": "active"}
        )
        return result

    async def get_workspace(self, *, agent_id: str, session_key: str) -> SessionWorkspaceRecord | None:
        return self._records.get(session_partition_key(agent_id=agent_id, session_key=session_key))

    async def list_workspaces(self) -> list[SessionWorkspaceRecord]:
        return list(self._records.values())

    async def restore_workspace_from_directory(
        self,
        *,
        policy: SandboxPolicy,
        agent_id: str,
        session_key: str,
        src_dir: str | Path,
        record: SessionWorkspaceRecord,
    ) -> SessionWorkspaceRecord:
        session_pk = session_partition_key(agent_id=agent_id, session_key=session_key)
        sandbox_id = await self._create_sandbox(policy=policy, session_pk=session_pk)
        archive_path = self._build_archive(src_dir=src_dir)
        remote_archive = "/tmp/anyagent-opensandbox/workspace.tar.gz"
        try:
            await self._upload_file(
                sandbox_id=sandbox_id,
                remote_path=remote_archive,
                local_path=archive_path,
                mode=0o644,
                content_type="application/gzip",
            )
            await self._run_command(
                sandbox_id=sandbox_id,
                cmd=(
                    f"mkdir -p {shlex.quote(self.workspace_root)} "
                    f"&& tar -xzf {shlex.quote(remote_archive)} -C {shlex.quote(self.workspace_root)}"
                ),
                cwd="/",
                timeout_seconds=120,
            )
        finally:
            archive_path.unlink(missing_ok=True)
            await self._run_command(
                sandbox_id=sandbox_id,
                cmd=f"rm -f {shlex.quote(remote_archive)}",
                cwd="/",
                timeout_seconds=30,
            )
        updated = record.model_copy(
            update={
                "state": "active",
                "sandbox_id": sandbox_id,
                "workspace_root": str(
                    policy.filesystem.workspace_root if policy.filesystem is not None else self.workspace_root
                ),
                "last_accessed_at_ms": _now_ms(),
            }
        )
        self._records[session_pk] = updated
        return updated

    async def hibernate_workspace(self, *, agent_id: str, session_key: str) -> SessionWorkspaceRecord:
        session_pk = session_partition_key(agent_id=agent_id, session_key=session_key)
        current = self._records.get(session_pk)
        if current is None or not current.sandbox_id:
            raise RuntimeError(f"opensandbox workspace not found: {session_pk}")

        remote_archive = "/tmp/anyagent-opensandbox/workspace.tar.gz"
        await self._run_command(
            sandbox_id=str(current.sandbox_id),
            cmd=(
                f"mkdir -p /tmp/anyagent-opensandbox "
                f"&& tar -czf {shlex.quote(remote_archive)} -C {shlex.quote(self.workspace_root)} ."
            ),
            cwd="/",
            timeout_seconds=120,
        )
        try:
            payload = await self._download_file(
                sandbox_id=str(current.sandbox_id),
                remote_path=remote_archive,
            )
        finally:
            await self._run_command(
                sandbox_id=str(current.sandbox_id),
                cmd=f"rm -f {shlex.quote(remote_archive)}",
                cwd="/",
                timeout_seconds=30,
            )

        extracted_dir, digest, total_bytes = self._extract_archive(
            payload,
            session_pk=session_pk,
            generation=int(current.generation) + 1,
        )
        updated = current.model_copy(
            update={
                "state": "hibernated",
                "generation": int(current.generation) + 1,
                "snapshot_uri": str(extracted_dir),
                "snapshot_digest": digest,
                "snapshot_bytes": total_bytes,
                "sandbox_id": None,
            }
        )
        self._runtime_diagnostics[session_pk] = AdminSandboxRuntimeDiagnostics(
            provider="opensandbox",
            sandbox_id=str(current.sandbox_id),
            state="hibernated",
            reason="CHECKPOINT_COMMITTED",
            message="sandbox checkpointed and removed after snapshot commit",
            image_uri=self.image,
        )
        await self._delete_remote_sandbox(sandbox_id=str(current.sandbox_id))
        self._records[session_pk] = updated
        return updated

    async def delete_workspace(self, *, agent_id: str, session_key: str) -> None:
        session_pk = session_partition_key(agent_id=agent_id, session_key=session_key)
        current = self._records.pop(session_pk, None)
        if current is not None and current.sandbox_id:
            self._runtime_diagnostics[session_pk] = AdminSandboxRuntimeDiagnostics(
                provider="opensandbox",
                sandbox_id=str(current.sandbox_id),
                state="deleted",
                reason="CONTROL_PLANE_DELETE",
                message="sandbox deleted by workspace service",
            )
            await self._delete_remote_sandbox(sandbox_id=str(current.sandbox_id))

    async def get_runtime_diagnostics(
        self,
        *,
        agent_id: str,
        session_key: str,
        record: SessionWorkspaceRecord | None = None,
    ) -> AdminSandboxRuntimeDiagnostics | None:
        session_pk = session_partition_key(agent_id=agent_id, session_key=session_key)
        current = record or self._records.get(session_pk)
        if current is not None and current.sandbox_id:
            try:
                diagnostics = await self._fetch_runtime_diagnostics(sandbox_id=str(current.sandbox_id))
            except httpx.HTTPStatusError:
                return self._runtime_diagnostics.get(session_pk)
            self._runtime_diagnostics[session_pk] = diagnostics
            return diagnostics
        return self._runtime_diagnostics.get(session_pk)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _ensure_sandbox(self, *, policy: SandboxPolicy, agent_id: str, session_key: str) -> SessionWorkspaceRecord:
        session_pk = session_partition_key(agent_id=agent_id, session_key=session_key)
        current = self._records.get(session_pk)
        if current is not None and current.sandbox_id:
            updated = current.model_copy(update={"last_accessed_at_ms": _now_ms(), "state": "active"})
            self._records[session_pk] = updated
            return updated

        sandbox_id = await self._create_sandbox(policy=policy, session_pk=session_pk)
        workspace_id = f"ws_{hashlib.sha256(session_pk.encode('utf-8', errors='replace')).hexdigest()[:16]}"
        record = SessionWorkspaceRecord(
            session_partition_key=session_pk,
            workspace_id=workspace_id,
            state="active",
            generation=0,
            sandbox_id=sandbox_id,
            workspace_root=str(policy.filesystem.workspace_root if policy.filesystem is not None else self.workspace_root),
            last_accessed_at_ms=_now_ms(),
        )
        self._records[session_pk] = record
        return record

    async def _create_sandbox(self, *, policy: SandboxPolicy, session_pk: str) -> str:
        workspace_root = _workspace_root_for_policy(policy, default=self.workspace_root)
        home_dir = posixpath.join(workspace_root, "home")
        tmp_dir = posixpath.join(workspace_root, "tmp")
        bootstrap_cmd = (
            f"mkdir -p {shlex.quote(workspace_root)} {shlex.quote(home_dir)} {shlex.quote(tmp_dir)} "
            f"&& sleep infinity"
        )
        request = OpenSandboxCreateSandboxRequest(
            image=OpenSandboxImageSpec(uri=self.image),
            timeout=_sandbox_timeout_for_policy(policy, default=self.sandbox_timeout_s),
            resourceLimits=_resource_limits_for_policy(
                policy,
                default_cpu_limit=self.cpu_limit,
                default_memory_limit=self.memory_limit,
            ),
            env={"HOME": home_dir, "TMPDIR": tmp_dir},
            metadata=_metadata_for_policy(policy, session_pk=session_pk, workspace_root=workspace_root),
            entrypoint=["/bin/bash", "-lc", bootstrap_cmd],
        )
        response = await self._client.post(
            "/sandboxes",
            json=request.model_dump(by_alias=True, exclude_none=True),
        )
        response.raise_for_status()
        payload = OpenSandboxCreateSandboxResponse.model_validate(response.json())
        self._runtime_diagnostics[session_pk] = AdminSandboxRuntimeDiagnostics(
            provider="opensandbox",
            sandbox_id=payload.id,
            state=payload.status.state,
            reason=payload.status.reason,
            message=payload.status.message,
            image_uri=self.image,
            last_transition_at=payload.status.last_transition_at,
        )
        await self._wait_for_proxy_ready(sandbox_id=payload.id)
        return payload.id

    async def _wait_for_proxy_ready(self, *, sandbox_id: str, timeout_seconds: int = 30) -> None:
        deadline = time.monotonic() + timeout_seconds
        while True:
            try:
                proxy_base = await self._resolve_proxy_base(sandbox_id=sandbox_id)
                response = await self._client.get(f"{proxy_base}/ping")
                if response.status_code == 200:
                    return
            except Exception:  # noqa: BLE001
                pass
            if time.monotonic() >= deadline:
                raise RuntimeError(f"opensandbox execd proxy not ready: {sandbox_id}")
            await asyncio.sleep(0.2)

    async def _resolve_proxy_base(self, *, sandbox_id: str) -> str:
        response = await self._client.get(
            f"/sandboxes/{sandbox_id}/endpoints/{self.proxy_port}",
            params={"use_server_proxy": "true"},
        )
        response.raise_for_status()
        payload = OpenSandboxEndpointRef.model_validate(response.json())
        return _as_proxy_base_url(payload.endpoint)

    async def _run_command(
        self,
        *,
        sandbox_id: str,
        cmd: str,
        cwd: str,
        timeout_seconds: int,
        env: dict[str, str] | None = None,
    ) -> CommandExecutionResult:
        proxy_base = await self._resolve_proxy_base(sandbox_id=sandbox_id)
        request = OpenSandboxCommandRequest(
            command=cmd,
            cwd=cwd,
            background=False,
            timeout=max(int(timeout_seconds), 1) * 1000,
            env=dict(env) if env is not None else None,
        )
        response = await self._client.post(
            f"{proxy_base}/command",
            json=request.model_dump(exclude_none=True),
            headers={"Accept": "text/event-stream"},
        )
        response.raise_for_status()

        stdout_parts: list[str] = []
        stderr_parts: list[str] = []
        duration_ms = 0
        error_text: str | None = None

        for raw_event in response.text.split("\n\n"):
            raw_event = raw_event.strip()
            if not raw_event:
                continue
            event = OpenSandboxCommandEvent.model_validate(json.loads(raw_event))
            if event.type == "stdout" and event.text:
                stdout_parts.append(event.text)
            elif event.type == "stderr" and event.text:
                stderr_parts.append(event.text)
            elif event.type == "execution_complete" and event.execution_time is not None:
                duration_ms = int(event.execution_time)
            elif event.type == "error" and event.error is not None:
                error_text = event.error.evalue or event.error.ename or "runtime error"

        exit_code = 0
        timed_out = False
        if error_text:
            exit_code = _extract_exit_code(error_text)
            timed_out = exit_code == 124
            stderr_parts.append(error_text)

        return CommandExecutionResult(
            command=cmd,
            exit_code=exit_code,
            stdout="".join(stdout_parts),
            stderr="".join(stderr_parts),
            duration_ms=duration_ms,
            cwd=cwd,
            timed_out=timed_out,
        )

    async def _stage_remote_files(
        self,
        *,
        sandbox_id: str,
        cwd: str,
        staged_files: list[CommandStagedFile],
    ) -> None:
        for item in staged_files:
            remote_path = posixpath.normpath(posixpath.join(cwd, item.relative_path))
            parent = posixpath.dirname(remote_path)
            if parent and parent != ".":
                await self._run_command(
                    sandbox_id=sandbox_id,
                    cmd=f"mkdir -p {shlex.quote(parent)}",
                    cwd="/",
                    timeout_seconds=30,
                )
            await self._upload_text(
                sandbox_id=sandbox_id,
                remote_path=remote_path,
                content=item.content,
                mode=0o600,
            )

    async def _upload_file(
        self,
        *,
        sandbox_id: str,
        remote_path: str,
        local_path: Path,
        mode: int,
        content_type: str,
    ) -> None:
        proxy_base = await self._resolve_proxy_base(sandbox_id=sandbox_id)
        metadata = {
            "path": remote_path,
            "owner": "root",
            "group": "root",
            "mode": int(mode),
        }
        payload = local_path.read_bytes()
        files = [
            ("metadata", ("metadata.json", json.dumps(metadata).encode("utf-8"), "application/json")),
            ("file", (local_path.name, payload, content_type)),
        ]
        response = await self._client.post(f"{proxy_base}/files/upload", files=files)
        response.raise_for_status()

    async def _upload_text(
        self,
        *,
        sandbox_id: str,
        remote_path: str,
        content: str,
        mode: int,
    ) -> None:
        fd, raw = tempfile.mkstemp(prefix="anyagent-opensandbox-file-", suffix=".txt")
        os.close(fd)
        path = Path(raw)
        try:
            path.write_text(content, encoding="utf-8")
            await self._upload_file(
                sandbox_id=sandbox_id,
                remote_path=remote_path,
                local_path=path,
                mode=mode,
                content_type="text/plain",
            )
        finally:
            path.unlink(missing_ok=True)

    async def _download_file(self, *, sandbox_id: str, remote_path: str) -> bytes:
        proxy_base = await self._resolve_proxy_base(sandbox_id=sandbox_id)
        response = await self._client.get(f"{proxy_base}/files/download", params={"path": remote_path})
        response.raise_for_status()
        return response.content

    async def _delete_remote_sandbox(self, *, sandbox_id: str) -> None:
        response = await self._client.delete(f"/sandboxes/{sandbox_id}")
        if response.status_code not in {204, 404}:
            response.raise_for_status()

    async def _fetch_runtime_diagnostics(self, *, sandbox_id: str) -> AdminSandboxRuntimeDiagnostics:
        response = await self._client.get(f"/sandboxes/{sandbox_id}")
        response.raise_for_status()
        payload = OpenSandboxSandboxRef.model_validate(response.json())
        return AdminSandboxRuntimeDiagnostics(
            provider="opensandbox",
            sandbox_id=payload.id,
            state=payload.status.state,
            reason=payload.status.reason,
            message=payload.status.message,
            image_uri=payload.image.uri,
            created_at=payload.created_at,
            expires_at=payload.expires_at,
            last_transition_at=payload.status.last_transition_at,
        )

    def _build_archive(self, *, src_dir: str | Path) -> Path:
        src = Path(src_dir).expanduser().resolve()
        fd, raw = tempfile.mkstemp(prefix="anyagent-opensandbox-", suffix=".tar.gz")
        os.close(fd)
        Path(raw).unlink(missing_ok=True)
        archive_path = Path(raw)
        with tarfile.open(archive_path, mode="w:gz") as tar:
            for item in sorted(src.rglob("*")):
                arcname = item.relative_to(src)
                tar.add(item, arcname=str(arcname))
        return archive_path

    def _extract_archive(self, payload: bytes, *, session_pk: str, generation: int) -> tuple[Path, str, int]:
        base = Path(tempfile.mkdtemp(prefix="anyagent-opensandbox-export-"))
        archive_path = base / "workspace.tar.gz"
        workspace_dir = base / "workspace"
        archive_path.write_bytes(payload)
        digest = hashlib.sha256(payload).hexdigest()
        workspace_dir.mkdir(parents=True, exist_ok=True)
        with tarfile.open(archive_path, mode="r:gz") as tar:
            tar.extractall(path=workspace_dir, filter="data")
        archive_path.unlink(missing_ok=True)
        return workspace_dir, digest, len(payload)


def _workspace_root_for_policy(policy: SandboxPolicy, *, default: str) -> str:
    if policy.filesystem is not None and isinstance(policy.filesystem.workspace_root, str):
        value = policy.filesystem.workspace_root.strip()
        if value:
            return value
    return default


def _sandbox_timeout_for_policy(policy: SandboxPolicy, *, default: int) -> int:
    raw = policy.ttl_seconds if isinstance(policy.ttl_seconds, int) else default
    return max(60, min(86400, int(raw)))


def _resource_limits_for_policy(
    policy: SandboxPolicy,
    *,
    default_cpu_limit: str,
    default_memory_limit: str,
) -> dict[str, str]:
    limits = {"cpu": default_cpu_limit, "memory": default_memory_limit}
    resources = policy.resource_limits
    if resources is None:
        return limits
    if resources.cpu_cores is not None:
        limits["cpu"] = f"{max(1, int(resources.cpu_cores * 1000))}m"
    if resources.memory_mb is not None:
        limits["memory"] = f"{int(resources.memory_mb)}Mi"
    if resources.disk_mb is not None:
        limits["disk"] = f"{int(resources.disk_mb)}Mi"
    return limits


def _metadata_for_policy(policy: SandboxPolicy, *, session_pk: str, workspace_root: str) -> dict[str, str]:
    metadata = {
        "session_partition_key": _safe_label_value(session_pk),
        "workspace_root": workspace_root,
        "sandbox_mode": policy.mode,
    }
    if policy.network is not None:
        metadata["network_enabled"] = "true" if policy.network.enabled else "false"
        metadata["network_allow_hosts"] = json.dumps(policy.network.allow_hosts or [], separators=(",", ":"))
        metadata["network_deny_hosts"] = json.dumps(policy.network.deny_hosts or [], separators=(",", ":"))
    if policy.resource_limits is not None and policy.resource_limits.output_max_bytes is not None:
        metadata["output_max_bytes"] = str(int(policy.resource_limits.output_max_bytes))
    if policy.filesystem is not None:
        metadata["filesystem_persistence_mode"] = policy.filesystem.persistence_mode
        if policy.filesystem.hot_idle_ttl_s is not None:
            metadata["filesystem_hot_idle_ttl_s"] = str(int(policy.filesystem.hot_idle_ttl_s))
        if policy.filesystem.cold_retention_s is not None:
            metadata["filesystem_cold_retention_s"] = str(int(policy.filesystem.cold_retention_s))
        if policy.filesystem.max_snapshot_bytes is not None:
            metadata["filesystem_max_snapshot_bytes"] = str(int(policy.filesystem.max_snapshot_bytes))
    return metadata
