"""Persist each report run as a dated JSON file in REPORT_STORAGE_DIR."""

import dataclasses
import json
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path

from reporter.config import settings
from reporter.fetcher import (
    FeaturedArticle,
    LangEdition,
    NewsItem,
    OverallStats,
    PeakHour,
    ReportData,
    RevertPage,
    TopPage,
)

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))


def _today() -> str:
    return datetime.now(KST).strftime("%Y-%m-%d")


def _report_path(date: str) -> Path:
    return Path(settings.report_storage_dir) / f"{date}.json"


# ── Save ──────────────────────────────────────────────────────────────────────


def save_report(sections: dict[str, str], data: ReportData) -> Path:
    """Write the report to <REPORT_STORAGE_DIR>/YYYY-MM-DD.json.

    Same-day re-runs overwrite the file (latest result wins).
    Returns the path of the saved file.
    """
    storage_dir = Path(settings.report_storage_dir)
    storage_dir.mkdir(parents=True, exist_ok=True)

    filepath = _report_path(_today())

    payload = {
        "generated_at": datetime.now(KST).isoformat(),
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
    return filepath


# ── Load ──────────────────────────────────────────────────────────────────────


def load_report(date: str = None) -> tuple[dict[str, str], ReportData]:
    """Load a saved report JSON and reconstruct (sections, ReportData).

    Args:
        date: 'YYYY-MM-DD' string. Defaults to today (KST).

    Raises:
        FileNotFoundError: if the JSON file for the given date does not exist.
    """
    filepath = _report_path(date or _today())
    if not filepath.exists():
        raise FileNotFoundError(f"No saved report found: {filepath}")

    with open(filepath, encoding="utf-8") as f:
        payload = json.load(f)

    sections: dict[str, str] = payload["sections"]

    data = ReportData(
        stats=OverallStats(**payload["stats"]),
        peak_hour=PeakHour(**payload["peak_hour"]),
        top_pages=[
            TopPage(
                **{k: v for k, v in p.items() if k != "lang_editions"},
                lang_editions=[LangEdition(**e) for e in p.get("lang_editions", [])],
            )
            for p in payload["top_pages"]
        ],
        revert_pages=[RevertPage(**r) for r in payload["revert_pages"]],
        featured_article=FeaturedArticle(**payload["featured_article"]),
        news_items=[NewsItem(**n) for n in payload["news_items"]],
    )

    logger.info("Report loaded ← %s", filepath)
    return sections, data
