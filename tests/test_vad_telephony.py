"""전화 음질(8kHz G.711 μ-law)에서 VadSegmenter가 성립하는지 검증한다.

Twilio Media Streams는 통화 오디오를 μ-law 8kHz로 보낸다. 16kHz 깨끗한
합성 오디오에서 통과한다고 전화에서도 통과한다는 보장이 없다. 특히
  - 8kHz에서 20ms 프레임 = 160샘플
  - μ-law 8비트 양자화 잡음
  - 회선 잡음
  - 노인 음성은 대체로 작다
이 네 가지가 겹친다.
"""

import numpy as np

from app.analysis.segments import VadSegment
from app.analysis.vad_segmenter import segment_audio

TELEPHONE_RATE = 8000

# 회선 잡음 수준. 이건 발화가 아니다.
LINE_NOISE_RMS = 0.005
# 목소리가 작은 어르신. 잡음의 3배지만 절대값은 작다.
QUIET_SPEECH_RMS = 0.015


def build_audio(*spans, sample_rate=TELEPHONE_RATE, noise_rms=0.0, seed=0):
    """('speech', 500, 0.3), ('silence', 1000) → float32 샘플.

    speech 항목의 세 번째 값은 진폭(= RMS, 교번 신호이므로).
    noise_rms를 주면 전체에 회선 잡음을 얹는다.
    """
    rng = np.random.default_rng(seed)
    chunks = []
    for span in spans:
        kind, duration_ms = span[0], span[1]
        amplitude = span[2] if len(span) > 2 else 0.3
        count = int(sample_rate * duration_ms / 1000)
        chunk = np.zeros(count, dtype=np.float32)
        if kind == "speech":
            chunk[0::2] = amplitude
            chunk[1::2] = -amplitude
        chunks.append(chunk)
    audio = np.concatenate(chunks) if chunks else np.zeros(0, dtype=np.float32)
    if noise_rms > 0:
        audio = audio + rng.normal(0.0, noise_rms, len(audio)).astype(np.float32)
    return audio


# ------------------------------------------------------- μ-law 코덱
# Python 3.13에서 audioop이 제거되어 직접 구현한다. G.711의 조각별 근사가
# 아니라 해석적 압신 공식 + 8비트 양자화 — 양자화 잡음 특성을 재현하는 것이
# 목적이므로 이 정도면 충분하다.

_MU = 255.0


def mulaw_roundtrip(audio):
    """μ-law로 인코딩했다가 되돌린다. 전화망을 통과한 효과."""
    clipped = np.clip(audio, -1.0, 1.0)
    companded = np.sign(clipped) * np.log1p(_MU * np.abs(clipped)) / np.log1p(_MU)
    quantized = np.round((companded + 1.0) * 127.5).astype(np.uint8)

    expanded = quantized.astype(np.float32) / 127.5 - 1.0
    return (
        np.sign(expanded) * np.expm1(np.abs(expanded) * np.log1p(_MU)) / _MU
    ).astype(np.float32)


# ------------------------------------------------------- 기본 성립


def test_segmentation_works_at_telephone_sample_rate():
    """8kHz에서도 16kHz와 같은 경계가 나와야 한다."""
    audio = build_audio(("speech", 500), ("silence", 1000), ("speech", 500))

    result = segment_audio(audio, TELEPHONE_RATE)

    assert result.speech == [
        VadSegment(start_ms=0, end_ms=500),
        VadSegment(start_ms=1500, end_ms=2000),
    ]
    assert result.pauses == [VadSegment(start_ms=500, end_ms=1500)]


def test_mulaw_compression_keeps_silence_silent():
    """μ-law 양자화 잡음이 무음을 발화로 만들면 안 된다."""
    audio = mulaw_roundtrip(build_audio(("silence", 1000)))

    result = segment_audio(audio, TELEPHONE_RATE)

    assert result.speech == []


def test_line_noise_is_not_speech():
    """회선 잡음만 있는 구간을 발화로 세면 침묵 지표가 무너진다."""
    audio = build_audio(("silence", 1000), noise_rms=LINE_NOISE_RMS)

    result = segment_audio(audio, TELEPHONE_RATE)

    assert result.speech == []


# ------------------------------------------------------- 조용한 어르신 음성


def test_quiet_elderly_speech_is_detected():
    """목소리가 작은 어르신도 검출되어야 한다.

    잡음(0.005)의 3배인 0.015 발화를 놓치면, 정작 위험 신호를 보내는
    분들(말수가 줄고 목소리가 작아진 분들)의 지표가 통째로 빈다.
    """
    audio = build_audio(
        ("silence", 500),
        ("speech", 1000, QUIET_SPEECH_RMS),
        ("silence", 500),
        noise_rms=LINE_NOISE_RMS,
    )

    result = segment_audio(audio, TELEPHONE_RATE)

    assert result.speech == [VadSegment(start_ms=500, end_ms=1500)]


def test_quiet_speech_survives_mulaw_compression():
    audio = mulaw_roundtrip(
        build_audio(
            ("silence", 500),
            ("speech", 1000, QUIET_SPEECH_RMS),
            ("silence", 500),
            noise_rms=LINE_NOISE_RMS,
        )
    )

    result = segment_audio(audio, TELEPHONE_RATE)

    assert result.speech == [VadSegment(start_ms=500, end_ms=1500)]


def test_loud_and_quiet_speakers_are_both_detected():
    """같은 통화에 큰 목소리와 작은 목소리가 섞여도 둘 다 잡아야 한다.

    AI 안내 음성(큰 소리)과 어르신 응답(작은 소리)이 번갈아 나오는 상황이다.
    """
    audio = build_audio(
        ("speech", 400, 0.30),
        ("silence", 500),
        ("speech", 400, QUIET_SPEECH_RMS),
        noise_rms=LINE_NOISE_RMS,
    )

    result = segment_audio(audio, TELEPHONE_RATE)

    assert result.speech == [
        VadSegment(start_ms=0, end_ms=400),
        VadSegment(start_ms=900, end_ms=1300),
    ]
