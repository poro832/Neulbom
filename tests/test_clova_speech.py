"""CLOVA Speech 단문 인식 어댑터.

ClovaVoice와 같은 패턴 — 전송 계층을 주입받으므로 키 없이도 규약 전체가
검증된다.
"""

import io
import json
import logging
import wave

import numpy as np
import pytest

from app.media.clova_speech import (
    STT_MAX_SECONDS,
    ClovaSpeech,
)


def tone(seconds: float, sample_rate: int = 8000, amplitude: float = 0.5):
    count = int(sample_rate * seconds)
    return np.full(count, amplitude, dtype=np.float32)


class FakeTransport:
    def __init__(self, reply: bytes):
        self.reply = reply
        self.calls: list[tuple[str, dict, bytes]] = []

    def __call__(self, url: str, *, headers: dict, content: bytes, timeout: float) -> bytes:
        self.calls.append((url, headers, content))
        return self.reply


def reply_of(text="안녕하세요", quota=15):
    return json.dumps({"text": text, "quota": quota}).encode()


def make(reply=None, **kwargs):
    transport = FakeTransport(reply if reply is not None else reply_of())
    stt = ClovaSpeech(
        invoke_url="https://example.test/external/v1/1234/abcd",
        secret_key="SECRET",
        transport=transport,
        **kwargs,
    )
    return stt, transport


def sent_audio(transport):
    """보낸 바디를 wav로 읽어 되돌린다."""
    _, _, content = transport.calls[0]
    with wave.open(io.BytesIO(content), "rb") as source:
        return source, source.readframes(source.getnframes())


# ------------------------------------------------------------ 요청 형식


def test_it_posts_to_the_domains_recognition_path():
    stt, transport = make()

    stt.transcribe(tone(1.0), 8000)

    url, _, _ = transport.calls[0]
    assert url == "https://example.test/external/v1/1234/abcd/recog/v1/stt?lang=Kor"


def test_the_secret_key_goes_in_the_clovaspeech_header():
    """Voice와 헤더 이름이 다르다. 섞어 쓰면 401이 나는데 원인이 안 보인다."""
    stt, transport = make()

    stt.transcribe(tone(1.0), 8000)

    _, headers, _ = transport.calls[0]
    assert headers["X-CLOVASPEECH-API-KEY"] == "SECRET"
    assert headers["Content-Type"] == "application/octet-stream"


def test_the_audio_is_wrapped_in_a_wav_container():
    """raw PCM은 지원 목록에 없다. 헤더 없이 보내면 인식이 통째로 실패한다."""
    stt, transport = make()

    stt.transcribe(tone(0.5), 8000)

    source, frames = sent_audio(transport)
    assert source.getframerate() == 8000
    assert source.getnchannels() == 1
    assert source.getsampwidth() == 2
    assert len(frames) == 8000 * 2 // 2  # 0.5초 × 8000샘플 × 2바이트


def test_float_audio_becomes_int16_without_wrapping_around():
    """범위를 넘는 값을 그냥 곱하면 정수가 뒤집혀 소리가 찢어진다.

    VAD가 넘겨주는 오디오는 정규화돼 있지만, 잘린 구간 경계에서 1을 살짝
    넘는 표본이 나올 수 있다. 그때 -32768로 돌아 버리면 그 프레임만
    폭발음이 되고, 인식은 그 구간을 통째로 잃는다.
    """
    stt, transport = make()

    stt.transcribe(np.array([1.5, -1.5, 0.0], dtype=np.float32), 8000)

    _, frames = sent_audio(transport)
    samples = np.frombuffer(frames, dtype="<i2")
    assert samples.tolist() == [32767, -32767, 0]


# ------------------------------------------------------------ 응답


def test_the_recognised_text_comes_back():
    stt, _ = make(reply=reply_of("무릎이 아파요"))

    assert stt.transcribe(tone(1.0), 8000) == "무릎이 아파요"


def test_a_reply_without_text_is_treated_as_not_understood():
    """빈 문자열은 ConversationResponder가 '못 알아들었다'로 읽는다 —
    그쪽에서 되묻기가 돈다. 여기서 예외를 던지면 그 경로가 안 산다."""
    stt, _ = make(reply=json.dumps({"quota": 15}).encode())

    assert stt.transcribe(tone(1.0), 8000) == ""


def test_a_broken_reply_does_not_raise():
    """사업자가 JSON이 아닌 걸 돌려줘도 통화는 이어져야 한다."""
    stt, _ = make(reply=b"<html>oops</html>")

    assert stt.transcribe(tone(1.0), 8000) == ""


def test_the_billed_quota_is_logged(caplog):
    """15초 단위로 과금된다 — 3초 발화도 15초다.

    턴이 짧고 잦은 대화라 이 반올림이 비용을 지배한다. 로그에 남기지
    않으면 청구서를 보고 나서야 알게 된다.
    """
    stt, _ = make(reply=reply_of(quota=30))

    with caplog.at_level(logging.INFO, logger="app.media.clova_speech"):
        stt.transcribe(tone(1.0), 8000)

    assert any("30" in record.getMessage() for record in caplog.records)


# ------------------------------------------------------------ 경계


def test_silence_is_not_sent_at_all():
    """빈 오디오를 보내도 15초가 과금된다. 보낼 이유가 없다."""
    stt, transport = make()

    assert stt.transcribe(np.zeros(0, dtype=np.float32), 8000) == ""
    assert transport.calls == []


def test_audio_longer_than_the_limit_is_cut_and_reported(caplog):
    """단문 인식은 60초까지다. 넘겨 보내면 요청이 통째로 실패한다.

    자르면 뒷부분을 잃지만, 실패하면 그 턴 전체를 잃는다.
    """
    stt, transport = make()

    with caplog.at_level(logging.WARNING, logger="app.media.clova_speech"):
        stt.transcribe(tone(STT_MAX_SECONDS + 5), 8000)

    source, frames = sent_audio(transport)
    assert source.getnframes() == 8000 * STT_MAX_SECONDS
    assert caplog.records
