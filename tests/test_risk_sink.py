"""위험 점수 배선 (설계 4.5).

이 배선이 없던 동안 assess_risk는 테스트에서만 불렸다. 지표까지 만들어 놓고
점수로 환산하지 않았다는 뜻이고, 그러면 "위험 점수는 재는 것"이라는 이
서비스의 간판 주장이 전화 경로에서 증명되지 않는다.
"""

import logging

from app.analysis.call_analysis import CallAnalysis
from app.analysis.metrics_calculator import CallMetrics, RiskAssessment
from app.analysis.outcome import CallOutcome
from app.api.outcome_store import InMemoryOutcomeStore
from app.api.store import InMemoryCallStore
from app.main import build_risk_sink


def analysis_of(speech_ratio=0.5, delay_ms=1500, degraded=False, duration_ms=60_000):
    return CallAnalysis(
        metrics=CallMetrics(
            speech_ratio=speech_ratio,
            silence_ratio=0.3,
            turn_count=5,
            negative_word_count=0,
            avg_response_delay_ms=delay_ms,
        ),
        clipped_ms=0,
        call_duration_ms=duration_ms,
        degraded=degraded,
    )


def past_outcome(call_id, elder_id=12, speech_ratio=0.5, delay_ms=1500, degraded=False):
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
        baseline_n=0,
        clipped_ms=0,
        call_duration_ms=60_000,
        degraded=degraded,
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
    assert result.calculator_version == "2.0.0"


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
    """모르는 통화의 결과를 지어내 남기지 않는다.

    통화 종료(409 영구 잠금 방지)는 _end_of_call의 finally와 stream_server의
    바깥 try/except가 이미 보장한다 — 이 테스트가 지키는 건 그게 아니다.
    store.get(call_id)가 KeyError를 던지는 통화를 sink에 넘겼을 때 예외가
    새지 않는 것과, 그 모르는 통화의 결과를 남의 기준선에 섞이게 지어내지
    않는 것을 확인한다.
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


def test_a_degraded_call_is_recorded_as_degraded():
    """analysis.degraded가 CallOutcome까지 그대로 전달된다.

    이 값이 새면(예: 하드코딩된 False로 바뀌면) degraded 통화가 멀쩡한
    통화로 저장되고, compute_baseline이 그 통화를 걸러낼 방법이 없어져
    오염된 지표가 그대로 14통짜리 기준선에 들어간다(설계 3.2). 지금은
    체인이 맞게 동작하지만 이 값 하나를 고정하는 테스트가 없었다.
    """
    _, outcomes, sink, call = make()

    sink(call.call_id, analysis_of(degraded=True))

    assert recorded_for(outcomes, call.call_id).degraded is True


def test_degraded_history_never_seeds_the_next_baseline():
    """degraded 통화만 쌓여도 기준선이 서지 않는다 — 저장부터 배제까지.

    compute_baseline은 degraded 통화를 거르므로(설계 3.2), 최근 통화가
    전부 degraded면 사용 가능한 과거가 0통이라 기준선이 없어야 한다. 이
    테스트는 위 test_a_degraded_call_is_recorded_as_degraded가 확인한
    "저장" 쪽과 baseline 모듈의 "배제" 쪽이 실제로 맞물리는지를 sink를
    통해 끝에서 끝까지 본다.
    """
    store, outcomes, sink, _ = make()
    for _ in range(4):
        degraded_call = store.create(elder_id=12, trigger_type="scheduled")
        sink(degraded_call.call_id, analysis_of(degraded=True))
    call = store.create(elder_id=12, trigger_type="scheduled")

    sink(call.call_id, analysis_of())

    assert recorded_for(outcomes, call.call_id).risk.baseline_delta is None


def test_a_degraded_call_gets_no_score_at_all():
    """근거가 부족한 통화에는 숫자를 붙이지 않는다.

    보호자는 숫자만 본다. "62점" 아래에 작게 "근거 부족"이라고 적어도 62가
    머리에 남는다. 그건 "조용히 틀린 숫자가 서버가 죽는 것보다 나쁘다"는
    이 프로젝트의 원칙과 정면으로 충돌한다 — 원칙을 지키려면 숫자를 내지
    않아야 한다.

    지표는 남긴다. 측정은 했고 판정만 하지 않은 것이라, 나중에 근거가
    채워지면 다시 판정할 수 있어야 한다.
    """
    _, outcomes, sink, call = make()

    sink(call.call_id, analysis_of(degraded=True))

    recorded = recorded_for(outcomes, call.call_id)
    assert recorded.risk is None
    assert recorded.degraded is True
    assert recorded.metrics.speech_ratio == 0.5


def test_a_degraded_call_does_not_log_a_failure(caplog):
    """점수를 내지 않는 것과 판정이 실패하는 것은 다르다.

    로그 줄이 risk를 무조건 읽으면 degraded 통화마다 AttributeError가 나고,
    그 예외는 아래 except가 삼켜서 "위험 판정 실패"로만 남는다. 결과는 이미
    기록된 뒤라 정상으로 보이므로, 결과만 검사하는 테스트로는 절대 잡히지
    않는다 — 로그를 봐야 한다.
    """
    _, _, sink, call = make()

    with caplog.at_level(logging.ERROR, logger="app.main"):
        sink(call.call_id, analysis_of(degraded=True))

    assert [record.message for record in caplog.records] == []


# --------------------------------- 판단 재료를 남긴다 (경계는 정하지 않는다)


def test_the_outcome_records_how_many_calls_the_baseline_used():
    """기준선을 몇 통으로 만들었는지가 결과에 남아야 한다.

    "몇 통부터 믿을 만한가"는 지금 알 수 없다 — 3이든 7이든 14든 근거가
    없기는 마찬가지다. 경계를 지어내는 대신 실제 표본 수를 남겨서, 실통
    데이터가 쌓이면 분포를 보고 정할 수 있게 한다.
    """
    history = [past_outcome(call_id) for call_id in (101, 102, 103, 104)]
    _, outcomes, sink, call = make(history)

    sink(call.call_id, analysis_of())

    assert recorded_for(outcomes, call.call_id).baseline_n == 4


def test_degraded_history_does_not_count_toward_the_baseline_sample():
    """기준선에 안 쓴 통화를 표본 수에 세면 그 숫자가 거짓말이 된다."""
    history = [past_outcome(call_id, degraded=True) for call_id in (101, 102, 103)]
    _, outcomes, sink, call = make(history)

    sink(call.call_id, analysis_of())

    recorded = recorded_for(outcomes, call.call_id)
    assert recorded.baseline_n == 0
    assert recorded.risk is not None
    assert recorded.risk.baseline_delta is None


def test_the_outcome_records_the_call_duration():
    """짧은 통화는 모든 비율이 불안정하다.

    8초 통화의 25%와 5분 통화의 25%는 다른 뜻인데, "몇 초 미만을 버릴
    것인가"는 실제 통화 분포를 봐야 정할 수 있다. 문턱을 지금 만들지 않고
    판단 재료인 길이를 남긴다.
    """
    _, outcomes, sink, call = make()

    sink(call.call_id, analysis_of(duration_ms=8_000))

    assert recorded_for(outcomes, call.call_id).call_duration_ms == 8_000
