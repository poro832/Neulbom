"""통화 중 "지금 말이 끝났나?"만 답하는 VAD (앱 통화 설계 2장).

배치 VadSegmenter와 나눠 둔 이유가 있다. 스트리밍 판정은 프레임 도착
타이밍에 따라 달라지므로, 이 결과를 위험 지표에 쓰면 설계 3.2의 재현성이
깨진다. 지표는 통화가 끝난 뒤 녹음 전체에 segment_audio를 다시 돌려 낸다.

임계값 공식은 배치와 공유한다(adaptive_threshold). 다만 배치는 전체 신호의
백분위를 쓰는데 스트리밍에는 아직 오지 않은 오디오가 있으므로, 최근
window_ms만 들고 매 프레임 다시 계산한다.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

import numpy as np

from app.analysis.vad_segmenter import (
    DEFAULT_FRAME_MS,
    DEFAULT_MIN_SPEECH_MS,
    adaptive_threshold,
)

# 잡음 바닥을 추정할 구간. 짧으면 발화 한 번에 윈도우가 가득 차고,
# 길면 환경 변화(TV가 켜짐)를 늦게 따라간다.
DEFAULT_WINDOW_MS = 3000

# 음절 사이 공백(300ms)보다 충분히 길어야 말을 자르지 않는다.
# 어르신은 천천히, 중간에 쉬면서 말씀하신다.
DEFAULT_END_OF_TURN_MS = 800


@dataclass(frozen=True)
class SpeechEnded:
    """한 턴의 발화가 끝났다. 시각은 통화 시작을 0으로 한다."""

    start_ms: int
    end_ms: int


class StreamingVad:
    def __init__(
        self,
        sample_rate: int,
        frame_ms: int = DEFAULT_FRAME_MS,
        window_ms: int = DEFAULT_WINDOW_MS,
        end_of_turn_ms: int = DEFAULT_END_OF_TURN_MS,
        min_speech_ms: int = DEFAULT_MIN_SPEECH_MS,
    ) -> None:
        self._frame_ms = frame_ms
        self._frame_length = int(sample_rate * frame_ms / 1000)
        self._end_of_turn_frames = max(1, end_of_turn_ms // frame_ms)
        self._min_speech_ms = min_speech_ms
        self._rms_window: deque[float] = deque(maxlen=max(1, window_ms // frame_ms))

        self._frame_index = 0
        self._speech_start: int | None = None
        self._last_voiced: int | None = None
        self._silence_run = 0

    @property
    def frame_length(self) -> int:
        return self._frame_length

    @property
    def frame_ms(self) -> int:
        return self._frame_ms

    def push(self, frame: np.ndarray) -> SpeechEnded | None:
        # 길이가 어긋나면 RMS는 일부만 반영되는데 _frame_index는 그대로
        # 한 틱 전진해, 이후 모든 SpeechEnded 시각이 조용히 밀린다.
        if len(frame) != self._frame_length:
            raise ValueError(
                f"frame 길이가 {self._frame_length}이어야 하는데 {len(frame)}다"
            )
        rms = float(np.sqrt(np.mean(np.asarray(frame, dtype=np.float32) ** 2)))
        self._rms_window.append(rms)
        threshold = adaptive_threshold(
            np.asarray(self._rms_window, dtype=np.float32)
        )

        ended: SpeechEnded | None = None
        if rms >= threshold:
            if self._speech_start is None:
                self._speech_start = self._frame_index
            self._last_voiced = self._frame_index
            self._silence_run = 0
        elif self._speech_start is not None:
            self._silence_run += 1
            if self._silence_run >= self._end_of_turn_frames:
                ended = self._close_turn()

        self._frame_index += 1
        return ended

    def _close_turn(self) -> SpeechEnded | None:
        """턴을 닫는다. 너무 짧으면 클릭음으로 보고 버린다.

        end_of_turn_ms보다 짧은 정적은 애초에 여기 오지 않으므로, 배치가
        _bridge_short_gaps로 먼저 잇고 나서 거르는 순서가 여기서도 지켜진다.
        """
        assert self._speech_start is not None and self._last_voiced is not None
        start_ms = self._speech_start * self._frame_ms
        end_ms = (self._last_voiced + 1) * self._frame_ms

        self._speech_start = None
        self._last_voiced = None
        self._silence_run = 0

        if end_ms - start_ms < self._min_speech_ms:
            return None
        return SpeechEnded(start_ms=start_ms, end_ms=end_ms)
