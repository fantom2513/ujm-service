from __future__ import annotations

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class FileMeta(CamelModel):
    name: str
    format: str
    size: int


class SourceContext(CamelModel):
    type: str
    title: str
    description: str
    file: FileMeta | None = None
    url: str | None = None
    stub: bool | None = None


class DiagramResult(CamelModel):
    session_id: str | None = None
    title: str
    mermaid_code: str
    source_text: str
    source_context: SourceContext
    details: str
    chat: list = []
    warnings: list[str] = []


class ChatResult(CamelModel):
    session_id: str
    mermaid_code: str
    message: str


class ApiError(CamelModel):
    code: str
    message: str
    field: str | None = None
