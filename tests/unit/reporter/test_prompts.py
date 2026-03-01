"""Unit tests for reporter.prompts module."""

from reporter.prompts import SYSTEM_PROMPT, build_user_message


class TestSystemPrompt:
    def test_is_non_empty_string(self):
        assert isinstance(SYSTEM_PROMPT, str)
        assert len(SYSTEM_PROMPT) > 0

    def test_contains_korean_editor_role(self):
        assert "한국어 Wikipedia" in SYSTEM_PROMPT


class TestBuildUserMessage:
    def test_contains_context(self):
        msg = build_user_message("## 테스트 컨텍스트", [])
        assert "## 테스트 컨텍스트" in msg

    def test_no_missing_descriptions_returns_empty_object_instruction(self):
        msg = build_user_message("ctx", [])
        assert "{}" in msg

    def test_missing_indices_listed_in_message(self):
        msg = build_user_message("ctx", [0, 3, 7])
        assert "[0, 3, 7]" in msg

    def test_missing_indices_in_schema(self):
        msg = build_user_message("ctx", [2, 5])
        assert '"2": "..."' in msg
        assert '"5": "..."' in msg

    def test_count_mentioned_for_missing_indices(self):
        msg = build_user_message("ctx", [0, 3, 7])
        assert "3개 모두 포함 필수" in msg

    def test_json_schema_keys_present(self):
        msg = build_user_message("ctx", [])
        for key in ("selected_indices", "headline", "top5_analysis",
                    "controversy", "numbers", "featured", "news_keywords"):
            assert key in msg
