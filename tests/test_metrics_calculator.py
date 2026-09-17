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


def test_apartment_is_not_a_negative_expression():
    """'아파트'는 어간 '아파'를 포함하지만 부정 표현이 아니다.

    독거노인 대부분이 아파트에 살고 그 얘기를 자주 한다. str.count처럼
    부분 문자열로만 잡으면 '아파트'가 매번 부정어 1개로 잡혀 명랑한
    통화가 위양성 알림을 만든다.
    """
    metrics = calculate_metrics(
        call_duration_ms=10_000,
        elder_speech=[],
        ai_turns=[],
        transcript="아파트 사는 게 좋아요",
    )

    assert metrics.negative_word_count == 0


def test_africa_documentary_is_not_a_negative_expression():
    """'아프리카'는 어간 '아프'를 포함하지만 부정 표현이 아니다."""
    metrics = calculate_metrics(
        call_duration_ms=10_000,
        elder_speech=[],
        ai_turns=[],
        transcript="아프리카 다큐 봤어요",
    )

    assert metrics.negative_word_count == 0


def test_apartment_mentioned_twice_is_still_not_negative():
    """같은 충돌 단어가 여러 번 나와도 매번 걸러야 한다."""
    metrics = calculate_metrics(
        call_duration_ms=10_000,
        elder_speech=[],
        ai_turns=[],
        transcript="손주가 아파트로 이사 갔어요. 아파트가 참 좋더라",
    )

    assert metrics.negative_word_count == 0


def test_pain_expression_with_neyo_ending_is_still_counted():
    """'아프네'처럼 흔한 어미가 붙은 형태는 계속 잡혀야 한다."""
    metrics = calculate_metrics(
        call_duration_ms=10_000,
        elder_speech=[],
        ai_turns=[],
        transcript="여기저기 아프네",
    )

    assert metrics.negative_word_count == 1


def test_loneliness_expression_is_still_counted():
    metrics = calculate_metrics(
        call_duration_ms=10_000,
        elder_speech=[],
        ai_turns=[],
        transcript="혼자라 외로워",
    )

    assert metrics.negative_word_count == 1


def test_annoyed_to_death_expression_is_still_counted():
    metrics = calculate_metrics(
        call_duration_ms=10_000,
        elder_speech=[],
        ai_turns=[],
        transcript="죽겠다 정말",
    )

    assert metrics.negative_word_count == 1


def test_hard_time_expression_is_still_counted():
    metrics = calculate_metrics(
        call_duration_ms=10_000,
        elder_speech=[],
        ai_turns=[],
        transcript="요즘 힘들어요",
    )

    assert metrics.negative_word_count == 1


def test_knee_pain_expression_is_still_counted():
    metrics = calculate_metrics(
        call_duration_ms=10_000,
        elder_speech=[],
        ai_turns=[],
        transcript="무릎이 아파요",
    )

    assert metrics.negative_word_count == 1


def test_depression_diagnosis_noun_is_counted_despite_no_verb_ending():
    """'우울증'은 어미가 아니라 명사 접미사 '증'이 붙었지만 진짜 부정 신호다.

    어미 기준만 쓰면 이런 진단명이 걸러져 버려서 예외로 명시한다.
    """
    metrics = calculate_metrics(
        call_duration_ms=10_000,
        elder_speech=[],
        ai_turns=[],
        transcript="요즘 우울증 진단받았어요",
    )

    assert metrics.negative_word_count == 1


def test_afghanistan_is_not_a_negative_expression():
    """'아프간'은 어간 '아프'를 포함하지만 나라 이름이다."""
    metrics = calculate_metrics(
        call_duration_ms=10_000,
        elder_speech=[],
        ai_turns=[],
        transcript="아프간 전쟁 다큐 봤어요",
    )

    assert metrics.negative_word_count == 0


# -------------------------------------------- 해체 종결형(문장이 어간에서 끝남)


def test_pain_expression_ending_in_a_period_is_counted():
    """'무릎이 아파.'는 잘린 문장이 아니라 완결된 해체 종결형이다."""
    metrics = calculate_metrics(
        call_duration_ms=10_000,
        elder_speech=[],
        ai_turns=[],
        transcript="무릎이 아파.",
    )

    assert metrics.negative_word_count == 1


