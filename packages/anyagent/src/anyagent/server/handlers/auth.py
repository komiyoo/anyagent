from __future__ import annotations

from typing import Any

from fastapi import HTTPException


def _require_user_auth(state: Any, authorization: str | None) -> None:
    _require_bearer(authorization=authorization, expected=state.api_key)


def _require_admin_auth(state: Any, authorization: str | None) -> None:
    _require_bearer(authorization=authorization, expected=state.admin_api_key)


def _require_internal_auth(state: Any, authorization: str | None) -> None:
    expected = state.admin_api_key or state.api_key
    _require_bearer(authorization=authorization, expected=expected)


def _require_bearer(*, authorization: str | None, expected: str | None) -> None:
    if not expected:
        return
    prefix = "bearer "
    if not isinstance(authorization, str) or not authorization.lower().startswith(prefix):
        raise HTTPException(status_code=401, detail="missing bearer authorization")
    token = authorization[len(prefix) :].strip()
    if token != expected:
        raise HTTPException(status_code=401, detail="invalid api key")
