"""
questdb_consumer 단위 테스트

테스트 대상:
- _should_skip(): log/canary 이벤트 필터
- _tag(): ILP tag value 이스케이프
- _str(): ILP string field 이스케이프
- event_to_ilp(): 이벤트 → ILP 라인 변환
"""

from questdb_consumer.main import _should_skip, _tag, _str, event_to_ilp

# ── _should_skip ────────────────────────────────────────────────────────────


class TestShouldSkip:
    def test_skip_log_type(self):
        assert _should_skip({"type": "log"}) is True

    def test_skip_canary_domain(self):
        assert _should_skip({"type": "edit", "meta": {"domain": "canary"}}) is True

    def test_pass_normal_edit(self):
        assert (
            _should_skip({"type": "edit", "meta": {"domain": "en.wikipedia.org"}})
            is False
        )

    def test_pass_new_type(self):
        assert _should_skip({"type": "new"}) is False

    def test_pass_missing_meta(self):
        assert _should_skip({"type": "edit"}) is False

    def test_pass_empty_event(self):
        assert _should_skip({}) is False


# ── _tag ────────────────────────────────────────────────────────────────────


class TestTag:
    def test_escapes_comma(self):
        assert _tag("a,b") == "a\\,b"

    def test_escapes_equals(self):
        assert _tag("a=b") == "a\\=b"

    def test_escapes_space(self):
        assert _tag("a b") == "a\\ b"

    def test_no_escape_needed(self):
        assert _tag("en.wikipedia.org") == "en.wikipedia.org"

    def test_multiple_special_chars(self):
        assert _tag("a, b=c") == "a\\,\\ b\\=c"


# ── _str ────────────────────────────────────────────────────────────────────


class TestStr:
    def test_escapes_backslash(self):
        assert _str("a\\b") == "a\\\\b"

    def test_escapes_double_quote(self):
        assert _str('a"b') == 'a\\"b'

    def test_removes_newline(self):
        assert _str("a\nb") == "ab"

    def test_removes_carriage_return(self):
        assert _str("a\rb") == "ab"

    def test_normal_string(self):
        assert _str("hello world") == "hello world"

    def test_converts_non_string(self):
        assert _str(42) == "42"


# ── event_to_ilp ────────────────────────────────────────────────────────────


class TestEventToIlp:
    def _make_event(self, **kwargs):
        base = {
            "server_name": "en.wikipedia.org",
            "type": "edit",
            "title": "Test Page",
            "user": "TestUser",
            "bot": False,
            "namespace": 0,
            "minor": False,
            "comment": "minor fix",
            "wikidata_label": "",
            "wikidata_description": "",
            "timestamp": 1700000000,
        }
        base.update(kwargs)
        return base

    def test_returns_string(self):
        result = event_to_ilp(self._make_event())
        assert isinstance(result, str)

    def test_ends_with_newline(self):
        result = event_to_ilp(self._make_event())
        assert result.endswith("\n")

    def test_measurement_name(self):
        result = event_to_ilp(self._make_event())
        assert result.startswith("wikimedia_events,")

    def test_tag_server_name(self):
        result = event_to_ilp(self._make_event(server_name="de.wikipedia.org"))
        assert "server_name=de.wikipedia.org" in result

    def test_tag_wiki_type(self):
        result = event_to_ilp(self._make_event(type="new"))
        assert "wiki_type=new" in result

    def test_bot_true(self):
        result = event_to_ilp(self._make_event(bot=True))
        assert "bot=t" in result

    def test_bot_false(self):
        result = event_to_ilp(self._make_event(bot=False))
        assert "bot=f" in result

    def test_minor_true(self):
        result = event_to_ilp(self._make_event(minor=True))
        assert "minor=t" in result

    def test_timestamp_ns(self):
        result = event_to_ilp(self._make_event(timestamp=1700000000))
        assert "1700000000000000000" in result

    def test_comment_truncated_to_500(self):
        long_comment = "x" * 600
        result = event_to_ilp(self._make_event(comment=long_comment))
        assert "x" * 500 in result
        assert "x" * 501 not in result

    def test_wikidata_description_truncated_to_200(self):
        long_desc = "d" * 300
        result = event_to_ilp(self._make_event(wikidata_description=long_desc))
        assert "d" * 200 in result
        assert "d" * 201 not in result

    def test_none_comment_becomes_empty(self):
        result = event_to_ilp(self._make_event(comment=None))
        assert 'comment=""' in result

    def test_special_chars_in_title_escaped(self):
        result = event_to_ilp(self._make_event(title='Page "quoted"'))
        assert '\\"quoted\\"' in result

    def test_invalid_event_returns_none(self):
        # timestamp이 변환 불가한 값
        result = event_to_ilp({"timestamp": "not-a-number"})
        assert result is None

    def test_namespace_as_integer(self):
        result = event_to_ilp(self._make_event(namespace=4))
        assert "namespace=4i" in result
