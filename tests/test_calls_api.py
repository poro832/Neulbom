"""트리거 API (전화망 설계 5장).

앱 버튼은 "전화를 걸어 달라"는 신호다. 인앱 마이크도 소켓도 없다.
FakeTelephony 덕분에 ClawOps 계정 없이 전부 검증된다.
"""

import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from app.api.calls import build_app
from app.api.lifecycle import CallLifecycle
from app.api.store import InMemoryCallStore
from app.media.stream_server import InMemoryCallRegistry
from app.telephony.client import FakeTelephony


def make_client(telephony=None, store=None):
    store = store or InMemoryCallStore(phones={12: "070-1111-2222"})
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


class WideWindowStore(InMemoryCallStore):
    """검사와 생성 사이를 일부러 벌린 저장소.

    이게 없으면 이 테스트는 자기가 증명한다고 적어 둔 것을 증명하지 못한다.
    find_active와 create 사이가 몇 마이크로초라, 락을 통째로 들어내도 다른
    스레드가 하필 그 사이에 끼어들 확률이 낮아 경합이 거의 재현되지 않는다
    (리뷰에서 락 없는 저장소로 30번 돌려 0번 검출).

    "활성 통화 없음"을 본 스레드를 붙잡아 두면 판이 뒤집힌다. 락이 있으면
    다른 스레드는 그동안 find_active_or_create에 들어오지도 못하므로 결과가
    스케줄링과 무관하게 늘 같고, 락이 없으면 모든 스레드가 이 틈에서 만나
    전부 "없음"을 보고 각자 전화를 건다 — 그래서 락이 깨지면 매번 드러난다.
    """

    def find_active(self, elder_id):
        found = super().find_active(elder_id)
        if found is None:
            time.sleep(0.05)
        return found


def test_concurrent_double_press_places_only_one_call():
    """동시에 두 번 눌러도 실제 전화는 한 번만 걸려야 한다.

    FastAPI는 sync 라우트를 스레드풀에서 돌린다. find_active와 create가
    따로 놀면 여러 스레드가 모두 "활성 통화 없음"을 본 뒤에야 각자 create를
    부를 수 있다. store의 락은 스케줄링과 무관하게 상호 배제를 강제하므로
    이 테스트는 매번 결정적으로 통과하고, WideWindowStore가 검사와 생성
    사이를 벌려 두었으므로 락이 깨지면 매번 실패로 드러난다.
    """
    store = WideWindowStore(phones={12: "070-1111-2222"})
    client, _, telephony, _ = make_client(store=store)
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


# ------------------------------------------------------- 통화의 끝


def test_a_finished_call_stops_blocking_the_next_request():
    """끝난 통화가 '진행 중'으로 남으면 그 어르신은 영원히 잠긴다.

    이건 조용한 고장이다: 서버는 409를 주고 앱은 409를 성공으로 보여 준다.
    어르신 화면에는 "곧 전화가 갑니다"가 뜨는데 전화기는 다시는 울리지
    않는다. 사업자 웹훅이 통화의 끝을 알려 왔으면 기록도 끝나야 한다.
    """
    client, store, telephony, _ = make_client()
    call_id = client.post("/v1/calls/request", json={"elder_id": 12}).json()["call_id"]
    sid = store.get(call_id).provider_call_sid

    client.post("/v1/stream-ended", data={"CallId": sid, "StreamEvent": "stop"})

    assert store.get(call_id).status == "no_answer"
    assert store.find_active(12) is None
    assert client.post("/v1/calls/request", json={"elder_id": 12}).status_code == 202
    assert len(telephony.placed) == 2


def test_a_finished_calls_token_is_no_longer_handed_out():
    """끝난 통화의 스트림 토큰이 남아 있으면 안 된다.

    /v1/voiceml에는 인증이 없다. CallId만 알면 누구나 부를 수 있고, 토큰이
    남아 있는 한 그 토큰으로 스트림 소켓에 붙을 수 있다 — 소켓의 유일한
    문이 그 토큰이기 때문이다(설계 7장).
    """
    client, store, _, _ = make_client()
    call_id = client.post("/v1/calls/request", json={"elder_id": 12}).json()["call_id"]
    sid = store.get(call_id).provider_call_sid
    assert client.post("/v1/voiceml", data={"CallId": sid}).status_code == 200

    client.post("/v1/stream-ended", data={"CallId": sid, "StreamEvent": "stop"})

    assert client.post("/v1/voiceml", data={"CallId": sid}).status_code == 404


