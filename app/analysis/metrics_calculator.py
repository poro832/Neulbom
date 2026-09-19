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
#
# 세 번의 수정을 거치며 매번 다른 활용형에서 새 오탐/누락이 나왔다(아파트
# 오탐 → 해체 종결형 누락 → 합니다체 누락 → 과거형/ㄹ탈락 누락). 그때그때
# 지적받은 사례만 패치하는 방식은 수렴하지 않는다는 게 분명해져서, 방식을
# 바꿨다: 6개 표현(아프다/힘들다/외롭다/귀찮다/죽겠다/우울하다) 각각에 대해
# 해체·해요체·합니다체·과거·연결형(-고/-지만)·관형형·문장 종결(어간에서
# 그냥 끝남)·존댓말, 8가지 활용을 전부 나열하고 실제로 어떤 문자열이
# 만들어지는지 손으로 적은 다음(사람이 말하듯이 — 코드를 거꾸로 돌려서
# 만든 게 아니라), 그 표를 그대로 tests/test_metrics_calculator.py의
# 데이터 기반 테스트(NEGATIVE_CONJUGATION_MATRIX)로 옮겼다. 이 사전과
# 아래 화이트리스트/예외 목록은 그 표를 통과시키는 데 필요한 만큼만 채운
# 결과다 — 화이트리스트를 넓혀서 우연히 통과되게 만든 게 아니라, 표의 각
# 칸이 왜 그런 문자열이 되는지(불규칙 활용 포함)를 먼저 설명한 뒤 채웠다.
#
# 목록에 "힘듭", "힘드", "힘든", "아픈", "외롭"처럼 사전적으로는 활용형인
# 것도 별도 항목으로 들어 있는 이유: 불규칙 활용(ㄹ탈락, ㅂ불규칙)이나
# 관형형화는 어미가 바뀌는 게 아니라 어간 자체의 글자를 완전히 다른
# 음절로 바꾼다.
#   - "힘들"+"습니다" → "힘듭니다" (ㄹ 탈락 + ㅂ, "들"이 사라지고 "듭")
#   - "힘들"+"네요"   → "힘드네요" (ㄴ 앞에서도 ㄹ 탈락, "들"이 사라지고 "드")
#   - "힘들"+"ㄴ"(관형형) → "힘든 하루" ("들"+ㄴ이 아예 새 음절 "든"으로 fuse)
#   - "아프"+"ㄴ"(관형형) → "아픈 다리" (마찬가지로 "프"+ㄴ이 "픈"으로 fuse)
#   - "외롭"+자음 어미(-습니다/-고/-지) → "외롭습니다"("로"가 아니라 애초에
#     "외롭"이 자음 어미 앞의 표면형이다. 모음 어미 앞에서만 "외로+워/운")
# 이런 경우는 어간 뒤에 아무리 좋은 어미 목록을 붙여도 못 잡는다 — 찾고
# 있는 문자열 자체가 전사에 없기 때문이다. 형태소 분석기 없이 고칠 수 있는
# 정직한 방법은 그 불규칙 표면형을 사전에 통째로 추가하는 것뿐이다(사전
# 확장이지 패턴 매칭 확장이 아니다).
DEFAULT_NEGATIVE_STEMS = frozenset(
    {
        "아프", "아파", "아팠", "아픕", "아픈",
        "힘들", "힘드", "힘듭", "힘든",
        "외로", "외롭",
        "귀찮", "죽겠", "우울",
    }
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
# "아파트"의 "트", "아프리카"의 "리", "아프간"의 "간"과, 이번에 추가한
# "힘드"/"힘든"/"아픈"/"외롭" 어간이 새로 노출하는 다른 낱말과의 우연한
# 충돌도 전부 이 화이트리스트로 걸러야 한다 — 조사한 범위에서 이 새 어간들과
# 무관한 일반 명사는 찾지 못했지만, 못 찾았다는 사실이 곧 없다는 뜻은
# 아니므로 테스트에서는 실제 충돌 대신 "화이트리스트에 없는 글자가 뒤에
# 오면 여전히 걸러지는가"라는 메커니즘 자체를 확인해 둔다.
#
# 존댓말(-시-/-세요/-셨어요/-십니다)은 의도적으로 세지 않는다 — 사고가 아니라
# 결정이다. 이 시스템은 어르신 쪽 발화만 전사한다. 어르신이 자기 자신의
# 상태를 존댓말 주체 높임으로 말하는 일은 한국어에서 거의 없다 — "아버님이
# 아프셨어요", "그이가 많이 힘드세요"처럼 존댓말 활용은 통화 상대인
# 배우자·부모 같은 제3자의 상태를 전하는 문장에서 나온다. 그건 어르신
# 본인의 위험 신호가 아니므로 세지 않는 게 맞다고 판단했다. 그래서 시/셔/셨/
# 세/십 계열은 화이트리스트에 절대 넣지 않는다 — "안 넣었다"가 "잊었다"가
# 아니라 "넣지 않기로 했다"라는 뜻이다.
#
# 다만 "우울" 하나는 이 결정을 어미 화이트리스트만으로는 지킬 수 없었다.
# "우울하고"/"우울하지만"/"우울하다"(평서)와 "우울하세요"/"우울하시네요"
# (존댓말)가 전부 "우울"+"하"로 시작해서, 다음 글자 하나만 보면 구분이
# 안 된다. 그래서 "하"는 예외 목록이 아니라 _TRANSPARENT_NEXT_CHARS에
# 넣어 "하" 다음 글자를 한 번 더 본다 — "하"+(화이트리스트에 있는 글자)면
# 평서형으로 세고, "하"+"시/세/셨" 같은 존댓말 글자면 세지 않는다. 자세한
# 동작은 _count_stems 안에 있다.
#
# 이 설계 전체의 잔여 오차는 위음성 쪽으로 치우쳐 있다 — 정직하게 말하면 이렇다.
# "어간 뒤 글자가 한글이 아니거나 없으면 센다"는 규칙은 어간 문자열이 실제로
# 전사에 살아남았을 때만 작동한다. 그 문자열 자체가 불규칙 활용으로 지워지면
# 이 규칙이 개입할 기회조차 없다 — 화이트리스트를 아무리 넓혀도 없는 문자열은
# 못 찾는다. 그래서 "애매하면 센다"는 국소 규칙과 별개로, 이 시스템의 진짜
# 위험은 언제나 위음성 쪽이다: 어르신이 새로운 활용형으로 말했는데 그 표면형이
# 아직 사전에 없으면 조용히 놓친다. 위양성(멀쩡한데 잡음)은 보호자가 통화를
# 들어보면 바로 해소되는 성가심이지만, 위음성은 이 서비스가 존재하는 이유
# 자체를 무력화하므로 항상 위음성 쪽을 더 두려워해야 한다.
#
# 그래도 이 방법이 놓치는 것 — 정직하게 적어 둔다:
# 1) 아직 사전에 없는 불규칙 표면형이나 활용형. 매트릭스 테스트로 8가지
#    활용 x 6개 표현을 조사했지만, 간접 인용("-다더라"), 방언, "-으오"체,
#    이중 과거("-았었-") 같은 드문 활용은 다루지 않는다.
# 2) "외로우면"/"외로우니"처럼 "외로"+모음 어미 "우"로 시작하는 비존댓말
#    연결형. "우"를 화이트리스트에 넣지 않은 건 존댓말 "외로우세요"와
#    다음 글자만으로 구분이 안 돼서인데(위 "하"와 같은 문제), "우울"의
#    "하"처럼 2단계 확인을 아직 만들지 않아서 이 연결형까지 같이 걸러진다
#    — 알고 있는 미해결 구멍이다.
# 3) "죽겠다"는 이미 "겠"(추측/의지 어미)이 굳어 있는 관용 표현이라 자연스러운
#    과거형이나 관형형이 따로 없다("죽겠었다", "죽겠는" 모두 부자연스럽다) —
#    매트릭스에서 이 두 칸은 "해당 없음"으로 비워 뒀다.
# 4) 다음 글자가 한글 음절인데 화이트리스트/어간별 목록에 없는 새로운 활용형이나
#    새 충돌 명사. 이 목록들은 지금 가진 어간들의 실제 활용형을 조사해서
#    채운 것이라 완전하지 않다.
# 5) 어미가 아니라 명사 접미사가 붙어도 진짜 부정 신호인 경우 — 대표적으로
#    "우울증"의 "증". 순수 어미 규칙만 쓰면 이것도 걸러지는데, 진단명은 놓치면
#    안 되는 신호라서 _NOUN_SUFFIX_EXCEPTIONS로 어간별 예외를 따로 둔다. 이
#    예외 목록도 마찬가지로 지금 알려진 것만 담았다 — "귀찮음"처럼 또 다른
#    파생 명사가 있다면 아직 못 잡는다.
_NEGATIVE_ENDING_STARTS = frozenset(
    {
        "다", "요", "네", "어", "아", "고", "니", "지", "워", "웠", "습",
        "면", "겠", "잖", "구", "던", "은", "운", "았", "었",
    }
)

# 어미 규칙으로는 못 잡는, 그러나 진짜 부정 신호인 어간별 추가 목록(직접
# 허용). "우울"은 규칙 활용(-다/-어/-네...)이 아니라 "하다"가 그대로 붙는
# 형용사(우울하다)라 해/했이 필요하고, 명사형 "우울증"과 관형형 "우울한"도
# 여기 넣는다. "합"은 "하"+"ㅂ니다"가 합쳐진 별개의 완성 음절이라("하다"류
# 형용사가 전부 이렇게 합니다체를 만든다) 화이트리스트가 아니라 여기 넣었다
# — "우울합니다"를 잡기 위함이다. 바로 아래 "하"가 없는 이유는
# _TRANSPARENT_NEXT_CHARS 설명을 보라 — 존댓말과 다음 글자 하나로 구분이
# 안 돼서 여기서 뺐다.
_NOUN_SUFFIX_EXCEPTIONS: dict[str, frozenset[str]] = {
    "우울": frozenset({"증", "해", "했", "한", "합"}),
}

# 어간별 "투명한" 다음 글자 — 그 글자 자체는 답이 아니고, 그 글자 다음
# 글자를 다시 봐야 평서형인지 존댓말인지 알 수 있는 경우다. "우울"+"하"가
# 유일하다: "우울하고/하지/하다/하네"(평서, 세야 함)와 "우울하세요/하시네요"
# (존댓말, 세면 안 됨)가 전부 "하"로 시작해서 한 글자로는 구분이 안 된다.
# "하" 다음 글자가 (없거나 한글이 아니거나) 어미 화이트리스트에 있으면
# 평서형으로 보고 세고, "시/세/셨"처럼 화이트리스트에 없는 한글이면
# 존댓말로 보고 세지 않는다.
_TRANSPARENT_NEXT_CHARS: dict[str, frozenset[str]] = {
    "우울": frozenset({"하"}),
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

    # 어르신 발화도 같은 규칙으로 거른다. 뒤집힌 구간이 들어오면 _total_ms가
    # 음수가 되어 speech_ratio가 음수, silence_ratio가 1을 넘는다 — 비율로서
    # 불가능한 값이라 그 위에서 계산하는 위험 점수가 의미를 잃는다. 길이 0인
    # 구간은 발화 턴 수만 공짜로 올린다. 실제 경로에서는 segment_audio가
    # min_speech_ms로 먼저 걸러 주지만, 이 함수는 직접 호출도 받는다.
    elder_speech = [segment for segment in elder_speech if segment.has_duration]

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
        transparent = _TRANSPARENT_NEXT_CHARS.get(stem, frozenset())
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
            if _is_negative_ending(next_char):
                total += 1
            elif next_char in exceptions:
                total += 1
            elif next_char in transparent:
                # "하"처럼 그 글자 자체로는 평서형/존댓말을 못 가른다. 한
                # 글자 더 보고 같은 규칙(문장 끝/비한글이면 완결, 화이트리스트에
                # 있으면 평서형)을 적용한다 — 존댓말 글자(시/세/셨)는 이
                # 화이트리스트에 없으므로 자연히 걸러진다.
                if _is_negative_ending(transcript[start + 1 : start + 2]):
                    total += 1
    return total


def _is_negative_ending(next_char: str) -> bool:
    """다음 글자가 문장의 끝(또는 비한글)이거나 어미 화이트리스트에 있는가.

    빈 문자열/비한글(공백, 문장부호 등)은 그 자체로 완결된 발화로 본다 —
    "무릎이 아파", "아파?"가 잘린 문장이 아니라 흔한 해체 종결형이라서다.
    """
    if not next_char or not _is_hangul_syllable(next_char):
        return True
    return next_char in _NEGATIVE_ENDING_STARTS


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

# 이 숫자들 중 하나라도 바꾸면 이전 점수와 비교할 수 없다 — 어제 42점과
# 오늘 42점이 다른 뜻이 된다. 결과에 함께 남겨서 나중에 구분할 수 있게 한다
# (db/schema.sql의 call_metrics.calculator_version).
CALCULATOR_VERSION = "1.0.0"


@dataclass(frozen=True)
class Baseline:
    """이 어르신의 평소 상태. 최근 통화들의 이동 평균으로 갱신된다.

    avg_response_delay_ms가 None인 것은 "평소 지연을 모른다"는 뜻이다. 기준선을
    만들 통화는 모였는데 그 전부에서 어르신이 한 번도 응답하지 않으면 그렇게
    된다 — 실제로 일어나고, 그 자체가 위험 신호다.

    0으로 채우면 안 된다. _delay_penalty는 `> 0` 가드에 걸려 절대 기준으로
    넘어가므로 무사하지만, _delta가 `delay - 0`을 계산해서 "평소보다 1.2초
    느려졌다"는 거짓을 보호자에게 낸다. 평소가 얼마인지 모르는데도.
    """

    speech_ratio: float
    avg_response_delay_ms: int | None


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
    baseline_delay = None if baseline is None else baseline.avg_response_delay_ms
    if baseline_delay is not None and baseline_delay > 0:
        rise = (delay - baseline_delay) / baseline_delay
    else:
        rise = (delay - _ABSOLUTE_DELAY_FLOOR_MS) / _ABSOLUTE_DELAY_SPAN_MS
    return _clamp01(rise) * _DELAY_WEIGHT


def _delta(metrics: CallMetrics, baseline: Baseline | None) -> BaselineDelta | None:
    if baseline is None:
        return None
    delay = metrics.avg_response_delay_ms
    baseline_delay = baseline.avg_response_delay_ms
    return BaselineDelta(
        # 부동소수점 잔여물이 그래프와 비교에 섞이지 않게 자른다.
        speech_ratio=round(metrics.speech_ratio - baseline.speech_ratio, 4),
        # 어느 한쪽이라도 모르면 델타는 없다. 0으로 적으면 거짓이 된다.
        avg_response_delay_ms=(
            None
            if delay is None or baseline_delay is None
            else delay - baseline_delay
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
