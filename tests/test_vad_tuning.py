"""시끄러운 현장에서 실시간 말 감지를 서버 재배포 없이 조일 수 있다(환경 변수)."""

from __future__ import annotations

import logging

import numpy as np
import pytest

from app.analysis.vad_segmenter import DEFAULT_NOISE_FACTOR, adaptive_threshold
from app.media.session import vad_settings_from_env
from app.media.streaming_vad import StreamingVad

SAMPLE_RATE = 16000
ENV_NAMES = (
    "STREAM_VAD_NOISE_FACTOR",
    "STREAM_VAD_NOISE_FLOOR",
    "STREAM_VAD_MIN_SPEECH_MS",
    "STREAM_VAD_END_OF_TURN_MS",
    "STREAM_VAD_NOISE_TRACKING",
)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in ENV_NAMES:
        monkeypatch.delenv(name, raising=False)


def audio(*spans, noise_rms=0.0, seed=1):
    rng = np.random.default_rng(seed)
    chunks = []
    for kind, duration_ms, amplitude in spans:
        count = int(SAMPLE_RATE * duration_ms / 1000)
        chunk = np.zeros(count, dtype=np.float32)
        if kind == "speech":
            chunk[0::2] = amplitude
            chunk[1::2] = -amplitude
        chunks.append(chunk)
    out = np.concatenate(chunks)
    if noise_rms:
        out = out + rng.normal(0.0, noise_rms, len(out)).astype(np.float32)
    return out


def feed(vad, samples):
    events = []
    for start in range(0, len(samples) - vad.frame_length + 1, vad.frame_length):
        event = vad.push(samples[start : start + vad.frame_length])
        if event is not None:
            events.append(event)
    return events


# ---------------------------------------------------------------- 환경 변수


def test_without_settings_the_defaults_are_untouched():
    assert vad_settings_from_env() == {}


def test_valid_settings_are_read(monkeypatch):
    monkeypatch.setenv("STREAM_VAD_NOISE_FACTOR", "4")
    monkeypatch.setenv("STREAM_VAD_MIN_SPEECH_MS", "350")
    monkeypatch.setenv("STREAM_VAD_END_OF_TURN_MS", "1000")
    monkeypatch.setenv("STREAM_VAD_NOISE_FLOOR", "0.015")

    assert vad_settings_from_env() == {
        "noise_factor": 4.0,
        "min_speech_ms": 350,
        "end_of_turn_ms": 1000,
        "noise_floor": 0.015,
    }


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("STREAM_VAD_NOISE_FACTOR", "abc"),
        ("STREAM_VAD_NOISE_FACTOR", "0.5"),  # 너무 낮으면 소음이 전부 말이 된다
        ("STREAM_VAD_NOISE_FACTOR", "50"),  # 너무 높으면 말을 하나도 못 잡는다
        ("STREAM_VAD_MIN_SPEECH_MS", "-1"),
        ("STREAM_VAD_MIN_SPEECH_MS", "99999"),
        ("STREAM_VAD_END_OF_TURN_MS", "10"),
        ("STREAM_VAD_NOISE_FLOOR", "5"),
    ],
)
def test_a_bad_value_falls_back_to_the_default_and_warns(monkeypatch, caplog, name, value):
    monkeypatch.setenv(name, value)

    with caplog.at_level(logging.WARNING, logger="app.media.session"):
        assert vad_settings_from_env() == {}

    assert name in caplog.text


def test_blank_values_are_ignored(monkeypatch):
    monkeypatch.setenv("STREAM_VAD_MIN_SPEECH_MS", "  ")

    assert vad_settings_from_env() == {}


# ---------------------------------------------------------------- 실제로 둔해지는가


def test_the_threshold_formula_still_defaults_to_the_shared_values():
    frames = np.full(100, 0.01, dtype=np.float32)

    assert adaptive_threshold(frames) == adaptive_threshold(
        frames, noise_factor=DEFAULT_NOISE_FACTOR
    )
    assert adaptive_threshold(frames, noise_factor=5.0) > adaptive_threshold(frames)


def test_a_short_burst_of_noise_is_not_a_turn_when_min_speech_is_raised():
    burst = audio(("silence", 1000, 0), ("speech", 200, 0.3), ("silence", 1500, 0))

    assert len(feed(StreamingVad(SAMPLE_RATE), burst)) == 1  # 기본(100ms)은 말로 센다
    assert feed(StreamingVad(SAMPLE_RATE, min_speech_ms=350), burst) == []  # 올리면 버린다


def test_real_speech_is_still_a_turn_when_min_speech_is_raised():
    talk = audio(("silence", 1000, 0), ("speech", 900, 0.3), ("silence", 1500, 0))

    assert len(feed(StreamingVad(SAMPLE_RATE, min_speech_ms=350), talk)) == 1


def test_a_higher_noise_factor_ignores_moderate_background_voices():
    """잡음 바닥 위로 조금 튀는 배경 소리는 올린 배율에서는 말이 아니다."""
    sound = audio(
        ("silence", 3000, 0),  # 현장 잡음 바닥(아래에서 더해진다)
        ("speech", 600, 0.03),  # 바닥의 3배쯤 되는 배경 사람 소리
        ("silence", 1500, 0),
        noise_rms=0.01,
    )

    # 잡음 추적 방식에서 배율만 비교한다(기본 방식은 계속 시끄러운 곳에서 처음부터 말로 센다)
    assert len(feed(StreamingVad(SAMPLE_RATE, noise_tracking=True), sound)) == 1
    assert feed(StreamingVad(SAMPLE_RATE, noise_tracking=True, noise_factor=6.0), sound) == []


