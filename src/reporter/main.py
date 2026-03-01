import logging

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from reporter.config import settings
from reporter.fetcher import fetch_report_data, fetch_news_with_keywords
from reporter.builder import build_report
from reporter.publisher import publish_report

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)


def run_report() -> None:
    logger.info("Starting daily trend report generation")
    try:
        # 1. Fetch all ClickHouse data + external APIs (no news yet)
        data = fetch_report_data()

        # 2. Claude: generate sections + extract news search keywords
        sections, news_keywords = build_report(data)

        # 3. Fetch news using Claude-extracted keywords for better relevance
        data.news_items = fetch_news_with_keywords(data.top_pages, news_keywords)
        logger.info(
            "News fetched: %d items (keywords: %s)", len(data.news_items), news_keywords
        )

        # 4. Publish to Discord
        publish_report(sections, data)
        logger.info("Daily trend report sent successfully")
    except Exception as e:
        logger.error("Failed to generate/send report: %s", e, exc_info=True)


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
