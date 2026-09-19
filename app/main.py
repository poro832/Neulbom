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

from app.analysis.baseline import BASELINE_WINDOW, compute_baseline
from app.analysis.call_analysis import CallAnalysis
from app.analysis.metrics_calculator import CALCULATOR_VERSION, assess_risk
from app.analysis.outcome import CallOutcome
from app.api import calls
from app.api.lifecycle import CallLifecycle
from app.api.outcome_store import InMemoryOutcomeStore, OutcomeStore
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

# 분석 결과를 받는 곳. 지금은 메모리에 쌓는다 — call_metrics 테이블에 쓰는
# 구현이 DB와 함께 들어온다. 규약을 먼저 뚫어 두면 그때 이 파일만 바뀐다.
AnalysisSink = Callable[[int, CallAnalysis], None]

# 미응답 이력을 몇 건까지 보는가. db/schema.sql의 no_answer_recent_7이
# 0~7을 강제하므로 그 이름과 맞춘다.
NO_ANSWER_WINDOW = 7


def build_risk_sink(store: CallStore, outcomes: OutcomeStore) -> AnalysisSink:
    """지표를 위험 점수로 환산해 남긴다 (설계 4.5).

    이 배선이 없던 동안 assess_risk는 테스트에서만 불렸다. 지표까지 만들어
    놓고 점수로 바꾸지 않았다는 뜻이고, 그러면 "위험 점수는 지어내는 게
    아니라 재는 것"이라는 간판 주장이 전화 경로에서 증명되지 않는다.

    순서가 중요하다. 기준선을 먼저 구하고 그다음에 기록한다 — 뒤집으면
    현재 통화가 자기 기준선에 섞여 델타가 희석되고, 나쁜 통화가 정상으로
    보인다. 아무 오류도 나지 않는다.
    """

    def sink(call_id: int, analysis: CallAnalysis) -> None:
        try:
            elder_id = store.get(call_id).elder_id
        except KeyError:
            logger.error("모르는 통화의 분석 결과다 — 버린다 call_id=%s", call_id)
            return

        try:
            # 아직 기록하지 않았으므로 이 조회에 현재 통화는 들어 있지 않다.
            baseline = compute_baseline(outcomes.recent(elder_id, BASELINE_WINDOW))
            history = store.recent_scheduled(
                elder_id, NO_ANSWER_WINDOW, exclude_call_id=call_id
            )
            no_answer = sum(1 for call in history if call.status == "no_answer")

            # 근거가 부족하다고 우리가 직접 표시한 통화다. 점수를 내지
            # 않는다 — 옆에 경고를 달아도 보호자 머리에는 숫자가 남는다.
            # 지표는 아래에서 그대로 기록하므로 나중에 다시 판정할 수 있다.
            risk = (
                None
                if analysis.degraded
                else assess_risk(
                    analysis.metrics, baseline=baseline, no_answer_recent_7=no_answer
                )
            )
            outcomes.record(
                CallOutcome(
                    call_id=call_id,
                    elder_id=elder_id,
                    metrics=analysis.metrics,
                    risk=risk,
                    no_answer_recent_7=no_answer,
                    clipped_ms=analysis.clipped_ms,
                    degraded=analysis.degraded,
                    calculator_version=CALCULATOR_VERSION,
                )
            )
            logger.info(
                "위험 판정 call_id=%s elder_id=%s score=%s level=%s 기준선=%s "
                "no_answer=%d speech_ratio=%.3f delay_ms=%s degraded=%s",
                call_id,
                elder_id,
                # 근거가 부족해 판정하지 않은 통화는 여기서도 숫자를 만들지
                # 않는다. %d로 두면 None에서 터지는데, 그 예외는 아래
                # except가 삼켜서 degraded 통화마다 조용히 실패 로그만 남는다.
                "없음" if risk is None else risk.risk_score,
                "없음" if risk is None else risk.risk_level,
                "있음" if baseline is not None else "없음",
                no_answer,
                analysis.metrics.speech_ratio,
                analysis.metrics.avg_response_delay_ms,
                analysis.degraded,
            )
        except Exception:
            # 통화 종료 자체는 이 except가 없어도 지켜진다 — _end_of_call의
            # finally가 lifecycle.stream_finished를 무조건 부르고,
            # stream_server의 on_call_end 호출부도 통째로 try/except로
            # 감싸여 있다(이중 안전망). 이 except가 막는 것은 그 두 층까지
            # 예외가 올라가 중복 스택으로 찍히는 것과, 실패 지점이 "위험
            # 판정"이라고 정확히 남기지 못하는 것이다 — 로그에서 원인을
            # 셋 중 어디로 좁혀야 할지 알 수 없게 된다.
            logger.exception("위험 판정 실패 call_id=%s", call_id)

    return sink


def build_server(
    *,
    store: CallStore,
    telephony: Telephony,
    public_base_url: str,
    stream_base_url: str,
    registry: CallRegistry | None = None,
    responder_factory: Callable[[], Responder] = default_responder,
    recordings_dir: Path = RECORDINGS_DIR,
    outcomes: OutcomeStore | None = None,
    sink: AnalysisSink | None = None,
) -> FastAPI:
    """트리거 API와 스트림 소켓을 한 앱에 올린다."""
    # 기본 조립은 실제 위험 판정을 단다. 테스트가 sink를 직접 넣으면 그쪽이
    # 이긴다 — 분석 훅만 보고 싶은 기존 테스트들이 그렇게 쓴다.
    outcomes = outcomes if outcomes is not None else InMemoryOutcomeStore()
    sink = sink if sink is not None else build_risk_sink(store, outcomes)

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
