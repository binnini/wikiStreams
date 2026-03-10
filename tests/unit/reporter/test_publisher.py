"""Unit tests for reporter.publisher module."""

from unittest.mock import MagicMock

import pytest

from reporter.fetcher import (
    FeaturedArticle,
    LangEdition,
    NewsItem,
    OverallStats,
    PeakHour,
    ReportData,
    TopPage,
)
from reporter.publisher import (
    _build_featured_blocks,
    _build_top5_blocks,
    _rank_badge,
    _truncate,
    _wiki_flag,
    publish_report,
)


# ─────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────


@pytest.fixture
def sample_top_page():
    return TopPage(
        label="Alan Turing",
        title="Alan_Turing",
        description="British mathematician",
        server_name="en.wikipedia.org",
        edits=100,
        url="https://en.wikipedia.org/wiki/Alan_Turing",
        thumbnail_url="https://example.com/thumb.jpg",
        rank_change=2,
        is_spike=True,
        spike_ratio_val=4.5,
        crosswiki_count=3,
    )


@pytest.fixture
def sample_data(sample_top_page):
    return ReportData(
        stats=OverallStats(total_edits=5000),
        top_pages=[sample_top_page],
        peak_hour=PeakHour(hour=14, edits=1000),
        featured_article=FeaturedArticle(
            title="Marie Curie",
            description="Physicist",
            extract="Marie Curie was a physicist...",
            url="https://en.wikipedia.org/wiki/Marie_Curie",
            thumbnail_url="https://example.com/marie.jpg",
        ),
        news_items=[
            NewsItem(
                title="Tech News", link="https://example.com/news", source="TechSource"
            )
        ],
    )


@pytest.fixture
def sample_sections():
    return {
        "date": "2026년 03월 01일",
        "headline": "헤드라인 텍스트입니다.",
        "top5_analysis": "Top 5 분석 내용입니다.",
        "controversy": "논쟁 문서 설명입니다.",
        "numbers": "숫자 브리핑 내용입니다.",
        "featured": "특집 문서 소개입니다.",
    }


def _mock_slack(mocker):
    """Patch httpx.Client so Slack POST doesn't actually fire."""
    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None

    mock_cm = MagicMock()
    mock_cm.__enter__.return_value = mock_cm
    mock_cm.__exit__.return_value = False
    mock_cm.post.return_value = mock_resp

    mocker.patch("httpx.Client", return_value=mock_cm)
    return mock_cm


def _all_texts(blocks: list[dict]) -> list[str]:
    """블록 목록에서 모든 텍스트 문자열 추출 (section.text + section.fields)."""
    texts = []
    for b in blocks:
        if b.get("type") == "section":
            if "text" in b:
                texts.append(b["text"]["text"])
            for f in b.get("fields", []):
                texts.append(f["text"])
    return texts


def _header_texts(blocks: list[dict]) -> list[str]:
    return [b["text"]["text"] for b in blocks if b.get("type") == "header"]


# ─────────────────────────────────────────────
# _rank_badge
# ─────────────────────────────────────────────


class TestRankBadge:
    def test_none_is_new(self):
        assert _rank_badge(None) == " 🆕"

    def test_positive_is_up(self):
        assert _rank_badge(3) == " ▲3"

    def test_negative_is_down(self):
        assert _rank_badge(-2) == " ▼2"

    def test_zero_is_same(self):
        assert _rank_badge(0) == " →"


# ─────────────────────────────────────────────
# _wiki_flag
# ─────────────────────────────────────────────


class TestWikiFlag:
    def test_english_wikipedia(self):
        assert _wiki_flag("en.wikipedia.org") == "🇺🇸"

    def test_korean_wikipedia(self):
        assert _wiki_flag("ko.wikipedia.org") == "🇰🇷"

    def test_japanese_wikipedia(self):
        assert _wiki_flag("ja.wikipedia.org") == "🇯🇵"

    def test_wikidata(self):
        assert _wiki_flag("www.wikidata.org") == "🌐"

    def test_unknown_server_returns_globe(self):
        assert _wiki_flag("xx.wikipedia.org") == "🌍"