def test_a_detected_turn_reports_how_loud_it_was_for_tuning():
    talk = audio(("silence", 1000, 0), ("speech", 900, 0.3), ("silence", 1500, 0))

    (turn,) = feed(StreamingVad(SAMPLE_RATE), talk)

    assert turn.mean_rms == pytest.approx(0.3, rel=0.05)
    assert turn.threshold > 0
    assert turn.mean_rms > turn.threshold  # 말은 임계값 위에 있다


# ---------------------------------------------------------------- 잡음 추적 방식 (계속 시끄러운 곳)


def test_in_steady_noise_the_default_method_swallows_the_noise_before_the_speech():
    """문제의 재현: 계속 시끄러운 곳에서는 통화 시작부터 말이 끝나지 않는 턴이 생긴다."""
    sound = audio(("silence", 3000, 0), ("speech", 1200, 0.05), ("silence", 2500, 0), noise_rms=0.01)

    (turn,) = feed(StreamingVad(SAMPLE_RATE), sound)

    assert turn.start_ms == 0  # 앞의 3초 잡음이 말에 붙었다


def test_noise_tracking_starts_the_turn_when_the_speech_really_starts():
    sound = audio(("silence", 3000, 0), ("speech", 1200, 0.05), ("silence", 2500, 0), noise_rms=0.01)

    (turn,) = feed(StreamingVad(SAMPLE_RATE, noise_tracking=True), sound)

    assert 2900 <= turn.start_ms <= 3100
    assert 4100 <= turn.end_ms <= 4300


def test_noise_tracking_hears_quiet_speech_over_noise():
    sound = audio(("silence", 3000, 0), ("speech", 1200, 0.03), ("silence", 2500, 0), noise_rms=0.01)

    (turn,) = feed(StreamingVad(SAMPLE_RATE, noise_tracking=True), sound)

    assert 2900 <= turn.start_ms <= 3100


def test_noise_tracking_does_not_cut_a_long_sentence_in_the_middle():
    sound = audio(("silence", 1000, 0), ("speech", 8000, 0.05), ("silence", 2000, 0), noise_rms=0.01)

    (turn,) = feed(StreamingVad(SAMPLE_RATE, noise_tracking=True), sound)

    assert turn.end_ms >= 8900  # 한 문장이 끝까지 한 턴이다


def test_steady_noise_alone_is_never_speech_with_tracking():
    sound = audio(("silence", 10_000, 0), noise_rms=0.01)

    assert feed(StreamingVad(SAMPLE_RATE, noise_tracking=True), sound) == []


def test_when_the_noise_gets_louder_for_good_the_turn_is_closed_and_the_new_level_becomes_the_floor():
    """TV를 켠 것처럼 소음이 한 단계 올라서 임계값을 넘은 채 굳으면, 말로 센 채 영원히 열려 있지 않는다."""
    sound = audio(
        ("silence", 3000, 0),
        ("silence", 6000, 0),  # 아래에서 소음 세기를 구간별로 바꾼다
        ("speech", 1000, 0.15),
        ("silence", 2500, 0),
        noise_rms=0.01,
    )
    louder = sound.copy()
    start = int(SAMPLE_RATE * 3.0)
    stop = int(SAMPLE_RATE * 9.0)
    rng = np.random.default_rng(7)
    louder[start:stop] += rng.normal(0.0, 0.04, stop - start).astype(np.float32)

    vad = StreamingVad(SAMPLE_RATE, noise_tracking=True, max_turn_ms=3000)
    events = feed(vad, louder)

    assert events, "굳은 소음도 어딘가에서 턴이 닫혀야 한다"
    assert all(e.end_ms - e.start_ms <= 3100 for e in events[:-1])
    # 새 소음 바닥 위로 올라온 진짜 말은 여전히 잡힌다
    assert events[-1].start_ms >= 9000 - 200


# ---------------------------------------------------------------- 환경 변수 (추적 방식)


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on"])
def test_noise_tracking_can_be_switched_on(monkeypatch, value):
    monkeypatch.setenv("STREAM_VAD_NOISE_TRACKING", value)

    assert vad_settings_from_env() == {"noise_tracking": True}


@pytest.mark.parametrize("value", ["", "0", "false", "off", "no"])
def test_noise_tracking_stays_off_by_default_or_when_told(monkeypatch, value):
    monkeypatch.setenv("STREAM_VAD_NOISE_TRACKING", value)

    assert vad_settings_from_env() == {}


def test_an_unknown_tracking_value_stays_off_and_warns(monkeypatch, caplog):
    monkeypatch.setenv("STREAM_VAD_NOISE_TRACKING", "maybe")

    with caplog.at_level(logging.WARNING, logger="app.media.session"):
        assert vad_settings_from_env() == {}

    assert "STREAM_VAD_NOISE_TRACKING" in caplog.text
