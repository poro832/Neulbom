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
