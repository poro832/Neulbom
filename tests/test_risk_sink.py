"""위험 점수 배선 (설계 4.5).

이 배선이 없던 동안 assess_risk는 테스트에서만 불렸다. 지표까지 만들어 놓고
점수로 환산하지 않았다는 뜻이고, 그러면 "위험 점수는 재는 것"이라는 이
서비스의 간판 주장이 전화 경로에서 증명되지 않는다.
"""

from app.analysis.call_analysis import CallAnalysis
from app.analysis.metrics_calculator import CallMetrics, RiskAssessment
from app.analysis.outcome import CallOutcome
from app.api.outcome_store import InMemoryOutcomeStore
from app.api.store import InMemoryCallStore
from app.main import build_risk_sink


def analysis_of(speech_ratio=0.5, delay_ms=1500, degraded=False):
    return CallAnalysis(
        metrics=CallMetrics(
            speech_ratio=speech_ratio,
            silence_ratio=0.3,
            turn_count=5,
            negative_word_count=0,
            avg_response_delay_ms=delay_ms,
        ),
        clipped_ms=0,
        degraded=degraded,
    )


def past_outcome(call_id, elder_id=12, speech_ratio=0.5, delay_ms=1500):
    return CallOutcome(
        call_id=call_id,
        elder_id=elder_id,
        metrics=CallMetrics(
            speech_ratio=speech_ratio,
            silence_ratio=0.3,
            turn_count=5,
            negative_word_count=0,
            avg_response_delay_ms=delay_ms,
        ),
        risk=RiskAssessment(risk_score=0, risk_level="normal", baseline_delta=None),
        no_answer_recent_7=0,
        clipped_ms=0,
        degraded=False,
        calculator_version="1.0.0",
    )


def make(history=()):
    """저장소 한 쌍과 sink, 그리고 '지금 끝난 통화' 하나를 만든다."""
    store = InMemoryCallStore(phones={12: "070-1111-2222"})
    outcomes = InMemoryOutcomeStore()
    for outcome in history:
        outcomes.record(outcome)
    call = store.create(elder_id=12, trigger_type="scheduled")
    return store, outcomes, build_risk_sink(store, outcomes), call


def recorded_for(outcomes, call_id):
    return next(o for o in outcomes.recent(12, 50) if o.call_id == call_id)


def test_a_finished_call_gets_a_risk_score():
    """점수가 실제로 나온다 — 이게 이 태스크의 전부다."""
    _, outcomes, sink, call = make()

    sink(call.call_id, analysis_of())

    result = recorded_for(outcomes, call.call_id)
    assert 0 <= result.risk.risk_score <= 100
    assert result.risk.risk_level in {"normal", "watch", "alert"}
    assert result.calculator_version == "1.0.0"


def test_the_first_call_has_no_baseline():
    """이력이 없으면 절대 기준으로 점수를 낸다 — 기준선을 지어내지 않는다."""
    _, outcomes, sink, call = make()

    sink(call.call_id, analysis_of())

    assert recorded_for(outcomes, call.call_id).risk.baseline_delta is None


def test_the_current_call_never_enters_its_own_baseline():
    """이 설계에서 가장 조용한 실패다.

    현재 통화가 자기 기준선에 섞이면 델타가 자기 쪽으로 희석돼 나쁜 통화가
    정상으로 보인다. 오류도 경고도 나지 않는다. 오염은 배선 순서가 뒤집힐
    때 생긴다 — 기록(6단계)이 기준선 계산(3단계) 앞으로 가면 바로 일어난다.
    """
    history = [past_outcome(call_id, speech_ratio=0.5) for call_id in (101, 102, 103, 104)]
    _, outcomes, sink, call = make(history)

    sink(call.call_id, analysis_of(speech_ratio=0.1))

    delta = recorded_for(outcomes, call.call_id).risk.baseline_delta
    assert delta is not None
    # 과거 4통만의 평균 0.5가 기준이다. 현재 통화가 섞이면 기준선이
    # (0.5×4 + 0.1) / 5 = 0.42가 되고 델타는 -0.32가 된다.
    assert delta.speech_ratio == -0.4


