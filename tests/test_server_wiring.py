"""조립된 서버 (전화망 설계 5장).

두 절반 — 전화를 거는 트리거 API와 오디오를 받는 스트림 소켓 — 은 같은
레지스트리와 저장소를 공유해야만 동작한다. 여기까지 와야 "한 통화"가
처음부터 끝까지 존재한다: 요청 → VoiceML → 스트림 → 종료 → 분석.

이 파일이 없던 동안 두 절반은 각자의 단위 테스트에서만 맞물렸다. 실제로는
발급한 토큰과 검사하는 토큰이 다른 사전에 들어 있어 모든 스트림이 거부됐고,
통화가 끝나도 아무도 그 사실을 기록하지 않았다.
"""

import base64
import json
import re

import numpy as np
from fastapi.testclient import TestClient

from app.main import build_server
from app.api.outcome_store import InMemoryOutcomeStore
from app.api.store import InMemoryCallStore
from app.media import ulaw
from app.telephony.client import FakeTelephony

FRAME_SAMPLES = 160


def silence_payload() -> str:
    return base64.b64encode(b"\xff" * FRAME_SAMPLES).decode()


def speech_payload() -> str:
    samples = np.empty(FRAME_SAMPLES, dtype=np.float32)
    samples[0::2] = 0.25
    samples[1::2] = -0.25
    return base64.b64encode(ulaw.encode(samples)).decode()


def start_event(token: str) -> dict:
    return {
        "event": "start",
        "start": {
            "streamId": "MZ1",
            "tracks": ["inbound"],
            "customParameters": {"token": token},
            "mediaFormat": {
                "encoding": "audio/x-mulaw",
                "sampleRate": 8000,
                "channels": 1,
            },
        },
    }


def media_event(payload: str, timestamp_ms: int) -> dict:
    return {
        "event": "media",
        "media": {"track": "inbound", "timestamp": str(timestamp_ms), "payload": payload},
    }


class _Beep:
    def respond(self, audio, sample_rate):
        return b"\x01\x02" * 400


def make_server(tmp_path, sink=None, outcomes=None):
    store = InMemoryCallStore(phones={12: "070-1111-2222"})
    telephony = FakeTelephony()
    app = build_server(
        store=store,
        telephony=telephony,
        public_base_url="https://api.example.com",
        stream_base_url="wss://api.example.com",
        responder_factory=_Beep,
        recordings_dir=tmp_path,
        outcomes=outcomes,
        sink=sink,
    )
    return TestClient(app), store, telephony


def place_call(client, store):
    """트리거 → VoiceML까지 실제 경로로 가서 스트림 토큰을 얻는다."""
    call_id = client.post("/v1/calls/request", json={"elder_id": 12}).json()["call_id"]
    sid = store.get(call_id).provider_call_sid
    xml = client.post("/v1/voiceml", data={"CallId": sid}).text
    token = re.search(r'name="token" value="([^"]+)"', xml).group(1)
    return call_id, sid, token


def run_stream(client, token, frames=30):
    """발화 다음 침묵. 배치 VAD가 발화 구간 하나를 잡을 만큼은 보낸다."""
    with client.websocket_connect("/v1/stream") as socket:
        socket.send_text(json.dumps(start_event(token)))
        index = 0
        for _ in range(frames):
            socket.send_text(json.dumps(media_event(speech_payload(), index * 20)))
            index += 1
        for _ in range(frames):
            socket.send_text(json.dumps(media_event(silence_payload(), index * 20)))
            index += 1
        socket.send_text(json.dumps({"event": "stop"}))


def test_the_trigger_api_and_the_stream_share_one_registry(tmp_path):
    """따로 조립하면 발급한 토큰과 검사하는 토큰이 다른 사전에 있다.

    그러면 문서에 적힌 실행 명령으로 띄운 서버가 모든 스트림을 거부한다 —
    어르신은 전화를 받았는데 아무 소리도 들리지 않는다.
    """
    client, store, _ = make_server(tmp_path)
    _, _, token = place_call(client, store)

    run_stream(client, token, frames=5)

    assert list(tmp_path.glob("*.wav"))


