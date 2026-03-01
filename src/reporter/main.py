import logging

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from reporter.config import settings
from reporter.fetcher import fetch_report_data
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
        data = fetch_report_data()
        sections = build_report(data)
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
    logger.info(
        "Reporter scheduled at %02d:00 KST daily", settings.report_hour_kst
    )
    scheduler.start()


if __name__ == "__main__":
    main()
