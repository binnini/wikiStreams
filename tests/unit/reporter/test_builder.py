"""Unit tests for reporter.builder module."""

import json
from unittest.mock import MagicMock

import pytest

from reporter.builder import _build_context, build_report
from reporter.fetcher import (
    FeaturedArticle,
    OverallStats,
    PeakHour,
    ReportData,
    RevertPage,
    TopPage,
)


# ─────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────


@pytest.fixture
def sample_data():
    return ReportData(
        stats=OverallStats(
            total_edits=5000,
            active_users=200,
            bot_ratio_pct=25.0,
            new_articles=50,
        ),
        top_pages=[
            TopPage(
                label="Alan Turing",
                title="Alan_Turing",
                description="British mathematician",
                server_name="en.wikipedia.org",
                edits=100,
                is_spike=True,
                spike_ratio_val=3.5,
                crosswiki_count=3,
            ),
            TopPage(
                label="파이썬",
                title="Python",
                description="프로그래밍 언어",
                server_name="ko.wikipedia.org",
                edits=80,
            ),
            TopPage(
                label="테스트",
                title="Test",
                description="",
                server_name="ko.wikipedia.org",
                edits=60,
            ),
            TopPage(
                label="Marie Curie",
                title="Marie_Curie",
                description="Physicist and chemist",
                server_name="en.wikipedia.org",
                edits=50,
            ),
            TopPage(
                label="축구",
                title="Football",
                description="스포츠",
                server_name="ko.wikipedia.org",
                edits=40,
            ),
        ],
        revert_pages=[
            RevertPage(
                label="Controversial Page",
                server_name="en.wikipedia.org",
                total_edits=30,
                reverts=10,
                revert_rate_pct=33.3,
            )
        ],
        featured_article=FeaturedArticle(
            title="Marie Curie",
            description="Physicist and chemist",
            extract="Marie Curie was a physicist...",
        ),
        peak_hour=PeakHour(hour=14, edits=1000),
    )


@pytest.fixture
def claude_response_json():
    return {
        "selected_indices": [0, 1, 2, 3, 4],
        "headline": "테스트 헤드라인 요약입니다.",
        "top5_analysis": "상위 5개 문서 분석 내용입니다.",
        "controversy": "논쟁 문서 정보입니다.",
        "numbers": "오늘의 통계 수치입니다.",
        "featured": "특집 문서 소개입니다.",
        "news_keywords": [["Alan Turing", "AI"], ["파이썬", "programming"], ["Test"]],
        "descriptions": {},
    }


def _mock_claude(mocker, response_json: dict):
    """Patch anthropic.Anthropic to return a fake Claude message."""
    mock_anthropic = mocker.patch("reporter.builder.anthropic.Anthropic")
    mock_client = MagicMock()
    mock_anthropic.return_value = mock_client
    mock_msg = MagicMock()
    mock_msg.content = [MagicMock(text=json.dumps(response_json))]
    mock_client.messages.create.return_value = mock_msg
    return mock_client


# ─────────────────────────────────────────────
# _build_context
# ─────────────────────────────────────────────


class TestBuildContext:
    def test_includes_overall_stats(self, sample_data):
        ctx = _build_context(sample_data, "2026년 03월 01일")

        assert "5,000" in ctx  # formatted total_edits
        assert "200" in ctx  # active_users
        assert "25.0" in ctx  # bot_ratio_pct
        assert "50" in ctx  # new_articles

    def test_includes_all_candidate_page_labels(self, sample_data):
        """All candidates (not just top 5) must appear in context."""
        ctx = _build_context(sample_data, "2026년 03월 01일")

        assert "Alan Turing" in ctx
        assert "파이썬" in ctx
        assert "Marie Curie" in ctx
        assert "축구" in ctx
        assert "en.wikipedia.org" in ctx

    def test_context_uses_zero_based_indices(self, sample_data):
        """Candidates are shown with [0], [1], ... prefix for LLM index selection."""
        ctx = _build_context(sample_data, "2026년 03월 01일")

        assert "[0]" in ctx
        assert "[1]" in ctx
        assert "[4]" in ctx  # 5 pages → indices 0-4

    def test_spike_badge_appears_in_context(self, sample_data):
        ctx = _build_context(sample_data, "2026년 03월 01일")

        assert "스파이크" in ctx
        assert "3.5" in ctx

    def test_crosswiki_badge_appears_in_context(self, sample_data):
        ctx = _build_context(sample_data, "2026년 03월 01일")

        assert "다국어" in ctx

    def test_revert_pages_included(self, sample_data):
        ctx = _build_context(sample_data, "2026년 03월 01일")

        assert "Controversial Page" in ctx
        assert "33.3" in ctx

    def test_featured_article_included(self, sample_data):
        ctx = _build_context(sample_data, "2026년 03월 01일")

        assert "Marie Curie" in ctx

    def test_peak_hour_included(self, sample_data):
        ctx = _build_context(sample_data, "2026년 03월 01일")

        assert "14시" in ctx

    def test_report_date_included(self, sample_data):
        ctx = _build_context(sample_data, "2026년 03월 01일")

        assert "2026년 03월 01일" in ctx


