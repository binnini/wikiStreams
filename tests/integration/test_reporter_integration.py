"""Integration tests for reporter — hit real external APIs.

These tests require internet access and may occasionally fail due to
rate-limiting or API unavailability.

Run with:
    PYTHONPATH=src pytest tests/integration/test_reporter_integration.py -m integration -v
"""

from datetime import datetime, timezone

import pytest

from reporter.fetcher import FeaturedArticle, _fetch_featured_article, _fetch_news


@pytest.mark.integration
class TestWikipediaFeaturedArticleAPI:
    """Tests against the real Wikipedia Featured Article REST API."""

    # Use a historical date to get stable results
    _DATE = datetime(2026, 1, 15, tzinfo=timezone.utc)

    def test_returns_featured_article_instance(self):
        result = _fetch_featured_article(self._DATE)

        assert isinstance(result, FeaturedArticle)

    def test_article_has_non_empty_title(self):
        result = _fetch_featured_article(self._DATE)

        assert (
            result.title != ""
        ), "Wikipedia always has a featured article; title should not be empty"

    def test_url_points_to_english_wikipedia(self):
        result = _fetch_featured_article(self._DATE)

        if result.url:
            assert "en.wikipedia.org" in result.url

    def test_extract_within_600_chars(self):
        result = _fetch_featured_article(self._DATE)

        assert len(result.extract) <= 600


@pytest.mark.integration
class TestGoogleNewsRSS:
    """Tests against the real Google News RSS feed."""

    def test_english_query_returns_list(self):
        result = _fetch_news("Python programming language", max_items=2)

        assert isinstance(result, list)

    def test_korean_query_returns_list(self):
        result = _fetch_news("파이썬 프로그래밍", max_items=2)

        assert isinstance(result, list)

    def test_news_items_have_title_and_link(self):
        result = _fetch_news("Wikipedia", max_items=3)

        for item in result:
            assert item.title != "", "News title must not be empty"
            assert item.link != "", "News link must not be empty"
            assert item.link.startswith("http"), "News link must be a valid URL"
