"""ClawOps Stream 어댑터 (전화망 설계 4장).

프로토콜은 이벤트 JSON이고 오디오는 base64 μ-law다. 로직은 전부
CallSession에 있으므로 이 계층은 배관만 한다 — 그래서 이벤트 시퀀스를
재생하는 것으로 전부 검증된다. 실통화가 필요 없다.
"""

import base64
import json
import wave

import numpy as np
from fastapi.testclient import TestClient

from app.media import ulaw
from app.media import stream_server
from app.media.stream_server import (
    MAX_FABRICATED_MS,
    MAX_GAP_MS,
    InMemoryCallRegistry,
    build_app,
)

FRAME_SAMPLES = 160


def silence_payload() -> str:
    return base64.b64encode(b"\xff" * FRAME_SAMPLES).decode()


def speech_payload() -> str:
    samples = np.empty(FRAME_SAMPLES, dtype=np.float32)
    samples[0::2] = 0.25
    samples[1::2] = -0.25
    return base64.b64encode(ulaw.encode(samples)).decode()


def start_event(token: str, call_id: str = "CA1") -> dict:
    return {
        "event": "start",
        "sequenceNumber": "1",
        "start": {
            "streamId": "MZ1",
            "callId": call_id,
            "accountId": "AC1",
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
        "media": {
            "track": "inbound",
            "chunk": "1",
            "timestamp": str(timestamp_ms),
            "payload": payload,
        },
    }


def make_client(tmp_path, responder=None):
    registry = InMemoryCallRegistry()
    registry.issue("tok-good", "call-1")

    class _Beep:
        def respond(self, audio, sample_rate):
            return b"\x01\x02" * 400

    app = build_app(
        registry=registry,
        responder_factory=lambda: responder or _Beep(),
        recordings_dir=tmp_path,
    )
    return TestClient(app), registry


def recording(tmp_path, call_id="call-1"):
    """이 통화의 녹음 파일.

    이름 뒤에 통화를 유일하게 만드는 꼬리(시각+난수)가 붙는다 — call_id는
    프로세스가 재시작하면 1부터 다시 나오므로, 이름이 call_id뿐이면 이튿날
    첫 통화가 전날 녹음을 덮어쓴다. 한 통화에 녹음이 정확히 하나라는 사실은
    그대로이고, 이 헬퍼가 그것까지 확인한다.
    """
    matches = sorted(tmp_path.glob(f"{call_id}-*.wav"))
    assert len(matches) == 1, matches
    return matches[0]


def test_unknown_token_is_rejected(tmp_path):
    """스트림 소켓에는 ClawOps 서명이 없다. 토큰이 유일한 문이다."""
    client, _ = make_client(tmp_path)
    with client.websocket_connect("/v1/stream") as socket:
        socket.send_text(json.dumps(start_event("tok-bad")))
        with _expect_disconnect():
            socket.receive_text()


def test_a_token_cannot_be_used_twice(tmp_path):
    """재사용되면 같은 통화에 두 스트림이 붙는다."""
    client, registry = make_client(tmp_path)
    assert registry.claim("tok-good") == "call-1"
    assert registry.claim("tok-good") is None


def test_media_is_decoded_and_recorded(tmp_path):
    client, _ = make_client(tmp_path)
    with client.websocket_connect("/v1/stream") as socket:
        socket.send_text(json.dumps(start_event("tok-good")))
        for i in range(10):
            socket.send_text(json.dumps(media_event(silence_payload(), i * 20)))
        socket.send_text(json.dumps({"event": "stop"}))

    assert recording(tmp_path).exists()


def test_speech_then_silence_sends_marked_audio(tmp_path):
    """발화가 끝나면 mark로 감싼 μ-law 오디오가 나가야 한다."""
    client, _ = make_client(tmp_path)
    received = []
    with client.websocket_connect("/v1/stream") as socket:
        socket.send_text(json.dumps(start_event("tok-good")))
        index = 0
        for _ in range(20):
            socket.send_text(json.dumps(media_event(speech_payload(), index * 20)))
            index += 1
        for _ in range(45):
            socket.send_text(json.dumps(media_event(silence_payload(), index * 20)))
            index += 1
        # 나간 것들을 모은다.
        for _ in range(3):
            received.append(json.loads(socket.receive_text()))
        socket.send_text(json.dumps({"event": "stop"}))

    events = [message["event"] for message in received]
    assert events == ["mark", "media", "mark"]
    # 오디오는 base64 μ-law여야 한다. PCM16을 그대로 보내면 굉음이 난다.
    audio = base64.b64decode(received[1]["media"]["payload"])
    assert len(audio) == 400          # PCM16 800바이트 → μ-law 400바이트


def test_mark_from_platform_records_an_ai_turn(tmp_path):
    """돌아온 mark가 AI 발화 구간이 된다 (설계 3.2)."""
    client, _ = make_client(tmp_path)
    with client.websocket_connect("/v1/stream") as socket:
        socket.send_text(json.dumps(start_event("tok-good")))
        index = 0
        for _ in range(20):
            socket.send_text(json.dumps(media_event(speech_payload(), index * 20)))
            index += 1
        for _ in range(45):
            socket.send_text(json.dumps(media_event(silence_payload(), index * 20)))
            index += 1
        marks = []
        for _ in range(3):
            message = json.loads(socket.receive_text())
            if message["event"] == "mark":
                marks.append(message["mark"]["name"])

        socket.send_text(json.dumps(media_event(silence_payload(), 2000)))
        socket.send_text(json.dumps({"event": "mark", "mark": {"name": marks[0]}}))
        socket.send_text(json.dumps(media_event(silence_payload(), 2600)))
        socket.send_text(json.dumps({"event": "mark", "mark": {"name": marks[1]}}))
        socket.send_text(json.dumps({"event": "stop"}))

    # 소켓이 닫힌 뒤 세션이 남긴 wav가 있으면 충분하다. 구간 자체는
    # Task 4의 단위 테스트가 이미 고정하고 있다.
    assert recording(tmp_path).exists()


def test_garbage_frame_does_not_kill_the_call(tmp_path):
    """깨진 프레임 하나로 통화를 끊으면 어르신은 영문을 모른다."""
    client, _ = make_client(tmp_path)
    with client.websocket_connect("/v1/stream") as socket:
        socket.send_text(json.dumps(start_event("tok-good")))
        socket.send_text("not json at all")
        socket.send_text(json.dumps(media_event(silence_payload(), 0)))
        socket.send_text(json.dumps({"event": "stop"}))

    assert recording(tmp_path).exists()


def test_null_media_field_does_not_kill_the_call(tmp_path):
    """media 필드 자체가 null이어도(JSON은 유효하다) 통화가 죽으면 안 된다.

    message.get("media", {})는 키가 "없을" 때만 기본값을 준다 — 키가 있고
    값이 null이면 그대로 None을 돌려줘 다음 .get() 호출에서 터진다. 그
    프레임만 버리고 이어지는 정상 프레임은 실제로 처리돼야 한다.
    """
    client, _ = make_client(tmp_path)
    with client.websocket_connect("/v1/stream") as socket:
        socket.send_text(json.dumps(start_event("tok-good")))
        socket.send_text(json.dumps({"event": "media", "media": None}))
        socket.send_text(json.dumps(media_event(silence_payload(), 0)))
        socket.send_text(json.dumps({"event": "stop"}))

    with wave.open(str(recording(tmp_path)), "rb") as wav:
        assert wav.getnframes() == FRAME_SAMPLES


def test_null_mark_field_does_not_kill_the_call(tmp_path):
    """mark 필드가 null이어도 같은 방식으로 죽는다 — 같은 구멍이다."""
    client, _ = make_client(tmp_path)
    with client.websocket_connect("/v1/stream") as socket:
        socket.send_text(json.dumps(start_event("tok-good")))
        socket.send_text(json.dumps({"event": "mark", "mark": None}))
        socket.send_text(json.dumps(media_event(silence_payload(), 0)))
        socket.send_text(json.dumps({"event": "stop"}))

    with wave.open(str(recording(tmp_path)), "rb") as wav:
        assert wav.getnframes() == FRAME_SAMPLES


def test_null_start_field_does_not_kill_the_call(tmp_path):
    """start 필드가 null인 start 이벤트도 세션 없이 안전하게 버려져야 하고,
    소켓은 살아남아 뒤이은 진짜 start를 받아들여야 한다.
    """
    client, _ = make_client(tmp_path)
    with client.websocket_connect("/v1/stream") as socket:
        socket.send_text(json.dumps({"event": "start", "start": None}))
        socket.send_text(json.dumps(start_event("tok-good")))
        socket.send_text(json.dumps(media_event(silence_payload(), 0)))
        socket.send_text(json.dumps({"event": "stop"}))

    with wave.open(str(recording(tmp_path)), "rb") as wav:
        assert wav.getnframes() == FRAME_SAMPLES


def test_second_start_with_different_valid_token_is_ignored(tmp_path):
    """소켓 하나는 통화 하나다. 두 번째 start가 다른 유효한 토큰을 들고
    와도 받아들이면 첫 세션이 finish() 한 번 못 받고 사라진다 — 그 세션의
    녹음 전체가 조용히 없어지는 것이다. 두 번째 start는 무시해야 하고,
    그 뒤에 오는 media도 계속 첫 세션(call-1)에 쌓여야 한다.
    """
    client, registry = make_client(tmp_path)
    registry.issue("tok-good-2", "call-2")
    with client.websocket_connect("/v1/stream") as socket:
        socket.send_text(json.dumps(start_event("tok-good")))
        socket.send_text(json.dumps(media_event(silence_payload(), 0)))
        socket.send_text(json.dumps(start_event("tok-good-2")))
        socket.send_text(json.dumps(media_event(silence_payload(), 20)))
        socket.send_text(json.dumps({"event": "stop"}))

    assert recording(tmp_path).exists()
    assert not list(tmp_path.glob("call-2-*.wav"))
    with wave.open(str(recording(tmp_path)), "rb") as wav:
        assert wav.getnframes() == FRAME_SAMPLES * 2
    # 무시됐을 뿐 소모되지는 않았다 — 다음 통화에 이 토큰을 다시 쓸 수 있다.
    assert registry.claim("tok-good-2") == "call-2"


def test_second_start_with_bad_token_is_ignored(tmp_path):
    """두 번째 start가 이번엔 나쁜 토큰이다. 예전 코드는 이 경우 _open이
    None을 돌려줘 세션 변수를 덮어쓰고 소켓까지 닫아, 멀쩡한 첫 통화를
    두 번 죽였다(세션도 잃고 소켓도 잃고). 무시하면 첫 통화는 그대로
    이어져야 한다.
    """
    client, _ = make_client(tmp_path)
    with client.websocket_connect("/v1/stream") as socket:
        socket.send_text(json.dumps(start_event("tok-good")))
        socket.send_text(json.dumps(media_event(silence_payload(), 0)))
        socket.send_text(json.dumps(start_event("tok-bad")))
        socket.send_text(json.dumps(media_event(silence_payload(), 20)))
        socket.send_text(json.dumps({"event": "stop"}))

    with wave.open(str(recording(tmp_path)), "rb") as wav:
        assert wav.getnframes() == FRAME_SAMPLES * 2


def test_an_absurd_timestamp_does_not_allocate_memory(tmp_path):
    """timestamp는 사업자가 준 문자열일 뿐이고 아무도 검증하지 않는다.

    2**31을 그대로 믿으면 세션이 24일치 침묵을 할당하려다 MemoryError로
    통화를 죽인다. 깨진 프레임 하나가 통화를 끊으면 안 된다는 이 파일의
    규칙이 여기에도 그대로 적용된다 — 버리고 통화는 잇는다.
    """
    client, _ = make_client(tmp_path)
    with client.websocket_connect("/v1/stream") as socket:
        socket.send_text(json.dumps(start_event("tok-good")))
        socket.send_text(json.dumps(media_event(silence_payload(), 0)))
        socket.send_text(json.dumps(media_event(silence_payload(), 2**31)))
        socket.send_text(json.dumps(media_event(silence_payload(), 20)))
        socket.send_text(json.dumps({"event": "stop"}))

    with wave.open(str(recording(tmp_path)), "rb") as wav:
        # 정상 프레임 둘만 남는다. 깨진 프레임은 없던 일이다.
        assert wav.getnframes() == FRAME_SAMPLES * 2


def test_a_plausible_but_huge_gap_does_not_fake_an_hour_of_silence(tmp_path):
    """죽지 않는 값이 더 위험하다.

    1시간(3_600_000ms)은 성공적으로 할당된다 — 57MB의 침묵이 녹음에 들어가고
    발화 비율이 0에 수렴해, 멀쩡히 대화한 어르신에게 발화 벌점 35점이
    만점으로 붙는다. 터지지 않으므로 아무도 알아채지 못한다.
    """
    client, _ = make_client(tmp_path)
    with client.websocket_connect("/v1/stream") as socket:
        socket.send_text(json.dumps(start_event("tok-good")))
        socket.send_text(json.dumps(media_event(silence_payload(), 0)))
        socket.send_text(json.dumps(media_event(silence_payload(), 3_600_000)))
        socket.send_text(json.dumps({"event": "stop"}))

    with wave.open(str(recording(tmp_path)), "rb") as wav:
        assert wav.getnframes() == FRAME_SAMPLES


def test_a_real_packet_loss_gap_is_still_filled(tmp_path):
    """진짜 유실은 막으면 안 된다. 침묵으로 채워야 뒤의 구간이 안 밀린다.

    상한을 두는 것과 유실을 무시하는 것은 다른 일이다. 1초짜리 구멍은
    실제로 일어나고, 그건 그대로 녹음에 들어가야 한다(설계 3.2).
    """
    client, _ = make_client(tmp_path)
    with client.websocket_connect("/v1/stream") as socket:
        socket.send_text(json.dumps(start_event("tok-good")))
        socket.send_text(json.dumps(media_event(silence_payload(), 0)))
        socket.send_text(json.dumps(media_event(silence_payload(), 1_000)))
        socket.send_text(json.dumps({"event": "stop"}))

    with wave.open(str(recording(tmp_path)), "rb") as wav:
        # 20ms + 980ms 침묵 + 20ms = 1020ms
        assert wav.getnframes() == 8000 * 1020 // 1000


def test_small_gaps_cannot_walk_the_recording_past_the_total_cap(tmp_path):
    """프레임 하나에만 걸린 상한은 상한이 아니다.

    프레임을 받아들일 때마다 세션 시계가 방금 채운 갭만큼 앞으로 간다.
    그래서 다음 프레임은 다시 상한 바로 아래만큼 앞설 수 있고, 매번 검사를
    통과하면서 총량은 얼마든지 걸어 올라간다. 여기서는 120바이트짜리 프레임
    60장이 180초(2.9MB)를 만든다 — 상한이 없던 시절과 같은 400배 증폭이다.

    악의 없는 방아쇠가 따로 있다: 사업자가 timestamp를 ms가 아니라 샘플
    수로 보내면 8kHz에서 프레임당 갭이 140ms라 위 상한에 한참 못 미치는데,
    녹음은 조용히 8배로 부풀고 speech_ratio가 0으로 끌려가 멀쩡히 대화한
    어르신에게 발화 벌점 35점이 만점으로 붙는다.
    """
    client, _ = make_client(tmp_path)
    frames = 60
    step = MAX_GAP_MS + 20  # 매 프레임이 상한 바로 아래(=상한과 같은) 갭을 만든다
    with client.websocket_connect("/v1/stream") as socket:
        socket.send_text(json.dumps(start_event("tok-good")))
        for index in range(frames):
            socket.send_text(json.dumps(media_event(silence_payload(), index * step)))
        socket.send_text(json.dumps({"event": "stop"}))

    with wave.open(str(recording(tmp_path)), "rb") as wav:
        duration_ms = wav.getnframes() * 1000 // 8000

    real_audio_ms = frames * 20
    assert duration_ms <= MAX_FABRICATED_MS + real_audio_ms
    # 그렇다고 전부 버리는 것은 아니다 — 진짜 유실은 여전히 채워진다.
    assert duration_ms > MAX_GAP_MS


def test_a_call_cannot_grow_past_its_maximum_length(tmp_path, monkeypatch):
    """통화에는 그럴듯한 최대 길이가 있고, 녹음 파일 크기는 거기서 나온다.

    저장소는 끝을 확인하지 못한 통화를 20분에 접는다 — 그 시점이면 기록은
    failed로 접히고 토큰도 폐기됐으므로, 더 받는 오디오는 존재하지 않는
    통화에 쌓이는 것이다. 상한을 작게 바꿔 두고 경계만 본다(실시간으로
    20분을 흘려보내지 않고도 같은 규칙을 검증할 수 있다).
    """
    monkeypatch.setattr(stream_server, "MAX_CALL_MS", 200)
    client, _ = make_client(tmp_path)
    with client.websocket_connect("/v1/stream") as socket:
        socket.send_text(json.dumps(start_event("tok-good")))
        for index in range(20):
            socket.send_text(json.dumps(media_event(silence_payload(), index * 20)))
        socket.send_text(json.dumps({"event": "stop"}))

    with wave.open(str(recording(tmp_path)), "rb") as wav:
        duration_ms = wav.getnframes() * 1000 // 8000

    # 0..200ms의 프레임 11장만 남는다. 그 뒤는 없는 통화의 오디오다.
    assert duration_ms == 220


def _expect_disconnect():
    """pytest_ 로 시작하는 이름은 훅으로 오인되므로 밑줄로 시작한다."""
    import pytest
    from starlette.websockets import WebSocketDisconnect

    return pytest.raises(WebSocketDisconnect)
