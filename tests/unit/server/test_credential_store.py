from __future__ import annotations

import asyncio

from anyagent.protocol.credential_vault import AdminCredentialSetRequest, CredentialScope
from anyagent.protocol.tool_runtime import AuthRef
from anyagent.server.security.credential_store import InMemoryCredentialStore


def test_resolve_prefers_agent_scope_over_global_scope() -> None:
    async def _run() -> None:
        store = InMemoryCredentialStore()
        await store.set(
            AdminCredentialSetRequest(
                credential_id="cred_api",
                kind="bearer_token",
                value="global-token",
                scope=CredentialScope(level="global"),
                metadata={},
            )
        )
        await store.set(
            AdminCredentialSetRequest(
                credential_id="cred_api",
                kind="bearer_token",
                value="agent-token",
                scope=CredentialScope(level="agent", agent_id="main"),
                metadata={},
            )
        )

        value = await store.resolve(AuthRef(kind="bearer_token", ref="cred_api"), scope_context={"agent_id": "main"})
        fallback = await store.resolve(AuthRef(kind="bearer_token", ref="cred_api"), scope_context={"agent_id": "other"})

        assert value == "agent-token"
        assert fallback == "global-token"

    asyncio.run(_run())


def test_resolve_rejects_missing_or_mismatched_kind() -> None:
    async def _run() -> None:
        store = InMemoryCredentialStore()
        await store.set(
            AdminCredentialSetRequest(
                credential_id="cred_api",
                kind="bearer_token",
                value="secret",
                scope=CredentialScope(level="global"),
                metadata={},
            )
        )

        assert await store.resolve(AuthRef(kind="", ref="cred_api")) is None
        assert await store.resolve(AuthRef(kind="basic_auth", ref="cred_api")) is None
        assert await store.resolve(AuthRef(kind="bearer_token", ref="missing")) is None

    asyncio.run(_run())


def test_delete_removes_resolved_value() -> None:
    async def _run() -> None:
        store = InMemoryCredentialStore()
        await store.set(
            AdminCredentialSetRequest(
                credential_id="cred_api",
                kind="bearer_token",
                value="secret",
                scope=CredentialScope(level="global"),
                metadata={"display_name": "API"},
            )
        )

        deleted = await store.delete("cred_api")
        resolved = await store.resolve(AuthRef(kind="bearer_token", ref="cred_api"))
        deleted_missing = await store.delete("cred_api")

        assert deleted == {"ok": True, "deleted": True, "credential_id": "cred_api"}
        assert resolved is None
        assert deleted_missing == {"ok": True, "deleted": False, "credential_id": "cred_api"}

    asyncio.run(_run())


def test_resolve_does_not_leak_agent_scoped_credential_to_other_agent() -> None:
    async def _run() -> None:
        store = InMemoryCredentialStore()
        await store.set(
            AdminCredentialSetRequest(
                credential_id="cred_agent_only",
                kind="bearer_token",
                value="agent-only-secret",
                scope=CredentialScope(level="agent", agent_id="agent-a"),
                metadata={},
            )
        )

        wrong_agent = await store.resolve(
            AuthRef(kind="bearer_token", ref="cred_agent_only"),
            scope_context={"agent_id": "agent-b"},
        )
        missing_scope = await store.resolve(AuthRef(kind="bearer_token", ref="cred_agent_only"))

        assert wrong_agent is None
        assert missing_scope is None

    asyncio.run(_run())
