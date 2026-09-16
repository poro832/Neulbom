"""AI 재생 구간을 어르신 발화에서 잘라낸다 (전화망 설계 3.4).

어르신 트랙에 AI 음성이 되울려 들어오면 발화 비율이 부풀려진다. AI가
언제 재생됐는지는 mark로 알고 있으므로(설계 3.2) 그 구간을 뺀다.

barge-in(어르신이 AI 말을 끊고 들어옴)도 같이 잘린다. 구별할 방법이 없고,
4주 범위에서는 지표를 부풀리는 쪽이 비우는 쪽보다 위험해 자르는 쪽을 택한다.
잘린 양이 크면 degraded로 표시한다.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from app.analysis.segments import VadSegment


@dataclass(frozen=True)
class ClipResult:
    segments: list[VadSegment]
    # 잘라낸 총량. 크면 에코가 심하거나 어르신이 자주 끊고 들어온 것이다.
    clipped_ms: int


def clip_ai_playback(
    elder: Sequence[VadSegment], ai_turns: Sequence[VadSegment]
) -> ClipResult:
    blocked = _merge(ai_turns)

    kept: list[VadSegment] = []
    clipped = 0
    for segment in elder:
        remaining = [segment]
        for block in blocked:
            nxt: list[VadSegment] = []
            for piece in remaining:
                nxt.extend(_subtract(piece, block))
            remaining = nxt
        kept.extend(remaining)
        clipped += (segment.end_ms - segment.start_ms) - sum(
            piece.end_ms - piece.start_ms for piece in remaining
        )

    return ClipResult(segments=kept, clipped_ms=clipped)


def _merge(turns: Sequence[VadSegment]) -> list[VadSegment]:
    """겹친 구간을 합친다. 안 합치면 겹친 만큼 clipped_ms가 두 번 세어진다."""
    merged: list[VadSegment] = []
    for turn in sorted(turns, key=lambda t: t.start_ms):
        if merged and turn.start_ms <= merged[-1].end_ms:
            last = merged[-1]
            merged[-1] = VadSegment(last.start_ms, max(last.end_ms, turn.end_ms))
        else:
            merged.append(turn)
    return merged


def _subtract(piece: VadSegment, block: VadSegment) -> list[VadSegment]:
    """한 구간에서 다른 구간을 뺀다. 가운데가 잘리면 둘로 나뉜다."""
    if block.end_ms <= piece.start_ms or block.start_ms >= piece.end_ms:
        return [piece]

    parts: list[VadSegment] = []
    if piece.start_ms < block.start_ms:
        parts.append(VadSegment(piece.start_ms, block.start_ms))
    if block.end_ms < piece.end_ms:
        parts.append(VadSegment(block.end_ms, piece.end_ms))
    return parts
