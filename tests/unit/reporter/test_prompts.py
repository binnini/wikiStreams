"""Unit tests for reporter.prompts package."""

import pytest

from reporter.prompts import SYSTEM_PROMPT, build_user_message
from reporter.prompts import default as default_prompts
from reporter.prompts import doro as doro_prompts


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


class TestDefaultPrompts:
    def test_system_prompt_is_non_empty(self):
        assert isinstance(default_prompts.SYSTEM_PROMPT, str)
        assert len(default_prompts.SYSTEM_PROMPT) > 0

    def test_system_prompt_contains_editor_role(self):
        assert "한국어 Wikipedia" in default_prompts.SYSTEM_PROMPT

    def test_build_user_message_contains_context(self):
        msg = default_prompts.build_user_message("## ctx", [])
        assert "## ctx" in msg

    def test_build_user_message_json_schema_keys_present(self):
        msg = default_prompts.build_user_message("ctx", [])
        for key in ("selected_indices", "headline", "top5_analysis",
                    "controversy", "numbers", "featured", "news_keywords"):
            assert key in msg

    def test_build_user_message_missing_indices(self):
        msg = default_prompts.build_user_message("ctx", [1, 2])
        assert '"1": "..."' in msg
        assert '"2": "..."' in msg

    def test_build_user_message_no_missing_indices(self):
        msg = default_prompts.build_user_message("ctx", [])
        assert "{}" in msg


class TestDoroPrompts:
    def test_system_prompt_is_non_empty(self):
        assert isinstance(doro_prompts.SYSTEM_PROMPT, str)
        assert len(doro_prompts.SYSTEM_PROMPT) > 0

    def test_system_prompt_contains_doro_character(self):
        assert "도로롱" in doro_prompts.SYSTEM_PROMPT

    def test_system_prompt_contains_doro_speech_style(self):
        assert "~와요" in doro_prompts.SYSTEM_PROMPT

    def test_build_user_message_contains_context(self):
        msg = doro_prompts.build_user_message("## ctx", [])
        assert "## ctx" in msg

    def test_build_user_message_json_schema_keys_present(self):
        msg = doro_prompts.build_user_message("ctx", [])
        for key in ("selected_indices", "headline", "top5_analysis",
                    "controversy", "numbers", "featured", "news_keywords"):
            assert key in msg

    def test_build_user_message_missing_indices(self):
        msg = doro_prompts.build_user_message("ctx", [1, 2])
        assert '"1": "..."' in msg
        assert '"2": "..."' in msg

    def test_build_user_message_no_missing_indices(self):
        msg = doro_prompts.build_user_message("ctx", [])
        assert "{}" in msg


class TestPromptStyleDispatch:
    def test_default_style_loads_default_module(self, monkeypatch):
        """PROMPT_STYLE=default should expose default module's SYSTEM_PROMPT."""
        assert "한국어 Wikipedia" in default_prompts.SYSTEM_PROMPT

    def test_doro_style_has_distinct_system_prompt(self):
        """doro prompt must differ from default prompt."""
        assert default_prompts.SYSTEM_PROMPT != doro_prompts.SYSTEM_PROMPT

    def test_both_styles_expose_same_interface(self):
        """Both styles must expose SYSTEM_PROMPT (str) and build_user_message (callable)."""
        for mod in (default_prompts, doro_prompts):
            assert isinstance(mod.SYSTEM_PROMPT, str)
            assert callable(mod.build_user_message)
