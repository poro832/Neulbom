"""CLOVA Voice TTS 어댑터.

네트워크를 타지 않는다. 전송 계층을 주입받으므로 키 없이도 규약 전체가
검증된다 — Telephony/Responder와 같은 패턴이다.
"""

import io
import logging
import wave

import pytest

from app.media.clova_voice import (
    TTS_MAX_CHARS,
    TTS_MAX_SENTENCE_CHARS,
    ClovaVoice,
    strip_unspoken,
)


def wav_bytes(pcm: bytes, sample_rate: int, extra_chunk: bool = False) -> bytes:
    """CLOVA가 돌려주는 모양의 wav를 만든다."""
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(sample_rate)
        out.writeframes(pcm)
    raw = buffer.getvalue()
    if not extra_chunk:
        return raw
    # RIFF 헤더가 항상 44바이트라는 보장은 없다. 청크를 하나 끼워 넣어
    # "44바이트를 잘라낸다"는 구현이면 깨지게 만든다.
    body = raw[12:]
    junk = b"LIST" + (4).to_bytes(4, "little") + b"INFO"
    # RIFF 크기는 "WAVE"부터 끝까지다. 여기를 4바이트 적게 적었다가 데이터
    # 꼬리가 잘려서, 구현이 아니라 픽스처가 틀린 실패를 한 번 봤다.
    size = len(b"WAVE") + len(junk) + len(body)
    return b"RIFF" + size.to_bytes(4, "little") + b"WAVE" + junk + body


class FakeTransport:
    """무엇을 요청받았는지 기록하고 미리 정한 wav를 돌려준다."""

    def __init__(self, reply: bytes) -> None:
        self.reply = reply
        self.calls: list[tuple[str, dict, dict]] = []

    def __call__(self, url: str, *, headers: dict, data: dict, timeout: float) -> bytes:
        self.calls.append((url, headers, data))
        return self.reply


PCM = b"\x01\x02" * 400


def make(sample_rate=8000, reply=None, **kwargs):
    transport = FakeTransport(reply or wav_bytes(PCM, sample_rate))
    voice = ClovaVoice(
        client_id="ID", client_secret="SECRET", transport=transport, **kwargs
    )
    return voice, transport


# ------------------------------------------------------------ 오디오 형식


def test_it_returns_raw_pcm_not_a_wav_file():
    """Responder 규약은 PCM16 LE 바이트다. wav 헤더가 섞이면 그대로 재생된다."""
    voice, _ = make()

    assert voice.synthesize("안녕하세요", 8000) == PCM


def test_the_wav_header_is_parsed_not_assumed_to_be_44_bytes():
    """RIFF 헤더 길이는 고정이 아니다.

    44바이트를 잘라내는 구현은 청크가 하나만 더 있어도 오디오 앞부분을
    먹거나 헤더 꼬리를 소리로 내보낸다.
    """
    voice, _ = make(reply=wav_bytes(PCM, 8000, extra_chunk=True))

    assert voice.synthesize("안녕하세요", 8000) == PCM


def test_it_asks_for_wav_at_the_sessions_sample_rate():
    """전화망은 8kHz다. 여기서 24000(기본값)을 받으면 재생 속도가 틀어진다."""
    voice, transport = make()

    voice.synthesize("안녕하세요", 8000)

    _, _, data = transport.calls[0]
    assert data["format"] == "wav"
    assert data["sampling-rate"] == 8000


def test_a_reply_at_the_wrong_sample_rate_is_refused():
    """요청한 레이트와 다른 오디오가 오면 소리가 빨라지거나 느려진다.

    조용히 재생하면 어르신은 이상한 목소리를 듣고, 우리는 지표만 본다.
    """
    voice, _ = make(reply=wav_bytes(PCM, 24000))

    with pytest.raises(ValueError, match="샘플레이트"):
        voice.synthesize("안녕하세요", 8000)


def test_an_unsupported_sample_rate_is_refused_before_the_call():
    """CLOVA가 지원하지 않는 레이트다. 요청을 보내 봐야 돈만 쓴다."""
    voice, transport = make()

    with pytest.raises(ValueError, match="지원하지 않는"):
        voice.synthesize("안녕하세요", 11025)

    assert transport.calls == []


# ------------------------------------------------------------ 요청 형식


def test_both_auth_headers_are_sent():
    voice, transport = make()

    voice.synthesize("안녕하세요", 8000)

    _, headers, _ = transport.calls[0]
    assert headers["X-NCP-APIGW-API-KEY-ID"] == "ID"
    assert headers["X-NCP-APIGW-API-KEY"] == "SECRET"