# ─────────────────────────────────────────────
# build_report
# ─────────────────────────────────────────────


class TestBuildReport:
    def test_returns_sections_dict_and_keywords_list(
        self, mocker, sample_data, claude_response_json
    ):
        _mock_claude(mocker, claude_response_json)

        sections, news_keywords = build_report(sample_data)

        assert isinstance(sections, dict)
        assert isinstance(news_keywords, list)

    def test_sections_contain_expected_keys(
        self, mocker, sample_data, claude_response_json
    ):
        _mock_claude(mocker, claude_response_json)

        sections, _ = build_report(sample_data)

        for key in (
            "headline",
            "top5_analysis",
            "controversy",
            "numbers",
            "featured",
            "date",
        ):
            assert key in sections

    def test_news_keywords_not_in_sections(
        self, mocker, sample_data, claude_response_json
    ):
        """news_keywords must be extracted from sections dict."""
        _mock_claude(mocker, claude_response_json)

        sections, news_keywords = build_report(sample_data)

        assert "news_keywords" not in sections
        assert news_keywords == [
            ["Alan Turing", "AI"],
            ["파이썬", "programming"],
            ["Test"],
        ]

    def test_selected_indices_not_in_sections(
        self, mocker, sample_data, claude_response_json
    ):
        """selected_indices must be extracted from sections dict."""
        _mock_claude(mocker, claude_response_json)

        sections, _ = build_report(sample_data)

        assert "selected_indices" not in sections

    def test_top_pages_filtered_by_selected_indices(self, mocker, sample_data):
        """data.top_pages is replaced with LLM-selected pages in order."""
        response = {
            "selected_indices": [2, 0, 4, 1, 3],  # reverse-ish order
            "headline": "h",
            "top5_analysis": "t",
            "controversy": "c",
            "numbers": "n",
            "featured": "f",
            "news_keywords": [],
        }
        _mock_claude(mocker, response)
        original_pages = list(sample_data.top_pages)

        build_report(sample_data)

        assert len(sample_data.top_pages) == 5
        assert sample_data.top_pages[0].label == original_pages[2].label
        assert sample_data.top_pages[1].label == original_pages[0].label
        assert sample_data.top_pages[2].label == original_pages[4].label

    def test_selected_indices_capped_at_5(self, mocker, sample_data):
        """Even if LLM returns 6+ indices, only first 5 are used."""
        response = {
            "selected_indices": [0, 1, 2, 3, 4, 0],  # 6 entries (last is duplicate)
            "headline": "h",
            "top5_analysis": "t",
            "controversy": "c",
            "numbers": "n",
            "featured": "f",
            "news_keywords": [],
        }
        _mock_claude(mocker, response)

        build_report(sample_data)

        assert len(sample_data.top_pages) == 5

    def test_fallback_to_first_5_when_selected_indices_empty(self, mocker, sample_data):
        """Empty selected_indices → fallback to first 5 pages."""
        response = {
            "selected_indices": [],
            "headline": "h",
            "top5_analysis": "t",
            "controversy": "c",
            "numbers": "n",
            "featured": "f",
            "news_keywords": [],
        }
        _mock_claude(mocker, response)

        build_report(sample_data)

        assert len(sample_data.top_pages) == 5

    def test_fallback_to_first_5_when_selected_indices_out_of_range(
        self, mocker, sample_data
    ):
        """Out-of-range indices are dropped; fallback to [:5] if none valid."""
        response = {
            "selected_indices": [99, 100],  # all out of range
            "headline": "h",
            "top5_analysis": "t",
            "controversy": "c",
            "numbers": "n",
            "featured": "f",
            "news_keywords": [],
        }
        _mock_claude(mocker, response)

        build_report(sample_data)

        assert len(sample_data.top_pages) == 5

    def test_fallback_when_selected_indices_is_not_list(self, mocker, sample_data):
        """Non-list selected_indices → fallback to [:5]."""
        response = {
            "selected_indices": "not a list",
            "headline": "h",
            "top5_analysis": "t",
            "controversy": "c",
            "numbers": "n",
            "featured": "f",
            "news_keywords": [],
        }
        _mock_claude(mocker, response)

        build_report(sample_data)

        assert len(sample_data.top_pages) == 5

    def test_date_injected_into_sections(
        self, mocker, sample_data, claude_response_json
    ):
        _mock_claude(mocker, claude_response_json)

        sections, _ = build_report(sample_data)

        assert "년" in sections["date"]  # Korean date format

    def test_invalid_json_falls_back_gracefully(self, mocker, sample_data):
        """Non-JSON Claude response: raw text becomes headline, keywords=[]."""
        mock_anthropic = mocker.patch("reporter.builder.anthropic.Anthropic")
        mock_client = MagicMock()
        mock_anthropic.return_value = mock_client
        mock_msg = MagicMock()
        mock_msg.content = [MagicMock(text="이건 JSON이 아닙니다.")]
        mock_client.messages.create.return_value = mock_msg

        sections, news_keywords = build_report(sample_data)

        assert sections["headline"] == "이건 JSON이 아닙니다."
        assert news_keywords == []

    def test_uses_haiku_model(self, mocker, sample_data, claude_response_json):
        mock_client = _mock_claude(mocker, claude_response_json)

        build_report(sample_data)

        create_kwargs = mock_client.messages.create.call_args.kwargs
        assert create_kwargs["model"] == "claude-haiku-4-5-20251001"

    def test_missing_news_keywords_field_returns_empty_list(self, mocker, sample_data):
        """If Claude omits news_keywords, return empty list without error."""
        response_without_keywords = {
            "selected_indices": [0, 1, 2, 3, 4],
            "headline": "헤드라인",
            "top5_analysis": "분석",
            "controversy": "없음",
            "numbers": "숫자",
            "featured": "특집",
        }
        _mock_claude(mocker, response_without_keywords)

        sections, news_keywords = build_report(sample_data)

        assert news_keywords == []
        assert "headline" in sections

    def test_non_list_news_keywords_normalised_to_empty(self, mocker, sample_data):
        """If Claude returns news_keywords as non-list, normalise to []."""
        response = {
            "selected_indices": [0, 1, 2, 3, 4],
            "headline": "h",
            "top5_analysis": "t",
            "controversy": "c",
            "numbers": "n",
            "featured": "f",
            "news_keywords": "not a list",
        }
        _mock_claude(mocker, response)

        _, news_keywords = build_report(sample_data)

        assert news_keywords == []

    def test_descriptions_applied_to_pages_missing_desc(self, mocker, sample_data):
        """Claude-generated descriptions fill in pages with empty description."""
        # sample_data index 2 has description="" (label="테스트")
        response = {
            "selected_indices": [0, 1, 2, 3, 4],
            "headline": "h",
            "top5_analysis": "t",
            "controversy": "c",
            "numbers": "n",
            "featured": "f",
            "news_keywords": [],
            "descriptions": {"2": "소프트웨어 테스트 기법"},
        }
        _mock_claude(mocker, response)

        build_report(sample_data)

        # After selected_indices=[0,1,2,3,4] filtering, top_pages[2] is the "테스트" page
        assert sample_data.top_pages[2].description == "소프트웨어 테스트 기법"

    def test_descriptions_not_overwrite_existing(self, mocker, sample_data):
        """Claude descriptions must not overwrite pages that already have one."""
        existing_desc = sample_data.top_pages[0].description  # "British mathematician"
        response = {
            "selected_indices": [0, 1, 2, 3, 4],
            "headline": "h",
            "top5_analysis": "t",
            "controversy": "c",
            "numbers": "n",
            "featured": "f",
            "news_keywords": [],
            "descriptions": {"0": "덮어쓰면 안 되는 설명"},
        }
        _mock_claude(mocker, response)

        build_report(sample_data)

        assert sample_data.top_pages[0].description == existing_desc

    def test_missing_descriptions_field_handled_gracefully(self, mocker, sample_data):
        """If Claude omits descriptions field, no error is raised."""
        response = {
            "selected_indices": [0, 1, 2, 3, 4],
            "headline": "h",
            "top5_analysis": "t",
            "controversy": "c",
            "numbers": "n",
            "featured": "f",
            "news_keywords": [],
        }
        _mock_claude(mocker, response)

        sections, _ = build_report(sample_data)

        assert "headline" in sections

    def test_descriptions_not_in_sections(
        self, mocker, sample_data, claude_response_json
    ):
        """descriptions must be extracted and not passed through to sections dict."""
        claude_response_json["descriptions"] = {"2": "테스트"}
        _mock_claude(mocker, claude_response_json)

        sections, _ = build_report(sample_data)

        assert "descriptions" not in sections

    def test_max_tokens_is_2000(self, mocker, sample_data, claude_response_json):
        mock_client = _mock_claude(mocker, claude_response_json)

        build_report(sample_data)

        create_kwargs = mock_client.messages.create.call_args.kwargs
        assert create_kwargs["max_tokens"] == 2000
