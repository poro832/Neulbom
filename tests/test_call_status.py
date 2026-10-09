"""통화 상태 통보 — 안 받음을 아는 유일한 길 (지금은 로그만 남긴다).

어르신이 받지 않으면 VoiceML도 종료 웹훅도 오지 않는다(2026-10-06, 안 받은
통화의 ClawOps 이벤트가 call.ringing 하나뿐이었다). 그래서 발신할 때 상태
통보 주소를 넘긴다. 통보의 필드 이름은 문서에 없어, 먼저 실제로 온 것을
기록하고 그 모양을 본 뒤에 안 받음 처리를 붙인다.
"""

from __future__ import annotations

import logging

import pytest
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


def _placed(client, store):
    created = client.post("/v1/calls/request", json={"elder_id": 12}).json()
    call = store.get(created["call_id"])
    return call.call_id, call.provider_call_sid


def test_an_unrecognised_field_changes_no_call_state():
    """CallStatus가 아닌 이름의 필드는 상태를 바꾸지 않는다 — 모르는 모양을 추측하지 않는다."""
    client, store, _ = make_client()
    call_id, sid = _placed(client, store)
    before = store.get(call_id).status

    client.post("/v1/call-status", data={"CallId": sid, "Status": "no-answer"})

    assert store.get(call_id).status == before


def test_no_answer_marks_an_unanswered_call_and_frees_the_elder():
    """실제 통보(2026-10-08): 안 받으면 ringing 약 30초 뒤 CallStatus=no-answer가 온다."""
    client, store, _ = make_client()
    call_id, sid = _placed(client, store)
    assert store.get(call_id).status == "ringing"

    response = client.post(
        "/v1/call-status",
        data={"CallId": sid, "CallStatus": "no-answer", "HangupCause": "no_answer"},
    )

    assert response.status_code == 204
    assert store.get(call_id).status == "no_answer"
    assert store.find_active(12) is None


def test_no_answer_revokes_the_stream_token():
    client, store, _ = make_client()
    _, sid = _placed(client, store)
    assert client.post("/v1/voiceml", data={"CallId": sid}).status_code == 200

    client.post("/v1/call-status", data={"CallId": sid, "CallStatus": "no-answer"})

    assert client.post("/v1/voiceml", data={"CallId": sid}).status_code == 404


def test_a_repeated_no_answer_is_harmless():
    client, store, _ = make_client()
    call_id, sid = _placed(client, store)

    for _ in range(2):
        r = client.post("/v1/call-status", data={"CallId": sid, "CallStatus": "no-answer"})
        assert r.status_code == 204

    assert store.get(call_id).status == "no_answer"


def test_no_answer_never_overwrites_a_call_that_was_answered():
    """받아서 대화한 통화를 '안 받음'으로 적으면 위험 점수의 미응답 20점이 틀린다."""
    client, store, _ = make_client()
    call_id, sid = _placed(client, store)
    store.mark_answered(call_id)

    client.post("/v1/call-status", data={"CallId": sid, "CallStatus": "no-answer"})

    assert store.get(call_id).status == "answered"


@pytest.mark.parametrize("status", ["initiated", "ringing", "in-progress", "completed", "busy", "failed"])
def test_other_statuses_do_not_change_the_call(status):
    """no-answer만 실제 통보로 확인했다. 나머지는 추측하지 않고 기록만 한다."""
    client, store, _ = make_client()
    call_id, sid = _placed(client, store)
    before = store.get(call_id).status

    client.post("/v1/call-status", data={"CallId": sid, "CallStatus": status})

    assert store.get(call_id).status == before


def test_no_answer_for_an_unknown_call_is_ignored_without_an_error():
    client, _, _ = make_client()

    response = client.post("/v1/call-status", data={"CallId": "CAnope", "CallStatus": "no-answer"})

    assert response.status_code == 204


def test_values_are_truncated_and_newlines_removed():
    line = describe_status_payload({"k": "x" * 200, "n": "a\nb\rc"})

    assert "…" in line
    assert "\n" not in line and "\r" not in line


# ------------------------------------------------------------ 안 받음 알림 훅


def _client_with_hook(hook):
    from app.api.lifecycle import CallLifecycle

    store = InMemoryCallStore(phones={12: "070-1111-2222"})
    registry = InMemoryCallRegistry()
    kit = auth_kit()
    app = build_app(
        store=store,
        telephony=FakeTelephony(),
        registry=registry,
        public_base_url="https://api.example.com",
        stream_base_url="wss://api.example.com",
        lifecycle=CallLifecycle(store, registry, on_no_answer=hook),
        guardian_auth=kit.auth,
        elders=kit.directory,
    )
    return TestClient(app, headers=kit.headers), store


def _place(client, store):
    created = client.post("/v1/calls/request", json={"elder_id": 12}).json()
    call = store.get(created["call_id"])
    return call.call_id, call.provider_call_sid


def test_no_answer_calls_the_alert_hook_once_with_the_finished_call():
    seen = []
    client, store = _client_with_hook(seen.append)
    call_id, sid = _place(client, store)

    client.post("/v1/call-status", data={"CallId": sid, "CallStatus": "no-answer"})
    client.post("/v1/call-status", data={"CallId": sid, "CallStatus": "no-answer"})

    assert [c.call_id for c in seen][:1] == [call_id]
    assert seen[0].status == "no_answer" and seen[0].trigger_type == "requested"
    assert len(seen) == 1  # 재전송은 이미 끝난 통화라 다시 부르지 않는다


def test_the_hook_is_not_called_for_a_call_that_was_answered():
    seen = []
    client, store = _client_with_hook(seen.append)
    call_id, sid = _place(client, store)
    store.mark_answered(call_id)

    client.post("/v1/call-status", data={"CallId": sid, "CallStatus": "no-answer"})

    assert seen == []


def test_a_failing_hook_does_not_stop_the_call_from_being_closed():
    def broken(call):
        raise RuntimeError("알림 저장소 고장")

    client, store = _client_with_hook(broken)
    call_id, sid = _place(client, store)

    response = client.post("/v1/call-status", data={"CallId": sid, "CallStatus": "no-answer"})

    assert response.status_code == 204
    assert store.get(call_id).status == "no_answer"
    assert store.find_active(12) is None