def test_requested_calls_do_not_raise_the_no_answer_penalty():
    """요청 통화의 미응답까지 세면 활발한 어르신이 감점된다(설계 3.3)."""
    store, outcomes, sink, _ = make()
    for _ in range(3):
        requested = store.create(elder_id=12, trigger_type="requested")
        store.mark_no_answer(requested.call_id)
    call = store.create(elder_id=12, trigger_type="scheduled")

    sink(call.call_id, analysis_of())

    assert recorded_for(outcomes, call.call_id).no_answer_recent_7 == 0


def test_missed_scheduled_calls_raise_the_no_answer_penalty():
    store, outcomes, sink, _ = make()
    for _ in range(3):
        missed = store.create(elder_id=12, trigger_type="scheduled")
        store.mark_no_answer(missed.call_id)
    call = store.create(elder_id=12, trigger_type="scheduled")

    sink(call.call_id, analysis_of())

    result = recorded_for(outcomes, call.call_id)
    assert result.no_answer_recent_7 == 3
    # 미응답 만점 지점이 3건이다 — 20점이 그대로 들어간다.
    assert result.risk.risk_score >= 20


def test_the_same_call_always_scores_the_same():
    """같은 입력이면 같은 점수. 이게 깨지면 제품 주장이 깨진다."""
    scores = []
    for _ in range(2):
        history = [past_outcome(cid, speech_ratio=0.5) for cid in (101, 102, 103)]
        _, outcomes, sink, call = make(history)
        sink(call.call_id, analysis_of(speech_ratio=0.2, delay_ms=2600))
        scores.append(recorded_for(outcomes, call.call_id).risk.risk_score)

    assert scores[0] == scores[1]


def test_a_broken_score_does_not_escape_the_sink():
    """점수를 못 내는 것보다 통화가 안 끝나는 쪽이 훨씬 나쁘다.

    sink에서 예외가 나가면 통화 종료 처리 뒤에 그대로 올라간다. 어르신이
    409로 영구 잠기는 경로라 여기서 막는다.
    """
    _, outcomes, sink, _ = make()

    sink(99999, analysis_of())  # 저장소에 없는 통화 — 예외가 나면 안 된다

    # 예외가 안 나는 것만으로는 부족하다. 모르는 통화의 결과를 지어내서
    # 남기지도 않아야 한다 — 남기면 그게 남의 기준선에 섞인다.
    assert outcomes.recent(12, 50) == []


class _ExplodingOutcomeStore:
    """record()가 항상 터지는 가짜 저장소.

    위의 test_a_broken_score_does_not_escape_the_sink는 store.get(call_id)가
    KeyError를 던지는 경로(위쪽 try/except)만 지난다. build_risk_sink 안의
    두 번째 try/except(assess_risk, outcomes.record를 감싸는 쪽)는 그
    테스트로는 한 번도 실행되지 않는다 — record 자체가 예외를 내야
    이 안전망이 실제로 동작하는지 알 수 있다.
    """

    def record(self, outcome):
        raise RuntimeError("저장소 장애")

    def recent(self, elder_id, limit):
        return []


def test_a_failing_outcome_store_does_not_escape_the_sink():
    """outcomes.record가 터져도 sink 밖으로 예외가 나가면 안 된다.

    통화 종료 자체는 _end_of_call의 finally와 stream_server의 바깥
    try/except가 이미 보장한다. 이 테스트가 지키는 것은 그것과 다르다 —
    sink 안의 except Exception이 실제로 이 경로(기준선 계산 이후,
    outcomes.record 실패)를 잡아내는지, 로직으로만이 아니라 실행으로
    확인하는 것이다.
    """
    store = InMemoryCallStore(phones={12: "070-1111-2222"})
    call = store.create(elder_id=12, trigger_type="scheduled")
    sink = build_risk_sink(store, _ExplodingOutcomeStore())

    sink(call.call_id, analysis_of())  # 예외가 나면 안 된다
