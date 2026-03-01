"""Unit tests for reporter.fetcher module."""
from datetime import datetime, timezone, timedelta
from email.utils import format_datetime
from unittest.mock import MagicMock

import httpx
import pytest

from reporter.fetcher import (
    FeaturedArticle,
    NewsItem,
    ReportData,
    TopPage,
    _fetch_featured_article,
    _fetch_news,
    _fetch_thumbnail,
    fetch_news_with_keywords,
    fetch_report_data,
    wiki_url,
)


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────


def _rss_xml(items: list[dict]) -> str:
    """Build a minimal RSS 2.0 XML string.

    Each item dict: title, link, source, pubdate (RFC 2822 str).
    """
    item_tags = ""
    for it in items:
        item_tags += f"""
        <item>
            <title>{it["title"]}</title>
            <link>{it["link"]}</link>
            <source>{it["source"]}</source>
            <pubDate>{it["pubdate"]}</pubDate>
        </item>"""
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>{item_tags}
  </channel>
</rss>"""


def _recent_pubdate(hours_ago: int = 1) -> str:
    dt = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    return format_datetime(dt)


def _old_pubdate() -> str:
    dt = datetime.now(timezone.utc) - timedelta(hours=72)
    return format_datetime(dt)


def _mock_client(mocker, text: str = "", json_data: dict | None = None):
    """Patch httpx.Client to return a single mock response."""
    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None
    mock_resp.text = text
    if json_data is not None:
        mock_resp.json.return_value = json_data

    mock_cm = MagicMock()
    mock_cm.__enter__.return_value = mock_cm
    mock_cm.__exit__.return_value = False
    mock_cm.get.return_value = mock_resp

    mocker.patch("httpx.Client", return_value=mock_cm)
    return mock_cm, mock_resp


def _make_http_cm(resp):
    """Build a mock context manager wrapping a mock response."""
    cm = MagicMock()
    cm.__enter__.return_value = cm
    cm.__exit__.return_value = False
    cm.get.return_value = resp
    return cm


# ─────────────────────────────────────────────
# wiki_url
# ─────────────────────────────────────────────


class TestWikiUrl:
    def test_simple_title(self):
        assert wiki_url("en.wikipedia.org", "Python") == "https://en.wikipedia.org/wiki/Python"

    def test_spaces_replaced_with_underscores(self):
        result = wiki_url("en.wikipedia.org", "Alan Turing")
        assert result == "https://en.wikipedia.org/wiki/Alan_Turing"

    def test_special_chars_percent_encoded(self):
        result = wiki_url("ko.wikipedia.org", "대한민국")
        assert "ko.wikipedia.org/wiki/" in result
        assert "대한민국" not in result  # must be percent-encoded

    def test_different_server(self):
        result = wiki_url("ja.wikipedia.org", "Python")
        assert result.startswith("https://ja.wikipedia.org/wiki/")


# ─────────────────────────────────────────────
# _fetch_news
# ─────────────────────────────────────────────


class TestFetchNews:
    def test_korean_edition_returns_results(self, mocker):
        rss = _rss_xml([
            {
                "title": "테스트 뉴스 제목",
                "link": "https://example.com/1",
                "source": "연합뉴스",
                "pubdate": _recent_pubdate(1),
            }
        ])
        _mock_client(mocker, text=rss)

        result = _fetch_news("테스트 쿼리", max_items=2)

        assert len(result) == 1
        assert result[0].title == "테스트 뉴스 제목"
        assert result[0].link == "https://example.com/1"
        assert result[0].source == "연합뉴스"

    def test_korean_empty_falls_back_to_english(self, mocker):
        empty_rss = _rss_xml([])
        en_rss = _rss_xml([
            {
                "title": "Wikipedia Trending Article",
                "link": "https://example.com/en1",
                "source": "Reuters",
                "pubdate": _recent_pubdate(2),
            }
        ])

        ko_resp = MagicMock()
        ko_resp.raise_for_status.return_value = None
        ko_resp.text = empty_rss

        en_resp = MagicMock()
        en_resp.raise_for_status.return_value = None
        en_resp.text = en_rss

        mocker.patch("httpx.Client", side_effect=[_make_http_cm(ko_resp), _make_http_cm(en_resp)])

        # Pass relevance keyword that matches the English title
        result = _fetch_news("wikipedia", relevance_keywords={"wikipedia"}, max_items=2)

        assert len(result) == 1
        assert result[0].title == "Wikipedia Trending Article"

    def test_48h_filter_removes_old_news(self, mocker):
        rss = _rss_xml([
            {
                "title": "Old News",
                "link": "https://example.com/old",
                "source": "Src",
                "pubdate": _old_pubdate(),
            },
            {
                "title": "Recent News",
                "link": "https://example.com/new",
                "source": "Src",
                "pubdate": _recent_pubdate(1),
            },
        ])
        _mock_client(mocker, text=rss)

        result = _fetch_news("query", max_items=5)

        titles = [r.title for r in result]
        assert "Old News" not in titles
        assert "Recent News" in titles

    def test_korean_edition_skips_relevance_filter(self, mocker):
        """Korean RSS results are not filtered by relevance_keywords."""
        rss = _rss_xml([
            {
                "title": "한국어 뉴스 제목",
                "link": "https://example.com/ko",
                "source": "MBC",
                "pubdate": _recent_pubdate(1),
            }
        ])
        _mock_client(mocker, text=rss)

        # The headline has no English keyword; Korean edition must still pass through
        result = _fetch_news("Korea", relevance_keywords={"unrelated_english_word"}, max_items=5)

        assert len(result) == 1
        assert result[0].title == "한국어 뉴스 제목"

    def test_english_edition_applies_relevance_filter(self, mocker):
        """English fallback filters by relevance_keywords."""
        empty_rss = _rss_xml([])
        en_rss = _rss_xml([
            {
                "title": "Relevant Python Story",
                "link": "https://example.com/py",
                "source": "TechNews",
                "pubdate": _recent_pubdate(2),
            },
            {
                "title": "Irrelevant Story About Cats",
                "link": "https://example.com/cats",
                "source": "PetNews",
                "pubdate": _recent_pubdate(3),
            },
        ])

        ko_resp = MagicMock()
        ko_resp.raise_for_status.return_value = None
        ko_resp.text = empty_rss

        en_resp = MagicMock()
        en_resp.raise_for_status.return_value = None
        en_resp.text = en_rss

        mocker.patch("httpx.Client", side_effect=[_make_http_cm(ko_resp), _make_http_cm(en_resp)])

        result = _fetch_news("python", relevance_keywords={"python"}, max_items=5)

        assert len(result) == 1
        assert result[0].title == "Relevant Python Story"

    def test_http_error_returns_empty(self, mocker):
        mock_cm = MagicMock()
        mock_cm.__enter__.return_value = mock_cm
        mock_cm.__exit__.return_value = False
        mock_cm.get.side_effect = httpx.HTTPError("Network error")
        mocker.patch("httpx.Client", return_value=mock_cm)

        result = _fetch_news("query", max_items=2)

        assert result == []

    def test_max_items_respected(self, mocker):
        rss = _rss_xml([
            {
                "title": f"News {i}",
                "link": f"https://example.com/{i}",
                "source": "Src",
                "pubdate": _recent_pubdate(1),
            }
            for i in range(5)
        ])
        _mock_client(mocker, text=rss)

        result = _fetch_news("query", max_items=2)

        assert len(result) == 2


# ─────────────────────────────────────────────
# fetch_news_with_keywords
# ─────────────────────────────────────────────


class TestFetchNewsWithKeywords:
    def test_uses_first_two_keywords_as_query(self, mocker):
        mock_fn = mocker.patch("reporter.fetcher._fetch_news", return_value=[])
        pages = [TopPage(label="Test Page", title="Test_Page", server_name="en.wikipedia.org")]

        fetch_news_with_keywords(pages, [["KeywordA", "KeywordB", "KeywordC"]])

        query = mock_fn.call_args_list[0][0][0]
        assert query == "KeywordA KeywordB"

    def test_falls_back_to_label_when_no_keywords(self, mocker):
        mock_fn = mocker.patch("reporter.fetcher._fetch_news", return_value=[])
        pages = [TopPage(label="My Article", title="My_Article", server_name="en.wikipedia.org")]

        fetch_news_with_keywords(pages, [])

        query = mock_fn.call_args_list[0][0][0]
        assert "My Article" in query

    def test_processes_at_most_first_3_pages(self, mocker):
        mock_fn = mocker.patch("reporter.fetcher._fetch_news", return_value=[])
        pages = [
            TopPage(label=f"Page {i}", title=f"Page_{i}", server_name="en.wikipedia.org")
            for i in range(5)
        ]

        fetch_news_with_keywords(pages, [["kw"] for _ in range(5)])

        assert mock_fn.call_count == 3

    def test_results_capped_at_5(self, mocker):
        news_per_page = [
            NewsItem(title=f"News {i}", link=f"https://example.com/{i}")
            for i in range(3)
        ]
        mocker.patch("reporter.fetcher._fetch_news", return_value=news_per_page)
        pages = [
            TopPage(label=f"Page {i}", title=f"Page_{i}", server_name="en.wikipedia.org")
            for i in range(3)
        ]

        result = fetch_news_with_keywords(pages, [["kw"] for _ in range(3)])

        assert len(result) <= 5


# ─────────────────────────────────────────────
# _fetch_featured_article
# ─────────────────────────────────────────────


class TestFetchFeaturedArticle:
    def test_success(self, mocker):
        tfa_data = {
            "tfa": {
                "title": "Alan Turing",
                "description": "British mathematician",
                "extract": "Alan Turing was a famous mathematician.",
                "content_urls": {"desktop": {"page": "https://en.wikipedia.org/wiki/Alan_Turing"}},
                "thumbnail": {"source": "https://example.com/turing.jpg"},
            }
        }
        _mock_client(mocker, json_data=tfa_data)

        result = _fetch_featured_article(datetime(2026, 3, 1, tzinfo=timezone.utc))

        assert result.title == "Alan Turing"
        assert result.description == "British mathematician"
        assert result.url == "https://en.wikipedia.org/wiki/Alan_Turing"
        assert result.thumbnail_url == "https://example.com/turing.jpg"

    def test_empty_tfa_returns_empty_article(self, mocker):
        _mock_client(mocker, json_data={"tfa": {}})

        result = _fetch_featured_article(datetime(2026, 3, 1, tzinfo=timezone.utc))

        assert result.title == ""

    def test_http_error_returns_empty_article(self, mocker):
        mock_cm = MagicMock()
        mock_cm.__enter__.return_value = mock_cm
        mock_cm.__exit__.return_value = False
        mock_cm.get.side_effect = httpx.HTTPError("Timeout")
        mocker.patch("httpx.Client", return_value=mock_cm)

        result = _fetch_featured_article(datetime(2026, 3, 1, tzinfo=timezone.utc))

        assert isinstance(result, FeaturedArticle)
        assert result.title == ""

    def test_extract_truncated_to_600_chars(self, mocker):
        tfa_data = {
            "tfa": {
                "title": "Long Article",
                "extract": "X" * 700,
                "content_urls": {"desktop": {"page": ""}},
            }
        }
        _mock_client(mocker, json_data=tfa_data)

        result = _fetch_featured_article(datetime(2026, 3, 1, tzinfo=timezone.utc))

        assert len(result.extract) == 600


# ─────────────────────────────────────────────
# _fetch_thumbnail
# ─────────────────────────────────────────────


class TestFetchThumbnail:
    def test_success(self, mocker):
        _mock_client(mocker, json_data={"thumbnail": {"source": "https://example.com/thumb.jpg"}})

        result = _fetch_thumbnail("en.wikipedia.org", "Alan Turing")

        assert result == "https://example.com/thumb.jpg"

    def test_wikidata_returns_empty_without_http_call(self, mocker):
        mock_client_cls = mocker.patch("httpx.Client")

        result = _fetch_thumbnail("www.wikidata.org", "Q42")

        assert result == ""
        mock_client_cls.assert_not_called()

    def test_no_thumbnail_field_returns_empty(self, mocker):
        _mock_client(mocker, json_data={"title": "Some Page"})

        result = _fetch_thumbnail("en.wikipedia.org", "Some Page")

        assert result == ""

    def test_http_error_returns_empty(self, mocker):
        mock_cm = MagicMock()
        mock_cm.__enter__.return_value = mock_cm
        mock_cm.__exit__.return_value = False
        mock_cm.get.side_effect = httpx.HTTPError("Timeout")
        mocker.patch("httpx.Client", return_value=mock_cm)

        result = _fetch_thumbnail("en.wikipedia.org", "Some Page")

        assert result == ""


# ─────────────────────────────────────────────
# fetch_report_data — enrichment & side effects
# ─────────────────────────────────────────────


class TestFetchReportData:
    """Tests for fetch_report_data() using mocked _query and external calls."""

    def _query_side_effect(
        self,
        top_rows=None,
        spike_rows=None,
        crosswiki_rows=None,
        yesterday_rows=None,
    ):
        """Return ordered side_effect list matching all _query() calls."""
        return [
            [{"value": "10000"}],   # total_edits
            [{"value": "500"}],     # active_users
            [{"value": "20.5"}],    # bot_ratio_pct
            [{"value": "100"}],     # new_articles
            top_rows or [],         # top_pages
            spike_rows or [],       # spike_pages
            crosswiki_rows or [],   # crosswiki_pages
            [],                     # revert_pages
            [{"hour": "14", "edits": "1000"}],  # peak_hour
            yesterday_rows or [],   # yesterday_rank
        ]

    def _patch_all(self, mocker, **kwargs):
        mocker.patch("reporter.fetcher._query", side_effect=self._query_side_effect(**kwargs))
        mocker.patch("reporter.fetcher._fetch_thumbnail", return_value="")
        mocker.patch("reporter.fetcher._fetch_featured_article", return_value=FeaturedArticle())

    def test_overall_stats_parsed(self, mocker):
        self._patch_all(mocker)

        data = fetch_report_data()

        assert data.stats.total_edits == 10000
        assert data.stats.active_users == 500
        assert data.stats.bot_ratio_pct == 20.5
        assert data.stats.new_articles == 100

    def test_peak_hour_parsed(self, mocker):
        self._patch_all(mocker)

        data = fetch_report_data()

        assert data.peak_hour.hour == 14
        assert data.peak_hour.edits == 1000

    def test_spike_enrichment(self, mocker):
        top_rows = [
            {
                "label": "Page A", "title": "Page_A", "description": "",
                "server_name": "en.wikipedia.org", "edits": "50",
            }
        ]
        spike_rows = [
            {
                "label": "Page A", "title": "Page_A",
                "server_name": "en.wikipedia.org",
                "edits_15m": "30", "spike_ratio": "5.2",
            }
        ]
        self._patch_all(mocker, top_rows=top_rows, spike_rows=spike_rows)

        data = fetch_report_data()

        assert data.top_pages[0].is_spike is True
        assert data.top_pages[0].spike_ratio_val == 5.2

    def test_crosswiki_enrichment(self, mocker):
        top_rows = [
            {
                "label": "Global Topic", "title": "Global_Topic", "description": "",
                "server_name": "en.wikipedia.org", "edits": "80",
            }
        ]
        crosswiki_rows = [
            {
                "title": "Global_Topic", "wiki_count": "5",
                "total_edits": "200", "wikis": "en, ko, de, fr, ja",
            }
        ]
        self._patch_all(mocker, top_rows=top_rows, crosswiki_rows=crosswiki_rows)

        data = fetch_report_data()

        assert data.top_pages[0].crosswiki_count == 5

    def test_rank_change_improved(self, mocker):
        """Page was rank 3 yesterday, rank 1 today → rank_change = +2."""
        top_rows = [
            {
                "label": "Rising Page", "title": "Rising_Page", "description": "",
                "server_name": "en.wikipedia.org", "edits": "100",
            }
        ]
        yesterday_rows = [
            {"title": "Other1", "server_name": "en.wikipedia.org"},
            {"title": "Other2", "server_name": "en.wikipedia.org"},
            {"title": "Rising_Page", "server_name": "en.wikipedia.org"},
        ]
        self._patch_all(mocker, top_rows=top_rows, yesterday_rows=yesterday_rows)

        data = fetch_report_data()

        assert data.top_pages[0].rank_change == 2  # prev=3, today=1

    def test_rank_change_new_entry_is_none(self, mocker):
        """Page absent from yesterday's top → rank_change is None."""
        top_rows = [
            {
                "label": "New Page", "title": "New_Page", "description": "",
                "server_name": "en.wikipedia.org", "edits": "100",
            }
        ]
        self._patch_all(mocker, top_rows=top_rows, yesterday_rows=[])

        data = fetch_report_data()

        assert data.top_pages[0].rank_change is None

    def test_thumbnail_fetched_for_first_page(self, mocker):
        top_rows = [
            {
                "label": "Top Page", "title": "Top_Page", "description": "",
                "server_name": "en.wikipedia.org", "edits": "100",
            }
        ]
        mocker.patch("reporter.fetcher._query", side_effect=self._query_side_effect(top_rows=top_rows))
        mock_thumb = mocker.patch(
            "reporter.fetcher._fetch_thumbnail",
            return_value="https://example.com/thumb.jpg",
        )
        mocker.patch("reporter.fetcher._fetch_featured_article", return_value=FeaturedArticle())

        data = fetch_report_data()

        mock_thumb.assert_called_once_with("en.wikipedia.org", "Top_Page")
        assert data.top_pages[0].thumbnail_url == "https://example.com/thumb.jpg"

    def test_query_failure_returns_empty_data(self, mocker):
        """ClickHouse errors are caught; empty ReportData is returned."""
        mocker.patch("reporter.fetcher._query", side_effect=Exception("ClickHouse down"))
        mocker.patch("reporter.fetcher._fetch_thumbnail", return_value="")
        mocker.patch("reporter.fetcher._fetch_featured_article", return_value=FeaturedArticle())

        data = fetch_report_data()

        assert data.stats.total_edits == 0
        assert data.top_pages == []
