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
    """바이트를 chunk_bytes씩 나눠 밀어넣고 나온 메시지를 모은다.

    타임스탬프는 push_audio 내부와 같은 정수 나눗셈(바이트 → ms)으로 누적한다.
    바이트 오프셋을 매번 새로 나누면 절단 오차가 누적돼 gap이 생기고,
    137바이트처럼 프레임 경계에 안 맞는 조각으로 나눠 보내는 테스트에서
    있지도 않은 침묵이 끼어든다.
    """
    out = []
    timestamp_ms = 0
    for start in range(0, len(data), chunk_bytes):
        chunk = data[start : start + chunk_bytes]
        out.extend(session.push_audio(chunk, timestamp_ms=timestamp_ms))
        timestamp_ms += len(chunk) * 1000 // (SAMPLE_RATE * 2)
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

    first = audio[:100]
    session.push_audio(first, timestamp_ms=0)
    # gap이 생기지 않도록 push_audio 내부와 같은 정수 나눗셈으로 다음 시각을 잇는다.
    session.push_audio(audio[100:], timestamp_ms=len(first) * 1000 // (SAMPLE_RATE * 2))
    path = session.finish(tmp_path)

    with wave.open(str(path), "rb") as wav:
        assert wav.readframes(wav.getnframes()) == audio


# 아래 세 테스트는 8kHz 통화(전화망 채널)를 다룬다. 위쪽 SAMPLE_RATE/FRAME_BYTES
# (16kHz, 앱 채널 테스트용)를 그대로 재대입하면 모듈 로드가 끝난 시점에 그 값이
# 8kHz로 바뀌어버려, 이 파일에 있는 기존 테스트가 전부 조용히 8kHz로 CallSession을
# 만들게 된다. 그래서 이름을 따로 둔다.
GAP_SAMPLE_RATE = 8000
GAP_FRAME_MS = 20
GAP_FRAME_SAMPLES = GAP_SAMPLE_RATE * GAP_FRAME_MS // 1000  # 160
GAP_FRAME_BYTES = GAP_FRAME_SAMPLES * 2  # PCM16


def silence_frame() -> bytes:
    return b"\x00" * GAP_FRAME_BYTES


def speech_frame(amplitude: int = 8000) -> bytes:
    """교번 신호. RMS가 곧 진폭이라 임계값 계산이 예측 가능하다."""
    samples = np.empty(GAP_FRAME_SAMPLES, dtype="<i2")
    samples[0::2] = amplitude
    samples[1::2] = -amplitude
    return samples.tobytes()


def wav_duration_ms(path) -> int:
    with wave.open(str(path), "rb") as wav:
        return round(wav.getnframes() * 1000 / wav.getframerate())


class _SilentResponder:
    """응답을 돌려주지 않는다. 타임라인만 보는 테스트에 쓴다."""

    def respond(self, audio: np.ndarray, sample_rate: int) -> bytes:
        return b""


def test_lost_frames_are_filled_with_silence(tmp_path):
    """유실 구간에 침묵을 채우지 않으면 뒤의 모든 발화가 앞으로 당겨진다.

    전화망에서 프레임 유실은 정상적으로 일어난다. 그때 지표가 조용히
    틀리는 것이 이 프로젝트가 가장 싫어하는 실패다.
    """
    session = CallSession("c1", GAP_SAMPLE_RATE, _SilentResponder())

    # 0~200ms: 정상
    for i in range(10):
        session.push_audio(silence_frame(), timestamp_ms=i * GAP_FRAME_MS)
    # 200~400ms: 통째로 유실 (아무것도 안 보냄)
    # 400~600ms: 다시 정상
    for i in range(20, 30):
        session.push_audio(silence_frame(), timestamp_ms=i * GAP_FRAME_MS)

    assert session.stream_duration_ms == 600
    assert wav_duration_ms(session.finish(tmp_path)) == 600


def test_duplicate_or_out_of_order_timestamp_does_not_rewind(tmp_path):
    """같은 타임스탬프가 두 번 와도 오디오를 되감지 않는다."""
    session = CallSession("c2", GAP_SAMPLE_RATE, _SilentResponder())
    session.push_audio(silence_frame(), timestamp_ms=0)
    session.push_audio(silence_frame(), timestamp_ms=20)
    session.push_audio(silence_frame(), timestamp_ms=20)   # 중복

    assert session.stream_duration_ms == 60
    assert wav_duration_ms(session.finish(tmp_path)) == 60


def test_speech_after_a_gap_keeps_its_absolute_position(tmp_path):
    """유실 뒤의 발화가 원래 시각에 남아 있는지 — 갭 채우기의 목적 자체."""
    session = CallSession("c3", GAP_SAMPLE_RATE, _SilentResponder())

    for i in range(10):                       # 0~200ms 침묵
        session.push_audio(silence_frame(), timestamp_ms=i * GAP_FRAME_MS)
    for i in range(30, 45):                   # 600~900ms 발화 (200~600ms 유실)
        session.push_audio(speech_frame(), timestamp_ms=i * GAP_FRAME_MS)

    path = session.finish(tmp_path)
    with wave.open(str(path), "rb") as wav:
        samples = np.frombuffer(wav.readframes(wav.getnframes()), dtype="<i2")

    # 600ms 지점부터 소리가 있어야 한다. 갭을 안 채웠다면 200ms에 있을 것이다.
    at_200ms = samples[GAP_SAMPLE_RATE * 200 // 1000 : GAP_SAMPLE_RATE * 240 // 1000]
    at_600ms = samples[GAP_SAMPLE_RATE * 600 // 1000 : GAP_SAMPLE_RATE * 640 // 1000]
    assert np.all(at_200ms == 0)
    assert np.any(at_600ms != 0)
