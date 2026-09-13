"""CallSession — 한 통화의 상태 (앱 통화 설계 3장).

WebSocket을 모른다. 바이트를 밀어넣고 나가야 할 메시지를 돌려받는 구조라
소켓 없이 전부 검증된다. 나중에 전화망(Asterisk AudioSocket)이 붙어도
프레임 출처만 다르고 이 클래스는 그대로 재사용된다.
"""

import struct
import wave

import numpy as np

from app.media.session import AudioMessage, CallSession, TextMessage

SAMPLE_RATE = 16000
FRAME_BYTES = 640  # 20ms × 16000Hz × 2bytes


class FakeResponder:
    """무엇이 언제 요청됐는지 기록한다."""

    def __init__(self, reply: bytes = b"\x10\x00") -> None:
        self.reply = reply
        self.calls: list[int] = []

    def respond(self, audio: np.ndarray, sample_rate: int) -> bytes:
        self.calls.append(len(audio))
        return self.reply


class BrokenResponder:
    def respond(self, audio: np.ndarray, sample_rate: int) -> bytes:
        raise RuntimeError("CLOVA가 죽었다")


def pcm16(*spans, sample_rate=SAMPLE_RATE):
    """('speech', 500), ('silence', 1000) → PCM16 LE 바이트."""
    values: list[int] = []
    for kind, duration_ms in spans:
        count = int(sample_rate * duration_ms / 1000)
        if kind == "speech":
            values.extend(9000 if i % 2 == 0 else -9000 for i in range(count))
        else:
            values.extend(0 for _ in range(count))
    return struct.pack(f"<{len(values)}h", *values)


def drain(session, data, chunk_bytes=FRAME_BYTES):
    """바이트를 chunk_bytes씩 나눠 밀어넣고 나온 메시지를 모은다."""
    out = []
    for start in range(0, len(data), chunk_bytes):
        out.extend(session.push_audio(data[start : start + chunk_bytes]))
    return out


def test_speech_end_produces_signal_then_audio():
    responder = FakeResponder()
    session = CallSession("c1", SAMPLE_RATE, responder)

    messages = drain(session, pcm16(("speech", 500), ("silence", 1000)))

    assert messages == [
        TextMessage({"type": "speech_end"}),
        AudioMessage(responder.reply),
    ]
    assert len(responder.calls) == 1


def test_silence_only_produces_nothing():
    session = CallSession("c1", SAMPLE_RATE, FakeResponder())

    assert drain(session, pcm16(("silence", 2000))) == []


def test_result_is_same_when_bytes_arrive_split_oddly():
    """WebSocket은 보낸 단위로 도착한다는 보장이 없다.

    버퍼링이 깨지면 조용히 어긋나므로 여기서 못 박는다.
    """
    audio = pcm16(("speech", 500), ("silence", 1000))

    aligned = drain(CallSession("c1", SAMPLE_RATE, FakeResponder()), audio)
    ragged = drain(CallSession("c2", SAMPLE_RATE, FakeResponder()), audio, 137)

    # push_audio가 몽땅 버려도 aligned == ragged([] == [])는 통과해버리므로,
    # 실제로 메시지가 나왔는지부터 확인해야 이 비교가 의미를 가진다.
    assert len(aligned) == 2
    assert aligned == ragged


def test_responder_failure_does_not_kill_the_call():
    """응답 하나 실패했다고 통화를 끊으면 어르신은 영문을 모른다."""
    session = CallSession("c1", SAMPLE_RATE, BrokenResponder())

    messages = drain(session, pcm16(("speech", 500), ("silence", 1000)))

    assert messages == [TextMessage({"type": "speech_end"})]


def test_finish_writes_the_whole_call_as_wav(tmp_path):
    session = CallSession("c1", SAMPLE_RATE, FakeResponder())
    audio = pcm16(("speech", 500), ("silence", 1000))
    drain(session, audio)

    path = session.finish(tmp_path)

    assert path == tmp_path / "c1.wav"
    with wave.open(str(path), "rb") as wav:
        assert wav.getnchannels() == 1
        assert wav.getsampwidth() == 2
        assert wav.getframerate() == SAMPLE_RATE
        assert wav.readframes(wav.getnframes()) == audio


def test_finish_without_audio_still_writes_a_file(tmp_path):
    """앱이 곧바로 끊겨도 통화 기록이 사라지면 안 된다."""
    session = CallSession("c1", SAMPLE_RATE, FakeResponder())

    path = session.finish(tmp_path)

    assert path.exists()
    with wave.open(str(path), "rb") as wav:
        assert wav.getnframes() == 0


def test_incomplete_trailing_bytes_are_kept_for_the_next_push(tmp_path):
    """640바이트에 못 미치는 꼬리를 버리면 오디오에 구멍이 생긴다."""
    session = CallSession("c1", SAMPLE_RATE, FakeResponder())
    audio = pcm16(("speech", 500), ("silence", 1000))

    session.push_audio(audio[:100])
    session.push_audio(audio[100:])
    path = session.finish(tmp_path)

    with wave.open(str(path), "rb") as wav:
        assert wav.readframes(wav.getnframes()) == audio
