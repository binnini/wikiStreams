import pytest
from pydantic import ValidationError

from producer.models import WikidataApiResponse, WikimediaEvent

# ---------------------------------------------------------------------------
# 테스트 픽스처
# ---------------------------------------------------------------------------

VALID_EVENT = {
    "title": "South Korea",
    "server_name": "en.wikipedia.org",
    "type": "edit",
    "namespace": 0,
    "timestamp": 1700000000,
    "user": "TestUser",
    "bot": False,
}


# ---------------------------------------------------------------------------
# WikimediaEvent
# ---------------------------------------------------------------------------


def test_wikimedia_event_valid():
    event = WikimediaEvent.model_validate(VALID_EVENT)
    assert event.title == "South Korea"
    assert event.bot is False


def test_wikimedia_event_missing_required_field():
    incomplete = {k: v for k, v in VALID_EVENT.items() if k != "server_name"}
    with pytest.raises(ValidationError):
        WikimediaEvent.model_validate(incomplete)


def test_wikimedia_event_type_mismatch():
    bad_type = {**VALID_EVENT, "namespace": "not_an_int"}
    with pytest.raises(ValidationError):
        WikimediaEvent.model_validate(bad_type)


def test_wikimedia_event_extra_fields_preserved():
    event_with_extra = {**VALID_EVENT, "comment": "fixed typo", "minor": True}
    event = WikimediaEvent.model_validate(event_with_extra)
    dumped = event.model_dump()
    assert dumped["comment"] == "fixed typo"
    assert dumped["minor"] is True


def test_wikimedia_event_enrichment_fields_default_none():
    event = WikimediaEvent.model_validate(VALID_EVENT)
    assert event.wikidata_label is None
    assert event.wikidata_description is None


def test_wikimedia_event_enrichment_fields_set():
    enriched = {
        **VALID_EVENT,
        "wikidata_label": "대한민국",
        "wikidata_description": "동아시아 국가",
    }
    event = WikimediaEvent.model_validate(enriched)
    assert event.wikidata_label == "대한민국"


# ---------------------------------------------------------------------------
# WikidataApiResponse
# ---------------------------------------------------------------------------


def test_wikidata_api_response_valid():
    raw = {
        "entities": {
            "Q884": {"labels": {"en": {"value": "South Korea"}}},
        },
        "success": 1,
    }
    resp = WikidataApiResponse.model_validate(raw)
    assert "Q884" in resp.entities


def test_wikidata_api_response_missing_entity():
    raw = {
        "entities": {
            "Q9999999": {"missing": ""},
        },
        "success": 1,
    }
    resp = WikidataApiResponse.model_validate(raw)
    assert "missing" in resp.entities["Q9999999"]


def test_wikidata_api_response_missing_entities_key():
    with pytest.raises(ValidationError):
        WikidataApiResponse.model_validate({"success": 0})
