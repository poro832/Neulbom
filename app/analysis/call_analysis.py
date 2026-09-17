"""통화 후 분석 — 녹음에서 지표까지 (전화망 설계 2장 ⑦).

통화 중 스트리밍 VAD가 낸 판정은 여기에 들어오지 않는다. 프레임 도착
타이밍에 따라 달라지기 때문이다. 지표는 저장된 wav 전체에 배치 VAD를
다시 돌려 낸다(설계 3.2).

이 모듈에는 네트워크도 LLM도 시계도 없다. 그래서 같은 입력이면 반드시
같은 숫자가 나온다.
"""

from __future__ import annotations

import wave
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from app.analysis.echo import clip_ai_playback
from app.analysis.metrics_calculator import CallMetrics, calculate_metrics
from app.analysis.segments import VadSegment
from app.analysis.vad_segmenter import segment_audio

# 어르신 발화의 이만큼이 AI 재생 구간과 겹쳤다면 지표를 그대로 믿기 어렵다.
DEGRADED_CLIP_RATIO = 0.3

_INT16_FULL_SCALE = 32768.0


@dataclass(frozen=True)
class CallAnalysis:
    metrics: CallMetrics
    clipped_ms: int
    # 실패가 아니라 "정확도 낮음"이다. 이전 두 주제에서 가져온 관례.
    degraded: bool


def analyze_call(
    *,
    wav_path: Path,
    ai_turns: Sequence[VadSegment],
    stream_duration_ms: int,
    transcript: str,
) -> CallAnalysis:
    samples, sample_rate = _read_wav(wav_path)
    detected = segment_audio(samples, sample_rate).speech

    # 스피커폰이면 AI 음성이 어르신 트랙으로 되울려 들어온다. 그걸 어르신
    # 발화로 세면 발화 비율이 부풀려진다(설계 3.4).
    clipped = clip_ai_playback(detected, ai_turns)

    # 길이가 있는 구간만 남긴다. 판정은 VadSegment.has_duration 하나를 쓴다 —
    # 같은 규칙을 여기서 다시 손으로 쓰면(전에 그랬다) AI 발화 쪽과 어르신
    # 발화 쪽이 갈라지고, 길이 0인 "구간"이 turn_count에 공짜로 +1을 더하거나
    # 뒤집힌 구간이 음수 길이로 들어와 speech_ratio를 음수로 만든다.
    # clip_ai_playback은 겹치는 AI 구간이 없으면 입력을 그대로 통과시키므로,
    # 배치 배선이 이 지점 하나뿐인 지금 막을 곳도 여기다.
    segments = [s for s in clipped.segments if s.has_duration]

    # detected에도 같은 규칙을 건다. 여기만 빼면 뒤집힌 구간 하나가 음수
    # 길이로 합계에 들어가 detected_ms를 0 이하로 끌어내리고, 그러면 아래
    # degraded 판정이 통째로 꺼진다 — 정확도가 낮은 통화가 조용히 '정상'이
    # 되어 보호자에게 그대로 나간다.
    detected_ms = sum(s.duration_ms for s in detected if s.has_duration)
    degraded = (
        detected_ms > 0 and clipped.clipped_ms / detected_ms > DEGRADED_CLIP_RATIO
    )

    return CallAnalysis(
        metrics=calculate_metrics(
            call_duration_ms=stream_duration_ms,
            elder_speech=segments,
            ai_turns=list(ai_turns),
            transcript=transcript,
        ),
        clipped_ms=clipped.clipped_ms,
        degraded=degraded,
    )


def _read_wav(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as wav:
        frames = wav.readframes(wav.getnframes())
        sample_rate = wav.getframerate()
    samples = np.frombuffer(frames, dtype="<i2").astype(np.float32)
    return samples / _INT16_FULL_SCALE, sample_rate
