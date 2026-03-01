"""Persist each report run as a dated JSON file in REPORT_STORAGE_DIR."""

import dataclasses
import json
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path

from reporter.config import settings
from reporter.fetcher import ReportData

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))


def save_report(sections: dict[str, str], data: ReportData) -> None:
    """Write the report to <REPORT_STORAGE_DIR>/YYYY-MM-DD.json.

    The file is overwritten if the same date is generated more than once
    (e.g. manual re-runs), so the directory always holds the latest result
    for each day.
    """
    storage_dir = Path(settings.report_storage_dir)
    storage_dir.mkdir(parents=True, exist_ok=True)

    now = datetime.now(KST)
    filepath = storage_dir / now.strftime("%Y-%m-%d.json")

    payload = {
        "generated_at": now.isoformat(),
        "prompt_style": settings.prompt_style,
        "sections": sections,
        "stats": dataclasses.asdict(data.stats),
        "peak_hour": dataclasses.asdict(data.peak_hour),
        "top_pages": [dataclasses.asdict(p) for p in data.top_pages],
        "revert_pages": [dataclasses.asdict(p) for p in data.revert_pages],
        "featured_article": dataclasses.asdict(data.featured_article),
        "news_items": [dataclasses.asdict(n) for n in data.news_items],
    }

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    logger.info("Report saved → %s", filepath)
