"""HTTP client for the built-in Admin API."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

import httpx

from anyagent.config.loader import load_effective_config
from anyagent.protocol.admin_storage import StorageHealthResponse
from anyagent.protocol.credential_vault import (
    AdminCredentialDeleteResponse,
    AdminCredentialListResponse,
    AdminCredentialRef,
    AdminCredentialSetRequest,
)
from anyagent.protocol.plugins import PluginCatalogResponse


def local_base_url(*, host: str, port: int) -> str:
    """Build an HTTP base URL for a locally bound server."""

    display_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
    if ":" in display_host and not display_host.startswith("["):
        display_host = f"[{display_host}]"
    return f"http://{display_host}:{port}"


def add_admin_flags(parser: argparse.ArgumentParser) -> None:
    """Register the Admin API connection flags."""

    parser.add_argument(
        "--admin-url",
        default=None,
        help="Admin API base URL. Defaults to the configured server host and port.",
    )
    parser.add_argument(
        "--admin-key",
        default=None,
        help="Admin API key. Defaults to server.admin_api_key from config.",
    )
    parser.add_argument(
        "--workspace",
        default=".",
        help="Workspace used to resolve the admin URL and key from config.",
    )


def admin_client_from_args(args: argparse.Namespace) -> AdminClient:
    """Build a client from explicit flags, then from the effective config."""

    url = _clean(getattr(args, "admin_url", None))
    key = _clean(getattr(args, "admin_key", None))
    if url is None or key is None:
        workspace = Path(getattr(args, "workspace", None) or ".").expanduser().resolve()
        effective = load_effective_config(workspace)
        if url is None:
            url = local_base_url(host=effective.server.host, port=int(effective.server.port))
        if key is None:
            key = _clean(effective.server.admin_api_key)
    if not key:
        raise SystemExit("ADMIN_API_KEY is required (use --admin-key or config server.admin_api_key)")
    return AdminClient(url=url.rstrip("/"), key=key)


def _clean(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


@dataclass(frozen=True, slots=True)
class AdminClient:
    """Minimal Admin API client used by credential, plugin, and storage commands."""

    url: str
    key: str

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.key}"}

    def set_credential(self, req: AdminCredentialSetRequest) -> AdminCredentialRef:
        response = httpx.post(
            f"{self.url}/admin/credentials",
            headers=self._headers(),
            json=req.model_dump(exclude_none=True),
            timeout=15.0,
        )
        raise_for_status(response)
        return AdminCredentialRef.model_validate(response.json())

    def list_credentials(self) -> AdminCredentialListResponse:
        response = httpx.get(
            f"{self.url}/admin/credentials",
            headers=self._headers(),
            timeout=15.0,
        )
        raise_for_status(response)
        return AdminCredentialListResponse.model_validate(response.json())

    def delete_credential(self, credential_id: str) -> AdminCredentialDeleteResponse:
        response = httpx.delete(
            f"{self.url}/admin/credentials/{credential_id}",
            headers=self._headers(),
            timeout=15.0,
        )
        raise_for_status(response)
        return AdminCredentialDeleteResponse.model_validate(response.json())

    def storage_health(self) -> StorageHealthResponse:
        response = httpx.get(
            f"{self.url}/admin/storage/health",
            headers=self._headers(),
            timeout=15.0,
        )
        raise_for_status(response)
        return StorageHealthResponse.model_validate(response.json())

    def plugin_catalog(self) -> PluginCatalogResponse:
        response = httpx.get(
            f"{self.url}/admin/plugins/catalog",
            headers=self._headers(),
            timeout=15.0,
        )
        raise_for_status(response)
        return PluginCatalogResponse.model_validate(response.json())


def raise_for_status(response: httpx.Response) -> None:
    """Raise SystemExit with a truncated body when the Admin API rejects the call."""

    if 200 <= response.status_code < 300:
        return
    text = response.text
    if len(text) > 2000:
        text = text[:2000] + "...(truncated)"
    raise SystemExit(f"HTTP {response.status_code}: {text}")