def test_speaker_and_prosody_are_sent_as_given():
    """speed는 양수가 '느리게'다(문서 기준). 부호를 뒤집지 않고 그대로 넘긴다."""
    voice, transport = make(speaker="nara_call", speed=2)

    voice.synthesize("안녕하세요", 8000)

    _, _, data = transport.calls[0]
    assert data["speaker"] == "nara_call"
    assert data["speed"] == 2


# ------------------------------------------------- 말해지지 않는 텍스트


@pytest.mark.parametrize(
    "raw,spoken",
    [
        ("(웃음) 오늘 날씨가 좋네요", "오늘 날씨가 좋네요"),
        ("밥은 드셨어요? (걱정)", "밥은 드셨어요?"),
        ("[안내] 곧 끊습니다", "곧 끊습니다"),
        ("괄호가 없으면 그대로", "괄호가 없으면 그대로"),
        ("문장부호는 남긴다. 억양에 쓰인다!", "문장부호는 남긴다. 억양에 쓰인다!"),
    ],
)
def test_bracketed_text_is_removed_before_sending(raw, spoken):
    """CLOVA는 괄호 안 텍스트를 읽지 않는다 — 오류도 없이 그냥 사라진다.

    우리가 먼저 지운다. 그래야 "보낸 것"과 "들린 것"이 같아지고, 무엇이
    빠졌는지 로그로 남길 수 있다.
    """
    assert strip_unspoken(raw) == spoken


def test_text_that_is_all_brackets_is_not_sent_at_all():
    """읽을 게 하나도 안 남으면 호출할 이유가 없다 — 빈 응답이 정답이다."""
    voice, transport = make()

    assert voice.synthesize("(침묵)", 8000) == b""
    assert transport.calls == []


def test_overlong_text_is_cut_and_reported(caplog):
    """한국어 2,000자 상한이다. 넘겨 보내면 통째로 실패한다.

    잘라서라도 말하는 편이 낫지만, 잘랐다는 사실은 남겨야 한다 — 안 그러면
    어르신이 문장 중간에서 끊기는 이유를 아무도 모른다.
    """
    voice, transport = make()

    with caplog.at_level(logging.WARNING, logger="app.media.clova_voice"):
        voice.synthesize("가" * (TTS_MAX_CHARS + 50), 8000)

    # 문장당 상한 때문에 여러 요청으로 나뉜다. 확인할 것은 "전체가 상한까지만
    # 갔는가"이지 "한 요청이 2,000자인가"가 아니다.
    sent = "".join(data["text"] for _, _, data in transport.calls)
    assert len(sent) == TTS_MAX_CHARS
    assert caplog.records


# ------------------------------------------------- 문장당 200자 (VS18)


def test_a_long_reply_is_split_into_sentences():
    """전체 2,000자와 별개로 문장당 200자 상한이 있다(오류 VS18).

    LLM이 쉼표로 길게 이어 붙인 한 문장을 뱉으면 — 어르신 말투를 흉내 내면
    충분히 있을 법하다 — 총 길이가 상한 안이어도 요청이 통째로 실패한다.
    그러면 그 턴은 소리가 안 나고 어르신은 침묵을 듣는다.
    """
    long_sentence = "가" * 250
    voice, transport = make(reply=wav_bytes(PCM, 8000))

    voice.synthesize(f"짧은 문장입니다. {long_sentence}", 8000)

    sent = [data["text"] for _, _, data in transport.calls]
    assert len(sent) > 1
    assert all(len(chunk) <= TTS_MAX_SENTENCE_CHARS for chunk in sent)
    # 잘라 버리지 않는다 — 다 말한다.
    assert sum(len(c) for c in sent) >= 250


def test_the_pieces_are_joined_back_into_one_audio_stream():
    """여러 번 합성해도 어르신에게는 한 번의 발화로 들려야 한다.

    조각 수를 손으로 세지 않는다 — 구두점이 없는 250자는 문장으로도 절로도
    안 끊겨서 글자 수로 잘리고, 그 개수는 상한에 딸린 값이다. 확인할 것은
    "요청한 만큼이 빠짐없이 이어 붙었는가"다.
    """
    voice, transport = make(reply=wav_bytes(PCM, 8000))

    audio = voice.synthesize("가" * 250 + ". " + "나" * 250, 8000)

    assert len(audio) == len(PCM) * len(transport.calls)


def test_a_short_reply_is_still_one_request():
    """쪼갤 이유가 없으면 왕복을 늘리지 않는다 — 왕복마다 어르신이 기다린다."""
    voice, transport = make()

    voice.synthesize("오늘 하루 어떠셨어요?", 8000)

    assert len(transport.calls) == 1
