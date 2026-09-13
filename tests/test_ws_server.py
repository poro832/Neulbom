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


def test_wrong_sample_rate_is_rejected(client):
    """조용히 틀린 결과를 내느니 연결을 거부한다."""
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/v1/app-call") as ws:
            ws.send_json({"type": "start", "sample_rate": 8000})
            ws.receive_bytes()
