"""MetricsCalculator — 통화에서 결정론적 지표를 뽑는다 (설계 3.2).

LLM도 네트워크도 개입하지 않는 순수 함수다. 같은 입력이면 반드시 같은 숫자가
나와야 하며, 그게 이 프로젝트의 간판이다.
"""

from app.analysis.metrics_calculator import (
    Baseline,
    CallMetrics,
    assess_risk,
    calculate_metrics,
)
from app.analysis.segments import VadSegment


def seg(start_ms, end_ms):
    return VadSegment(start_ms=start_ms, end_ms=end_ms)


# ------------------------------------------------------------ 발화량


def test_speech_ratio_is_elder_speech_over_call_duration():
    metrics = calculate_metrics(
        call_duration_ms=10_000,
        elder_speech=[seg(0, 2_000), seg(5_000, 6_000)],
        ai_turns=[],
        transcript="",
    )

    assert metrics.speech_ratio == 0.3


def test_turn_count_is_the_number_of_elder_speech_segments():
    metrics = calculate_metrics(
        call_duration_ms=10_000,
        elder_speech=[seg(0, 1_000), seg(3_000, 4_000), seg(7_000, 8_000)],
        ai_turns=[],
        transcript="",
    )

    assert metrics.turn_count == 3


def test_silence_ratio_excludes_ai_speech():
    """AI가 말하는 동안은 '어르신의 침묵'이 아니다."""
    metrics = calculate_metrics(
        call_duration_ms=10_000,
        elder_speech=[seg(4_000, 6_000)],
        ai_turns=[seg(0, 3_000)],
        transcript="",
    )

    # 통화 10초 중 AI 3초, 어르신 2초 → 나머지 5초가 침묵
    assert metrics.silence_ratio == 0.5


def test_empty_call_does_not_divide_by_zero():
    metrics = calculate_metrics(
        call_duration_ms=0, elder_speech=[], ai_turns=[], transcript=""
    )

    assert metrics.speech_ratio == 0.0
    assert metrics.silence_ratio == 0.0
    assert metrics.turn_count == 0


# ------------------------------------------------------------ 부정 표현


def test_negative_expressions_are_counted_from_transcript():
    metrics = calculate_metrics(
        call_duration_ms=10_000,
        elder_speech=[],
        ai_turns=[],
        transcript="요즘 여기저기 아프고 혼자 있으니까 외로워요",
    )

    assert metrics.negative_word_count == 2


def test_conjugated_forms_are_matched_by_stem():
    """'아프다/아파요/아픈'을 다 잡아야 한다. 한국어라 어미가 변한다."""
    metrics = calculate_metrics(
        call_duration_ms=10_000,
        elder_speech=[],
        ai_turns=[],
        transcript="무릎이 아파요. 어제도 아팠고 오늘도 아픕니다",
    )

    assert metrics.negative_word_count == 3


def test_ordinary_conversation_has_no_negative_expressions():
    metrics = calculate_metrics(
        call_duration_ms=10_000,
        elder_speech=[],
        ai_turns=[],
        transcript="오늘 아침은 밥이랑 국이랑 잘 먹었어요. 날씨가 좋네요",
    )

    assert metrics.negative_word_count == 0


# ------------------------------------------------------------ 응답 지연


def test_response_delay_is_measured_from_ai_turn_end_to_elder_reply():
    """정신운동 지연 지표. AI가 말을 끝낸 뒤 어르신이 입을 떼기까지."""
    metrics = calculate_metrics(
        call_duration_ms=20_000,
        elder_speech=[seg(4_000, 6_000)],
        ai_turns=[seg(0, 3_000)],
        transcript="",
    )

    assert metrics.avg_response_delay_ms == 1_000


def test_response_delay_averages_every_turn():
    metrics = calculate_metrics(
        call_duration_ms=30_000,
        elder_speech=[seg(4_000, 5_000), seg(11_000, 12_000)],
        ai_turns=[seg(0, 3_000), seg(8_000, 9_000)],
        transcript="",
    )

    # 1000ms, 2000ms → 평균 1500ms
    assert metrics.avg_response_delay_ms == 1_500


def test_response_delay_is_none_when_elder_never_replies():
    """미응답은 지연 0이 아니라 '측정 불가'다. 0으로 두면 평균이 왜곡된다."""
    metrics = calculate_metrics(
        call_duration_ms=20_000,
        elder_speech=[],
        ai_turns=[seg(0, 3_000)],
        transcript="",
    )

    assert metrics.avg_response_delay_ms is None


def test_ai_turn_with_no_reply_after_it_is_skipped():
    """마지막 AI 발화(작별 인사) 뒤에는 응답이 없다. 이걸 세면 안 된다."""
    metrics = calculate_metrics(
        call_duration_ms=30_000,
        elder_speech=[seg(4_000, 5_000)],
        ai_turns=[seg(0, 3_000), seg(25_000, 28_000)],
        transcript="",
    )

    assert metrics.avg_response_delay_ms == 1_000


# ============================================================ 위험 판정


def metrics_of(
    speech_ratio=0.5, delay_ms=1500, negatives=0, turns=5, silence_ratio=0.3
):
    """지표를 직접 조립한다 — 판정 로직만 격리해서 본다."""
    return CallMetrics(
        speech_ratio=speech_ratio,
        silence_ratio=silence_ratio,
        turn_count=turns,
        negative_word_count=negatives,
        avg_response_delay_ms=delay_ms,
    )


