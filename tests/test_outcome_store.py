"""분석 결과 저장소 (설계 4.3, 4.6).

최신순은 구현 편의가 아니라 규약이다. 기준선의 창이 이 순서 위에 서 있고,
깨지면 아무 오류 없이 점수만 틀린다.
"""

from app.analysis.metrics_calculator import CallMetrics, RiskAssessment
from app.analysis.outcome import CallOutcome
from app.api.outcome_store import InMemoryOutcomeStore


def outcome(call_id, elder_id=12, speech_ratio=0.5):
    return CallOutcome(
        call_id=call_id,
        elder_id=elder_id,
        metrics=CallMetrics(
            speech_ratio=speech_ratio,
            silence_ratio=0.3,
            turn_count=5,
            negative_word_count=0,
            avg_response_delay_ms=1500,
        ),
        risk=RiskAssessment(risk_score=0, risk_level="normal", baseline_delta=None),
        no_answer_recent_7=0,
        clipped_ms=0,
        degraded=False,
        calculator_version="1.0.0",
    )


def test_an_elder_without_history_gets_an_empty_list():
    assert InMemoryOutcomeStore().recent(12, 14) == []


def test_results_come_back_newest_first_whatever_the_insert_order():
    """삽입 순서가 아니라 call_id가 시간 순서를 정한다 (설계 4.6)."""
    store = InMemoryOutcomeStore()
    for call_id in (3, 1, 5, 2):
        store.record(outcome(call_id))

    assert [o.call_id for o in store.recent(12, 14)] == [5, 3, 2, 1]


def test_limit_keeps_the_newest():
    store = InMemoryOutcomeStore()
    for call_id in range(1, 21):
        store.record(outcome(call_id))

    assert [o.call_id for o in store.recent(12, 3)] == [20, 19, 18]


def test_another_elders_results_are_not_mixed_in():
    """한 어르신의 기준선에 다른 분의 통화가 섞이면 판정이 통째로 무의미해진다."""
    store = InMemoryOutcomeStore()
    store.record(outcome(1, elder_id=12))
    store.record(outcome(2, elder_id=99))

    assert [o.call_id for o in store.recent(12, 14)] == [1]


def test_recording_the_same_call_twice_overwrites():
    """call_metrics의 PK는 call_id다 — 한 통화에 결과가 둘일 수 없다."""
    store = InMemoryOutcomeStore()
    store.record(outcome(1, speech_ratio=0.2))
    store.record(outcome(1, speech_ratio=0.7))

    results = store.recent(12, 14)
    assert len(results) == 1
    assert results[0].metrics.speech_ratio == 0.7
