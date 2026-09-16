"""통화 후처리 배선 (전화망 설계 2장 ⑦).

세션이 통화 중에 모아 둔 것(AI 발화 구간, 스트림 길이, 짝 안 맞은 표식)이
분석으로 실제로 건너가는지를 본다. 분석 자체의 정확도는 test_call_analysis가
이미 고정하고 있으므로, 여기서는 "건너갔는가"만 확인한다.
"""

import wave
from dataclasses import dataclass, field

import numpy as np

from app.analysis.segments import VadSegment
from app.post_call import analyze_session

SAMPLE_RATE = 8000


@dataclass
class FakeSession:
    """analyze_session이 실제로 읽는 네 가지만 갖춘 대역.

    진짜 CallSession을 쓰면 mark 왕복까지 재현해야 해서, 무엇이 배선의
    입력인지가 오히려 흐려진다.
    """

    call_id: str = "7"
    ai_turns: list = field(default_factory=list)
    stream_duration_ms: int = 4000
    unmatched_marks: int = 0


def write_wav(path, spans):
    chunks = []
    for kind, duration_ms in spans:
        count = SAMPLE_RATE * duration_ms // 1000
        chunk = np.zeros(count, dtype="<i2")
        if kind == "speech":
            chunk[0::2] = 8000
            chunk[1::2] = -8000
        chunks.append(chunk)
    samples = np.concatenate(chunks)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(SAMPLE_RATE)
        wav.writeframes(samples.tobytes())
    return path


def test_the_sessions_ai_turns_reach_the_echo_clipper(tmp_path):
    """mark로 잡은 AI 발화 구간이 분석까지 가야 에코 제거가 일어난다.

    안 넘기면 스피커폰으로 되울려 들어온 AI 음성이 어르신 발화로 세어져
    발화 비율이 부풀고, 위험 점수는 실제보다 낮게 나온다(설계 3.4).
    """
    path = write_wav(tmp_path / "a.wav", [("speech", 2000), ("silence", 2000)])

    quiet = analyze_session(FakeSession(), path)
    echoed = analyze_session(FakeSession(ai_turns=[VadSegment(0, 1000)]), path)

    assert echoed.metrics.speech_ratio < quiet.metrics.speech_ratio
    assert echoed.clipped_ms > 0


def test_unmatched_marks_make_the_call_degraded(tmp_path):
    """짝이 안 맞은 표식은 AI 발화 구간을 통째로 잃었다는 뜻이다.

    숫자는 그래도 나오지만 근거가 줄었다. 실패로 처리하지도, 멀쩡한 척하지도
    않고 '정확도 낮음'을 표시한다(설계 8장) — 이 신호는 지금까지 아무 데도
    연결돼 있지 않았다.
    """
    path = write_wav(tmp_path / "b.wav", [("speech", 2000), ("silence", 2000)])

    clean = analyze_session(FakeSession(), path)
    lossy = analyze_session(FakeSession(unmatched_marks=1), path)

    assert clean.degraded is False
    assert lossy.degraded is True
    # 표시만 달라진다. 지표 자체를 지어내거나 버리지 않는다.
    assert lossy.metrics == clean.metrics


def test_transcript_is_empty_because_there_is_no_stt(tmp_path):
    """STT가 없다. 부정어 수는 0이고, 그건 '측정하지 않았다'는 뜻이다.

    여기에 지어낸 문장을 넣으면 위험 점수 20점이 근거 없이 움직인다.
    """
    path = write_wav(tmp_path / "c.wav", [("speech", 1000), ("silence", 1000)])

    result = analyze_session(FakeSession(stream_duration_ms=2000), path)

    assert result.metrics.negative_word_count == 0
