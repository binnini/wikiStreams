"""Unit tests for reporter.publisher module."""

from unittest.mock import MagicMock

import pytest

from reporter.fetcher import (
    FeaturedArticle,
    NewsItem,
    OverallStats,
    PeakHour,
    ReportData,
    TopPage,
)
from reporter.publisher import (
    _build_featured_embed,
    _build_top5_embed,
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


def _mock_discord(mocker):
    """Patch httpx.Client so Discord POST doesn't actually fire."""
    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None

    mock_cm = MagicMock()
    mock_cm.__enter__.return_value = mock_cm
    mock_cm.__exit__.return_value = False
    mock_cm.post.return_value = mock_resp

    mocker.patch("httpx.Client", return_value=mock_cm)
    return mock_cm


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
# _build_top5_embed
# ─────────────────────────────────────────────


class TestBuildTop5Embed:
    def test_returns_dict_with_required_keys(self, sample_data):
        embed = _build_top5_embed(sample_data, "분석")

        assert "title" in embed
        assert "color" in embed
        assert "fields" in embed

    def test_spike_badge_in_field_value(self, sample_data):
        embed = _build_top5_embed(sample_data, "")
        value = embed["fields"][0]["value"]

        assert "⚡" in value
        assert "4.5x" in value

    def test_crosswiki_badge_in_field_value(self, sample_data):
        embed = _build_top5_embed(sample_data, "")
        value = embed["fields"][0]["value"]

        assert "🌍" in value
        assert "3개 언어판" in value

    def test_rank_badge_in_field_name(self, sample_data):
        embed = _build_top5_embed(sample_data, "")
        name = embed["fields"][0]["name"]

        assert "▲2" in name

    def test_url_in_field_value(self, sample_data):
        embed = _build_top5_embed(sample_data, "")
        value = embed["fields"][0]["value"]

        assert "https://en.wikipedia.org/wiki/Alan_Turing" in value

    def test_language_flag_in_field_value(self, sample_data):
        embed = _build_top5_embed(sample_data, "")
        value = embed["fields"][0]["value"]

        assert "🇺🇸" in value

    def test_thumbnail_set_from_first_page(self, sample_data):
        embed = _build_top5_embed(sample_data, "")

        assert embed.get("thumbnail", {}).get("url") == "https://example.com/thumb.jpg"

    def test_no_thumbnail_key_when_url_empty(self, sample_data):
        sample_data.top_pages[0].thumbnail_url = ""
        embed = _build_top5_embed(sample_data, "")

        assert "thumbnail" not in embed

    def test_analysis_text_as_description(self, sample_data):
        embed = _build_top5_embed(sample_data, "분석 내용입니다.")

        assert embed.get("description") == "분석 내용입니다."

    def test_news_field_appended_when_news_present(self, sample_data):
        embed = _build_top5_embed(sample_data, "")
        field_names = [f["name"] for f in embed["fields"]]

        assert "📰 관련 최신 뉴스" in field_names

    def test_no_news_field_when_news_empty(self, sample_data):
        sample_data.news_items = []
        embed = _build_top5_embed(sample_data, "")
        field_names = [f["name"] for f in embed["fields"]]

        assert "📰 관련 최신 뉴스" not in field_names

    def test_empty_analysis_omits_description_key(self, sample_data):
        embed = _build_top5_embed(sample_data, "")

        # empty string is falsy — description should not be set
        assert embed.get("description") is None or embed.get("description") == ""


# ─────────────────────────────────────────────
# _build_featured_embed
# ─────────────────────────────────────────────


class TestBuildFeaturedEmbed:
    def test_title_contains_교양코너(self, sample_data):
        embed = _build_featured_embed(sample_data, "특집 소개")

        assert embed is not None
        assert "교양 코너" in embed["title"]

    def test_returns_none_when_no_title(self, sample_data):
        sample_data.featured_article.title = ""
        embed = _build_featured_embed(sample_data, "")

        assert embed is None

    def test_url_set(self, sample_data):
        embed = _build_featured_embed(sample_data, "소개")

        assert embed["url"] == "https://en.wikipedia.org/wiki/Marie_Curie"

    def test_thumbnail_set(self, sample_data):
        embed = _build_featured_embed(sample_data, "소개")

        assert embed["thumbnail"]["url"] == "https://example.com/marie.jpg"

    def test_featured_text_used_in_field_value(self, sample_data):
        embed = _build_featured_embed(sample_data, "특집 소개 텍스트")
        value = embed["fields"][0]["value"]

        assert "특집 소개 텍스트" in value

    def test_fallback_to_extract_when_no_text(self, sample_data):
        embed = _build_featured_embed(sample_data, "")
        value = embed["fields"][0]["value"]

        assert "Marie Curie was a physicist" in value


# ─────────────────────────────────────────────
# publish_report
# ─────────────────────────────────────────────


class TestPublishReport:
    def test_posts_json_to_discord(self, mocker, sample_data, sample_sections):
        mock_cm = _mock_discord(mocker)

        publish_report(sample_sections, sample_data)

        mock_cm.post.assert_called_once()
        payload = mock_cm.post.call_args.kwargs["json"]
        assert "embeds" in payload

    def test_five_embeds_when_featured_present(
        self, mocker, sample_data, sample_sections
    ):
        """Headline + Numbers + Top5 + Controversy + Featured = 5."""
        mock_cm = _mock_discord(mocker)

        publish_report(sample_sections, sample_data)

        embeds = mock_cm.post.call_args.kwargs["json"]["embeds"]
        assert len(embeds) == 5

    def test_four_embeds_when_no_featured(self, mocker, sample_data, sample_sections):
        sample_data.featured_article.title = ""
        mock_cm = _mock_discord(mocker)

        publish_report(sample_sections, sample_data)

        embeds = mock_cm.post.call_args.kwargs["json"]["embeds"]
        assert len(embeds) == 4

    def test_embed_order(self, mocker, sample_data, sample_sections):
        """Order: headline → numbers → top5 → controversy → featured."""
        mock_cm = _mock_discord(mocker)

        publish_report(sample_sections, sample_data)

        embeds = mock_cm.post.call_args.kwargs["json"]["embeds"]
        assert "Wikipedia 일일 트렌드" in embeds[0]["title"]
        assert "숫자로" in embeds[1]["title"]
        assert "Top 5" in embeds[2]["title"]
        assert "논쟁" in embeds[3]["title"]
        assert "교양 코너" in embeds[4]["title"]

    def test_peak_hour_field_in_numbers_embed(
        self, mocker, sample_data, sample_sections
    ):
        mock_cm = _mock_discord(mocker)

        publish_report(sample_sections, sample_data)

        numbers_embed = mock_cm.post.call_args.kwargs["json"]["embeds"][1]
        field_names = [f["name"] for f in numbers_embed["fields"]]
        assert "⏰ 편집 피크 시간대" in field_names

    def test_no_peak_hour_field_when_hour_negative(
        self, mocker, sample_data, sample_sections
    ):
        """PeakHour.hour == -1 (default) means no peak hour field."""
        sample_data.peak_hour = PeakHour(hour=-1, edits=0)
        mock_cm = _mock_discord(mocker)

        publish_report(sample_sections, sample_data)

        numbers_embed = mock_cm.post.call_args.kwargs["json"]["embeds"][1]
        field_names = [f["name"] for f in numbers_embed["fields"]]
        assert "⏰ 편집 피크 시간대" not in field_names
