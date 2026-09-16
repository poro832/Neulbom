"""CallSession — 한 통화의 상태 (앱 통화 설계 3장).

WebSocket을 모른다. 바이트를 밀어넣고 나가야 할 메시지를 돌려받는 구조라
소켓 없이 전부 검증된다. 나중에 전화망(Asterisk AudioSocket)이 붙어도
프레임 출처만 다르고 이 클래스는 그대로 재사용된다.
"""

import struct
import wave

import numpy as np

from app.analysis.segments import VadSegment
from app.media.session import AudioMessage, CallSession, MarkMessage, TextMessage

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
    """감지된 발화 종료는 제어 신호를 먼저, 그다음 응답 오디오를 낸다.

    응답 오디오는 mark로 앞뒤가 감싸인다(turn1-begin/turn1-end) — 순서 자체가
    이 테스트가 못 박는 것이므로 mark의 위치도 그대로 고정한다.
    """
    responder = FakeResponder()
    session = CallSession("c1", SAMPLE_RATE, responder)

    messages = drain(session, pcm16(("speech", 500), ("silence", 1000)))

    assert messages == [
        TextMessage({"type": "speech_end"}),
        MarkMessage("turn1-begin"),
        AudioMessage(responder.reply),
        MarkMessage("turn1-end"),
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
    # (signal, mark-begin, audio, mark-end) — mark가 추가되며 2에서 4로 늘었다.
    assert len(aligned) == 4
    # mark 이름은 세션마다 turn_index=0부터 다시 세므로("turn1-begin"...), 갓 만든
    # 두 세션이 도착 단위만 다르면 이름까지 완전히 같은 메시지를 내야 한다.
    # 이 비교가 곧 그것의 증거다 — 이름이 도착 청크에 좌우됐다면 여기서 어긋난다.
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


def test_tiny_out_of_order_chunks_do_not_freeze_the_clock(tmp_path):
    """duration_ms가 0으로 내림되는 작은 조각이 역순으로 여러 번 와도
    시계가 recorded 버퍼와 어긋나면 안 된다.

    8kHz에서 16바이트(1ms) 미만인 조각은 길이를 ms로 환산하면 0으로
    내려앉는다. 시계를 그 값만큼 누적으로만 더해 나가면, 역순으로 온
    조각(gap_ms < 0)이 버퍼에는 계속 쌓이는데 시계는 한 걸음도 못 뗀다 —
    그러면 다음에 온 정상 프레임이 있지도 않은 갭으로 오판된다. 하드코딩한
    숫자가 아니라 실제로 저장된 wav 길이와 맞대어 검증한다.
    """
    session = CallSession("c4", GAP_SAMPLE_RATE, _SilentResponder())
    session.push_audio(silence_frame(), timestamp_ms=0)  # 0~20ms 정상

    tiny = b"\x00" * 8  # 8000Hz에서 8바이트 = 0.5ms, duration_ms가 0으로 내림된다
    for _ in range(20):
        session.push_audio(tiny, timestamp_ms=0)  # 항상 과거 시각 — gap_ms < 0

    path = session.finish(tmp_path)
    assert session.stream_duration_ms == wav_duration_ms(path)


class _OneBeepResponder:
    """한 번만 응답하고 그 뒤로는 침묵. AI 턴이 몇 개인지 세기 쉽다."""

    def __init__(self) -> None:
        self.calls = 0

    def respond(self, audio: np.ndarray, sample_rate: int) -> bytes:
        self.calls += 1
        return b"\x01\x02" * 400 if self.calls == 1 else b""


def _drive_one_turn(session: CallSession) -> list:
    """발화 400ms → 침묵 900ms. StreamingVad의 end_of_turn(800ms)을 넘긴다.

    8kHz 채널용 speech_frame/silence_frame(GAP_FRAME_MS=20ms)을 쓴다 —
    이 세션들도 GAP_SAMPLE_RATE로 만들어야 프레임 길이가 맞는다.
    """
    outgoing = []
    index = 0
    for _ in range(20):
        outgoing += session.push_audio(speech_frame(), timestamp_ms=index * GAP_FRAME_MS)
        index += 1
    for _ in range(45):
        outgoing += session.push_audio(silence_frame(), timestamp_ms=index * GAP_FRAME_MS)
        index += 1
    return outgoing


def test_ai_audio_is_bracketed_by_marks():
    """오디오만 보내면 언제 재생됐는지 알 수 없다. 앞뒤로 mark가 붙어야 한다."""
    session = CallSession("c4", GAP_SAMPLE_RATE, _OneBeepResponder())
    outgoing = _drive_one_turn(session)

    kinds = [type(message).__name__ for message in outgoing]
    assert kinds.count("AudioMessage") == 1
    audio_at = kinds.index("AudioMessage")
    assert kinds[audio_at - 1] == "MarkMessage"
    assert kinds[audio_at + 1] == "MarkMessage"


def test_ai_turn_takes_its_time_from_the_media_clock():
    """mark에는 타임스탬프가 없다. 직전 inbound media의 시각을 쓴다.

    _drive_one_turn은 프레임 0~64를 소비해 시계를 1300ms에 남긴다. 그 뒤로는
    앞으로만 흐르는 타임스탬프를 밀어 넣는다 — 시계를 되감는 입력은 설계상
    무시되므로(gap_ms < 0), 여기서 뒤로 가는 타임스탬프를 주면 mark는 항상
    1300ms로 찍혀 버려 begin과 end를 구별할 수 없다.
    """
    session = CallSession("c5", GAP_SAMPLE_RATE, _OneBeepResponder())
    outgoing = _drive_one_turn(session)
    marks = [m.name for m in outgoing if isinstance(m, MarkMessage)]

    # 재생 시작 확인: 시계를 한 프레임(20ms) 전진시킨 뒤 온 mark → 1320ms.
    session.push_audio(silence_frame(), timestamp_ms=1300)
    session.on_mark(marks[0])
    # 재생 종료 확인: 그 뒤로 14프레임(1320~1580ms)을 더 흘려보낸 뒤 mark → 1600ms.
    for i in range(66, 80):
        session.push_audio(silence_frame(), timestamp_ms=i * GAP_FRAME_MS)
    session.on_mark(marks[1])

    assert session.ai_turns == [VadSegment(start_ms=1320, end_ms=1600)]
    assert session.unmatched_marks == 0


def test_a_turn_with_only_one_mark_is_not_counted():
    """한쪽 mark가 유실되면 구간을 모른다. 지어내지 않고 빼고 표시한다."""
    session = CallSession("c6", GAP_SAMPLE_RATE, _OneBeepResponder())
    outgoing = _drive_one_turn(session)
    marks = [m.name for m in outgoing if isinstance(m, MarkMessage)]

    session.push_audio(silence_frame(), timestamp_ms=1300)
    session.on_mark(marks[0])      # begin만 오고 end는 안 온다

    assert session.ai_turns == []
    assert session.unmatched_marks == 1
