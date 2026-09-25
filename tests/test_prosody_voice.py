"""Prosody(휴멜로 DIVE) TTS 어댑터.

네트워크를 타지 않는다. 전송 계층을 주입받으므로 키 없이도 규약 전체가
검증된다 — ClovaVoice/PollyVoice와 같은 패턴이다.

**이 파일이 특히 지키는 것:** DIVE는 `outputFormat`에 모르는 값이 오면
거절하는 대신 조용히 `wav_48000`으로 바꾼다(API 문서). 그러면 48kHz wav가
PCM16 8kHz인 척 파이프라인에 들어가고, 어르신은 잡음을 듣는데 우리 쪽에는
아무 오류도 남지 않는다. 응답 헤더 대조가 그걸 막는 유일한 장치다.
"""

import logging

import pytest

from app.media.prosody_voice import (
    DIVE_URL,
    TTS_MAX_CHARS,
    TTS_MAX_PIECE_CHARS,
    ProsodyVoice,
)

KEY = "test-api-key"
VOICE = "시아"

PCM = b"\x01\x02" * 400


class FakeTransport:
    """무엇을 요청받았는지 기록하고 미리 정한 바이트를 돌려준다."""

    def __init__(self, reply: bytes = PCM, *, output_format: str | None = None) -> None:
        self.reply = reply
        self.output_format = output_format
        self.calls: list[dict] = []

    def __call__(self, url, *, headers, json, timeout):
        self.calls.append(
            {"url": url, "headers": headers, "json": json, "timeout": timeout}
        )
        fmt = self.output_format or json["outputFormat"]
        return self.reply, {"X-Prosody-Output-Format": fmt}


def voice(transport=None, **over):
    return ProsodyVoice(
        KEY, voice_name=VOICE, transport=transport or FakeTransport(), **over
    )


# ------------------------------------------------------------ 요청의 모양


def test_it_asks_for_raw_pcm_at_the_requested_rate():
    """pcm_8000은 헤더 없는 PCM16 LE라 규약이 요구하는 것과 정확히 같다.

    wav를 받으면 RIFF를 풀어야 하고, ulaw를 받으면 다른 어댑터와 형식이
    달라진다. 둘 다 이 자리에서 할 일이 아니다.
    """
    transport = FakeTransport()

    voice(transport).synthesize("안녕하세요", 8000)

    sent = transport.calls[0]["json"]
    assert sent["outputFormat"] == "pcm_8000"
    assert sent["rawData"] is True


def test_it_goes_to_the_dive_endpoint_with_the_key_in_a_header():
    transport = FakeTransport()

    voice(transport).synthesize("안녕하세요", 8000)

    call = transport.calls[0]
    assert call["url"] == DIVE_URL
    assert call["headers"]["X-API-Key"] == KEY
    assert call["headers"]["Content-Type"] == "application/json"


def test_the_preset_voice_and_emotion_are_sent():
    transport = FakeTransport()

    voice(transport, emotion="happy").synthesize("안녕하세요", 8000)

    sent = transport.calls[0]["json"]
    assert sent["mode"] == "preset"
    assert sent["voiceName"] == VOICE
    assert sent["emotion"] == "happy"
    assert sent["lang"] == "ko"


def test_the_sentence_silence_is_always_sent_explicitly():
    """문장 사이 무음은 업체가 AI 오디오 **안에** 넣는다(기본 0.4초). 그 길이가
    AI 발화 길이에 들어가고, 그게 지표의 분모다. 기본값에 맡기면 업체가
    기본값을 바꾸는 날 우리 점수가 조용히 움직인다."""
    transport = FakeTransport()

    voice(transport, sentence_silence_seconds=0.6).synthesize("안녕하세요", 8000)

    assert transport.calls[0]["json"]["sentenceSilenceSec"] == 0.6


def test_speed_pitch_volume_are_sent_even_at_their_defaults():
    """같은 이유다. 어느 설정이 어느 통화를 만들었는지가 점수의 전제다."""
    transport = FakeTransport()

    voice(transport).synthesize("안녕하세요", 8000)

    sent = transport.calls[0]["json"]
    assert sent["speed"] == 1.0
    assert sent["pitch"] == 0
    assert sent["volume"] == 50


