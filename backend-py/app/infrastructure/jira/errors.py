from typing import Literal

JiraErrorCode = Literal[
    "UNAUTHORIZED",
    "NOT_FOUND",
    "HTTP_ERROR",
    "TIMEOUT",
    "NETWORK_ERROR",
]


class JiraError(Exception):
    def __init__(self, code: JiraErrorCode, message: str, cause: Exception | None = None):
        super().__init__(message)
        self.code: JiraErrorCode = code
        if cause is not None:
            self.__cause__ = cause
