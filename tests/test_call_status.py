"""통화 상태 통보 — 안 받음을 아는 유일한 길 (지금은 로그만 남긴다).

어르신이 받지 않으면 VoiceML도 종료 웹훅도 오지 않는다(2026-10-06, 안 받은
통화의 ClawOps 이벤트가 call.ringing 하나뿐이었다). 그래서 발신할 때 상태
통보 주소를 넘긴다. 통보의 필드 이름은 문서에 없어, 먼저 실제로 온 것을
기록하고 그 모양을 본 뒤에 안 받음 처리를 붙인다.
"""

from __future__ import annotations

import logging

from fastapi.testclient import TestClient

from app.api.calls import MAX_STATUS_BODY_BYTES, build_app, describe_status_payload
from app.api.store import InMemoryCallStore
from app.media.stream_server import InMemoryCallRegistry
from app.telephony.client import ClawOpsTelephony, FakeTelephony

import httpx

from tests.auth_helpers import auth_kit


def make_client():
    store = InMemoryCallStore(phones={12: "070-1111-2222"})
    telephony = FakeTelephony()
    kit = auth_kit()
    app = build_app(
        store=store,
        telephony=telephony,
        registry=InMemoryCallRegistry(),
        public_base_url="https://api.example.com",
        stream_base_url="wss://api.example.com",
        guardian_auth=kit.auth,
        elders=kit.directory,
    )
    return TestClient(app, headers=kit.headers), store, telephony


# ------------------------------------------------------------ 발신할 때 넘긴다


def test_the_trigger_hands_the_carrier_a_status_callback_address():
    client, _, telephony = make_client()

    client.post("/v1/calls/request", json={"elder_id": 12})

    assert telephony.status_callbacks == ["https://api.example.com/v1/call-status"]


def test_clawops_receives_the_callback_address_and_events(monkeypatch):
    sent = {}

    def fake_post(url, **kwargs):
        sent.update(kwargs["data"])
        return httpx.Response(
            201, json={"callId": "CAx"}, request=httpx.Request("POST", url)
        )

    monkeypatch.setattr(httpx, "post", fake_post)
    telephony = ClawOpsTelephony(account_sid="AC1", api_key="k", from_number="0700")

    telephony.place_call(
        to="01012345678",
        answer_url="https://x/voiceml",
        status_callback_url="https://x/v1/call-status",
    )

    assert sent["StatusCallback"] == "https://x/v1/call-status"
    assert sent["StatusCallbackEvent"] == "initiated ringing answered completed"


def test_without_a_callback_address_nothing_extra_is_sent(monkeypatch):
    sent = {}

    def fake_post(url, **kwargs):
        sent.update(kwargs["data"])
        return httpx.Response(
            201, json={"callId": "CAx"}, request=httpx.Request("POST", url)
        )

    monkeypatch.setattr(httpx, "post", fake_post)
    telephony = ClawOpsTelephony(account_sid="AC1", api_key="k", from_number="0700")

    telephony.place_call(to="01012345678", answer_url="https://x/voiceml")

    assert "StatusCallback" not in sent
    assert "StatusCallbackEvent" not in sent


# ------------------------------------------------------------ 받는 쪽 (로그만)


def test_a_form_payload_is_accepted_and_its_fields_are_logged(caplog):
    client, _, _ = make_client()

    with caplog.at_level(logging.INFO, logger="app.api.calls"):
        response = client.post(
            "/v1/call-status",
            data={"CallId": "CAabc", "Status": "no-answer", "Duration": "0"},
        )

    assert response.status_code == 204
    assert "CallId=CAabc" in caplog.text
    assert "Status=no-answer" in caplog.text


def test_a_json_payload_is_accepted_too(caplog):
    """ClawOps가 폼이 아니라 JSON으로 보낼 수도 있다 — 문서에 없다."""
    client, _, _ = make_client()

    with caplog.at_level(logging.INFO, logger="app.api.calls"):
        response = client.post(
            "/v1/call-status", json={"callId": "CAabc", "status": "completed"}
        )

    assert response.status_code == 204
    assert "status=completed" in caplog.text


def test_phone_numbers_never_reach_the_log(caplog):
    client, _, _ = make_client()

    with caplog.at_level(logging.INFO, logger="app.api.calls"):
        client.post(
            "/v1/call-status",
            data={"CallId": "CAabc", "To": "01034472884", "From": "070-5276-7846"},
        )

    assert "01034472884" not in caplog.text
    assert "5276" not in caplog.text
    assert "To=***" in caplog.text


def test_it_never_answers_with_an_error_so_the_carrier_does_not_retry():
    client, _, _ = make_client()

    assert client.post("/v1/call-status").status_code == 204
    assert (
        client.post(
            "/v1/call-status", content=b"{not json", headers={"content-type": "application/json"}
        ).status_code
        == 204
    )


def test_an_oversized_body_is_dropped_without_logging_it(caplog):
    client, _, _ = make_client()
    huge = "a" * (MAX_STATUS_BODY_BYTES + 100)

    with caplog.at_level(logging.INFO, logger="app.api.calls"):
        response = client.post("/v1/call-status", data={"CallId": huge})

    assert response.status_code == 204
    assert huge[:50] not in caplog.text


def test_it_changes_no_call_state_yet():
    """지금은 관찰만 한다. 필드 모양을 보기 전에 상태를 바꾸면 추측이 된다."""
    client, store, _ = make_client()
    created = client.post("/v1/calls/request", json={"elder_id": 12}).json()
    before = store.get(created["call_id"]).status

    client.post(
        "/v1/call-status",
        data={"CallId": store.get(created["call_id"]).provider_call_sid, "Status": "no-answer"},
    )

    assert store.get(created["call_id"]).status == before


def test_values_are_truncated_and_newlines_removed():
    line = describe_status_payload({"k": "x" * 200, "n": "a\nb\rc"})

    assert "…" in line
    assert "\n" not in line and "\r" not in line
