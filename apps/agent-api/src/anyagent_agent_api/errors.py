from __future__ import annotations

from fastapi.responses import JSONResponse


def openai_error(status_code: int, *, message: str, type_: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "message": message,
                "type": type_,
            }
        },
    )