def test_a_lost_webhook_does_not_lock_the_elder_forever():
    """끝을 알리는 신호가 하나도 오지 않을 수도 있다.

    웹훅은 유실되고 스트림은 시작도 못 한 채 죽을 수 있다. 그때 기록이
    영원히 활성으로 남으면 복구할 방법이 없다 — 시간 자체를 바닥으로 둔다.
    """
    now = [1000.0]
    store = InMemoryCallStore(
        phones={12: "070-1111-2222"}, clock=lambda: now[0], max_active_seconds=600
    )
    client, _, telephony, _ = make_client(store=store)

    client.post("/v1/calls/request", json={"elder_id": 12})
    # 아직 통화 중일 수 있는 시각이다 — 여기서 열어 주면 전화가 두 번 걸린다.
    now[0] += 599
    assert client.post("/v1/calls/request", json={"elder_id": 12}).status_code == 409

    now[0] += 2
    assert client.post("/v1/calls/request", json={"elder_id": 12}).status_code == 202
    assert len(telephony.placed) == 2


def test_a_non_terminal_stream_event_does_not_end_the_call():
    """action URL로 오는 것이 전부 '끝'은 아니다.

    StreamEvent를 로그에만 쓰고 버리던 동안은 '스트림이 시작됐다'는 통보
    하나가 통화를 끝내 버렸다 — 어르신은 방금 받았는데 기록은 미응답이
    되고, 토큰까지 폐기돼 실제로 오디오가 붙지 못한다. /v1/stream-ended에는
    인증이 없어서 CallId만 알면 누구나 이 값을 보낼 수 있다.
    """
    client, store, _, _ = make_client()
    call_id = client.post("/v1/calls/request", json={"elder_id": 12}).json()["call_id"]
    sid = store.get(call_id).provider_call_sid

    response = client.post(
        "/v1/stream-ended", data={"CallId": sid, "StreamEvent": "stream-started"}
    )

    assert response.status_code == 200
    assert store.get(call_id).status == "ringing"
    # 토큰도 살아 있어야 한다 — 이제부터 스트림이 붙을 차례다.
    assert client.post("/v1/voiceml", data={"CallId": sid}).status_code == 200


def token_from(xml: str) -> str:
    """VoiceML에 심긴 1회용 스트림 토큰. 소켓의 유일한 문이다(설계 7장)."""
    return re.search(r'name="token" value="([^"]+)"', xml).group(1)


def test_an_expired_call_has_its_stream_token_revoked():
    """바닥 시간이 통화를 접으면 그 통화의 토큰도 같이 접혀야 한다.

    이 경로는 끝 신호가 둘 다 유실된 통화다 — 우리 스트림 종료도, 사업자
    웹훅도 오지 않았다. 토큰을 폐기할 다른 기회가 아예 없으므로 여기서 안
    닫으면 그 토큰은 영원히 유효하다. 인증 없는 /v1/voiceml이 끝난 통화의
    토큰을 계속 내주고, 그 토큰을 쥔 누구든 스트림 소켓에 붙을 수 있다.
    """
    now = [1000.0]
    store = InMemoryCallStore(
        phones={12: "070-1111-2222"}, clock=lambda: now[0], max_active_seconds=600
    )
    client, _, _, registry = make_client(store=store)

    call_id = client.post("/v1/calls/request", json={"elder_id": 12}).json()["call_id"]
    sid = store.get(call_id).provider_call_sid
    token = token_from(client.post("/v1/voiceml", data={"CallId": sid}).text)

    now[0] += 601
    # 재요청이 만료 정리를 돌리는 유일한 경로다.
    assert client.post("/v1/calls/request", json={"elder_id": 12}).status_code == 202
    assert store.get(call_id).status == "failed"

    assert client.post("/v1/voiceml", data={"CallId": sid}).status_code == 404
    assert registry.claim(token) is None


def test_attach_sid_does_not_reopen_a_finished_call():
    """끝난 기록을 다시 활성으로 되돌리는 전이가 있으면 안 된다.

    mark_* 는 전부 활성 검사를 하는데 attach_sid만 없었다. 없으면 늦게 온
    발신 후처리 하나가 failed로 접힌 기록을 ringing으로 되살리고, 되살아난
    기록은 그 어르신을 다시 409로 잠근다 — 그 잠금은 아무도 풀지 못한다.
    """
    store = InMemoryCallStore(phones={12: "070-1111-2222"})
    call = store.create(12, trigger_type="requested")
    store.mark_failed(call.call_id)

    store.attach_sid(call.call_id, "CA-late")

    assert store.get(call.call_id).status == "failed"
    assert store.find_active(12) is None


def make_lifecycle(store):
    """앱과 같은 lifecycle을 손에 쥔 채로 조립한다.

    종료 처리의 실패 경로는 라우트를 통해서는 못 건드린다 — 통화를 끝내는
    쪽은 스트림 소켓이기 때문이다.
    """
    registry = InMemoryCallRegistry()
    lifecycle = CallLifecycle(store, registry)
    app = build_app(
        store=store,
        telephony=FakeTelephony(),
        registry=registry,
        public_base_url="https://api.example.com",
        stream_base_url="wss://api.example.com",
        lifecycle=lifecycle,
    )
    return TestClient(app), lifecycle


