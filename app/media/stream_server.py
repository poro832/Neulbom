"""ClawOps Stream WebSocket 어댑터 (전화망 설계 4장).

프로토콜은 이벤트 JSON이고 오디오는 base64 μ-law다. 로직은 전부
CallSession에 있으므로 이 파일은 배관만 한다.

이 모듈만으로는 서버가 되지 않는다 — 토큰을 발급하는 트리거 API와 같은
레지스트리를 써야 스트림이 통과한다. 조립은 app/main.py가 한다.
실행: uvicorn app.main:app --host 0.0.0.0 --port 8000
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

    def revoke(self, token: str) -> None:
        """통화가 끝났다. 쓰이지 않은 토큰도 더는 유효하지 않다."""
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

    def revoke(self, token: str) -> None:
        # 통화가 끝났는데 토큰이 남아 있으면, 그 토큰을 쥔 누구든 나중에
        # 스트림을 열 수 있다. 끝난 통화의 문은 닫아 둔다.
        self._tokens.pop(token, None)


def default_responder() -> Responder:
    """골격의 고정 응답. CLOVA가 붙으면 이 함수만 바뀐다."""
    return CannedResponder(
        [
            beep(duration_ms=200, sample_rate=ulaw.SAMPLE_RATE, frequency_hz=440),
            beep(duration_ms=200, sample_rate=ulaw.SAMPLE_RATE, frequency_hz=660),
        ]
    )


# 통화가 끝났을 때 불린다. wav 경로는 저장에 실패했으면 None이지만 그래도
# 불린다 — 녹음을 못 남긴 것과 통화가 안 끝난 것은 다른 일이다.
CallEndHook = Callable[[CallSession, "Path | None"], None]


def add_stream_route(
    app: FastAPI,
    registry: CallRegistry,
    responder_factory: Callable[[], Responder] = default_responder,
    recordings_dir: Path = RECORDINGS_DIR,
    on_call_end: CallEndHook | None = None,
) -> None:
    """스트림 소켓을 이미 있는 앱에 붙인다.

    앱 생성과 분리한 이유는 트리거 API와 같은 FastAPI 앱에 얹기 위해서다.
    각자 앱을 만들면 레지스트리도 각자가 되어, 토큰을 발급한 쪽과 검사하는
    쪽이 달라진다 — 그러면 모든 스트림이 거부된다.
    """

    @app.websocket("/v1/stream")
    async def stream(websocket: WebSocket) -> None:
        await websocket.accept()
        session: CallSession | None = None
        try:
            while True:
                raw = await websocket.receive_text()
                message = _parse(raw)
                if message is None:
                    # 최상위가 JSON도 dict도 아닌 프레임 하나로 통화를
                    # 끊지 않는다(설계 8장). 중첩 필드가 null인 경우는
                    # 아래 각 분기에서 따로 막는다 — 여기서는 못 잡는다.
                    continue

                event = message.get("event")
                if event == "start":
                    if session is not None:
                        # 소켓 하나는 통화 하나다. 두 번째 start를 받아들여
                        # session을 덮어쓰면 첫 세션은 finish()가 다시는
                        # 불리지 않아 녹음이 통째로 사라진다 — 반면 여기서
                        # 소켓을 닫으면 멀쩡히 진행 중이던 첫 통화까지
                        # 끊어버리므로, 침묵 손실보다 더 나쁘다. 그래서
                        # 무시하고 첫 세션을 계속 쓴다.
                        logger.warning(
                            "이미 세션이 열린 소켓에 start가 다시 왔다 — 무시한다 call_id=%s",
                            session.call_id,
                        )
                        continue
                    start = message.get("start")
                    if not isinstance(start, dict):
                        # start가 null이면 토큰도 없어 세션을 열 수 없다.
                        # 다음에 오는 진짜 start를 기다린다.
                        logger.warning("start 필드가 비어 있다(null) — 버린다")
                        continue
                    session = _open(start, registry, responder_factory)
                    if session is None:
                        await websocket.close(code=_POLICY_VIOLATION)
                        return
                elif session is None:
                    # start 전에 온 것은 시각도 세션도 없이 해석할 수 없다.
                    continue
                elif event == "media":
                    media = message.get("media")
                    if not isinstance(media, dict):
                        # null이면 payload도 timestamp도 없다 — 이 프레임만
                        # 버리고 통화는 계속한다.
                        logger.warning(
                            "media 필드가 비어 있다(null) — 버린다 call_id=%s",
                            session.call_id,
                        )
                        continue
                    for outgoing in _push(session, media):
                        await _send(websocket, outgoing)
                elif event == "mark":
                    mark = message.get("mark")
                    if not isinstance(mark, dict):
                        logger.warning(
                            "mark 필드가 비어 있다(null) — 버린다 call_id=%s",
                            session.call_id,
                        )
                        continue
                    session.on_mark(mark.get("name", ""))
                elif event == "stop":
                    break
        except WebSocketDisconnect:
            logger.info("스트림이 끊겼다 call_id=%s", session.call_id if session else "-")
        finally:
            if session is not None:
                _end_call(session, recordings_dir, on_call_end)


def build_app(
    registry: CallRegistry,
    responder_factory: Callable[[], Responder] = default_responder,
    recordings_dir: Path = RECORDINGS_DIR,
    on_call_end: CallEndHook | None = None,
) -> FastAPI:
    """스트림만 있는 앱. 어댑터 단위 테스트가 쓴다 — 실행용이 아니다."""
    app = FastAPI(title="늘봄 전화망 스트림")
    add_stream_route(app, registry, responder_factory, recordings_dir, on_call_end)
    return app


def _end_call(
    session: CallSession, recordings_dir: Path, on_call_end: CallEndHook | None
) -> None:
    """통화를 마무리한다. 한 단계가 실패해도 다음 단계는 실행된다.

    둘은 독립적이다 — 녹음 저장이 실패해도 통화가 끝난 사실은 그대로이고,
    그 사실을 기록하지 못하면 어르신은 '통화 중'으로 영원히 잠긴다. 한쪽이
    다른 쪽을 삼키지 않도록 따로 감싼다.
    """
    wav_path: Path | None = None
    try:
        wav_path = session.finish(recordings_dir)
    except Exception:
        logger.exception("녹음 저장 실패 call_id=%s", session.call_id)

    if on_call_end is None:
        return
    try:
        on_call_end(session, wav_path)
    except Exception:
        logger.exception("통화 종료 처리 실패 call_id=%s", session.call_id)


def _parse(raw: str) -> dict | None:
    try:
        message = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("JSON이 아닌 프레임을 버린다")
        return None
    return message if isinstance(message, dict) else None


def _open(
    start: dict,
    registry: CallRegistry,
    responder_factory: Callable[[], Responder],
) -> CallSession | None:
    """토큰을 확인하고 세션을 연다. 호출부가 start가 dict임을 이미 보장한다.

    이 소켓에는 ClawOps 서명이 없다. Parameter로 심어 둔 1회용 토큰이
    유일한 문이다(설계 7장).
    """
    custom_params = start.get("customParameters") or {}
    token = custom_params.get("token", "")
    call_id = registry.claim(token) if token else None
    if call_id is None:
        logger.warning("알 수 없는 토큰으로 스트림 접속 — 거부한다")
        return None
    return CallSession(call_id, ulaw.SAMPLE_RATE, responder_factory())


def _push(session: CallSession, media: dict) -> list:
    """media 프레임을 세션에 밀어 넣는다. 호출부가 media가 dict임을 이미 보장한다."""
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
