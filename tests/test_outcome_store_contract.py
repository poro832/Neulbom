"""OutcomeStore 규약 — 두 구현에 같은 테스트를 돌린다.

같은 이유로 존재한다: `tests/test_call_store_contract.py`의 모듈 설명을 보라.
여기가 위험 점수가 실제로 보관되는 곳이라, 두 구현이 갈라지면 "테스트는 다
통과하는데 보호자가 보는 숫자만 틀린" 상황이 된다.
"""

from __future__ import annotations

import os

import pytest

from app.analysis.metrics_calculator import CallMetrics, RiskAssessment
from app.analysis.outcome import CallOutcome
from app.api.outcome_store import InMemoryOutcomeStore

ELDER = 12
DATABASE_URL = os.getenv("DATABASE_URL")


@pytest.fixture(
    params=[
        "memory",
        pytest.param(
            "postgres",
            marks=pytest.mark.skipif(
                not DATABASE_URL,
                reason="DATABASE_URL이 없다 — Postgres 규약 테스트를 건너뛴다. "
                "두 구현이 갈라져도 이 실행은 잡지 못한다.",
            ),
        ),
    ]
)
def store(request):
    if request.param == "memory":
        return InMemoryOutcomeStore()

    from app.api.db import connect
    from app.api.postgres_outcome_store import PostgresOutcomeStore

    made = PostgresOutcomeStore(pool=connect(DATABASE_URL))
    made.reset_for_tests()
    return made


def outcome(call_id, elder_id=ELDER, *, risk=None, degraded=False, **over):
    """판정 하나. 기본은 점수가 없는 통화다 — degraded 경로가 더 까다로워
    거기를 기본으로 두면 빠뜨리기 어렵다."""
    fields = dict(
        call_id=call_id,
        elder_id=elder_id,
        metrics=CallMetrics(
            speech_ratio=0.4,
            silence_ratio=0.6,
            turn_count=5,
            negative_word_count=2,
            avg_response_delay_ms=1500,
            elder_speech_ms=40_000,
            ai_speech_ms=20_000,
            silence_ms=60_000,
            response_delays_ms=(900, 1500, 2100),
        ),
        risk=risk,
        no_answer_recent_7=0,
        baseline_n=3,
        baseline_speech_ratio=0.5,
        baseline_avg_response_delay_ms=1200,
        clipped_ms=0,
        filled_gap_ms=0,
        call_duration_ms=120_000,
        degraded=degraded,
        degraded_reasons=("echo_clip",) if degraded else (),
        calculator_version="2.0.0",
        transcription_enabled=True,
    )
    fields.update(over)
    return CallOutcome(**fields)


def scored(call_id, elder_id=ELDER, **over):
    return outcome(
        call_id,
        elder_id,
        risk=RiskAssessment(risk_score=45, risk_level="watch", baseline_delta=0.1),
        **over,
    )


# ------------------------------------------------------------ 기록과 조회


def test_an_elder_without_history_gets_nothing(store):
    assert store.recent(ELDER, 14) == []


def test_a_recorded_outcome_comes_back_whole(store):
    """지표 원자료까지 그대로 돌아와야 한다. 녹음은 30일 뒤 사라지므로
    여기 남지 않은 값은 그 뒤로 어디에서도 복구할 수 없다."""
    store.record(scored(10))

    got = store.recent(ELDER, 14)[0]

    assert got == scored(10)


def test_an_outcome_without_a_score_survives(store):
    """근거가 부족한 통화는 점수를 내지 않는다(risk=None). 그래도 지표는
    남는다 — 점수를 안 낸다고 통화를 버리면 멀쩡히 측정된 값이 함께 사라진다."""
    store.record(outcome(10, degraded=True))

    got = store.recent(ELDER, 14)[0]

    assert got.risk is None
    assert got.degraded is True
    assert got.degraded_reasons == ("echo_clip",)
    assert got.metrics.speech_ratio == 0.4


def test_a_missing_baseline_stays_missing(store):
    """표본이 모자라 기준선을 못 만든 통화다. 0으로 바뀌면 '기준선이 0이었다'와
    '기준선이 없었다'가 같은 값이 되어 나중에 구분할 수 없다."""
    store.record(
        scored(10, baseline_n=0, baseline_speech_ratio=None,
               baseline_avg_response_delay_ms=None)
    )

    got = store.recent(ELDER, 14)[0]

    assert got.baseline_n == 0
    assert got.baseline_speech_ratio is None
    assert got.baseline_avg_response_delay_ms is None


def test_a_missing_response_delay_stays_missing(store):
    """어르신이 한 번도 응답하지 않으면 NULL이다. 0으로 두면 평균이 왜곡된다."""
    store.record(scored(10, metrics=CallMetrics(
        speech_ratio=0.0, silence_ratio=1.0, turn_count=0,
        negative_word_count=0, avg_response_delay_ms=None,
    )))

    assert store.recent(ELDER, 14)[0].metrics.avg_response_delay_ms is None


def test_recording_the_same_call_twice_overwrites(store):
    """call_metrics의 기본키가 call_id다 — 한 통화에 결과가 둘일 수 없다."""
    store.record(scored(10))
    store.record(scored(10, no_answer_recent_7=4))

    got = store.recent(ELDER, 14)
    assert len(got) == 1
    assert got[0].no_answer_recent_7 == 4


# ------------------------------------------------------------ 순서와 창


def test_results_come_back_newest_first(store):
    """최신순은 구현 편의가 아니라 규약이다. 기준선의 창이 이 순서 위에 서
    있어서, 순서가 틀리면 엉뚱한 통화들의 평균이 기준선이 된다."""
    for call_id in (10, 30, 20):
        store.record(scored(call_id))

    assert [o.call_id for o in store.recent(ELDER, 14)] == [30, 20, 10]


def test_limit_keeps_the_newest(store):
    for call_id in (10, 20, 30):
        store.record(scored(call_id))

    assert [o.call_id for o in store.recent(ELDER, 2)] == [30, 20]


def test_another_elders_results_are_not_mixed_in(store):
    store.record(scored(10, elder_id=99))

    assert store.recent(ELDER, 14) == []


def test_before_call_id_excludes_itself_and_later_calls(store):
    """현재 통화가 자기 기준선에 들어가면 델타가 희석되어 나쁜 통화가
    정상으로 보인다. 전사가 비동기라 기록 순서가 통화 순서와 어긋날 수
    있으므로, 순서가 아니라 조건으로 막는다."""
    for call_id in (10, 20, 30):
        store.record(scored(call_id))

    got = store.recent(ELDER, 14, before_call_id=20)

    assert [o.call_id for o in got] == [10]


def test_the_window_is_applied_after_the_cut(store):
    """잘라내기가 먼저고 창이 나중이다. 반대로 하면 최근 14통을 고른 뒤
    거기서 미래 통화를 빼게 되어 표본이 14보다 적어진다."""
    for call_id in range(1, 21):
        store.record(scored(call_id))

    got = store.recent(ELDER, 3, before_call_id=15)

    assert [o.call_id for o in got] == [14, 13, 12]


def test_omitting_before_call_id_returns_everything(store):
    for call_id in (10, 20):
        store.record(scored(call_id))

    assert len(store.recent(ELDER, 14)) == 2
