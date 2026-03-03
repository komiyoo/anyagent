from __future__ import annotations

from fastapi.responses import JSONResponse


def openai_error(
    status_code: int,
    *,
    message: str,
    type_: str,
    code: str | None = None,
    retryable: bool | None = None,
) -> JSONResponse:
    err: dict[str, object] = {"message": message, "type": type_}
    if isinstance(code, str) and code.strip():
        err["code"] = code.strip()
    if retryable is not None:
        err["retryable"] = bool(retryable)
    return JSONResponse(
        status_code=status_code,
        content={
            "error": err
        },
    )