# ─────────────────────────────────────────────
# _truncate
# ─────────────────────────────────────────────


class TestTruncate:
    def test_short_string_unchanged(self):
        assert _truncate("hello", 10) == "hello"

    def test_long_string_gets_ellipsis(self):
        result = _truncate("a" * 200, 100)
        assert len(result) == 100
        assert result.endswith("...")

    def test_exactly_at_limit_unchanged(self):
        text = "a" * 50
        assert _truncate(text, 50) == text


# ─────────────────────────────────────────────
# _build_top5_blocks
# ─────────────────────────────────────────────


class TestBuildTop5Blocks:
    def test_returns_list_of_blocks(self, sample_data):
        blocks = _build_top5_blocks(sample_data, "분석")
        assert isinstance(blocks, list)
        assert all(isinstance(b, dict) for b in blocks)

    def test_first_block_is_header(self, sample_data):
        blocks = _build_top5_blocks(sample_data, "")
        assert blocks[0]["type"] == "header"
        assert "Top 5" in blocks[0]["text"]["text"]

    def test_spike_badge_in_text(self, sample_data):
        blocks = _build_top5_blocks(sample_data, "")
        texts = _all_texts(blocks)
        assert any("⚡" in t and "4.5x" in t for t in texts)

    def test_crosswiki_badge_in_text(self, sample_data):
        blocks = _build_top5_blocks(sample_data, "")
        texts = _all_texts(blocks)
        assert any("🌍" in t and "3개 언어판" in t for t in texts)

    def test_rank_badge_in_text(self, sample_data):
        blocks = _build_top5_blocks(sample_data, "")
        texts = _all_texts(blocks)
        assert any("▲2" in t for t in texts)

    def test_url_in_text(self, sample_data):
        blocks = _build_top5_blocks(sample_data, "")
        texts = _all_texts(blocks)
        assert any("https://en.wikipedia.org/wiki/Alan_Turing" in t for t in texts)

    def test_language_flag_in_text(self, sample_data):
        blocks = _build_top5_blocks(sample_data, "")
        texts = _all_texts(blocks)
        assert any("🇺🇸" in t for t in texts)

    def test_analysis_text_in_section(self, sample_data):
        blocks = _build_top5_blocks(sample_data, "분석 내용입니다.")
        texts = _all_texts(blocks)
        assert any("분석 내용입니다." in t for t in texts)

    def test_news_section_appended_when_news_present(self, sample_data):
        blocks = _build_top5_blocks(sample_data, "")
        texts = _all_texts(blocks)
        assert any("📰" in t for t in texts)

    def test_no_news_when_news_empty(self, sample_data):
        sample_data.news_items = []
        blocks = _build_top5_blocks(sample_data, "")
        texts = _all_texts(blocks)
        assert not any("📰" in t for t in texts)

    def test_lang_editions_shows_each_edition_and_total(self):
        page = TopPage(
            label="Iran Strikes",
            url="https://en.wikipedia.org/wiki/Iran_Strikes",
            server_name="en.wikipedia.org",
            edits=450,
            lang_editions=[
                LangEdition(server_name="en.wikipedia.org", edits=450),
                LangEdition(server_name="ru.wikipedia.org", edits=320),
                LangEdition(server_name="es.wikipedia.org", edits=280),
            ],
        )
        data = ReportData(top_pages=[page])
        blocks = _build_top5_blocks(data, "")
        texts = _all_texts(blocks)
        combined = " ".join(texts)
        assert "450" in combined
        assert "320" in combined
        assert "280" in combined
        assert "1,050" in combined
        assert "합계" in combined

    def test_single_edition_shows_standard_format(self, sample_data):
        blocks = _build_top5_blocks(sample_data, "")
        texts = _all_texts(blocks)
        assert any("편집" in t for t in texts)
        assert not any("합계" in t for t in texts)

    def test_ends_with_divider(self, sample_data):
        blocks = _build_top5_blocks(sample_data, "")
        assert blocks[-1]["type"] == "divider"


