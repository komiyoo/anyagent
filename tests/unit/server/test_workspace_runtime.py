from __future__ import annotations

import asyncio
import subprocess
import sys
import textwrap

import pytest

from anyagent.server.sandbox.workspace_runtime import (
    WorkspaceRuntimeConfig,
    build_workspace_lease_store_from_config,
    build_workspace_runtime,
)


def test_workspace_runtime_builds_disabled_service_without_snapshot_store(tmp_path) -> None:
    assembly = asyncio.run(
        build_workspace_runtime(
            WorkspaceRuntimeConfig(
                allow_sandbox=False,
                sandbox_root_dir=str(tmp_path),
            )
        )
    )

    try:
        assert assembly.service.config.enabled is False
        assert assembly.service.config.backend == "disabled"
        assert assembly.metadata_backend == "local_file"
        assert assembly.lease_backend == "memory"
        assert assembly.snapshot_backend == "disabled"
        assert assembly.sandbox_manager is None
    finally:
        asyncio.run(assembly.service.aclose())


def test_workspace_runtime_builds_local_reference_service(tmp_path) -> None:
    assembly = asyncio.run(
        build_workspace_runtime(
            WorkspaceRuntimeConfig(
                allow_sandbox=True,
                sandbox_backend="local_reference",
                sandbox_isolation_mode="local_unsafe",
                sandbox_root_dir=str(tmp_path),
                sandbox_filesystem_persistence_mode="session_hot_cold",
                workspace_snapshot_backend="local_file",
            )
        )
    )

    try:
        assert assembly.service.config.enabled is True
        assert assembly.service.config.backend == "local_reference"
        assert assembly.service.config.sandbox_mode == "local-unsafe"
        assert assembly.metadata_backend == "local_file"
        assert assembly.lease_backend == "memory"
        assert assembly.snapshot_backend == "local_file"
        assert assembly.sandbox_manager is not None

        result = asyncio.run(
            assembly.service.execute_command(
                policy=assembly.service.sandbox_policy_for_agent("main"),
                agent_id="main",
                session_key="sess-runtime",
                cmd="printf runtime-ok",
                workdir=None,
                timeout_seconds=10,
            )
        )
        assert result.exit_code == 0
        assert result.stdout == "runtime-ok"
        ref = asyncio.run(assembly.service.get_ref(agent_id="main", session_key="sess-runtime"))
        assert ref is not None
        assert ref.state == "active"
    finally:
        asyncio.run(assembly.service.aclose())


def test_workspace_runtime_rejects_invalid_sandbox_isolation_mode(tmp_path) -> None:
    with pytest.raises(RuntimeError, match="SANDBOX_ISOLATION_MODE"):
        asyncio.run(
            build_workspace_runtime(
                WorkspaceRuntimeConfig(
                    allow_sandbox=True,
                    sandbox_isolation_mode="disabled",
                    sandbox_root_dir=str(tmp_path),
                )
            )
        )


def test_workspace_runtime_explicit_redis_requires_dsn(tmp_path) -> None:
    with pytest.raises(RuntimeError, match="REDIS_DSN"):
        asyncio.run(
            build_workspace_lease_store_from_config(
                WorkspaceRuntimeConfig(
                    sandbox_root_dir=str(tmp_path),
                    workspace_lease_backend="redis",
                    redis_dsn=None,
                )
            )
        )


def test_workspace_runtime_import_keeps_optional_backends_lazy() -> None:
    script = textwrap.dedent(
        """
        import importlib.abc
        import sys

        class Blocker(importlib.abc.MetaPathFinder):
            blocked = ("sqlalchemy", "redis", "minio")

            def find_spec(self, fullname, path=None, target=None):
                if fullname in self.blocked or fullname.startswith(tuple(name + "." for name in self.blocked)):
                    raise ModuleNotFoundError(f"blocked optional dependency: {fullname}")
                return None

        sys.meta_path.insert(0, Blocker())
        import anyagent.server.sandbox as sandbox

        sandbox.WorkspaceRuntimeConfig(allow_sandbox=False)
        print("ok")
        """
    )

    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        capture_output=True,
        text=True,
    )
    assert completed.stdout.strip() == "ok"