def test_a_streamed_call_ends_and_frees_the_elder(tmp_path):
    """정상적으로 끝난 통화에는 종료 상태가 있어야 한다.

    사업자 웹훅은 오지 않을 수도 있다. 우리 스트림이 닫히는 순간이 통화의
    끝을 우리가 직접 본 유일한 시점이므로, 여기서 기록을 옮기지 않으면
    정상 통화일수록 'ringing'으로 굳어 그 어르신을 영구히 잠근다.
    """
    client, store, telephony = make_server(tmp_path)
    call_id, _, token = place_call(client, store)

    run_stream(client, token, frames=5)

    record = store.get(call_id)
    assert record.status == "completed"
    # 끝난 통화에는 분석할 오디오가 있어야 한다(스키마의 제약과 같은 규칙).
    assert record.audio_key
    assert (tmp_path / record.audio_key).exists()

    assert client.post("/v1/calls/request", json={"elder_id": 12}).status_code == 202
    assert len(telephony.placed) == 2


def test_a_late_carrier_webhook_does_not_rewrite_the_result(tmp_path):
    """웹훅과 스트림 종료는 순서가 보장되지 않는다.

    늦게 온 웹훅이 방금 completed로 끝난 통화를 no_answer로 되돌리면,
    미응답 통계가 조용히 틀린다 — 멀쩡히 통화한 어르신이 '전화를 받지
    않는 사람'으로 집계된다.
    """
    client, store, _ = make_server(tmp_path)
    call_id, sid, token = place_call(client, store)
    run_stream(client, token, frames=5)

    client.post("/v1/stream-ended", data={"CallId": sid, "StreamEvent": "stop"})

    assert store.get(call_id).status == "completed"


def test_post_call_analysis_runs_on_a_real_call(tmp_path):
    """분석이 실제 통화 경로에서 돈다 — 테스트에서만 불리면 없는 기능이다.

    이 훅이 없던 동안 세션이 mark 왕복으로 잡아 둔 AI 발화 구간과 스트림
    길이는 소켓이 닫히는 순간 그대로 버려졌다. 에코 제거도, degraded 표시도
    한 번도 실행된 적이 없었다는 뜻이다.
    """
    seen = []
    client, store, _ = make_server(tmp_path, sink=lambda cid, a: seen.append((cid, a)))
    call_id, _, token = place_call(client, store)

    run_stream(client, token)

    assert len(seen) == 1
    analyzed_id, analysis = seen[0]
    assert analyzed_id == call_id
    # 녹음에서 실제로 잰 값이다. 발화 절반, 침묵 절반을 보냈다.
    assert 0.3 < analysis.metrics.speech_ratio < 0.7
    assert analysis.metrics.turn_count >= 1
    # STT가 없어 전사는 빈 문자열이다 — 없는 부정어를 지어내지 않는다.
    assert analysis.metrics.negative_word_count == 0


def test_a_failing_analysis_still_ends_the_call(tmp_path):
    """분석이 터져도 통화는 끝난 것이다.

    후처리 실패가 상태 전이를 삼키면, 실패한 분석 하나가 그 어르신을
    영원히 잠근다 — 분석은 나중에 다시 돌릴 수 있지만 잠금은 못 푼다.
    """

    def exploding_sink(call_id, analysis):
        raise RuntimeError("분석기 오류")

    client, store, _ = make_server(tmp_path, sink=exploding_sink)
    call_id, _, token = place_call(client, store)

    run_stream(client, token, frames=5)

    assert store.get(call_id).status == "completed"
    assert client.post("/v1/calls/request", json={"elder_id": 12}).status_code == 202


def test_a_finished_call_cannot_be_streamed_again(tmp_path):
    """끝난 통화의 토큰은 폐기돼야 한다.

    /v1/voiceml에는 인증이 없다. 토큰이 남아 있으면 통화가 끝난 뒤에도
    그 토큰으로 소켓에 붙을 수 있고, 소켓의 유일한 문이 그 토큰이다.
    """
    client, store, _ = make_server(tmp_path)
    _, sid, token = place_call(client, store)
    run_stream(client, token, frames=5)

    assert client.post("/v1/voiceml", data={"CallId": sid}).status_code == 404


