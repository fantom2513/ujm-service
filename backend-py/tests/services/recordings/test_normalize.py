from app.services.recordings.normalize import is_recording_format, normalize_recording


def test_is_recording_format_accepts_known_formats():
    for fmt in ("mp3", "m4a", "mp4", "webm"):
        assert is_recording_format(fmt) is True


def test_is_recording_format_rejects_unknown_format():
    assert is_recording_format("pdf") is False


def test_normalize_recording_is_stub():
    result = normalize_recording("meeting.mp3", size=1024)
    assert result.type == "recording"
    assert result.stub is True
    assert result.file["format"] == "MP3"