# ------------------------------------------------------------ 조용히 틀리는 경로


def test_a_mismatched_output_format_in_the_response_is_an_error():
    """DIVE는 모르는 outputFormat을 거절하지 않고 wav_48000으로 바꾼다.

    오타 하나로 48kHz wav가 PCM16 8kHz인 척 들어온다. 예외가 없으면
    어르신이 잡음을 듣고 우리 로그는 깨끗하다.
    """
    transport = FakeTransport(output_format="wav_48000")

    with pytest.raises(ValueError, match="pcm_8000"):
        voice(transport).synthesize("안녕하세요", 8000)


def test_a_missing_output_format_header_is_also_an_error():
    """헤더가 없으면 무엇을 받았는지 모른다. 모르는 것을 소리로 내보내지 않는다."""

    class NoHeader(FakeTransport):
        def __call__(self, url, *, headers, json, timeout):
            super().__call__(url, headers=headers, json=json, timeout=timeout)
            return self.reply, {}

    with pytest.raises(ValueError):
        voice(NoHeader()).synthesize("안녕하세요", 8000)


def test_the_header_check_ignores_case_and_spacing():
    """HTTP 헤더 이름은 대소문자를 가리지 않는다. 여기서 깐깐하게 굴면
    사업자가 헤더를 소문자로 보내는 날 멀쩡한 응답이 전부 실패한다."""

    class LowerCase(FakeTransport):
        def __call__(self, url, *, headers, json, timeout):
            super().__call__(url, headers=headers, json=json, timeout=timeout)
            return self.reply, {"x-prosody-output-format": " PCM_8000 "}

    assert voice(LowerCase()).synthesize("안녕하세요", 8000) == PCM


def test_an_unsupported_sample_rate_never_leaves_the_process():
    """실패한 요청도 왕복 시간과 크레딧을 쓴다."""
    transport = FakeTransport()

    with pytest.raises(ValueError, match="22050"):
        voice(transport).synthesize("안녕하세요", 22050)

    assert transport.calls == []


# ------------------------------------------------------------ 텍스트 다듬기


def test_bracketed_stage_directions_never_reach_the_elder():
    transport = FakeTransport()

    voice(transport).synthesize("안녕하세요 (웃음) 잘 지내셨어요?", 8000)

    assert "웃음" not in transport.calls[0]["json"]["text"]


def test_nothing_left_to_say_costs_nothing():
    """읽을 게 안 남았으면 부르지 않는다. 빈 바이트는 오류가 아니다."""
    transport = FakeTransport()

    assert voice(transport).synthesize("(웃음)", 8000) == b""
    assert transport.calls == []


def test_long_text_is_split_instead_of_dropped():
    """요청당 상한이 있다. 잘라 버리면 어르신은 말이 끊긴 걸 듣는다."""
    transport = FakeTransport()
    text = ". ".join(["가" * 300] * 3)

    voice(transport).synthesize(text, 8000)

    assert len(transport.calls) == 3
    assert all(len(c["json"]["text"]) <= TTS_MAX_PIECE_CHARS for c in transport.calls)


def test_split_pieces_come_back_joined_in_order():
    transport = FakeTransport(reply=b"\x09\x09")
    text = ". ".join(["나" * 300] * 3)

    assert voice(transport).synthesize(text, 8000) == b"\x09\x09" * 3


def test_absurdly_long_text_is_truncated_and_says_so(caplog):
    """자르는 건 최후 수단이다. 자른 사실을 남기지 않으면 어르신이 문장
    중간에서 끊기는 이유를 아무도 알 수 없다."""
    transport = FakeTransport()

    with caplog.at_level(logging.WARNING, logger="app.media.prosody_voice"):
        voice(transport).synthesize("다" * (TTS_MAX_CHARS + 100), 8000)

    assert "자른다" in caplog.text
    assert sum(len(c["json"]["text"]) for c in transport.calls) <= TTS_MAX_CHARS
