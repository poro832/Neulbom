"""ClawOps Stream WebSocket 어댑터 (전화망 설계 4장).

프로토콜은 이벤트 JSON이고 오디오는 base64 μ-law다. 로직은 전부
CallSession에 있으므로 이 파일은 배관만 한다.

실행: uvicorn app.media.stream_server:app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import base64
import binascii
import json
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from app.media import ulaw
from app.media.responder import CannedResponder, Responder, beep
from app.media.session import AudioMessage, CallSession, MarkMessage, TextMessage

logger = logging.getLogger(__name__)

RECORDINGS_DIR = Path("recordings")

# 정책 위반이 아니라 인증 실패이므로 1008(Policy Violation).
_POLICY_VIOLATION = 1008


class CallRegistry(Protocol):
    def issue(self, token: str, call_id: str) -> None:
        """이 통화에 쓸 1회용 토큰을 등록한다. 트리거 API가 부른다."""
        ...

    def claim(self, token: str) -> str | None:
        """토큰을 소모하고 call_id를 돌려준다. 모르거나 이미 쓴 토큰이면 None."""
        ...


class InMemoryCallRegistry:
    """DB가 붙기 전까지 쓰는 구현. 규약이 같으므로 나중에 갈아끼우면 된다."""

    def __init__(self) -> None:
        self._tokens: dict[str, str] = {}

    def issue(self, token: str, call_id: str) -> None:
        self._tokens[token] = call_id

    def claim(self, token: str) -> str | None:
        # 1회용이다. 재사용되면 같은 통화에 두 스트림이 붙는다.
        return self._tokens.pop(token, None)


def _default_responder() -> Responder:
    """골격의 고정 응답. CLOVA가 붙으면 이 함수만 바뀐다."""
    return CannedResponder(
        [
            beep(duration_ms=200, sample_rate=ulaw.SAMPLE_RATE, frequency_hz=440),
            beep(duration_ms=200, sample_rate=ulaw.SAMPLE_RATE, frequency_hz=660),
        ]
    )


def build_app(
    registry: CallRegistry,
    responder_factory: Callable[[], Responder] = _default_responder,
    recordings_dir: Path = RECORDINGS_DIR,
) -> FastAPI:
    app = FastAPI(title="늘봄 전화망 스트림")

    @app.websocket("/v1/stream")
    async def stream(websocket: WebSocket) -> None:
        await websocket.accept()
        session: CallSession | None = None
        try:
            while True:
                raw = await websocket.receive_text()
                message = _parse(raw)
                if message is None:
                    # 깨진 프레임 하나로 통화를 끊지 않는다(설계 8장).
                    continue

                event = message.get("event")
                if event == "start":
                    session = _open(message, registry, responder_factory)
                    if session is None:
                        await websocket.close(code=_POLICY_VIOLATION)
                        return
                elif session is None:
                    # start 전에 온 것은 시각도 세션도 없이 해석할 수 없다.
                    continue
                elif event == "media":
                    for outgoing in _push(session, message):
                        await _send(websocket, outgoing)
                elif event == "mark":
                    session.on_mark(message.get("mark", {}).get("name", ""))
                elif event == "stop":
                    break
        except WebSocketDisconnect:
            logger.info("스트림이 끊겼다 call_id=%s", session.call_id if session else "-")
        finally:
            if session is not None:
                session.finish(recordings_dir)

    return app


def _parse(raw: str) -> dict | None:
    try:
        message = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("JSON이 아닌 프레임을 버린다")
        return None
    return message if isinstance(message, dict) else None


def _open(
    message: dict,
    registry: CallRegistry,
    responder_factory: Callable[[], Responder],
) -> CallSession | None:
    """토큰을 확인하고 세션을 연다.

    이 소켓에는 ClawOps 서명이 없다. <Parameter>로 심어 둔 1회용 토큰이
    유일한 문이다(설계 7장).
    """
    start = message.get("start", {})
    token = start.get("customParameters", {}).get("token", "")
    call_id = registry.claim(token) if token else None
    if call_id is None:
        logger.warning("알 수 없는 토큰으로 스트림 접속 — 거부한다")
        return None
    return CallSession(call_id, ulaw.SAMPLE_RATE, responder_factory())


def _push(session: CallSession, message: dict) -> list:
    media = message.get("media", {})
    try:
        payload = base64.b64decode(media.get("payload", ""), validate=True)
        timestamp_ms = int(media.get("timestamp", "0"))
    except (binascii.Error, ValueError):
        logger.warning("media 프레임이 깨졌다 — 버린다 call_id=%s", session.call_id)
        return []
    return session.push_audio(ulaw.decode_to_pcm16(payload), timestamp_ms=timestamp_ms)


async def _send(websocket: WebSocket, outgoing) -> None:
    if isinstance(outgoing, MarkMessage):
        await websocket.send_json({"event": "mark", "mark": {"name": outgoing.name}})
    elif isinstance(outgoing, AudioMessage):
        payload = base64.b64encode(ulaw.encode_from_pcm16(outgoing.pcm)).decode()
        await websocket.send_json({"event": "media", "media": {"payload": payload}})
    elif isinstance(outgoing, TextMessage):
        # speech_end는 앱 화면용 신호였다. 전화망에는 보낼 곳이 없다.
        pass


app = build_app(registry=InMemoryCallRegistry())
