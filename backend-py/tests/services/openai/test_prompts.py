from app.services.openai.prompts import build_generate_prompt


def test_build_generate_prompt_includes_source_and_details():
    result = build_generate_prompt("Some spec text", "extra details")
    assert "<SOURCE_SPECIFICATION>" in result
    assert "Some spec text" in result
    assert "<ADDITIONAL_DETAILS>" in result
    assert "extra details" in result


def test_build_generate_prompt_empty_details_block_is_empty():
    result = build_generate_prompt("spec", "")
    assert "<ADDITIONAL_DETAILS></ADDITIONAL_DETAILS>" in result


def test_build_generate_prompt_sanitizes_triple_backticks():
    result = build_generate_prompt("spec with ``` fence", "")
    assert "```" not in result.split("<SOURCE_SPECIFICATION>")[1].split("</SOURCE_SPECIFICATION>")[0].replace("'''", "")
