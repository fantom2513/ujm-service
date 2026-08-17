from __future__ import annotations

from app.services.files.extract import NormalizedSource, get_extension, sanitize_filename

_RECORDING_FORMATS = {"mp3", "m4a", "mp4", "webm"}


def is_recording_format(fmt: str) -> bool:
    return fmt in _RECORDING_FORMATS


def normalize_recording(filename: str, size: int) -> NormalizedSource:
    fmt = get_extension(filename)
    safe_name = sanitize_filename(filename)

    return NormalizedSource(
        type="recording",
        title=safe_name,
        text="Временная транскрибация записи. Реальное извлечение аудиодорожки и распознавание речи подключаются в сервисе recordings.",
        description=f"{fmt.upper()} · {round(size / 1024)} КБ",
        file={"name": safe_name, "format": fmt.upper(), "size": size},
        stub=True,
    )
