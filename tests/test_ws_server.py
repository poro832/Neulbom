"""WebSocket 어댑터 — 소켓과 CallSession 사이에서 바이트만 옮긴다.

바이너리는 소리, 텍스트는 신호. 로직은 CallSession에 있으므로
여기서는 배관이 맞물리는지만 본다.
"""

import struct

import pytest
from fastapi.testclient import TestClient

from app.media import ws_server

SAMPLE_RATE = 16000


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(ws_server, "RECORDINGS_DIR", tmp_path)
    return TestClient(ws_server.app)


def pcm16(*spans, sample_rate=SAMPLE_RATE):
    values: list[int] = []
    for kind, duration_ms in spans:
        count = int(sample_rate * duration_ms / 1000)
        if kind == "speech":
            values.extend(9000 if i % 2 == 0 else -9000 for i in range(count))
        else:
            values.extend(0 for _ in range(count))
    return struct.pack(f"<{len(values)}h", *values)


def test_speech_round_trip_returns_signal_and_audio(client):
    with client.websocket_connect("/v1/app-call") as ws:
        ws.send_json({"type": "start", "sample_rate": SAMPLE_RATE})
        ws.send_bytes(pcm16(("speech", 500), ("silence", 1000)))

        assert ws.receive_json() == {"type": "speech_end"}
        assert len(ws.receive_bytes()) > 0

        ws.send_json({"type": "end"})


def test_call_is_saved_as_wav(client, tmp_path):
    with client.websocket_connect("/v1/app-call") as ws:
        ws.send_json({"type": "start", "sample_rate": SAMPLE_RATE})
        ws.send_bytes(pcm16(("silence", 100)))
        ws.send_json({"type": "end"})

    assert list(tmp_path.glob("*.wav"))


def test_unrelated_end_substring_does_not_hang_up(client):
    """제어 어휘가 늘어날 때를 대비한 테스트.

    "type"이 아닌 다른 필드에 "end"라는 값이 들어 있어도 부분 문자열만
    보고 통화를 끊으면 안 된다. 실제 발화를 보내 speech_end가 정상적으로
    돌아오는지로 연결이 살아있음을 확인한다.
    """
    with client.websocket_connect("/v1/app-call") as ws:
        ws.send_json({"type": "start", "sample_rate": SAMPLE_RATE})
        ws.send_json({"type": "note", "reason": "end"})
        ws.send_bytes(pcm16(("speech", 500), ("silence", 1000)))

        assert ws.receive_json() == {"type": "speech_end"}
        assert len(ws.receive_bytes()) > 0

        ws.send_json({"type": "end"})


def test_wrong_sample_rate_is_rejected(client):
    """조용히 틀린 결과를 내느니 연결을 거부한다."""
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/v1/app-call") as ws:
            ws.send_json({"type": "start", "sample_rate": 8000})
            ws.receive_bytes()


def test_malformed_first_frame_is_rejected_not_crashed(client):
    """첫 텍스트 프레임이 JSON이 아니어도(예: "ping") 죽지 않고 거부한다.

    인증 없이 도달하는 프레임이라 json.loads를 무방비로 걸면 서비스
    거부로 이어진다. _is_end와 같은 1003으로 정리되는지 확인한다.
    """
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/v1/app-call") as ws:
            ws.send_text("ping")
            ws.receive_bytes()


def test_json_scalar_first_frame_is_rejected_not_crashed(client):
    """JSON이지만 dict가 아니면(스칼라) .get()에서 AttributeError가 난다."""
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/v1/app-call") as ws:
            ws.send_text("42")
            ws.receive_bytes()


def test_start_with_wrong_type_is_rejected(client):
    """sample_rate만 맞으면 type을 안 봐도 통과하던 구멍을 막는다."""
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/v1/app-call") as ws:
            ws.send_json({"type": "note", "sample_rate": SAMPLE_RATE})
            ws.receive_bytes()
