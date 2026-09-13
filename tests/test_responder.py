"""Responder — 발화를 받아 응답 오디오를 돌려주는 자리.

골격에서는 고정 응답이다. CLOVA는 NCP 이용 신청이 끝나면 같은 규약으로
갈아끼운다. 규약을 먼저 세워 두는 이유가 그것이다.
"""

import numpy as np

from app.media.responder import CannedResponder, beep

SAMPLE_RATE = 16000


def test_beep_length_matches_duration():
    """PCM16 mono이므로 샘플당 2바이트."""
    pcm = beep(duration_ms=100, sample_rate=SAMPLE_RATE)

    assert len(pcm) == int(SAMPLE_RATE * 0.1) * 2


def test_beep_is_not_silence():
    pcm = beep(duration_ms=100, sample_rate=SAMPLE_RATE)
    samples = np.frombuffer(pcm, dtype="<i2")

    assert np.abs(samples).max() > 0


def test_canned_responder_cycles_through_clips():
    """응답이 매번 같으면 통화가 기계처럼 들린다."""
    responder = CannedResponder([b"\x01\x00", b"\x02\x00"])
    audio = np.zeros(320, dtype=np.float32)

    first = responder.respond(audio, SAMPLE_RATE)
    second = responder.respond(audio, SAMPLE_RATE)
    third = responder.respond(audio, SAMPLE_RATE)

    assert (first, second, third) == (b"\x01\x00", b"\x02\x00", b"\x01\x00")


def test_canned_responder_without_clips_returns_nothing():
    responder = CannedResponder([])
    audio = np.zeros(320, dtype=np.float32)

    assert responder.respond(audio, SAMPLE_RATE) == b""
