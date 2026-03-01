"""Unit tests for reporter.main.run_report()."""

import pytest

from reporter.fetcher import NewsItem, PeakHour, ReportData, TopPage
from reporter.main import run_report


@pytest.fixture
def mock_data():
    data = ReportData(peak_hour=PeakHour(hour=14, edits=500))
    data.top_pages = []
    data.news_items = []
    return data


@pytest.fixture
def mock_sections():
    return {
        "headline": "헤드라인",
        "top5_analysis": "분석",
        "controversy": "없음",
        "numbers": "숫자",
        "featured": "특집",
        "date": "2026년 03월 01일",
    }


class TestRunReport:
    def test_full_pipeline_executes_in_order(self, mocker, mock_data, mock_sections):
        mock_keywords = [["kw1", "kw2"]]

        mock_fetch = mocker.patch(
            "reporter.main.fetch_report_data", return_value=mock_data
        )
        mock_build = mocker.patch(
            "reporter.main.build_report", return_value=(mock_sections, mock_keywords)
        )
        mocker.patch("reporter.main.fetch_thumbnail", return_value="")
        mock_news = mocker.patch(
            "reporter.main.fetch_news_with_keywords", return_value=[]
        )
        mock_publish = mocker.patch("reporter.main.publish_report")

        run_report()

        mock_fetch.assert_called_once()
        mock_build.assert_called_once_with(mock_data)
        mock_news.assert_called_once_with(mock_data.top_pages, mock_keywords)
        mock_publish.assert_called_once_with(mock_sections, mock_data)

    def test_thumbnail_fetched_for_first_page_after_build(
        self, mocker, mock_data, mock_sections
    ):
        """fetch_thumbnail is called for the first selected page after build_report."""
        mock_data.top_pages = [
            TopPage(
                label="Top Article",
                title="Top_Article",
                server_name="en.wikipedia.org",
            )
        ]
        mocker.patch("reporter.main.fetch_report_data", return_value=mock_data)
        mocker.patch("reporter.main.build_report", return_value=(mock_sections, []))
        mock_thumb = mocker.patch(
            "reporter.main.fetch_thumbnail",
            return_value="https://example.com/thumb.jpg",
        )
        mocker.patch("reporter.main.fetch_news_with_keywords", return_value=[])
        mocker.patch("reporter.main.publish_report")

        run_report()

        mock_thumb.assert_called_once_with("en.wikipedia.org", "Top_Article")
        assert mock_data.top_pages[0].thumbnail_url == "https://example.com/thumb.jpg"

    def test_thumbnail_not_fetched_when_no_pages(
        self, mocker, mock_data, mock_sections
    ):
        """fetch_thumbnail is not called when top_pages is empty."""
        mock_data.top_pages = []
        mocker.patch("reporter.main.fetch_report_data", return_value=mock_data)
        mocker.patch("reporter.main.build_report", return_value=(mock_sections, []))
        mock_thumb = mocker.patch("reporter.main.fetch_thumbnail")
        mocker.patch("reporter.main.fetch_news_with_keywords", return_value=[])
        mocker.patch("reporter.main.publish_report")

        run_report()

        mock_thumb.assert_not_called()

    def test_fetched_news_assigned_to_data_before_publish(
        self, mocker, mock_data, mock_sections
    ):
        news_items = [NewsItem(title="News", link="https://example.com")]

        mocker.patch("reporter.main.fetch_report_data", return_value=mock_data)
        mocker.patch("reporter.main.build_report", return_value=(mock_sections, []))
        mocker.patch("reporter.main.fetch_thumbnail", return_value="")
        mocker.patch("reporter.main.fetch_news_with_keywords", return_value=news_items)
        mock_publish = mocker.patch("reporter.main.publish_report")

        run_report()

        published_data: ReportData = mock_publish.call_args.args[1]
        assert published_data.news_items == news_items

    def test_exception_in_fetch_is_caught(self, mocker):
        """Exceptions must not propagate; run_report() should always return."""
        mocker.patch(
            "reporter.main.fetch_report_data", side_effect=Exception("ClickHouse down")
        )

        run_report()  # must not raise

    def test_exception_prevents_publish(self, mocker):
        mocker.patch("reporter.main.fetch_report_data", side_effect=Exception("Error"))
        mock_publish = mocker.patch("reporter.main.publish_report")

        run_report()

        mock_publish.assert_not_called()

    def test_exception_in_build_prevents_publish(self, mocker, mock_data):
        mocker.patch("reporter.main.fetch_report_data", return_value=mock_data)
        mocker.patch(
            "reporter.main.build_report", side_effect=Exception("Claude error")
        )
        mock_publish = mocker.patch("reporter.main.publish_report")

        run_report()

        mock_publish.assert_not_called()
