from __future__ import annotations

from typing import Any

from fastapi.responses import JSONResponse


def tool_error(
    *,
    status_code: int,
    type_: str,
    code: str,
    message: str,
    retryable: bool = False,
    meta: dict[str, Any] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "status": "error",
            "error": {
                "type": type_,
                "code": code,
                "message": message,
                "retryable": retryable,
            },
            "meta": meta or {"duration_ms": 0, "audit_ref": None},
        },
    )
