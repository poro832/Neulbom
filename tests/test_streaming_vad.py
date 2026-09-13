"""StreamingVad — 프레임을 순서대로 받아 발화 종료를 알린다 (앱 통화 설계 2장).

배치 VadSegmenter와 목적이 다르다. 이쪽은 "지금 말이 끝났나?"만 빠르게
답하면 되고, 정확한 구간은 통화가 끝난 뒤 배치가 다시 낸다. 그래서
근사여도 되지만, 대신 아직 도착하지 않은 오디오의 백분위를 쓸 수 없다.
최근 3초만 들고 같은 공식을 다시 계산한다.
"""

import numpy as np

from app.media.streaming_vad import SpeechEnded, StreamingVad

SAMPLE_RATE = 16000
FRAME_MS = 20

# 회선 잡음 수준. 이건 발화가 아니다.
NOISE_RMS = 0.005
# 목소리가 작은 어르신. 잡음의 3배지만 절대값은 작다.
QUIET_SPEECH_RMS = 0.015


def build_audio(*spans, sample_rate=SAMPLE_RATE, noise_rms=0.0, seed=0):
    """('speech', 500, 0.3), ('silence', 1000) → float32 샘플.

    speech 항목의 세 번째 값은 진폭(= RMS, 교번 신호이므로).
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


def feed(vad, audio):
    """오디오를 프레임 단위로 밀어넣고 나온 이벤트를 모은다."""
    events = []
    length = vad.frame_length
    for start in range(0, len(audio) - length + 1, length):
        event = vad.push(audio[start : start + length])
        if event is not None:
            events.append(event)
    return events


def test_silence_only_yields_no_event():
    vad = StreamingVad(SAMPLE_RATE)

    assert feed(vad, build_audio(("silence", 2000))) == []


def test_line_noise_alone_is_not_speech():
    """잡음만 흐르는데 응답하면 어르신은 혼자 떠드는 AI를 듣게 된다."""
    vad = StreamingVad(SAMPLE_RATE)
    audio = build_audio(("silence", 3000), noise_rms=NOISE_RMS)

    assert feed(vad, audio) == []


def test_speech_then_long_silence_ends_the_turn():
    vad = StreamingVad(SAMPLE_RATE)
    audio = build_audio(("speech", 1000), ("silence", 1000))

    assert feed(vad, audio) == [SpeechEnded(start_ms=0, end_ms=1000)]


def test_short_gap_inside_speech_does_not_end_the_turn():
    """음절 사이 300ms 공백에서 끊고 들어가면 말을 자르게 된다."""
    vad = StreamingVad(SAMPLE_RATE)
    audio = build_audio(
        ("speech", 500), ("silence", 300), ("speech", 500), ("silence", 1000)
    )

    assert feed(vad, audio) == [SpeechEnded(start_ms=0, end_ms=1300)]


def test_quiet_elderly_voice_is_detected():
    """8kHz에서 찾은 그 버그의 16kHz 형제.

    고정 임계값이면 잡음의 3배인 작은 목소리를 통째로 놓친다.
    """
    vad = StreamingVad(SAMPLE_RATE)
    audio = build_audio(
        ("silence", 600),
        ("speech", 1000, QUIET_SPEECH_RMS),
        ("silence", 1000),
        noise_rms=NOISE_RMS,
    )

    events = feed(vad, audio)

    assert len(events) == 1
    assert events[0].start_ms == 600
    assert events[0].end_ms == 1600


def test_continuous_speech_does_not_erase_itself():
    """윈도우가 발화로 가득 차도 잡음 추정이 발화까지 올라가면 안 된다.

    _NOISE_PEAK_CAP이 스트리밍에서도 도는지 확인한다.
    """
    vad = StreamingVad(SAMPLE_RATE)
    audio = build_audio(("speech", 6000), ("silence", 1000))

    assert feed(vad, audio) == [SpeechEnded(start_ms=0, end_ms=6000)]


def test_click_shorter_than_min_speech_is_discarded():
    """60ms짜리 클릭음에 AI가 대꾸하면 안 된다."""
    vad = StreamingVad(SAMPLE_RATE)
    audio = build_audio(("silence", 200), ("speech", 60), ("silence", 1000))

    assert feed(vad, audio) == []


def test_two_turns_are_reported_separately():
    vad = StreamingVad(SAMPLE_RATE)
    audio = build_audio(
        ("speech", 500),
        ("silence", 1000),
        ("speech", 500),
        ("silence", 1000),
    )

    assert feed(vad, audio) == [
        SpeechEnded(start_ms=0, end_ms=500),
        SpeechEnded(start_ms=1500, end_ms=2000),
    ]
