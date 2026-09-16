"""통화 후 분석 — 녹음에서 지표까지 (전화망 설계 2장 ⑦).

통화 중 스트리밍 VAD가 낸 판정은 여기에 들어오지 않는다. 지표는 저장된
wav 전체에 배치 VAD를 다시 돌려 낸다(설계 3.2). 그래야 같은 통화를 다시
분석해도 같은 점수가 나온다.
"""

import wave

import numpy as np

from app.analysis import call_analysis
from app.analysis.call_analysis import DEGRADED_CLIP_RATIO, analyze_call
from app.analysis.echo import ClipResult
from app.analysis.segments import VadSegment

SAMPLE_RATE = 8000


def write_wav(path, spans):
    """[('speech', 1000), ('silence', 500)] → 8kHz PCM16 wav."""
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


def test_speech_ratio_comes_from_the_recording(tmp_path):
    path = write_wav(tmp_path / "a.wav", [("speech", 2000), ("silence", 2000)])
    result = analyze_call(
        wav_path=path,
        ai_turns=[],
        stream_duration_ms=4000,
        transcript="",
    )
    # 4초 중 2초가 발화다. VAD 경계가 프레임 단위라 정확히 0.5는 아니다.
    assert 0.4 < result.metrics.speech_ratio < 0.6


def test_ai_playback_is_removed_from_elder_speech(tmp_path):
    """스피커폰 에코가 발화 비율을 부풀리면 안 된다 (설계 3.4)."""
    path = write_wav(tmp_path / "b.wav", [("speech", 2000), ("silence", 2000)])

    without_ai = analyze_call(
        wav_path=path, ai_turns=[], stream_duration_ms=4000, transcript=""
    )
    with_ai = analyze_call(
        wav_path=path,
        ai_turns=[VadSegment(0, 1000)],  # 앞 1초는 AI가 말하던 중이었다
        stream_duration_ms=4000,
        transcript="",
    )

    assert with_ai.metrics.speech_ratio < without_ai.metrics.speech_ratio
    assert with_ai.clipped_ms > 0


def test_heavy_clipping_marks_the_call_degraded(tmp_path):
    """잘라낸 양이 크면 에코가 심하거나 어르신이 자주 끊고 들어온 것이다.

    실패로 처리하지 않고 '정확도 낮음'을 정직하게 표시한다.
    """
    path = write_wav(tmp_path / "c.wav", [("speech", 2000), ("silence", 2000)])
    result = analyze_call(
        wav_path=path,
        ai_turns=[VadSegment(0, 1900)],
        stream_duration_ms=4000,
        transcript="",
    )
    assert result.degraded is True


def test_a_clean_call_is_not_degraded(tmp_path):
    path = write_wav(tmp_path / "d.wav", [("speech", 2000), ("silence", 2000)])
    result = analyze_call(
        wav_path=path, ai_turns=[], stream_duration_ms=4000, transcript=""
    )
    assert result.degraded is False
    assert result.clipped_ms == 0


def test_negative_words_come_from_the_transcript(tmp_path):
    path = write_wav(tmp_path / "e.wav", [("speech", 1000), ("silence", 1000)])
    result = analyze_call(
        wav_path=path,
        ai_turns=[],
        stream_duration_ms=2000,
        transcript="무릎이 아파요 그리고 요즘 많이 힘들어요",
    )
    assert result.metrics.negative_word_count == 2


def test_analysis_is_identical_across_repeated_runs(tmp_path):
    """이 프로젝트의 간판 주장을 전화망 경로에서 증명한다.

    같은 녹음을 100번 분석해 값이 하나라도 흔들리면, 보호자가 보는
    추이 그래프는 노이즈가 되고 알림은 무시당하게 된다.
    """
    path = write_wav(
        tmp_path / "f.wav",
        [("silence", 500), ("speech", 1500), ("silence", 900), ("speech", 1100)],
    )
    ai_turns = [VadSegment(500, 900), VadSegment(2400, 2900)]

    results = {
        analyze_call(
            wav_path=path,
            ai_turns=ai_turns,
            stream_duration_ms=4000,
            transcript="무릎이 아파요",
        )
        for _ in range(100)
    }
    assert len(results) == 1


def test_zero_length_segments_are_dropped_before_metrics(tmp_path, monkeypatch):
    """clip_ai_playback는 길이 0인 구간을 그대로 통과시킨다(리뷰에서 발견).

    오늘은 segment_audio가 min_speech_ms 미만을 걸러서 실제로는 생기지 않지만,
    analyze_call이 이 둘을 처음 잇는 지점이므로 여기서 막아야 한다. 안 그러면
    길이 0인 "구간"이 turn_count에 공짜로 +1을 더한다.
    """
    path = write_wav(tmp_path / "g.wav", [("silence", 200)])

    def fake_clip(elder, ai_turns):
        return ClipResult(segments=[VadSegment(1000, 1000)], clipped_ms=0)

    monkeypatch.setattr(call_analysis, "clip_ai_playback", fake_clip)

    result = analyze_call(
        wav_path=path,
        ai_turns=[],
        stream_duration_ms=200,
        transcript="",
    )
    assert result.metrics.turn_count == 0
