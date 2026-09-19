"""기준선 — 이 어르신의 '평소' (설계 3.1, 3.2).

저장하지 않고 매번 과거에서 계산한다. 저장된 기준선은 이력과 어긋날 수 있고,
그 어긋남은 아무 신호도 내지 않으면서 점수만 틀리게 만든다.
"""

from app.analysis.baseline import compute_baseline
from app.analysis.metrics_calculator import CallMetrics, RiskAssessment
from app.analysis.outcome import CallOutcome


def outcome(call_id=1, speech_ratio=0.5, delay_ms=1500, degraded=False):
    return CallOutcome(
        call_id=call_id,
        elder_id=12,
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


def test_no_history_has_no_baseline():
    assert compute_baseline([]) is None


def test_two_calls_are_not_enough_to_call_it_usual():
    """1~2통 평균은 기준선이 아니다 — 근거 없는 평균을 지어내지 않는다."""
    assert compute_baseline([outcome(1), outcome(2)]) is None


def test_three_calls_make_a_baseline():
    baseline = compute_baseline(
        [
            outcome(3, speech_ratio=0.4, delay_ms=1000),
            outcome(2, speech_ratio=0.5, delay_ms=1500),
            outcome(1, speech_ratio=0.6, delay_ms=2000),
        ]
    )

    assert baseline is not None
    assert baseline.speech_ratio == 0.5
    assert baseline.avg_response_delay_ms == 1500


def test_degraded_calls_never_enter_the_baseline():
    """degraded는 '근거가 부족하다'고 우리가 직접 표시한 통화다.

    넣으면 한 통의 오염이 창이 지나갈 때까지 모든 비교를 따라다닌다.
    """
    baseline = compute_baseline(
        [
            outcome(4, speech_ratio=0.0, degraded=True),
            outcome(3, speech_ratio=0.5),
            outcome(2, speech_ratio=0.5),
            outcome(1, speech_ratio=0.5),
        ]
    )

    assert baseline is not None
    assert baseline.speech_ratio == 0.5


def test_a_window_of_only_degraded_calls_has_no_baseline():
    assert (
        compute_baseline([outcome(i, degraded=True) for i in range(1, 6)]) is None
    )


def test_calls_without_a_response_are_left_out_of_the_delay_average():
    """None은 '응답이 없었다'이지 '0ms였다'가 아니다.

    0으로 세면 평균이 내려가 이후 모든 통화가 '느려졌다'가 된다.
    """
    baseline = compute_baseline(
        [
            outcome(3, delay_ms=1000),
            outcome(2, delay_ms=None),
            outcome(1, delay_ms=2000),
        ]
    )

    assert baseline is not None
    # 1000과 2000의 평균. None을 0으로 세면 1000이 된다.
    assert baseline.avg_response_delay_ms == 1500


def test_a_baseline_can_know_speech_but_not_delay():
    """3통 내내 응답이 없었다 — 말수 기준선은 있고 지연 기준선은 없다."""
    baseline = compute_baseline(
        [outcome(i, speech_ratio=0.2, delay_ms=None) for i in range(1, 4)]
    )

    assert baseline is not None
    assert baseline.speech_ratio == 0.2
    assert baseline.avg_response_delay_ms is None
