"""전화망 기능의 조립 지점 (전화망 설계 5장).

트리거 API와 스트림 소켓은 따로 놓으면 둘 다 동작하지 않는다. 토큰을
발급하는 쪽과 검사하는 쪽이 같은 레지스트리를 봐야 하고, 통화를 만드는
쪽과 끝내는 쪽이 같은 저장소를 봐야 한다. 그 둘을 한 번만 만들어
양쪽에 건네는 곳이 여기다 — 여기가 없으면 두 절반은 테스트 안에서만
맞물린다.

실행: uvicorn app.main:app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from pathlib import Path

from fastapi import FastAPI

from app.analysis.call_analysis import CallAnalysis
from app.api import calls
from app.api.lifecycle import CallLifecycle
from app.api.store import CallStore, InMemoryCallStore
from app.media.responder import Responder
from app.media.session import CallSession
from app.media.stream_server import (
    RECORDINGS_DIR,
    CallRegistry,
    InMemoryCallRegistry,
    add_stream_route,
    default_responder,
)
from app.post_call import analyze_session
from app.telephony.client import ClawOpsTelephony, FakeTelephony, Telephony

logger = logging.getLogger(__name__)

# 분석 결과를 받는 곳. 지금은 로그뿐이다 — call_metrics 테이블에 쓰는
# 구현이 DB와 함께 들어온다. 규약을 먼저 뚫어 두면 그때 이 파일만 바뀐다.
AnalysisSink = Callable[[int, CallAnalysis], None]


def log_analysis(call_id: int, analysis: CallAnalysis) -> None:
    logger.info(
        "통화 분석 call_id=%s speech_ratio=%.3f silence_ratio=%.3f turns=%d "
        "delay_ms=%s clipped_ms=%d degraded=%s",
        call_id,
        analysis.metrics.speech_ratio,
        analysis.metrics.silence_ratio,
        analysis.metrics.turn_count,
        analysis.metrics.avg_response_delay_ms,
        analysis.clipped_ms,
        analysis.degraded,
    )


def build_server(
    *,
    store: CallStore,
    telephony: Telephony,
    public_base_url: str,
    stream_base_url: str,
    registry: CallRegistry | None = None,
    responder_factory: Callable[[], Responder] = default_responder,
    recordings_dir: Path = RECORDINGS_DIR,
    sink: AnalysisSink = log_analysis,
) -> FastAPI:
    """트리거 API와 스트림 소켓을 한 앱에 올린다."""
    registry = registry if registry is not None else InMemoryCallRegistry()
    lifecycle = CallLifecycle(store, registry)

    app = calls.build_app(
        store=store,
        telephony=telephony,
        registry=registry,
        public_base_url=public_base_url,
        stream_base_url=stream_base_url,
        lifecycle=lifecycle,
    )
    add_stream_route(
        app,
        registry=registry,
        responder_factory=responder_factory,
        recordings_dir=recordings_dir,
        on_call_end=_end_of_call(lifecycle, sink),
        on_call_start=_start_of_call(lifecycle),
    )
    return app


def _start_of_call(lifecycle: CallLifecycle):
    """스트림이 붙는 순간 — 어르신이 실제로 받았다는 것을 아는 유일한 지점이다.

    이 배선이 없던 동안 'answered'는 아무도 쓰지 않는 상태였고, 그래서 종료
    처리는 "여기까지 활성이면 오디오가 안 붙었다"고 추론할 수밖에 없었다.
    그 추론 때문에 통화 중에 도착한 사업자 웹훅 하나가 녹음까지 남은 통화를
    no_answer로 적었다.
    """

    def handle(session: CallSession) -> None:
        call_id = _numeric_call_id(session.call_id)
        if call_id is None:
            return
        lifecycle.stream_started(call_id)

    return handle


def _end_of_call(lifecycle: CallLifecycle, sink: AnalysisSink):
    """통화가 끝나는 순간 — 여기가 분석이 실제로 도는 유일한 지점이다.

    이 훅이 없던 동안 세션의 ai_turns와 stream_duration_ms는 소켓이 닫히는
    순간 그대로 버려졌다. mark 왕복으로 AI 발화 구간을 잡아 놓고도 에코
    제거가 한 번도 실행되지 않았다는 뜻이다.
    """

    def handle(session: CallSession, wav_path: Path | None) -> None:
        call_id = _numeric_call_id(session.call_id)
        try:
            if wav_path is None:
                logger.error("녹음이 없어 분석을 건너뛴다 call_id=%s", session.call_id)
            elif call_id is None:
                logger.error("분석 결과를 붙일 통화를 알 수 없다 call_id=%s", session.call_id)
            else:
                sink(call_id, analyze_session(session, wav_path))
        finally:
            # 분석이 실패해도 통화는 끝나야 한다. 상태를 못 옮기면 그
            # 어르신은 다시는 전화를 요청할 수 없다(409 영구 잠금).
            if call_id is not None:
                lifecycle.stream_finished(
                    call_id, wav_path.name if wav_path is not None else None
                )

    return handle


def _numeric_call_id(call_id: str) -> int | None:
    """세션의 call_id는 레지스트리가 돌려준 문자열이다.

    우리 트리거 API가 넣은 값이면 반드시 숫자지만, 레지스트리 구현이
    바뀌면 아닐 수도 있다. 여기서 터지면 분석도 상태 전이도 둘 다 날아간다.
    """
    try:
        return int(call_id)
    except ValueError:
        logger.error("숫자가 아닌 call_id — 통화 상태를 옮길 수 없다 call_id=%s", call_id)
        return None


def _telephony_from_env() -> Telephony:
    account_sid = os.getenv("CLAWOPS_ACCOUNT_SID")
    api_key = os.getenv("CLAWOPS_API_KEY")
    from_number = os.getenv("CLAWOPS_FROM_NUMBER")
    if account_sid and api_key and from_number:
        return ClawOpsTelephony(account_sid, api_key, from_number)
    # 계정 없이도 서버는 떠야 한다(아직 신청 중이다). 다만 조용히 뜨면
    # 아무도 전화를 못 받는 이유를 찾느라 하루를 쓴다 — 크게 남긴다.
    logger.warning(
        "ClawOps 자격 증명이 없다 — 실제 전화는 나가지 않는다"
        " (CLAWOPS_ACCOUNT_SID/API_KEY/FROM_NUMBER)"
    )
    return FakeTelephony()


def _phones_from_env() -> dict[int, str]:
    """ELDER_PHONES="1:070-1111-2222,2:070-3333-4444" — DB가 붙기 전까지만."""
    raw = os.getenv("ELDER_PHONES", "")
    phones: dict[int, str] = {}
    for entry in raw.split(","):
        if not entry.strip():
            continue
        elder_id, _, phone = entry.partition(":")
        try:
            phones[int(elder_id.strip())] = phone.strip()
        except ValueError:
            logger.error("ELDER_PHONES 항목을 읽을 수 없다 — 건너뛴다 entry=%s", entry)
    return phones


app = build_server(
    store=InMemoryCallStore(phones=_phones_from_env()),
    telephony=_telephony_from_env(),
    public_base_url=os.getenv("PUBLIC_BASE_URL", "http://localhost:8000"),
    stream_base_url=os.getenv("STREAM_BASE_URL", "ws://localhost:8000"),
)