def test_the_module_level_app_serves_both_halves():
    """문서의 실행 명령(uvicorn app.main:app)이 실제로 맞아야 한다."""
    from app.main import app

    paths = {route.path for route in app.routes}
    assert "/v1/calls/request" in paths
    assert "/v1/voiceml" in paths
    assert "/v1/stream-ended" in paths
    assert "/v1/stream" in paths


def test_a_webhook_during_the_call_does_not_file_it_as_no_answer(tmp_path):
    """사업자 웹훅과 우리 소켓 종료는 서로 다른 경로다 — 순서가 뒤집힌다.

    <Connect action>의 POST는 우리가 소켓을 닫는 바로 그 순간에 온다. 통화
    중에 먼저 도착하는 것이 정상이라는 뜻이다. "여기까지 활성이면 오디오가
    안 붙었다"고 추론하면 그 순간 받아서 대화하고 녹음까지 남긴 통화가
    no_answer로 기록된다. 그 값은 위험 점수의 입력이고(미응답 이력 20점),
    녹음이 있는데 audio_key가 없는 행이 되어 스키마 규칙과도 어긋난다.
    조용히 틀린 숫자라 아무도 알아채지 못한다.

    이미 있는 test_a_late_carrier_webhook_does_not_rewrite_the_result는
    소켓이 닫힌 뒤를 본다. 문제가 되는 순서는 이쪽이다.
    """
    client, store, _ = make_server(tmp_path)
    call_id, sid, token = place_call(client, store)

    with client.websocket_connect("/v1/stream") as socket:
        socket.send_text(json.dumps(start_event(token)))
        index = 0
        for _ in range(20):
            socket.send_text(json.dumps(media_event(speech_payload(), index * 20)))
            index += 1
        for _ in range(45):
            socket.send_text(json.dumps(media_event(silence_payload(), index * 20)))
            index += 1
        # 나가는 mark/오디오를 받아 서버가 여기까지 실제로 읽었음을 확인한다.
        # 이게 없으면 웹훅이 start보다 먼저 처리돼 이 테스트가 증명하려는
        # 순서가 아니게 된다.
        for _ in range(3):
            socket.receive_text()

        # 스트림이 붙었다는 사실이 기록에 남아야 한다 — 이게 '받았다'와
        # '받지 않았다'를 추론이 아니라 기록으로 가르는 값이다.
        assert store.get(call_id).status == "answered"

        webhook = client.post(
            "/v1/stream-ended", data={"CallId": sid, "StreamEvent": "stop"}
        )
        assert webhook.status_code == 200
        assert store.get(call_id).status != "no_answer"

        for _ in range(10):
            socket.send_text(json.dumps(media_event(silence_payload(), index * 20)))
            index += 1
        socket.send_text(json.dumps({"event": "stop"}))

    record = store.get(call_id)
    assert record.status == "completed"
    # 녹음이 있는 통화에는 audio_key가 있어야 한다(스키마의 제약과 같은 규칙).
    assert record.audio_key
    assert (tmp_path / record.audio_key).exists()


def test_a_real_call_produces_a_risk_score(tmp_path):
    """조립 기본값이 실제로 점수를 낸다 — sink를 주입하지 않은 경로다.

    단위 테스트는 sink를 직접 불러 숫자를 고정한다. 여기서 보는 것은
    "그 sink가 기본 조립에 실제로 달려 있는가" 하나다.
    """
    outcomes = InMemoryOutcomeStore()
    client, store, _ = make_server(tmp_path, outcomes=outcomes)
    call_id, _, token = place_call(client, store)

    run_stream(client, token)

    results = outcomes.recent(12, 14)
    assert len(results) == 1
    assert results[0].call_id == call_id
    assert 0 <= results[0].risk.risk_score <= 100
    # STT가 없어 부정 표현은 항상 0이다 — 없는 부정어를 지어내지 않는다.
    assert results[0].metrics.negative_word_count == 0
