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

# 이 스트림은 20ms짜리 프레임을 쉬지 않고 보낸다 — 어르신이 말하지 않는
# 동안에도 침묵이 담긴 프레임이 계속 온다. 그래서 타임스탬프의 '간격'은 곧
# 연속으로 유실된 프레임 수다(간격 ÷ 20ms). 150프레임은 3초 내내 한 장도
# 도착하지 않았다는 뜻이고, 그건 지터나 재전송이 감당하는 범위가 아니라
# 이미 끊어진 연결이다. 반대로 흔한 유실(한 자리 수 프레임, 수백 ms)은
# 이 아래에 들어오므로 그대로 침묵으로 채워진다 — 채워야 뒤의 모든 발화
# 구간이 제자리에 남는다.
#
# 상한이 없으면 timestamp를 그대로 믿고 그만큼 침묵을 할당한다. 그런데
# timestamp는 사업자가 준 문자열일 뿐 아무도 검증하지 않는다. 2**31이면
# 24일치를 할당하려다 MemoryError로 통화가 죽고, 더 나쁜 것은 죽지 않는
# 값이다: 1시간(3_600_000)이면 57MB의 침묵이 녹음에 들어가 발화 비율이 0에
# 수렴하고, 멀쩡히 대화한 어르신에게 발화 벌점 35점이 만점으로 붙는다.
_CARRIER_FRAME_MS = 20
MAX_GAP_FRAMES = 150
MAX_GAP_MS = MAX_GAP_FRAMES * _CARRIER_FRAME_MS

# 위의 상한은 프레임 하나에만 걸린다. 그래서 그것만으로는 상한이 아니다.
# 프레임을 받아들일 때마다 세션 시계가 방금 채운 갭만큼 앞으로 가므로, 다음
# 프레임은 다시 MAX_GAP_MS만큼 앞설 수 있다 — 매번 상한 아래에 머무르면서
# 총량은 얼마든지 걸어 올라간다. 120바이트짜리 프레임 300장이 900초짜리
# 침묵(디스크 14.4MB)을 만든다. 400배다.
#
# 악의가 없는 현실적인 방아쇠가 따로 있다: 사업자가 timestamp를 ms가 아니라
# 샘플 수로 보내는 단위 불일치다. 8kHz에서 프레임당 갭이 140ms라 위 상한에
# 한참 못 미치는데, 녹음은 조용히 8배로 부풀고 speech_ratio는 0으로 끌려가
# 멀쩡히 대화한 어르신에게 발화 벌점 35점이 만점으로 붙는다.
#
# 진짜 불변식은 두 개다.
#
# 1) 지어낸 침묵의 총량에 상한이 있다. 채운 침묵은 측정한 오디오가 아니라
#    "이만큼 유실됐다고 믿기로 한 값"이다. 한 통화에서 30초를 지어냈다면
#    대화 한 턴이 통째로 없어진 것이고, 그 위에서 계산한 발화/침묵 비율은
#    더 이상 측정이 아니다. 프레임 하나의 상한(3초)이 열 번 일어난 양을
#    바닥으로 잡았다. 총량에 붙은 상한이라 위의 걸어 올리기가 닫힌다.
# 2) 통화에는 그럴듯한 최대 길이가 있다. 저장소가 끝을 확인하지 못한 통화를
#    20분에 접는 것과 같은 판단이다(store.MAX_ACTIVE_SECONDS) — 그 시점이면
#    기록은 이미 failed로 접히고 토큰도 폐기됐으므로, 더 받는 오디오는
#    존재하지 않는 통화에 쌓이는 것이다. 8kHz/16bit에서 이 상한이 곧 녹음
#    파일의 상한(19.2MB)이 된다.
MAX_FABRICATED_MS = 30 * 1000
MAX_CALL_MS = 20 * 60 * 1000


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

# 스트림이 이 통화에 붙는 순간 불린다. 통화 기록을 '받았다'로 옮기는 곳이
# 여기다 — 우리 쪽에서 어르신이 실제로 받았다는 것을 아는 유일한 시점이다.
CallStartHook = Callable[[CallSession], None]


