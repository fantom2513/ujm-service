from typing import Literal

JiraErrorCode = Literal[
    "UNAUTHORIZED",
    "NOT_FOUND",
    "HTTP_ERROR",
    "TIMEOUT",
    "NETWORK_ERROR",
]


class JiraError(Exception):
    def __init__(self, code: JiraErrorCode, message: str):
        super().__init__(message)
        self.code: JiraErrorCode = code