def test_a_store_failure_at_the_end_still_revokes_the_token():
    """통화를 끝내는 일은 두 가지이고, 한쪽이 터져도 다른 쪽은 일어나야 한다.

    상태 전이가 예외로 끊기면 폐기는 아예 불리지 않았다 — 그러면 끝나지도
    않고 토큰도 살아 있는 통화가 남는다. 둘 중 더 나쁜 쪽은 토큰이다:
    상태는 바닥 시간이 나중에라도 접어 주지만, 남은 토큰은 인증 없는
    /v1/voiceml에서 계속 꺼내진다.
    """

    class BrokenStore(InMemoryCallStore):
        def mark_completed(self, call_id, audio_key):
            raise RuntimeError("DB 오류")

    store = BrokenStore(phones={12: "070-1111-2222"})
    client, lifecycle = make_lifecycle(store)
    call_id = client.post("/v1/calls/request", json={"elder_id": 12}).json()["call_id"]
    sid = store.get(call_id).provider_call_sid
    assert client.post("/v1/voiceml", data={"CallId": sid}).status_code == 200

    with pytest.raises(RuntimeError):
        lifecycle.stream_finished(call_id, "a.wav")

    assert client.post("/v1/voiceml", data={"CallId": sid}).status_code == 404


def test_ending_a_call_we_do_not_know_does_not_raise():
    """모르는 call_id로 끝이 불려도 KeyError로 터지면 안 된다.

    터지는 지점이 하필 토큰 폐기 앞이라, 예외 하나가 그 통화의 토큰을
    그대로 흘린다. 모르는 것 때문에 아는 일까지 못 하게 두지 않는다.
    """
    store = InMemoryCallStore(phones={12: "070-1111-2222"})
    _, lifecycle = make_lifecycle(store)

    lifecycle.stream_finished(999, "a.wav")
    store.mark_no_answer(999)


# ------------------------------------------------- 미응답 집계의 재료 (설계 3.3)


def finished_call(store, elder_id, trigger_type, status):
    """끝난 통화 하나를 만든다. 상태 전이는 실제 경로를 그대로 쓴다."""
    call = store.create(elder_id=elder_id, trigger_type=trigger_type)
    if status == "no_answer":
        store.mark_no_answer(call.call_id)
    elif status == "failed":
        store.mark_failed(call.call_id)
    else:
        store.mark_completed(call.call_id, audio_key=f"{call.call_id}.wav")
    return call


def test_requested_calls_are_not_counted_as_no_answer_history():
    """요청 통화의 미응답은 "버튼을 누르고 전화기를 못 찾았다"일 뿐이다.

    위험 신호로 세면 활발한 어르신이 오히려 감점된다(db/schema.sql 주석).
    """
    store = InMemoryCallStore(phones={12: "070-1111-2222"})
    finished_call(store, 12, "requested", "no_answer")
    scheduled = finished_call(store, 12, "scheduled", "completed")

    found = store.recent_scheduled(12, 7)

    assert [call.call_id for call in found] == [scheduled.call_id]


def test_calls_still_in_progress_do_not_take_a_slot():
    """결과가 미정인 통화가 창의 한 칸을 먹으면 실제 미응답 이력이 희석된다."""
    store = InMemoryCallStore(phones={12: "070-1111-2222"})
    done = finished_call(store, 12, "scheduled", "no_answer")
    store.create(elder_id=12, trigger_type="scheduled")  # 아직 진행 중

    found = store.recent_scheduled(12, 7)

    assert [call.call_id for call in found] == [done.call_id]


def test_the_current_call_can_be_excluded():
    store = InMemoryCallStore(phones={12: "070-1111-2222"})
    older = finished_call(store, 12, "scheduled", "completed")
    current = finished_call(store, 12, "scheduled", "completed")

    found = store.recent_scheduled(12, 7, exclude_call_id=current.call_id)

    assert [call.call_id for call in found] == [older.call_id]


def test_recent_scheduled_is_newest_first_and_capped():
    store = InMemoryCallStore(phones={12: "070-1111-2222"})
    made = [finished_call(store, 12, "scheduled", "completed") for _ in range(10)]

    found = store.recent_scheduled(12, 7)

    assert [call.call_id for call in found] == [
        call.call_id for call in reversed(made[-7:])
    ]


def test_another_elders_calls_are_not_counted():
    store = InMemoryCallStore(phones={12: "070-1111-2222", 99: "070-3333-4444"})
    mine = finished_call(store, 12, "scheduled", "no_answer")
    finished_call(store, 99, "scheduled", "no_answer")

    found = store.recent_scheduled(12, 7)

    assert [call.call_id for call in found] == [mine.call_id]