def add_stream_route(
    app: FastAPI,
    registry: CallRegistry,
    responder_factory: Callable[[], Responder] = default_responder,
    recordings_dir: Path = RECORDINGS_DIR,
    on_call_end: CallEndHook | None = None,
    on_call_start: CallStartHook | None = None,
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
                    _started(session, on_call_start)
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
    on_call_start: CallStartHook | None = None,
) -> FastAPI:
    """스트림만 있는 앱. 어댑터 단위 테스트가 쓴다 — 실행용이 아니다."""
    app = FastAPI(title="늘봄 전화망 스트림")
    add_stream_route(
        app, registry, responder_factory, recordings_dir, on_call_end, on_call_start
    )
    return app


def _started(session: CallSession, on_call_start: CallStartHook | None) -> None:
    """스트림이 붙었다는 사실을 바깥에 알린다.

    통화를 끊지 않는다. 이 통보가 실패해도 어르신은 이미 전화기를 들고
    있고, 그 통화를 끊는 것이 기록 하나를 못 옮긴 것보다 나쁘다.
    """
    if on_call_start is None:
        return
    try:
        on_call_start(session)
    except Exception:
        logger.exception("스트림 시작 처리 실패 call_id=%s", session.call_id)


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

    # 검사는 세션이 아니라 여기, 프로토콜 경계에서 한다. timestamp는 방금
    # 파싱한 신뢰할 수 없는 입력이고, 바로 위에서 base64와 int를 검사해
    # 깨진 프레임을 버리는 것과 같은 성격의 일이다. CallSession은 검증이
    # 끝난 값을 받는 쪽이며 '샘플 위치 = 통화 내 시각'을 전제로 동작한다 —
    # 그 전제를 지키는 문이 이 지점이다. push_audio를 부르는 곳은 여기
    # 하나뿐이고, 다른 호출부가 생기면 그쪽도 이 검사를 지나야 한다.
    #
    # stream_duration_ms는 다음 프레임이 시작해야 할 시각과 같은 값이다(둘 다
    # recorded 버퍼 길이에서 구한다). 세션이 채울 침묵의 양이 곧 이 차이다.
    gap_ms = timestamp_ms - session.stream_duration_ms
    if gap_ms > MAX_GAP_MS:
        # 다른 깨진 프레임과 똑같이 다룬다 — 버리고 통화는 살린다. 여기서
        # 대신 시계를 그 값에 맞춰 주면(유실을 사실로 인정해 버리면) 있지도
        # 않은 침묵이 지표에 들어가 점수가 조용히 틀린다. 지어내느니 세지
        # 않는다. 진짜로 3초 넘게 끊긴 통화라면 이후 프레임도 계속 버려져
        # 사실상 귀를 닫게 되는데, 그건 이미 통화라고 부를 수 없는 상태이고
        # 틀린 점수를 내느니 아무 점수도 내지 않는 쪽이 낫다.
        logger.warning(
            "timestamp가 믿을 수 없을 만큼 앞서 있다 — 버린다 call_id=%s gap=%dms",
            session.call_id,
            gap_ms,
        )
        return []

    if timestamp_ms > MAX_CALL_MS:
        # 통화 하나가 가질 수 있는 최대 길이를 넘었다. 저장소는 이 시점에
        # 이미 기록을 접었다 — 여기부터는 없는 통화에 오디오를 붙이는 것이다.
        logger.warning(
            "통화 최대 길이를 넘은 timestamp — 버린다 call_id=%s timestamp=%dms",
            session.call_id,
            timestamp_ms,
        )
        return []

    if gap_ms > 0 and session.filled_gap_ms + gap_ms > MAX_FABRICATED_MS:
        # 프레임 하나씩은 다 상한 아래였는데 총량이 넘었다. 여기부터 채우면
        # 녹음의 대부분이 우리가 지어낸 침묵이 되고, 그 위에서 나온 발화
        # 비율은 측정이 아니라 창작이다. 지어내느니 세지 않는다.
        logger.warning(
            "지어낸 침묵이 상한을 넘었다 — 버린다 call_id=%s filled=%dms gap=%dms",
            session.call_id,
            session.filled_gap_ms,
            gap_ms,
        )
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
