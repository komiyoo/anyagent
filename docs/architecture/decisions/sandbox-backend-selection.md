# Sandbox Backend Selection

Status: Accepted
Date: 2026-05-29
Req: `requirements.md#req-12`, `requirements.md#req-12-1` ~ `requirements.md#req-12-8`
Scope: Server sandbox backend selection for the second non-local execution backend.

## Decision

anyagent selects **OpenSandbox on Kubernetes** as the second sandbox backend candidate, exposed through the existing `SandboxPolicy.mode = "opensandbox"` protocol value.

The local backend remains the reference/dev backend:

- `local-unsafe`: local development and deterministic contract tests only.
- `opensandbox`: production-oriented container isolation path.
- `external`: reserved adapter boundary for a separately managed sandbox service.

## Rationale

OpenSandbox matches the production sandbox story already described in [sandbox-session-filesystem-design.md](../runtime/sandbox-session-filesystem-design.md):

- It gives anyagent a container isolation boundary without tying the protocol to Docker, containerd, or one host runtime.
- It has a natural control-plane/data-plane split: anyagent owns policy, credentials, events, and workspace lifecycle; OpenSandbox owns sandbox creation and command execution.
- It aligns with session workspace hibernation: `/workspace` can be checkpointed by the control plane while the sandbox remains credential-isolated.
- It leaves a path to microVM isolation later without changing `SandboxPolicy`.

## Contract

`opensandbox` must consume the same policy model as `local-unsafe`:

- `SandboxPolicy.mode`
- `NetworkSandboxPolicy.enabled`, `allow_hosts`, `deny_hosts`
- `ResourceLimits.cpu_cores`, `memory_mb`, `disk_mb`, `output_max_bytes`
- `FileSystemSandboxPolicy.persistence_mode`, `workspace_root`, `hot_idle_ttl_s`, `cold_retention_s`, `max_snapshot_bytes`
- `ttl_seconds`

The agent loop must continue to call only the `exec` tool. Backend selection remains a server concern owned by `SandboxManager` and workspace runtime wiring.

## Consequences

- `opensandbox` becomes the production candidate for the second backend P0.
- Any implementation must be testable without live OpenSandbox by using a fake transport/client at the backend boundary.
- `local-unsafe` stays available for development, but production docs must not present it as an isolation boundary.
- Docker/containerd/runc direct backends are deferred until a stronger need appears; they would add host-runtime coupling without improving the protocol contract.

## Evidence

- Protocol mode is already part of `anyagent.protocol.sandbox.SandboxMode`.
- The production filesystem design already names OpenSandbox/Kubernetes as the service path.
- Runtime wiring already has an `OpenSandboxWorkspaceBackend` for workspace lifecycle; command execution must use the same candidate boundary.
