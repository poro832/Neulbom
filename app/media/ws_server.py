"""앱 채널 WebSocket 엔드포인트 (앱 통화 설계 4장).

한 소켓에서 바이너리는 소리, 텍스트는 신호를 나른다. 로직은 전부
CallSession에 있으므로 이 파일은 배관만 한다.

실행: uvicorn app.media.ws_server:app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from app.media.responder import CannedResponder, beep
from app.media.session import AudioMessage, CallSession, TextMessage

logger = logging.getLogger(__name__)

app = FastAPI(title="늘봄 앱 채널")

RECORDINGS_DIR = Path("recordings")
EXPECTED_SAMPLE_RATE = 16000

# 정책 위반이 아니라 프로토콜 불일치이므로 1003(Unsupported Data).
_UNSUPPORTED_DATA = 1003


def _build_responder() -> CannedResponder:
    """골격의 고정 응답. CLOVA가 붙으면 이 함수만 바뀐다."""
    return CannedResponder(
        [
            beep(duration_ms=200, sample_rate=EXPECTED_SAMPLE_RATE, frequency_hz=660),
            beep(duration_ms=200, sample_rate=EXPECTED_SAMPLE_RATE, frequency_hz=880),
        ]
    )


@app.websocket("/v1/app-call")
async def app_call(websocket: WebSocket) -> None:
    await websocket.accept()

    # start가 올 때까지 오디오는 버린다. 순서가 뒤집혀 도착하면
    # 샘플레이트를 모르는 채로 바이트를 해석하게 된다.
    while True:
        first = await websocket.receive()
        if first["type"] == "websocket.disconnect":
            return
        if (text := first.get("text")) is not None:
            break

    if json.loads(text).get("sample_rate") != EXPECTED_SAMPLE_RATE:
        # 조용히 틀린 결과를 내느니 거부한다.
        await websocket.close(code=_UNSUPPORTED_DATA)
        return

    session = CallSession(uuid.uuid4().hex, EXPECTED_SAMPLE_RATE, _build_responder())
    try:
        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                break
            if (payload := message.get("bytes")) is not None:
                for outgoing in session.push_audio(payload):
                    if isinstance(outgoing, TextMessage):
                        await websocket.send_json(outgoing.payload)
                    elif isinstance(outgoing, AudioMessage):
                        await websocket.send_bytes(outgoing.pcm)
            elif (text := message.get("text")) is not None and '"end"' in text:
                break
    except WebSocketDisconnect:
        # 앱이 갑자기 끊겼다. 아래 finally에서 녹음을 남긴다.
        logger.info("앱이 연결을 끊었다 call_id=%s", session.call_id)
    finally:
        session.finish(RECORDINGS_DIR)
