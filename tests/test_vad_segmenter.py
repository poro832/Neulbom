"""VadSegmenter — 오디오에서 발화/침묵 구간을 뽑는다 (설계 4장).

발화 구간은 FillerDetector의 경로 B 입력이 되고, 침묵 구간은 계약 5.3의
pauses / pause_count / pause_total_ms가 된다.

합성 오디오로 전부 검증한다 — 실제 녹음도 AWS도 필요 없다.
"""

import numpy as np

from app.analysis.vad_segmenter import VadSegment, segment_audio

SAMPLE_RATE = 16000


def build_audio(*spans, sample_rate=SAMPLE_RATE):
    """('speech', 500), ('silence', 1000) → float32 샘플 배열."""
    chunks = []
    for kind, duration_ms in spans:
        count = int(sample_rate * duration_ms / 1000)
        if kind == "speech":
            # ±0.3 교번 → RMS 0.3. 무음(0.0)과 확실히 구분된다.
            chunk = np.empty(count, dtype=np.float32)
            chunk[0::2] = 0.3
            chunk[1::2] = -0.3
        else:
            chunk = np.zeros(count, dtype=np.float32)
        chunks.append(chunk)
    return np.concatenate(chunks) if chunks else np.zeros(0, dtype=np.float32)


def test_all_silence_yields_no_speech_and_no_pauses():
    result = segment_audio(build_audio(("silence", 1000)), SAMPLE_RATE)

    assert result.speech == []
    assert result.pauses == []


def test_continuous_speech_is_a_single_segment():
    result = segment_audio(build_audio(("speech", 1000)), SAMPLE_RATE)

    assert result.speech == [VadSegment(start_ms=0, end_ms=1000)]
    assert result.pauses == []


def test_speech_silence_speech_yields_two_segments_and_one_pause():
    result = segment_audio(
        build_audio(("speech", 500), ("silence", 1000), ("speech", 500)),
        SAMPLE_RATE,
    )

    assert result.speech == [
        VadSegment(start_ms=0, end_ms=500),
        VadSegment(start_ms=1500, end_ms=2000),
    ]
    assert result.pauses == [VadSegment(start_ms=500, end_ms=1500)]


def test_leading_and_trailing_silence_are_not_pauses():
    """말을 시작하기 전 정적은 '답변 중의 침묵'이 아니다 — 리포트에서 빼야 한다."""
    result = segment_audio(
        build_audio(("silence", 500), ("speech", 1000), ("silence", 500)),
        SAMPLE_RATE,
    )

    assert result.speech == [VadSegment(start_ms=500, end_ms=1500)]
    assert result.pauses == []


def test_empty_audio_yields_nothing():
    result = segment_audio(build_audio(), SAMPLE_RATE)

    assert result.speech == []
    assert result.pauses == []


# ------------------------------------------------------------ 평활화


def test_short_dip_inside_speech_does_not_split_it():
    """음절 사이 미세 공백까지 침묵으로 세면 가짜 pause가 쏟아진다."""
    result = segment_audio(
        build_audio(("speech", 500), ("silence", 60), ("speech", 500)),
        SAMPLE_RATE,
    )

    assert result.speech == [VadSegment(start_ms=0, end_ms=1060)]
    assert result.pauses == []


def test_dip_longer_than_threshold_does_split_speech():
    result = segment_audio(
        build_audio(("speech", 500), ("silence", 400), ("speech", 500)),
        SAMPLE_RATE,
    )

    assert result.speech == [
        VadSegment(start_ms=0, end_ms=500),
        VadSegment(start_ms=900, end_ms=1400),
    ]
    assert result.pauses == [VadSegment(start_ms=500, end_ms=900)]


def test_blip_shorter_than_min_speech_is_ignored():
    """클릭음·마이크 툭 치는 소리를 발화로 세지 않는다."""
    result = segment_audio(
        build_audio(("silence", 500), ("speech", 40), ("silence", 500)),
        SAMPLE_RATE,
    )

    assert result.speech == []
    assert result.pauses == []
