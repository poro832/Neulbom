"""Amazon Polly TTS 어댑터.

boto3 클라이언트를 주입받으므로 자격 증명 없이 규약 전체가 검증된다 —
ClovaVoice가 전송 계층을 주입받는 것과 같은 자리다.
"""

import io
import logging

import pytest

from app.media.polly_voice import (
    POLLY_MAX_BILLED_CHARS,
    PollyVoice,
)

PCM = b"\x01\x02" * 400


class FakeStream:
    def __init__(self, payload: bytes):
        self._payload = payload
        self.closed = False

    def read(self) -> bytes:
        return self._payload

    def close(self) -> None:
        self.closed = True


class FakeClient:
    def __init__(self, payload: bytes = PCM, characters: int = 12):
        self.payload = payload
        self.characters = characters
        self.calls: list[dict] = []
        self.streams: list[FakeStream] = []

    def synthesize_speech(self, **kwargs):
        self.calls.append(kwargs)
        stream = FakeStream(self.payload)
        self.streams.append(stream)
        return {
            "AudioStream": stream,
            "ContentType": "audio/pcm",
            "RequestCharacters": self.characters,
        }


def make(client=None, **kwargs):
    client = client or FakeClient()
    return PollyVoice(client=client, **kwargs), client


# ------------------------------------------------------------ 요청


def test_it_asks_for_raw_pcm_not_a_container():
    """Responder 규약이 PCM16 LE다. Polly의 pcm이 바로 그 형식이라
    CLOVA Voice와 달리 헤더를 벗길 일이 없다."""
    voice, client = make()

    assert voice.synthesize("안녕하세요", 8000) == PCM
    assert client.calls[0]["OutputFormat"] == "pcm"


def test_the_sample_rate_is_sent_as_a_string():
    """Polly는 SampleRate를 문자열로 받는다. 정수를 주면 거절당한다."""
    voice, client = make()

    voice.synthesize("안녕하세요", 8000)

    assert client.calls[0]["SampleRate"] == "8000"


def test_a_rate_that_pcm_does_not_support_is_refused_before_the_call():
    """pcm은 8000과 16000만 된다. 24000은 mp3에서만 되는 값이라
    그대로 보내면 InvalidSampleRateException이 돌아온다."""
    voice, client = make()

    with pytest.raises(ValueError, match="지원하지 않는"):
        voice.synthesize("안녕하세요", 24000)

    assert client.calls == []


def test_the_voice_and_engine_are_sent():
    voice, client = make(voice_id="Jihye", engine="neural")

    voice.synthesize("안녕하세요", 8000)

    assert client.calls[0]["VoiceId"] == "Jihye"
    assert client.calls[0]["Engine"] == "neural"


def test_bracketed_text_is_removed_before_sending():
    """Polly는 CLOVA와 반대로 괄호 안을 **그대로 읽는다.**

    LLM이 "(웃음)"을 뱉으면 어르신이 "웃음"이라는 소리를 듣는다. 벤더가
    달라도 우리가 원하는 소리는 같으므로 같은 자리에서 지운다.
    """
    voice, client = make()

    voice.synthesize("(웃음) 오늘 날씨가 좋네요", 8000)

    assert client.calls[0]["Text"] == "오늘 날씨가 좋네요"


def test_text_that_is_all_brackets_is_not_sent_at_all():
    voice, client = make()

    assert voice.synthesize("(침묵)", 8000) == b""
    assert client.calls == []


def test_overlong_text_is_cut_and_reported(caplog):
    """과금 글자 수 상한을 넘기면 TextLengthExceededException으로 통째로 실패한다.

    잘라서라도 말하는 편이 낫지만, 잘랐다는 사실은 남겨야 한다.
    """
    voice, client = make()

    with caplog.at_level(logging.WARNING, logger="app.media.polly_voice"):
        voice.synthesize("가" * (POLLY_MAX_BILLED_CHARS + 50), 8000)

    assert len(client.calls[0]["Text"]) == POLLY_MAX_BILLED_CHARS
    assert caplog.records


# ------------------------------------------------------------ 응답


def test_the_billed_character_count_is_logged(caplog):
    """글자 수가 곧 요금이다. 남기지 않으면 청구서를 보고 나서야 안다."""
    voice, _ = make(client=FakeClient(characters=57))

    with caplog.at_level(logging.INFO, logger="app.media.polly_voice"):
        voice.synthesize("안녕하세요", 8000)

    assert any("57" in record.getMessage() for record in caplog.records)


def test_the_audio_stream_is_closed():
    """StreamingBody는 HTTP 연결을 물고 있다. 안 닫으면 통화마다 하나씩
    새고, 오래 도는 서버에서 연결 풀이 마른다."""
    voice, client = make()

    voice.synthesize("안녕하세요", 8000)

    assert client.streams[0].closed


def test_a_reply_without_audio_is_treated_as_silence():
    class NoAudio:
        def synthesize_speech(self, **kwargs):
            return {"RequestCharacters": 5}

    voice, _ = make(client=NoAudio())

    assert voice.synthesize("안녕하세요", 8000) == b""