def test_pain_expression_at_end_of_transcript_is_counted():
    """뒤에 아무 글자도 없어도(전사가 거기서 끝나도) 완결된 발화다."""
    metrics = calculate_metrics(
        call_duration_ms=10_000,
        elder_speech=[],
        ai_turns=[],
        transcript="무릎이 아파",
    )

    assert metrics.negative_word_count == 1


def test_pain_expression_ending_in_exclamation_is_counted():
    metrics = calculate_metrics(
        call_duration_ms=10_000,
        elder_speech=[],
        ai_turns=[],
        transcript="여기가 아파!",
    )

    assert metrics.negative_word_count == 1


def test_pain_expression_as_a_bare_question_is_counted():
    metrics = calculate_metrics(
        call_duration_ms=10_000,
        elder_speech=[],
        ai_turns=[],
        transcript="아파?",
    )

    assert metrics.negative_word_count == 1


def test_bare_stem_trailing_off_at_end_of_string_is_counted():
    """'너무 힘들'처럼 어미 없이 어간에서 말이 끊겨도 놓치면 안 된다.

    위음성(아픈데 못 세는 것)이 위양성보다 이 서비스에 더 위험한 오차라서,
    다음 글자가 아예 없는 경우는 세는 쪽으로 기운다.
    """
    metrics = calculate_metrics(
        call_duration_ms=10_000,
        elder_speech=[],
        ai_turns=[],
        transcript="너무 힘들",
    )

    assert metrics.negative_word_count == 1


def test_depression_haeyo_conjugation_is_counted():
    """'우울해요'는 '우울하다'가 '해'로 활용한 형태다.

    '하/해/했'은 어미 화이트리스트가 아니라 '우울' 전용 추가 목록에 있다.
    """
    metrics = calculate_metrics(
        call_duration_ms=10_000,
        elder_speech=[],
        ai_turns=[],
        transcript="우울해요",
    )

    assert metrics.negative_word_count == 1


def test_annoying_attributive_form_is_counted():
    """'귀찮은 일'처럼 관형형(-은)이 붙어도 잡아야 한다."""
    metrics = calculate_metrics(
        call_duration_ms=10_000,
        elder_speech=[],
        ai_turns=[],
        transcript="요즘 귀찮은 일이 많아요",
    )

    assert metrics.negative_word_count == 1


def test_lonely_attributive_form_is_counted():
    """'외로운'처럼 ㅂ불규칙 관형형도 잡아야 한다."""
    metrics = calculate_metrics(
        call_duration_ms=10_000,
        elder_speech=[],
        ai_turns=[],
        transcript="외로운 하루였어요",
    )

    assert metrics.negative_word_count == 1


# -------------------------------------------- 합니다체(격식체)와 불규칙 활용


def test_formal_register_pain_is_counted():
    """'아픕니다'는 원래도 되던 케이스 — 회귀 확인용."""
    metrics = calculate_metrics(
        call_duration_ms=10_000,
        elder_speech=[],
        ai_turns=[],
        transcript="무릎이 아픕니다",
    )

    assert metrics.negative_word_count == 1


def test_formal_register_annoyance_is_counted():
    """'귀찮습니다'도 원래 되던 케이스 — 회귀 확인용."""
    metrics = calculate_metrics(
        call_duration_ms=10_000,
        elder_speech=[],
        ai_turns=[],
        transcript="요즘 다 귀찮습니다",
    )

    assert metrics.negative_word_count == 1


def test_formal_register_annoyed_to_death_is_counted():
    """'죽겠습니다'도 원래 되던 케이스 — 회귀 확인용."""
    metrics = calculate_metrics(
        call_duration_ms=10_000,
        elder_speech=[],
        ai_turns=[],
        transcript="아이고 죽겠습니다",
    )

    assert metrics.negative_word_count == 1


def test_formal_register_hard_time_is_counted_despite_irregular_stem():
    """'힘듭니다'는 어미가 바뀐 게 아니라 어간 자체가 'ㄹ 탈락'으로 바뀐다.

    '힘들'이 문자열에 아예 없으니 어미 화이트리스트로는 못 잡는다.
    불규칙 표면형 '힘듭'을 사전에 그대로 추가해야 한다.
    """
    metrics = calculate_metrics(
        call_duration_ms=10_000,
        elder_speech=[],
        ai_turns=[],
        transcript="요즘 힘듭니다",
    )

    assert metrics.negative_word_count == 1


