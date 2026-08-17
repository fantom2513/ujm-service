from app.infrastructure.llm.errors import LLMError


def test_llm_error_has_code_and_message():
    err = LLMError("TIMEOUT", "timed out")
    assert err.code == "TIMEOUT"
    assert str(err) == "timed out"
    assert isinstance(err, Exception)


def test_llm_error_stores_cause():
    cause = ValueError("root")
    err = LLMError("HTTP_ERROR", "bad", cause)
    assert err.__cause__ is cause
