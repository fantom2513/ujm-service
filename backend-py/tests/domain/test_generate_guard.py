from app.domain.generate_guard import required_source_error


def test_text_file_without_file_returns_file_required():
    assert required_source_error("text-file", has_file=False, link="") == "file-required"


def test_recording_without_file_returns_file_required():
    assert required_source_error("recording", has_file=False, link="") == "file-required"


def test_text_file_with_file_passes():
    assert required_source_error("text-file", has_file=True, link="") is None


def test_recording_with_file_passes():
    assert required_source_error("recording", has_file=True, link="") is None


def test_link_without_value_returns_link_required():
    assert required_source_error("link", has_file=False, link="") == "link-required"


def test_link_with_only_whitespace_returns_link_required():
    assert required_source_error("link", has_file=False, link="   ") == "link-required"


def test_link_with_value_passes():
    assert required_source_error("link", has_file=False, link="https://example.com/task/1") is None


def test_missing_source_type_returns_diagram_generation():
    assert required_source_error(None, has_file=False, link="") == "diagram-generation"


def test_unknown_source_type_returns_diagram_generation():
    assert required_source_error("totally-bogus", has_file=True, link="https://x") == "diagram-generation"


def test_empty_source_type_returns_diagram_generation():
    assert required_source_error("", has_file=False, link="") == "diagram-generation"
