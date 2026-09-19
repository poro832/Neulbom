"""통화가 끝난 직후 한 번 도는 후처리 (전화망 설계 2장 ⑦).

CallSession(매체)과 analyze_call(분석)은 서로를 모른다 — 그래야 분석이
소켓 없이 재현된다. 둘을 잇는 배선만 여기에 둔다.

transcript는 빈 문자열이다. STT가 아직 없어서 통화 중 발화를 글로 만드는
곳이 이 프로젝트에 존재하지 않는다. 지어낸 문장을 넣으면 negative_word_count가
거짓이 되고, 그 숫자는 위험 점수에 20점으로 들어간다 — 측정하지 않은 것은
0으로 둔다(없는 것과 세지 않은 것은 다르지만, 여기서는 둘 다 "부정어를
발견하지 못했다"이고 점수를 올리지 않는 쪽이라 안전하다).
"""

from __future__ import annotations

import logging
from dataclasses import replace
from pathlib import Path

from app.analysis.call_analysis import (
    DEGRADED_FABRICATED_SILENCE,
    DEGRADED_UNMATCHED_MARKS,
    CallAnalysis,
    analyze_call,
)
from app.media.session import CallSession

logger = logging.getLogger(__name__)

# 녹음의 이만큼이 유실을 메운 침묵이면 지표를 그대로 믿기 어렵다.
# clip 쪽과 같은 관례를 쓴다(call_analysis.DEGRADED_CLIP_RATIO).
DEGRADED_FABRICATED_RATIO = 0.3


def analyze_session(
    session: CallSession, wav_path: Path, transcript: str = ""
) -> CallAnalysis:
    """끝난 세션의 녹음을 분석한다.

    스트리밍 중 나온 VAD 판정은 쓰지 않는다. 프레임 도착 타이밍에 따라
    달라지기 때문이다 — wav 전체에 배치 VAD를 다시 돌린다(설계 3.2).
    세션에서 가져오는 것은 타이밍에 좌우되지 않는 두 가지뿐이다: mark
    왕복으로 확정된 AI 발화 구간과, 녹음 길이에서 구한 스트림 시간.
    """
    analysis = analyze_call(
        wav_path=wav_path,
        ai_turns=session.ai_turns,
        stream_duration_ms=session.stream_duration_ms,
        transcript=transcript,
    )

    fabricated = session.filled_gap_ms
    duration = session.stream_duration_ms
    # 판정에 쓰든 안 쓰든 원본은 남긴다 — 녹음이 30일 뒤 사라지면 통신
    # 품질이 이 통화의 지표에 얼마나 개입했는지 다시 볼 방법이 없다.
    analysis = replace(analysis, filled_gap_ms=fabricated)
    if duration > 0 and fabricated / duration > DEGRADED_FABRICATED_RATIO:
        # 녹음의 상당 부분이 우리가 채운 침묵이다. 분모(stream_duration_ms)에는
        # 들어가는데 분자(발화)에는 안 들어가므로 발화 비율이 아래로 끌린다 —
        # 지어낸 값이 그대로 발화 벌점 35점 쪽으로 간다. 숫자를 안 내는 대신
        # 근거가 줄었다고 정직하게 표시한다(설계 8장).
        logger.warning(
            "지어낸 침묵이 많다 — degraded로 표시한다 call_id=%s filled=%dms duration=%dms",
            session.call_id,
            fabricated,
            duration,
        )
        analysis = replace(
            analysis,
            degraded_reasons=analysis.degraded_reasons
            + (DEGRADED_FABRICATED_SILENCE,),
        )

    if session.unmatched_marks:
        # 짝이 안 맞은 표식은 AI 발화 구간 하나를 통째로 잃었다는 뜻이다.
        # 그 구간은 에코 제거에서도 빠지고(어르신 발화가 부풀려진다) 응답
        # 지연 계산에서도 빠진다. 숫자는 나오지만 근거가 줄었으므로 실패가
        # 아니라 '정확도 낮음'으로 표시한다(설계 8장).
        logger.warning(
            "짝이 안 맞은 표식이 있다 — degraded로 표시한다 call_id=%s count=%d",
            session.call_id,
            session.unmatched_marks,
        )
        analysis = replace(
            analysis,
            degraded_reasons=analysis.degraded_reasons + (DEGRADED_UNMATCHED_MARKS,),
        )

    return analysis
