from __future__ import annotations

from anyagent.protocol.sandbox import FileSystemSandboxPolicy, SandboxPolicy


def test_sandbox_policy_accepts_filesystem_block() -> None:
    policy = SandboxPolicy.model_validate(
        {
            "mode": "local-unsafe",
            "filesystem": {
                "persistence_mode": "session_hot_cold",
                "workspace_root": "/workspace",
                "hot_idle_ttl_s": 300,
                "cold_retention_s": 3600,
                "max_snapshot_bytes": 1024,
            },
        }
    )

    assert isinstance(policy.filesystem, FileSystemSandboxPolicy)
    assert policy.filesystem.persistence_mode == "session_hot_cold"
    assert policy.filesystem.workspace_root == "/workspace"
