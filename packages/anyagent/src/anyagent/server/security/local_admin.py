"""Manage credentials against the configured backend without a running server."""

from __future__ import annotations

from pathlib import Path

from anyagent.config.schema import CredentialsConfig
from anyagent.protocol.credential_vault import (
    AdminCredentialDeleteResponse,
    AdminCredentialListResponse,
    AdminCredentialRef,
    AdminCredentialSetRequest,
)

from .credential_backends import ReadOnlyCredentialStoreError
from .credential_runtime import build_credential_store, run_credential_coro


class CredentialAdminError(RuntimeError):
    """Raised when local credential admin cannot use the configured backend."""


def local_set_credential(
    config: CredentialsConfig,
    workspace_dir: str | Path,
    req: AdminCredentialSetRequest,
) -> AdminCredentialRef:
    """Write one credential. Fails when the backend is ``none`` or not writable."""

    return run_credential_coro(_set(config, workspace_dir, req))


def local_list_credentials(
    config: CredentialsConfig,
    workspace_dir: str | Path,
) -> AdminCredentialListResponse:
    """List credential refs. Fails when the backend is ``none``. Read-only stores can list."""

    return run_credential_coro(_list(config, workspace_dir))


def local_delete_credential(
    config: CredentialsConfig,
    workspace_dir: str | Path,
    credential_id: str,
) -> AdminCredentialDeleteResponse:
    """Delete one credential. Fails when the backend is ``none`` or not writable."""

    return run_credential_coro(_delete(config, workspace_dir, credential_id))


def _backend_name(config: CredentialsConfig) -> str:
    return (config.backend or "none").strip().lower() or "none"


def _ensure_configured(config: CredentialsConfig, *, mutate: bool) -> str:
    backend = _backend_name(config)
    if backend in {"", "none"}:
        raise CredentialAdminError(
            "credential backend is 'none'; configure credentials.backend before managing credentials locally"
        )
    if mutate and not config.writable:
        raise CredentialAdminError(
            f"credential backend '{backend}' is not writable; set credentials.writable to true"
        )
    return backend


async def _open(config: CredentialsConfig, workspace_dir: str | Path, *, mutate: bool):
    _ensure_configured(config, mutate=mutate)
    store = build_credential_store(config, workspace_dir=workspace_dir)
    if store is None:
        raise CredentialAdminError(
            "credential backend is 'none'; configure credentials.backend before managing credentials locally"
        )
    return store


async def _set(
    config: CredentialsConfig,
    workspace_dir: str | Path,
    req: AdminCredentialSetRequest,
) -> AdminCredentialRef:
    store = await _open(config, workspace_dir, mutate=True)
    try:
        await store.set(
            credential_id=req.credential_id,
            kind=req.kind,
            value=req.value,
            scope=req.scope,
            metadata=req.metadata,
            expires_at=req.expires_at,
            rotate_before=req.rotate_before,
        )
    except ReadOnlyCredentialStoreError as exc:
        raise CredentialAdminError(str(exc)) from exc
    return AdminCredentialRef(
        credential_id=req.credential_id,
        kind=req.kind,
        scope=req.scope,
        metadata=dict(req.metadata),
        expires_at=req.expires_at,
        rotate_before=req.rotate_before,
    )


async def _list(config: CredentialsConfig, workspace_dir: str | Path) -> AdminCredentialListResponse:
    store = await _open(config, workspace_dir, mutate=False)
    refs = await store.list_refs()
    credentials = [
        AdminCredentialRef.model_validate({key: value for key, value in ref.items() if key != "value"})
        for ref in refs
    ]
    return AdminCredentialListResponse(credentials=credentials)


async def _delete(
    config: CredentialsConfig,
    workspace_dir: str | Path,
    credential_id: str,
) -> AdminCredentialDeleteResponse:
    store = await _open(config, workspace_dir, mutate=True)
    try:
        deleted = await store.delete(credential_id)
    except ReadOnlyCredentialStoreError as exc:
        raise CredentialAdminError(str(exc)) from exc
    return AdminCredentialDeleteResponse(ok=True, deleted=bool(deleted), credential_id=credential_id)
