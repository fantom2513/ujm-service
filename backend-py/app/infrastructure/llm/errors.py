from typing import Literal

LLMErrorCode = Literal[
    "TIMEOUT",
    "HTTP_ERROR",
    "NETWORK_ERROR",
    "INVALID_JSON",
    "SCHEMA_MISMATCH",
    "STRUCTURED_OUTPUT_UNSUPPORTED",
    "EMPTY_RESPONSE",
]


class LLMError(Exception):
    def __init__(self, code: LLMErrorCode, message: str, cause: Exception | None = None):
        super().__init__(message)
        self.code: LLMErrorCode = code
        if cause is not None:
            self.__cause__ = cause
