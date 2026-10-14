"""인증 없는 요청의 값을 로그에 찍을 때 — 줄바꿈으로 가짜 로그 줄을 끼워 넣지 못하게 한다."""

from __future__ import annotations

import logging

from fastapi.testclient import TestClient

from app.api.log_safe import sanitize_for_log
from tests.test_call_status import make_client

EVIL = "CAx\nWARNING fake line\rinjected " + "z" * 200


def test_newlines_and_other_control_characters_are_replaced():
    assert "\n" not in sanitize_for_log("a\nb\rc\x00d\x1be")
    assert sanitize_for_log("a\nb") == "a b"


def test_long_values_are_cut_to_the_limit_and_marked():
    text = sanitize_for_log("x" * 500, limit=10)

    assert text == "x" * 10 + "…"
    assert sanitize_for_log("short") == "short"
    assert len(sanitize_for_log("y" * 500)) == 64 + 1


def test_non_strings_are_accepted():
    assert sanitize_for_log(None) == "None"
    assert sanitize_for_log(123) == "123"


def _records_text(caplog):
    return [r.getMessage() for r in caplog.records]


def test_voiceml_log_with_a_hostile_call_id_stays_one_short_line(caplog):
    client, _, _ = make_client()

    with caplog.at_level(logging.INFO):
        client.post("/v1/voiceml", data={"CallId": EVIL})

    lines = [m for m in _records_text(caplog) if "VoiceML" in m]
    assert len(lines) == 1
    assert "\n" not in lines[0] and "\r" not in lines[0]
    assert "z" * 100 not in lines[0]


def test_stream_ended_logs_stay_one_short_line_each(caplog):
    client, _, _ = make_client()

    with caplog.at_level(logging.INFO):
        client.post("/v1/stream-ended", data={"CallId": EVIL, "StreamEvent": EVIL})

    messages = _records_text(caplog)
    assert messages  # 스트림 종료 로그와 모르는 CallId 로그
    for message in messages:
        assert "\n" not in message and "\r" not in message
        assert "z" * 100 not in message
