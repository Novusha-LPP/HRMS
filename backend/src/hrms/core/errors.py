"""Errors that carry a machine-readable code alongside the human message."""

from collections.abc import Mapping

from fastapi import HTTPException


class CodedHTTPException(HTTPException):
    """
    An HTTPException whose JSON body also includes {"code": ...}, so the
    frontend can branch on the reason (e.g. PASSWORD_CHANGE_REQUIRED) without
    parsing the message. See the handler registered in main.py.
    """

    def __init__(
        self,
        status_code: int,
        detail: str,
        code: str,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        super().__init__(status_code=status_code, detail=detail, headers=dict(headers or {}))
        self.code = code