TYPICAL = Baseline(speech_ratio=0.5, avg_response_delay_ms=1500)


def test_call_matching_the_baseline_scores_zero():
    result = assess_risk(metrics_of(), baseline=TYPICAL)

    assert result.risk_score == 0
    assert result.risk_level == "normal"


def test_speech_drop_against_personal_baseline_raises_score():
    """말수가 평소의 40%로 줄었다."""
    result = assess_risk(metrics_of(speech_ratio=0.2), baseline=TYPICAL)

    assert result.risk_score == 21


def test_response_delay_doubling_raises_score():
    """대답이 느려지는 건 정신운동 지연 신호다."""
    result = assess_risk(metrics_of(delay_ms=3000), baseline=TYPICAL)

    assert result.risk_score == 25


def test_negative_expressions_raise_score():
    result = assess_risk(metrics_of(negatives=5), baseline=TYPICAL)

    assert result.risk_score == 20


def test_missed_calls_raise_score():
    result = assess_risk(metrics_of(), baseline=TYPICAL, no_answer_recent_7=3)

    assert result.risk_score == 20


def test_risk_levels_are_derived_from_score():
    assert assess_risk(metrics_of(), baseline=TYPICAL).risk_level == "normal"

    watch = assess_risk(metrics_of(negatives=5), baseline=TYPICAL, no_answer_recent_7=2)
    assert watch.risk_score == 33
    assert watch.risk_level == "watch"

    alert = assess_risk(
        metrics_of(speech_ratio=0.0, negatives=5), baseline=TYPICAL, no_answer_recent_7=3
    )
    assert alert.risk_score == 75
    assert alert.risk_level == "alert"


def test_baseline_delta_reports_change_not_absolute_value():
    """원래 말수가 적은 분과 갑자기 준 분은 다르다 (설계 3.2)."""
    result = assess_risk(metrics_of(speech_ratio=0.2, delay_ms=2000), baseline=TYPICAL)

    assert result.baseline_delta.speech_ratio == -0.3
    assert result.baseline_delta.avg_response_delay_ms == 500


def test_without_baseline_absolute_thresholds_are_used():
    """첫 통화라 기준선이 없어도 판정은 나와야 한다."""
    result = assess_risk(metrics_of(speech_ratio=0.0, delay_ms=None), baseline=None)

    assert result.risk_score == 35
    assert result.baseline_delta is None


def test_score_is_identical_across_repeated_runs():
    """이 프로젝트의 간판. 같은 입력이면 반드시 같은 점수."""
    metrics = metrics_of(speech_ratio=0.23, delay_ms=2870, negatives=3)

    scores = {
        assess_risk(metrics, baseline=TYPICAL, no_answer_recent_7=1).risk_score
        for _ in range(100)
    }

    assert len(scores) == 1


def test_an_unanswered_turn_does_not_borrow_a_later_reply():
    """대답 없이 지나간 턴이 뒤 질문의 대답을 자기 것으로 끌어다 쓰면 안 된다.

    AI가 두 번 말했고 어르신은 두 번째에만 답했다. 첫 턴의 '응답 지연'을
    두 번째 대답으로 재면 중간의 AI 발화와 침묵까지 전부 지연으로 세어져
    3000ms가 나온다. 실제로 잰 것은 두 번째 턴의 1000ms 하나뿐이다.
    """
    metrics = calculate_metrics(
        call_duration_ms=10_000,
        elder_speech=[seg(8_000, 9_000)],
        ai_turns=[seg(1_000, 3_000), seg(5_000, 7_000)],
        transcript="",
    )

    assert metrics.avg_response_delay_ms == 1_000


def test_unanswered_turns_do_not_manufacture_a_maximum_penalty():
    """이 버그의 실제 피해는 점수다.

    짧은 질문 셋 중 마지막에만 답한 통화에서 평균 지연이 7500ms로 나왔다.
    지연 벌점은 6000ms에서 이미 만점(25점)이라, 미응답 두 번이 멀쩡한
    어르신에게 만점짜리 벌점을 만들어 준다. 진짜 값은 6500ms이고, 그건
    첫 두 턴을 세지 않고 마지막 턴 하나만 잰 결과다.
    """
    metrics = calculate_metrics(
        call_duration_ms=12_000,
        elder_speech=[seg(9_000, 9_500)],
        ai_turns=[seg(0, 500), seg(1_000, 1_500), seg(2_000, 2_500)],
        transcript="",
    )

    assert metrics.avg_response_delay_ms == 6_500


def test_a_reply_before_the_next_turn_still_counts():
    """경계를 넣었다고 정상적인 대답까지 버리면 안 된다.

    두 턴 모두 그 턴과 다음 턴 사이에 대답이 있다. 둘 다 세어야 한다.
    """
    metrics = calculate_metrics(
        call_duration_ms=20_000,
        elder_speech=[seg(3_500, 4_000), seg(9_000, 9_500)],
        ai_turns=[seg(1_000, 3_000), seg(7_000, 8_000)],
        transcript="",
    )

    # 500ms, 1000ms → 평균 750ms
    assert metrics.avg_response_delay_ms == 750
