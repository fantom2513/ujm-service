import pytest

from app.domain.undo import UNDO_PHRASES, is_undo_request, normalize_undo_message


@pytest.mark.parametrize("phrase", sorted(UNDO_PHRASES))
def test_every_ported_undo_phrase_matches(phrase: str):
    assert is_undo_request(phrase) is True


@pytest.mark.parametrize("punctuation", [".", "!", "?"])
def test_case_whitespace_and_one_trailing_punctuation_are_normalized(punctuation: str):
    message = f"  ВЕРНИ\t\nПРЕДЫДУЩУЮ   ВЕРСИЮ{punctuation}  "

    assert normalize_undo_message(message) == "верни предыдущую версию"
    assert is_undo_request(message) is True


@pytest.mark.parametrize(
    "message",
    [
        "",
        "верни версию",
        "покажи предыдущую версию",
        "верни предыдущую версию, пожалуйста",
        "верни предыдущую версию?!",
    ],
)
def test_non_undo_message_does_not_match(message: str):
    assert is_undo_request(message) is False
