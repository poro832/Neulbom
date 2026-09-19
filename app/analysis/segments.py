"""분석 모듈들이 공유하는 시간 구간 타입.

VadSegmenter가 만들고 FillerDetector가 소비하므로 한쪽이 다른 쪽을 import하면
의존 방향이 어색해진다. 양쪽 모두 여기서 가져온다.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class VadSegment:
    """발화 또는 침묵으로 판정된 시간 구간."""

    start_ms: int
    end_ms: int

    @property
    def duration_ms(self) -> int:
        return self.end_ms - self.start_ms

    @property
    def has_duration(self) -> bool:
        """길이가 있는가. 길이 없는 구간은 어느 소비자에게도 구간이 아니다.

        판정을 여기 두는 이유는 소비자마다 다르게 판단했기 때문이다. 에코
        제거는 길이 0인 AI 발화를 버리는데 지표 계산은 그대로 세어서, 같은
        구간이 한쪽에서는 없는 것이고 다른 쪽에서는 있는 것이 됐다. 규칙이
        한 군데 있어야 두 쪽이 갈라지지 않는다.
        """
        return self.end_ms > self.start_ms


def merge_overlapping(segments: Sequence[VadSegment]) -> list[VadSegment]:
    """겹친 구간을 합쳐 시작 시각 순으로 돌려준다. 길이 없는 구간은 버린다.

    has_duration과 같은 이유로 여기 있다. 에코 제거는 겹친 AI 구간을 합쳐서
    썼는데(안 합치면 겹친 만큼 clipped_ms가 두 번 세어진다) 지표 계산은
    그냥 더했다. 그래서 같은 구간이 한쪽에서는 9초, 다른 쪽에서는 12초였다.

    지표 쪽에서 이게 특히 위험했다. 부풀려진 AI 시간이 분모(어르신이 말할
    수 있었던 시간)를 깎고, 심하면 0 이하로 만들어 발화 비율을 0.0으로
    접는다. 0.0은 "측정 불가"가 아니라 "말을 안 했다"로 읽히므로 멀쩡한
    통화에 발화 벌점 35점이 그대로 붙는다 — 아무 오류도 없이.
    """
    merged: list[VadSegment] = []
    for segment in sorted(segments, key=lambda s: s.start_ms):
        if not segment.has_duration:
            continue
        if merged and segment.start_ms <= merged[-1].end_ms:
            last = merged[-1]
            merged[-1] = VadSegment(last.start_ms, max(last.end_ms, segment.end_ms))
        else:
            merged.append(segment)
    return merged


def clip_to_window(
    segments: Sequence[VadSegment], start_ms: int, end_ms: int
) -> list[VadSegment]:
    """구간을 [start_ms, end_ms] 안으로 자른다. 밖으로 나간 부분은 버린다.

    통화 창 밖의 소리는 그 통화의 발화가 아니다. 감추려고 자르는 게 아니라,
    세는 대상을 창 안으로 한정하는 것이다.

    실제로 어긋나는 경로가 있다. stream_duration_ms는 녹음 바이트 수를 정수
    나눗셈해서 구하므로 내림되는데, VAD는 wav 전체를 보므로 마지막 구간이
    끝을 몇 ms 넘길 수 있다. 짧은 통화에서는 그게 비율을 1 너머로 밀어내고,
    스키마의 CHECK (speech_ratio BETWEEN 0 AND 1)에 걸려 결과가 통째로
    버려진다 — 점수가 틀리는 게 아니라 아예 남지 않는다.
    """
    clipped: list[VadSegment] = []
    for segment in segments:
        piece = VadSegment(
            max(segment.start_ms, start_ms), min(segment.end_ms, end_ms)
        )
        if piece.has_duration:
            clipped.append(piece)
    return clipped
