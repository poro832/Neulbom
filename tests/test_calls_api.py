"""트리거 API (전화망 설계 5장).

앱 버튼은 "전화를 걸어 달라"는 신호다. 인앱 마이크도 소켓도 없다.
FakeTelephony 덕분에 ClawOps 계정 없이 전부 검증된다.
"""

from fastapi.testclient import TestClient

from app.api.calls import build_app
from app.api.store import InMemoryCallStore
from app.media.stream_server import InMemoryCallRegistry
from app.telephony.client import FakeTelephony


def make_client(telephony=None):
    store = InMemoryCallStore(phones={12: "070-1111-2222"})
    telephony = telephony or FakeTelephony()
    registry = InMemoryCallRegistry()
    app = build_app(
        store=store,
        telephony=telephony,
        registry=registry,
        public_base_url="https://api.example.com",
        stream_base_url="wss://api.example.com",
    )
    return TestClient(app), store, telephony, registry


def test_request_places_a_call():
    client, _, telephony, _ = make_client()
    response = client.post("/v1/calls/request", json={"elder_id": 12})

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "requested"
    assert isinstance(body["call_id"], int)

    assert len(telephony.placed) == 1
    to, answer_url = telephony.placed[0]
    assert to == "070-1111-2222"
    assert answer_url.startswith("https://api.example.com")


def test_a_token_is_issued_for_the_stream():
    """토큰이 없으면 스트림 소켓이 아무나 접속할 수 있다(설계 7장)."""
    client, store, _, _ = make_client()
    call_id = client.post("/v1/calls/request", json={"elder_id": 12}).json()["call_id"]
    sid = store.get(call_id).provider_call_sid

    voiceml = client.post(
        "/v1/voiceml", data={"CallId": sid, "From": "070", "To": "070-1111-2222"}
    )
    assert voiceml.status_code == 200
    assert voiceml.headers["content-type"].startswith("application/xml")
    assert 'track="inbound"' in voiceml.text


def test_second_press_returns_409_with_the_existing_call_id():
    """두 번 누르는 것은 오류가 아니다. 그 통화의 대기 화면으로 보내야 한다."""
    client, _, telephony, _ = make_client()
    first = client.post("/v1/calls/request", json={"elder_id": 12})
    second = client.post("/v1/calls/request", json={"elder_id": 12})

    assert second.status_code == 409
    assert second.json()["call_id"] == first.json()["call_id"]
    assert second.json()["status"] == "in_progress"
    # 두 번째로 실제 전화가 또 걸리면 안 된다.
    assert len(telephony.placed) == 1


def test_unknown_elder_is_404():
    client, _, _, _ = make_client()
    assert client.post("/v1/calls/request", json={"elder_id": 999}).status_code == 404


def test_provider_failure_does_not_leave_a_stuck_call():
    """발신이 실패했는데 통화가 '진행 중'으로 남으면 영원히 409가 난다."""
    client, store, _, _ = make_client(FakeTelephony(fail_with=RuntimeError("사업자 오류")))
    response = client.post("/v1/calls/request", json={"elder_id": 12})

    assert response.status_code == 502
    assert store.find_active(12) is None

    # 다시 시도할 수 있어야 한다.
    client2, _, _, _ = make_client()
    assert client2.post("/v1/calls/request", json={"elder_id": 12}).status_code == 202


def test_requested_calls_are_tagged_so_metrics_can_exclude_them():
    """미응답 지표는 scheduled만 센다(설계 6장)."""
    client, store, _, _ = make_client()
    body = client.post("/v1/calls/request", json={"elder_id": 12}).json()
    assert store.get(body["call_id"]).trigger_type == "requested"


def test_voiceml_for_an_unknown_call_is_refused():
    """우리가 만들지 않은 통화에 토큰을 내주면 안 된다."""
    client, _, _, _ = make_client()
    assert client.post("/v1/voiceml", data={"CallId": "CA-nope"}).status_code == 404
