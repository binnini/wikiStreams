import logging

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from reporter.config import settings
from reporter.fetcher import (
    fetch_report_data,
    fetch_news_with_keywords,
    fetch_thumbnail,
)
from reporter.builder import build_report
from reporter.publisher import publish_report
from reporter.storage import save_report, load_report

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)


def build_and_save() -> None:
    """Fetch data, call Claude, collect news → save to JSON.

    This is the expensive step (Anthropic API + Wikipedia + Google News).
    Does NOT send anything to Discord.
    """
    logger.info("Starting report build")
    data = fetch_report_data()
    sections, news_keywords = build_report(data)

    if data.top_pages:
        data.top_pages[0].thumbnail_url = fetch_thumbnail(
            data.top_pages[0].server_name, data.top_pages[0].title
        )

    data.news_items = fetch_news_with_keywords(data.top_pages, news_keywords)
    logger.info(
        "News fetched: %d items (keywords: %s)", len(data.news_items), news_keywords
    )

    save_report(sections, data)
    logger.info("Build complete")


def publish_saved(date: str = None) -> None:
    """Load a saved JSON report and publish it to Discord.

    No Anthropic API calls are made.

    Args:
        date: 'YYYY-MM-DD' to publish a specific day. Defaults to today (KST).
    """
    logger.info("Publishing saved report (date=%s)", date or "today")
    sections, data = load_report(date)
    publish_report(sections, data)
    logger.info("Publish complete")


def run_report() -> None:
    """Full pipeline: build + save + publish. Used by the scheduler."""
    try:
        build_and_save()
        publish_saved()
    except Exception as e:
        logger.error("Failed to run report: %s", e, exc_info=True)


def main() -> None:
    scheduler = BlockingScheduler(timezone="Asia/Seoul")
    scheduler.add_job(
        run_report,
        CronTrigger(hour=settings.report_hour_kst, minute=0, timezone="Asia/Seoul"),
    )
    logger.info("Reporter scheduled at %02d:00 KST daily", settings.report_hour_kst)
    scheduler.start()


if __name__ == "__main__":
    main()