# ─────────────────────────────────────────────
# _build_featured_blocks
# ─────────────────────────────────────────────


class TestBuildFeaturedBlocks:
    def test_first_block_is_header_with_교양코너(self, sample_data):
        blocks = _build_featured_blocks(sample_data, "특집 소개")
        assert blocks[0]["type"] == "header"
        assert "교양 코너" in blocks[0]["text"]["text"]

    def test_returns_empty_when_no_title(self, sample_data):
        sample_data.featured_article.title = ""
        blocks = _build_featured_blocks(sample_data, "")
        assert blocks == []

    def test_url_in_text(self, sample_data):
        blocks = _build_featured_blocks(sample_data, "소개")
        texts = _all_texts(blocks)
        assert any("https://en.wikipedia.org/wiki/Marie_Curie" in t for t in texts)

    def test_thumbnail_image_block(self, sample_data):
        blocks = _build_featured_blocks(sample_data, "소개")
        assert any(b.get("type") == "image" for b in blocks)

    def test_featured_text_in_section(self, sample_data):
        blocks = _build_featured_blocks(sample_data, "특집 소개 텍스트")
        texts = _all_texts(blocks)
        assert any("특집 소개 텍스트" in t for t in texts)

    def test_fallback_to_extract_when_no_text(self, sample_data):
        blocks = _build_featured_blocks(sample_data, "")
        texts = _all_texts(blocks)
        assert any("Marie Curie was a physicist" in t for t in texts)


# ─────────────────────────────────────────────
# publish_report
# ─────────────────────────────────────────────


class TestPublishReport:
    def test_posts_json_to_slack(self, mocker, sample_data, sample_sections):
        mock_cm = _mock_slack(mocker)

        publish_report(sample_sections, sample_data)

        mock_cm.post.assert_called_once()
        payload = mock_cm.post.call_args.kwargs["json"]
        assert "blocks" in payload

    def test_fallback_text_set(self, mocker, sample_data, sample_sections):
        mock_cm = _mock_slack(mocker)

        publish_report(sample_sections, sample_data)

        payload = mock_cm.post.call_args.kwargs["json"]
        assert "Wikipedia 일일 트렌드" in payload["text"]

    def test_all_section_headers_present(self, mocker, sample_data, sample_sections):
        """Headline + 숫자 + Top5 + 논쟁 + 교양 = 5 headers."""
        mock_cm = _mock_slack(mocker)

        publish_report(sample_sections, sample_data)

        headers = _header_texts(mock_cm.post.call_args.kwargs["json"]["blocks"])
        assert any("Wikipedia 일일 트렌드" in h for h in headers)
        assert any("숫자로" in h for h in headers)
        assert any("Top 5" in h for h in headers)
        assert any("논쟁" in h for h in headers)
        assert any("교양 코너" in h for h in headers)

    def test_four_section_headers_when_no_featured(
        self, mocker, sample_data, sample_sections
    ):
        sample_data.featured_article.title = ""
        mock_cm = _mock_slack(mocker)

        publish_report(sample_sections, sample_data)

        headers = _header_texts(mock_cm.post.call_args.kwargs["json"]["blocks"])
        assert not any("교양 코너" in h for h in headers)
        assert len(headers) == 4

    def test_peak_hour_in_stats_fields(self, mocker, sample_data, sample_sections):
        mock_cm = _mock_slack(mocker)

        publish_report(sample_sections, sample_data)

        texts = _all_texts(mock_cm.post.call_args.kwargs["json"]["blocks"])
        assert any("편집 피크 시간대" in t for t in texts)

    def test_no_peak_hour_when_hour_negative(
        self, mocker, sample_data, sample_sections
    ):
        sample_data.peak_hour = PeakHour(hour=-1, edits=0)
        mock_cm = _mock_slack(mocker)

        publish_report(sample_sections, sample_data)

        texts = _all_texts(mock_cm.post.call_args.kwargs["json"]["blocks"])
        assert not any("편집 피크 시간대" in t for t in texts)
