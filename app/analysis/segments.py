"""분석 모듈들이 공유하는 시간 구간 타입.

VadSegmenter가 만들고 FillerDetector가 소비하므로 한쪽이 다른 쪽을 import하면
의존 방향이 어색해진다. 양쪽 모두 여기서 가져온다.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class VadSegment:
    """발화 또는 침묵으로 판정된 시간 구간."""

    start_ms: int
    end_ms: int
