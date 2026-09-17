"""통화에서 결정론적 위험 지표를 계산한다 (설계 3.2).

이 모듈에는 LLM도 네트워크도 개입하지 않는다. 같은 입력이면 반드시 같은
숫자가 나오며, 그래야 "오늘 62점 내일 71점" 같은 일이 생기지 않는다.
LLM은 여기서 나온 숫자를 사람 말로 설명하는 역할만 한다.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from app.analysis.segments import VadSegment

# 어간으로 매칭한다. 한국어는 어미가 변해서 완전 일치로는 거의 못 잡는다.
# "아프다 / 아파요 / 아픕니다"를 모두 잡으려면 어간 목록이 필요하다.
DEFAULT_NEGATIVE_STEMS = frozenset(
    {"아프", "아파", "아팠", "아픕", "힘들", "외로", "귀찮", "죽겠", "우울"}
)

# str.count는 부분 문자열이면 어디든 잡는다. 그런데 "아파트"의 "아파", "아프리카"의
# "아프"처럼 어간과 우연히 겹치는 일반 명사가 있고, 독거노인 통화에서 가장 자주
# 나오는 명사가 하필 "아파트"다. 명랑한 통화가 "아파트" 언급 몇 번만으로 부정어
# 점수(100점 중 20점)를 채우고 오탐 알림을 만들 수 있다.
#
# 택한 방법: 어간 바로 다음 글자 하나로 "이게 정말 용언 활용인가"를 본다.
# 다음 글자가 없거나(문장이 거기서 끝남) 한글 음절이 아니면(공백, 마침표,
# 느낌표, 물음표, 쉼표 등) 그 자체로 완결된 발화로 본다 — "무릎이 아파",
# "여기가 아파!", "아파?"는 노인 통화에서 가장 흔한 해체 종결형이지 잘린
# 문장이 아니다. 다음 글자가 한글 음절이면 그때만 어미 화이트리스트
# (_NEGATIVE_ENDING_STARTS, 필요하면 어간별 추가 목록)에 있는지 확인한다.
# "아파트"의 "트", "아프리카"의 "리", "아프간"의 "간"은 전부 한글 음절이면서
# 화이트리스트에 없으니 계속 걸러진다.
#
# 이 판정의 비대칭성 — 어느 쪽으로 틀리는 게 덜 위험한지:
# 위양성(멀쩡한데 잡음)은 보호자가 통화 내용을 확인하면 바로 해소되는
# 성가심이다. 위음성(아픈데 못 잡음)은 이 서비스가 존재하는 이유 자체를
# 무력화한다 — "아프다"고 말했는데 시스템이 안 세면, 그 통화는 조용히
# '정상'으로 넘어간다. 그래서 애매한 경우(다음 글자가 한글이 아니거나 없음)는
# 반드시 세는 쪽으로 기울였다. 남아 있는 오차는 그래서 "위양성이 남았다"가
# 아니라 "아직 못 잡는 위음성이 있다"는 방향이고, 그게 이 설계에서 의도적으로
# 택한, 덜 위험한 쪽의 오차다.
#
# 그래도 이 방법이 놓치는 것 — 정직하게 적어 둔다:
# 1) 다음 글자가 한글 음절인데 화이트리스트/어간별 목록에 없는 새로운 활용형이나
#    새 충돌 명사. 이 목록들은 지금 가진 9개 어간의 실제 활용형을 조사해서
#    채운 것이라 완전하지 않다 — 예를 들어 "우울합니다"의 "합"은 "하"와 다른
#    음절이라 지금 목록으로는 못 잡는다(격식체 자체가 이 서비스가 겨냥하는
#    통화에서 드물다고 보고 남겨 둔 구멍이다).
# 2) 어미가 아니라 명사 접미사가 붙어도 진짜 부정 신호인 경우 — 대표적으로
#    "우울증"의 "증". 순수 어미 규칙만 쓰면 이것도 걸러지는데, 진단명은 놓치면
#    안 되는 신호라서 _NOUN_SUFFIX_EXCEPTIONS로 어간별 예외를 따로 둔다. 이
#    예외 목록도 마찬가지로 지금 알려진 것만 담았다 — "귀찮음"처럼 또 다른
#    파생 명사가 있다면 아직 못 잡는다.
_NEGATIVE_ENDING_STARTS = frozenset(
    {
        "다", "요", "네", "어", "아", "고", "니", "지", "워", "웠", "습",
        "면", "겠", "잖", "구", "던", "은", "운",
    }
)

# 어미 규칙으로는 못 잡는, 그러나 진짜 부정 신호인 어간별 추가 목록.
# "우울"은 규칙 활용(-다/-어/-네...)이 아니라 "하다"가 그대로 붙는
# 형용사(우울하다)라 하/해/했이 필요하고, 명사형 "우울증"과 관형형
# "우울한"도 여기 넣는다.
_NOUN_SUFFIX_EXCEPTIONS: dict[str, frozenset[str]] = {
    "우울": frozenset({"증", "하", "해", "했", "한"}),
}


def _is_hangul_syllable(ch: str) -> bool:
    return "가" <= ch <= "힣"


@dataclass(frozen=True)
class CallMetrics:
    speech_ratio: float
    silence_ratio: float
    turn_count: int
    negative_word_count: int
    # 어르신이 한 번도 응답하지 않으면 None. 0으로 두면 평균이 왜곡된다.
    avg_response_delay_ms: int | None


def calculate_metrics(
    *,
    call_duration_ms: int,
    elder_speech: Sequence[VadSegment],
    ai_turns: Sequence[VadSegment],
    transcript: str,
    negative_stems: frozenset[str] = DEFAULT_NEGATIVE_STEMS,
) -> CallMetrics:
    # 길이 없는 구간은 재생 시간이 없으므로 AI 발화가 아니다. echo._merge가
    # 이미 같은 규칙으로 버리는데 여기서만 세면 같은 구간이 한쪽에서는 없는
    # 것이 되고 다른 쪽에서는 있는 것이 된다. 특히 응답 지연에서 이게
    # 위험한데, 길이 0인 턴의 end_ms는 재생이 '시작'된 시각이라 거기서부터
    # 재면 AI가 말한 시간까지 통째로 어르신의 지연으로 들어간다.
    ai_turns = [turn for turn in ai_turns if turn.has_duration]

    elder_ms = _total_ms(elder_speech)
    ai_ms = _total_ms(ai_turns)

    if call_duration_ms <= 0:
        speech_ratio = 0.0
        silence_ratio = 0.0
    else:
        speech_ratio = elder_ms / call_duration_ms
        # AI가 말하는 동안은 '어르신의 침묵'이 아니다.
        silence_ratio = max(0, call_duration_ms - elder_ms - ai_ms) / call_duration_ms

    return CallMetrics(
        avg_response_delay_ms=_average_response_delay(elder_speech, ai_turns),
        speech_ratio=speech_ratio,
        silence_ratio=silence_ratio,
        turn_count=len(elder_speech),
        negative_word_count=_count_stems(transcript, negative_stems),
    )


def _total_ms(segments: Sequence[VadSegment]) -> int:
    return sum(segment.duration_ms for segment in segments)


def _count_stems(transcript: str, stems: frozenset[str]) -> int:
    """어간이 실제 용언 활용(또는 알려진 명사 예외)으로 이어질 때만 센다.

    str.count는 부분 문자열이면 문맥과 상관없이 다 잡는다. "아파트"의 "아파"가
    그렇게 잡혀서 부정어로 세어지면, 아파트 얘기만 몇 번 해도 오탐 알림이
    만들어진다. 어간 뒤 글자 하나를 봐서 그게 정말 어미(또는 알려진 명사
    예외)로 이어지는지, 혹은 거기서 문장이 끝나는지를 확인한다. 무엇을
    놓치는지, 그리고 왜 그 방향의 오차를 택했는지는 DEFAULT_NEGATIVE_STEMS
    옆 주석에 적어 뒀다.
    """
    total = 0
    for stem in stems:
        exceptions = _NOUN_SUFFIX_EXCEPTIONS.get(stem, frozenset())
        start = 0
        while True:
            idx = transcript.find(stem, start)
            if idx == -1:
                break
            # str.count와 같은 방식으로 어간 길이만큼 건너뛴다(겹치는 매칭은
            # 세지 않는다) — 기존 동작(및 그걸 검증하는 회귀 테스트)과 맞추기
            # 위함이다.
            start = idx + len(stem)
            next_char = transcript[start : start + 1]
            if not _is_hangul_syllable(next_char):
                # 다음 글자가 없거나(문장 끝) 한글 음절이 아니면(공백/문장부호)
                # "아파", "아파?", "너무 힘들" 같은 해체 종결형이 이미 완결된
                # 발화라는 뜻이다 — 잘린 문장이 아니라 노인 통화에서 가장 흔한
                # 어법이다. 애매하면 놓치는 쪽(위음성)보다 세는 쪽을 택한다.
                total += 1
            elif next_char in _NEGATIVE_ENDING_STARTS or next_char in exceptions:
                total += 1
    return total


def _average_response_delay(
    elder_speech: Sequence[VadSegment], ai_turns: Sequence[VadSegment]
) -> int | None:
    """AI 발화 종료 → 어르신 발화 시작까지의 평균.

    AI 발화 뒤에 어르신 응답이 없으면(작별 인사 등, 또는 그냥 못 들은
    질문) 그 턴은 세지 않는다. 응답이 하나도 없으면 0이 아니라 None이다 —
    측정 불가와 즉답을 같은 값으로 두면 평균이 왜곡된다.

    "그 턴의 응답"은 다음 AI 발화가 시작되기 전에 시작한 발화만이다.
    그 경계가 없으면, 대답 없이 지나간 턴이 한참 뒤 다른 질문에 대한
    대답을 자기 것으로 끌어다 쓴다 — 중간의 AI 발화와 침묵을 전부 건너뛴
    시간이 그 턴의 '응답 지연'이 되는 것이다. 응답 없는 질문 하나가
    7.5초짜리 지연을 만들어 내고, 그 값은 지연 벌점 25점을 만점으로
    올린다. 멀쩡한 어르신에게 붙는, 지어낸 벌점이다.
    """
    # 시각 순서를 가정하지 않는다. VAD는 순서대로 내놓지만, 여기서 그
    # 가정이 깨지면 엉뚱한 발화가 응답으로 잡혀도 아무 신호가 없다.
    turns = sorted(ai_turns, key=lambda t: t.start_ms)
    replies = sorted(elder_speech, key=lambda s: s.start_ms)

    delays = []
    for index, turn in enumerate(turns):
        # 다음 AI 발화가 시작되면 이 턴의 응답 기회는 끝난 것이다.
        next_turn_start = (
            turns[index + 1].start_ms if index + 1 < len(turns) else None
        )
        reply = next(
            (
                s
                for s in replies
                if s.start_ms >= turn.end_ms
                and (next_turn_start is None or s.start_ms < next_turn_start)
            ),
            None,
        )
        if reply is not None:
            delays.append(reply.start_ms - turn.end_ms)
    if not delays:
        return None
    return round(sum(delays) / len(delays))


# ---------------------------------------------------------------- 위험 판정

# 각 지표가 100점 중 차지하는 몫. 합이 100이다.
_SPEECH_WEIGHT = 35
_DELAY_WEIGHT = 25
_NEGATIVE_WEIGHT = 20
_NO_ANSWER_WEIGHT = 20

# 기준선이 없을 때(첫 통화) 쓰는 절대 기준
_ABSOLUTE_HEALTHY_SPEECH_RATIO = 0.4
_ABSOLUTE_DELAY_FLOOR_MS = 2_000
_ABSOLUTE_DELAY_SPAN_MS = 4_000

# 만점에 도달하는 지점
_NEGATIVE_SATURATION = 5
_NO_ANSWER_SATURATION = 3

_WATCH_THRESHOLD = 30
_ALERT_THRESHOLD = 60


@dataclass(frozen=True)
class Baseline:
    """이 어르신의 평소 상태. 최근 통화들의 이동 평균으로 갱신된다."""

    speech_ratio: float
    avg_response_delay_ms: int


@dataclass(frozen=True)
class BaselineDelta:
    """평소 대비 변화. 절대값이 아니라 이게 판정의 실제 근거다."""

    speech_ratio: float
    avg_response_delay_ms: int | None


@dataclass(frozen=True)
class RiskAssessment:
    risk_score: int
    risk_level: str  # normal | watch | alert
    baseline_delta: BaselineDelta | None


def assess_risk(
    metrics: CallMetrics,
    *,
    baseline: Baseline | None = None,
    no_answer_recent_7: int = 0,
) -> RiskAssessment:
    """지표를 위험 점수로 환산한다.

    LLM도 난수도 시각도 개입하지 않는다. 같은 입력이면 반드시 같은 점수가
    나오며, 그게 이 서비스가 알림을 신뢰받는 근거다(설계 3.2).
    """
    score = (
        _speech_penalty(metrics, baseline)
        + _delay_penalty(metrics, baseline)
        + _clamp01(metrics.negative_word_count / _NEGATIVE_SATURATION)
        * _NEGATIVE_WEIGHT
        + _clamp01(no_answer_recent_7 / _NO_ANSWER_SATURATION) * _NO_ANSWER_WEIGHT
    )
    return RiskAssessment(
        risk_score=round(score),
        risk_level=_level_for(round(score)),
        baseline_delta=_delta(metrics, baseline),
    )


def _speech_penalty(metrics: CallMetrics, baseline: Baseline | None) -> float:
    """말수가 얼마나 줄었나. 기준선이 있으면 평소 대비, 없으면 절대 기준."""
    if baseline is not None and baseline.speech_ratio > 0:
        drop = (baseline.speech_ratio - metrics.speech_ratio) / baseline.speech_ratio
    else:
        drop = 1 - metrics.speech_ratio / _ABSOLUTE_HEALTHY_SPEECH_RATIO
    return _clamp01(drop) * _SPEECH_WEIGHT


def _delay_penalty(metrics: CallMetrics, baseline: Baseline | None) -> float:
    """대답이 얼마나 느려졌나. 측정 불가면 벌점을 주지 않는다."""
    delay = metrics.avg_response_delay_ms
    if delay is None:
        return 0.0
    if baseline is not None and baseline.avg_response_delay_ms > 0:
        rise = (delay - baseline.avg_response_delay_ms) / baseline.avg_response_delay_ms
    else:
        rise = (delay - _ABSOLUTE_DELAY_FLOOR_MS) / _ABSOLUTE_DELAY_SPAN_MS
    return _clamp01(rise) * _DELAY_WEIGHT


def _delta(metrics: CallMetrics, baseline: Baseline | None) -> BaselineDelta | None:
    if baseline is None:
        return None
    delay = metrics.avg_response_delay_ms
    return BaselineDelta(
        # 부동소수점 잔여물이 그래프와 비교에 섞이지 않게 자른다.
        speech_ratio=round(metrics.speech_ratio - baseline.speech_ratio, 4),
        avg_response_delay_ms=(
            None if delay is None else delay - baseline.avg_response_delay_ms
        ),
    )


def _level_for(score: int) -> str:
    if score >= _ALERT_THRESHOLD:
        return "alert"
    if score >= _WATCH_THRESHOLD:
        return "watch"
    return "normal"


def _clamp01(value: float) -> float:
    return min(1.0, max(0.0, value))
