"""어르신이 채팅에서 한 위급한 말 찾기 — **AI가 아니라 정해 둔 표현 목록(규칙)이 한다.**

같은 말에는 항상 같은 결과가 나와야 보호자가 알림을 믿는다(전화 점수와 같은 원칙). 모델은 대화만 한다.

이것은 의료 응급을 가려내는 장치가 아니다. 놓치는 말이 있을 수 있고, 평소와 다른 말을 보호자께
알리는 안전망일 뿐이다. 반대로 아닌 말을 잡는 일(예: "어지러운 이야기를 TV에서 봤어")도 있다 — 알림은
어르신당 하루 한 번으로 묶어 두었으므로 그 대가는 작다.

공백을 모두 지우고 찾는다("가슴이 아파요", "가슴이아파요", "가슴 이 아파"를 같게). 부정("안 아파요")은
표현 사이에 '안'이 끼어 목록에 걸리지 않는다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

MEDICAL = "medical"
FALL = "fall"
SELF_HARM = "self_harm"
HELP = "help"

# "너무 아파요"처럼 강조하는 말은 끼어도 같은 말이다. '안'은 여기 없다 — 부정은 걸리지 않아야 한다.
_INT = r"(너무|많이|엄청|정말|진짜|갑자기|자꾸|계속|좀|몹시|심하게)?"

# (분류, 공백을 지운 글에서 찾을 정규식). 위에 있는 것이 먼저 잡힌다 — 가장 급한 분류를 앞에 둔다.
_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    (SELF_HARM, re.compile(r"죽고싶|죽을래|죽어버리|목숨을?끊|자살|살기싫|사라지고싶")),
    (HELP, re.compile(r"119|구급차|응급(실|상황)?|살려(줘|주세요|줘요|요)|도와(줘|주세요|줘요)")),
    (FALL, re.compile(r"넘어졌|넘어져서|넘어졌어|미끄러졌|낙상|일어나지못|일어날수없|못일어나")),
    (
        MEDICAL,
        re.compile(
            rf"가슴(이|을|가)?{_INT}(아프|아파|아픕|답답|조여|조이|쥐어|뻐근)"
            rf"|심장(이|을|가)?{_INT}(아프|아파|아픕|두근|멎|멈|터질)"
            rf"|숨(이|을|도)?{_INT}(차|찹|가빠|가쁘|안쉬|못쉬|막혀|막히|쉬기힘)"
            r"|쓰러(졌|질|지겠|져|짐)|정신(을|이)?(잃|못차|가물)|의식(이|을)?(없|잃)"
            r"|어지러(워|운|움|웠|우|워서)|어지럽(다|네|고|습니다|구)"
            r"|피(를|가)?(토|쏟|많이나)|토(했|하고|할것)"
            r"|마비|(말이|말을)(안나|못하)|한쪽(팔|다리|이|손)?(이)?(안움직|힘이없|저려)"
        ),
    ),
)


@dataclass(frozen=True)
class UrgentMatch:
    category: str  # medical | fall | self_harm | help


def detect_urgent(text: str) -> UrgentMatch | None:
    """위급한 표현이 있으면 분류를, 없으면 None."""
    squeezed = re.sub(r"\s+", "", text or "")
    if not squeezed:
        return None
    for category, pattern in _RULES:
        if pattern.search(squeezed):
            return UrgentMatch(category)
    return None


# AI 답 뒤에 **서버가 직접 붙이는** 안내. 모델이 빠뜨려도 이 말은 반드시 나간다.
_NOTICE = {
    SELF_HARM: (
        "많이 힘드시군요. 혼자 견디지 마시고 자살예방상담전화 109(24시간)나 119에 전화하시거나 "
        "가족에게 바로 연락해 주세요. 가족분께도 알려 드릴게요."
    ),
    FALL: "다치셨다면 움직이지 마시고 119에 전화하시거나 가족에게 바로 연락해 주세요. 가족분께도 알려 드릴게요.",
    HELP: "급하시면 119에 전화하시거나 가족에게 바로 연락해 주세요. 가족분께도 알려 드릴게요.",
    MEDICAL: "많이 불편하시면 참지 마시고 119에 전화하시거나 가족에게 바로 연락해 주세요. 가족분께도 알려 드릴게요.",
}


def safety_notice(category: str) -> str:
    return _NOTICE.get(category, _NOTICE[MEDICAL])


# 보호자에게 가는 알림 문구. 어르신이 한 말을 싣지 않는다 — 위험을 알리는 것과 대화 내용을 보여 주는 것을 나눈다.
GUARDIAN_ALERT_MESSAGE = "채팅에서 위급할 수 있는 표현이 있었어요. 직접 연락해 보세요."
