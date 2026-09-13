"""오디오에서 발화 구간과 침묵 구간을 뽑는다 (설계 4장).

프레임별 RMS 에너지를 임계값과 비교하는 규칙 기반 VAD다. 외부 서비스에
의존하지 않으므로 합성 오디오만으로 전부 테스트된다.

두 산출물의 쓰임이 다르다.
  - speech : FillerDetector 경로 B의 입력 (발화인데 단어가 없으면 삼켜진 필러)
  - pauses : 계약 5.3의 pauses / pause_count / pause_total_ms
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from app.analysis.segments import VadSegment

DEFAULT_FRAME_MS = 20

# 임계값을 고정하면 전화 음질에서 목소리가 작은 어르신을 통째로 놓친다.
# 잡음 바닥을 추정해 상대적으로 정한다.
#
#   임계값 = max(NOISE_FLOOR, 잡음바닥 × NOISE_FACTOR)
#
# NOISE_FLOOR는 회선 잡음(약 0.005)보다 위, 작은 목소리(약 0.015)보다 아래.
# 통화 전체가 잡음뿐인 경우를 발화로 오인하지 않으려면 절대 하한이 필요하다.
DEFAULT_NOISE_FLOOR = 0.008
DEFAULT_NOISE_FACTOR = 2.5
# 통화 전체가 발화면 하위 백분위도 발화 수준이 된다. 잡음 추정이 피크를
# 따라 올라가 자기 발화를 지워버리지 않도록 상한을 둔다.
_NOISE_PEAK_CAP = 0.3
# 이보다 짧은 정적은 음절 사이 공백으로 보고 발화에 흡수한다.
DEFAULT_MIN_SILENCE_MS = 300
# 이보다 짧은 발화는 클릭음·잡음으로 보고 버린다.
DEFAULT_MIN_SPEECH_MS = 100


@dataclass(frozen=True)
class VadResult:
    speech: list[VadSegment]
    pauses: list[VadSegment]


def segment_audio(
    samples: Sequence[float] | np.ndarray,
    sample_rate: int,
    frame_ms: int = DEFAULT_FRAME_MS,
    rms_threshold: float | None = None,
    min_silence_ms: int = DEFAULT_MIN_SILENCE_MS,
    min_speech_ms: int = DEFAULT_MIN_SPEECH_MS,
) -> VadResult:
    speech = _speech_segments(samples, sample_rate, frame_ms, rms_threshold)
    # 순서가 중요하다. 먼저 잇고 나서 거른다 — 반대로 하면 짧은 공백으로 나뉜
    # 조각들이 각각 기준 미달로 버려져 발화 전체가 사라진다.
    speech = _bridge_short_gaps(speech, min_silence_ms)
    speech = [s for s in speech if s.end_ms - s.start_ms >= min_speech_ms]
    return VadResult(speech=speech, pauses=_pauses_between(speech))


def _bridge_short_gaps(speech: list[VadSegment], min_silence_ms: int) -> list[VadSegment]:
    """기준보다 짧은 정적으로 갈라진 발화를 하나로 잇는다."""
    merged: list[VadSegment] = []
    for segment in speech:
        if merged and segment.start_ms - merged[-1].end_ms < min_silence_ms:
            merged[-1] = VadSegment(merged[-1].start_ms, segment.end_ms)
        else:
            merged.append(segment)
    return merged


def _speech_segments(
    samples: Sequence[float] | np.ndarray,
    sample_rate: int,
    frame_ms: int,
    rms_threshold: float | None,
) -> list[VadSegment]:
    audio = np.asarray(samples, dtype=np.float32)
    frame_length = int(sample_rate * frame_ms / 1000)
    frame_count = len(audio) // frame_length
    if frame_count == 0:
        return []

    frames = audio[: frame_count * frame_length].reshape(frame_count, frame_length)
    frame_rms = np.sqrt(np.mean(frames**2, axis=1))
    threshold = (
        _adaptive_threshold(frame_rms) if rms_threshold is None else rms_threshold
    )
    is_speech = frame_rms >= threshold

    segments: list[VadSegment] = []
    start_frame: int | None = None
    for index, voiced in enumerate(is_speech):
        if voiced and start_frame is None:
            start_frame = index
        elif not voiced and start_frame is not None:
            segments.append(_segment(start_frame, index, frame_ms))
            start_frame = None
    if start_frame is not None:
        segments.append(_segment(start_frame, frame_count, frame_ms))
    return segments


def _pauses_between(speech: list[VadSegment]) -> list[VadSegment]:
    """발화와 발화 사이의 정적만 침묵으로 센다.

    말을 시작하기 전이나 끝낸 뒤의 정적은 '답변 중의 침묵'이 아니므로 제외한다.
    """
    return [
        VadSegment(start_ms=earlier.end_ms, end_ms=later.start_ms)
        for earlier, later in zip(speech, speech[1:])
    ]


def _segment(start_frame: int, end_frame: int, frame_ms: int) -> VadSegment:
    return VadSegment(start_ms=start_frame * frame_ms, end_ms=end_frame * frame_ms)


def _adaptive_threshold(frame_rms: np.ndarray) -> float:
    """잡음 바닥을 추정해 임계값을 정한다.

    하위 백분위를 잡음으로 보되, 통화 전체가 발화인 경우 잡음 추정이
    발화 수준까지 올라가 스스로를 지우므로 피크 대비 상한을 씌운다.
    """
    if frame_rms.size == 0:
        return DEFAULT_NOISE_FLOOR
    quiet = float(np.percentile(frame_rms, 10))
    peak = float(np.percentile(frame_rms, 95))
    noise = min(quiet, peak * _NOISE_PEAK_CAP)
    return max(DEFAULT_NOISE_FLOOR, noise * DEFAULT_NOISE_FACTOR)
