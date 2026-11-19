from __future__ import annotations

from typing import Any

from fastapi.responses import JSONResponse


def success_response(
    data: Any = None,
    message: str = "Success",
    status_code: int = 200,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "status": "success",
            "status_code": status_code,
            "message": message,
            "data": data,
            "error_message": None,
        },
    )


def error_response(
    message: str = "An error occurred",
    status_code: int = 400,
    error_message: str | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "status": "error",
            "status_code": status_code,
            "message": message,
            "data": None,
            "error_message": error_message or message,
        },
    )