def test_formal_register_loneliness_is_counted_despite_irregular_stem():
    """'외롭습니다'도 마찬가지다 — 'ㅂ 불규칙'이라 '외로'가 아니라 '외롭'이 표면형이다."""
    metrics = calculate_metrics(
        call_duration_ms=10_000,
        elder_speech=[],
        ai_turns=[],
        transcript="혼자 있으니 외롭습니다",
    )

    assert metrics.negative_word_count == 1


def test_formal_register_depression_is_counted_despite_syllable_fusion():
    """'우울합니다'의 '합'은 '하'와 다른 완성 음절이라 별도 예외가 필요하다."""
    metrics = calculate_metrics(
        call_duration_ms=10_000,
        elder_speech=[],
        ai_turns=[],
        transcript="요즘 마음이 우울합니다",
    )

    assert metrics.negative_word_count == 1


def test_new_irregular_stems_do_not_swallow_arbitrary_continuations():
    """'힘듭'/'외롭'을 사전에 추가해도 무조건 다 세는 와일드카드가 되면 안 된다.

    실제로 '힘듭'/'외롭'으로 시작하면서 이 두 형용사와 무관한 일반 명사는
    조사한 범위에서 찾지 못했다 — 그래서 여기서는 대신 메커니즘 자체를
    검증한다: 화이트리스트에 없는 글자가 이어지면(가상의 예시라도) 여전히
    걸러져야 한다. '아파트'를 걸렀던 것과 같은 규칙이 새 어간에도 그대로
    적용된다는 뜻이다.
    """
    metrics = calculate_metrics(
        call_duration_ms=10_000,
        elder_speech=[],
        ai_turns=[],
        transcript="힘듭카페에서 만나요",
    )

    assert metrics.negative_word_count == 0


def test_apartment_still_not_negative_after_sentence_end_rule():
    """문장 종결 규칙을 추가해도 '아파트' 오탐이 다시 열리면 안 된다.

    '아파트'는 항상 한글 음절('트')로 이어지므로 이 규칙의 적용 대상이
    아니다 — 그걸 테스트로 못박아 둔다.
    """
    metrics = calculate_metrics(
        call_duration_ms=10_000,
        elder_speech=[],
        ai_turns=[],
        transcript="아파트 사는 게 좋아요. 아파트 최고",
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


def test_a_zero_length_ai_turn_is_not_a_turn():
    """길이 0인 AI 발화는 재생된 적이 없다 — 두 소비자가 같게 봐야 한다.

    에코 제거(echo._merge)는 이미 이런 구간을 버린다. 지표 계산만 세면 같은
    구간이 한쪽에서는 없는 것이고 다른 쪽에서는 있는 것이 된다. 게다가 길이
    0인 턴의 end_ms는 재생이 '시작'된 시각이라, 거기서부터 지연을 재면 AI가
    말한 시간 전체가 조용히 어르신의 응답 지연에 들어간다.
    """
    mark_returned_late = calculate_metrics(
        call_duration_ms=20_000,
        elder_speech=[seg(5_000, 6_000)],
        ai_turns=[seg(1_000, 1_000)],
        transcript="",
    )

    # 잴 수 있는 AI 발화가 없다. 4000ms짜리 지연을 지어내면 안 된다.
    assert mark_returned_late.avg_response_delay_ms is None


def test_a_zero_length_ai_turn_does_not_shift_the_silence_ratio():
    """길이 없는 턴이 'AI가 말한 시간'에 끼어들면 침묵 비율이 흔들린다."""
    with_empty = calculate_metrics(
        call_duration_ms=10_000,
        elder_speech=[seg(0, 2_000)],
        ai_turns=[seg(3_000, 5_000), seg(7_000, 7_000)],
        transcript="",
    )
    without_empty = calculate_metrics(
        call_duration_ms=10_000,
        elder_speech=[seg(0, 2_000)],
        ai_turns=[seg(3_000, 5_000)],
        transcript="",
    )

    assert with_empty == without_empty
