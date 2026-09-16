"""트리거 API (전화망 설계 5장).

앱 버튼은 "전화를 걸어 달라"는 신호다. 인앱 마이크도 소켓도 없다.
FakeTelephony 덕분에 ClawOps 계정 없이 전부 검증된다.
"""

import threading
from concurrent.futures import ThreadPoolExecutor

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


def test_voiceml_repeat_delivery_returns_the_same_response():
    """사업자 웹훅은 느리거나 실패한 ACK에 재전송한다 — 정상 동작이다.

    토큰을 pop해 버리면 재전송의 두 번째 배달이 404를 받아 실제 통화가
    무너진다. 같은 CallId의 반복 배달에는 같은 응답을 돌려줘야 한다.
    """
    client, store, _, _ = make_client()
    call_id = client.post("/v1/calls/request", json={"elder_id": 12}).json()["call_id"]
    sid = store.get(call_id).provider_call_sid

    first = client.post("/v1/voiceml", data={"CallId": sid})
    second = client.post("/v1/voiceml", data={"CallId": sid})

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.text == second.text


def test_post_dial_failure_does_not_leave_a_stuck_call():
    """전화는 이미 걸렸는데 후처리가 실패해도 재요청은 열려 있어야 한다.

    place_call 이후 단계(attach_sid 등)에서 예외가 나면, 실제 전화는
    나갔지만 토큰이 없어 그 통화는 VoiceML에서 404로 끝나 어차피 붙지
    않는다. '진행 중'으로 영원히 잠그는 것(구버전 버그)보다, 실패로
    돌려 재시도를 여는 쪽이 낫다 — 최악의 경우 전화가 한 번 더 걸리는
    정도이고, 그건 복구 가능하다. 영구 잠금은 복구가 안 된다.
    """

    class AttachSidFailsOnceStore(InMemoryCallStore):
        """DB가 첫 통화에서만 튕긴다고 가정한다 — 재시도는 정상 경로를 탄다."""

        def __init__(self, phones):
            super().__init__(phones)
            self._raised = False

        def attach_sid(self, call_id, sid):
            if not self._raised:
                self._raised = True
                raise RuntimeError("DB 오류")
            super().attach_sid(call_id, sid)

    store = AttachSidFailsOnceStore(phones={12: "070-1111-2222"})
    telephony = FakeTelephony()
    registry = InMemoryCallRegistry()
    app = build_app(
        store=store,
        telephony=telephony,
        registry=registry,
        public_base_url="https://api.example.com",
        stream_base_url="wss://api.example.com",
    )
    client = TestClient(app)

    response = client.post("/v1/calls/request", json={"elder_id": 12})
    assert response.status_code == 502
    # 전화는 실제로 나갔다 — 이 사실 자체가 후처리 실패의 어려움이다.
    assert len(telephony.placed) == 1
    # 하지만 통화 기록이 '진행 중'으로 남아 영원히 409가 나면 안 된다.
    assert store.find_active(12) is None

    retry = client.post("/v1/calls/request", json={"elder_id": 12})
    assert retry.status_code == 202


def test_concurrent_double_press_places_only_one_call():
    """동시에 두 번 눌러도 실제 전화는 한 번만 걸려야 한다.

    FastAPI는 sync 라우트를 스레드풀에서 돌린다. find_active와 create가
    따로 놀면 여러 스레드가 모두 "활성 통화 없음"을 본 뒤에야 각자
    create를 부를 수 있다. store의 락은 스케줄링과 무관하게 상호 배제를
    강제하므로, 이 테스트는 매번 결정적으로 통과한다 — 통과 여부가
    타이밍에 좌우되지 않는다(락이 깨지면 매번 실패로 드러난다).
    """
    client, _, telephony, _ = make_client()
    threads_count = 8
    barrier = threading.Barrier(threads_count)

    def press():
        barrier.wait()
        return client.post("/v1/calls/request", json={"elder_id": 12})

    with ThreadPoolExecutor(max_workers=threads_count) as pool:
        responses = list(pool.map(lambda _: press(), range(threads_count)))

    statuses = sorted(r.status_code for r in responses)
    assert statuses == [202] + [409] * (threads_count - 1)
    assert len(telephony.placed) == 1
