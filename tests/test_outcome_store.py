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
        baseline_n=0,
        baseline_speech_ratio=None,
        baseline_avg_response_delay_ms=None,
        clipped_ms=0,
        filled_gap_ms=0,
        call_duration_ms=60_000,
        degraded=False,
        degraded_reasons=(),
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


def test_before_call_id_excludes_the_call_itself():
    """현재 통화가 자기 기준선에 들어가면 델타가 희석되어 나쁜 통화가
    정상으로 보인다. 아무 오류도 나지 않는다.

    지금까지 이것은 '기록보다 조회가 먼저'라는 순서로만 보장됐다. 누가 그
    순서를 바꾸면 조용히 깨진다 — 조건으로 못 박는다.
    """
    store = InMemoryOutcomeStore()
    for call_id in (10, 20, 30):
        store.record(outcome(call_id))

    assert [o.call_id for o in store.recent(12, 10, before_call_id=30)] == [20, 10]


def test_before_call_id_excludes_future_calls():
    """전사가 늦게 끝나면 통화 30이 통화 20보다 먼저 기록될 수 있다
    (설계 6장 — CallStore._expire_stale이 잠금 순서를 깨뜨리는 경로).

    그때 통화 20의 기준선에 통화 30이 들어가면 '미래의 자기'와 비교하게 된다.
    """
    store = InMemoryOutcomeStore()
    store.record(outcome(30))
    store.record(outcome(10))

    assert [o.call_id for o in store.recent(12, 10, before_call_id=20)] == [10]


def test_the_window_is_applied_after_the_cut():
    """잘라내기가 먼저고 창이 나중이다. 반대로 하면 최근 14통을 고른 뒤
    거기서 미래 통화를 빼게 되어 표본이 14보다 적어진다.
    """
    store = InMemoryOutcomeStore()
    for call_id in range(1, 21):
        store.record(outcome(call_id))

    got = store.recent(12, 3, before_call_id=15)

    assert [o.call_id for o in got] == [14, 13, 12]


def test_omitting_before_call_id_changes_nothing():
    """기존 호출부(테스트 포함)가 그대로 돌아야 한다."""
    store = InMemoryOutcomeStore()
    for call_id in (10, 20):
        store.record(outcome(call_id))

    assert [o.call_id for o in store.recent(12, 10)] == [20, 10]
