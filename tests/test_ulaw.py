"""G.711 μ-law 코덱 (전화망 설계 4.1).

전화망 오디오는 전부 μ-law다. 여기가 틀리면 그 위의 VAD도 지표도 전부
잡음 위에서 돈다. 순수 함수라 합성 데이터만으로 검증된다.
"""

import numpy as np
import pytest

from app.media import ulaw


def test_frame_size_is_160_bytes_for_20ms():
    # 8000Hz * 20ms = 160샘플. μ-law는 샘플당 1바이트다.
    assert ulaw.FRAME_BYTES == 160
    assert ulaw.SAMPLE_RATE == 8000
    assert len(ulaw.decode(b"\xff" * ulaw.FRAME_BYTES)) == 160


def test_0xff_is_silence():
    # μ-law 0xFF는 +0이다. 회선이 조용할 때 실제로 오는 값이라
    # 여기가 틀리면 침묵이 잡음으로 잡힌다.
    decoded = ulaw.decode(b"\xff" * 10)
    assert np.all(decoded == 0.0)


def test_encode_silence_produces_0xff():
    # 침묵(0.0)을 인코드하면 표준 G.711 침묵 마크 0xFF가 나와야 한다.
    # 통신사로 보낼 프레임이 표준 바이트를 쓰도록 한다.
    encoded = ulaw.encode(np.array([0.0], dtype=np.float32))
    assert encoded[0] == 0xFF


def test_decode_reaches_full_scale():
    # 0x00은 μ-law 최소값(-32124), 0x80은 최대값(+32124)이다.
    assert ulaw.decode(bytes([0x00]))[0] == pytest.approx(-32124 / 32768, abs=1e-6)
    assert ulaw.decode(bytes([0x80]))[0] == pytest.approx(32124 / 32768, abs=1e-6)


def test_round_trip_is_idempotent():
    """한 번 μ-law를 거친 신호는 다시 거쳐도 바뀌지 않는다.

    인코드와 디코드가 같은 표를 쓴다는 것을 보장한다. 두 벌이 갈라지면
    통화가 길어질수록 왜곡이 누적된다.
    """
    rng = np.random.default_rng(0)
    original = rng.uniform(-1.0, 1.0, size=2000).astype(np.float32)

    once = ulaw.decode(ulaw.encode(original))
    twice = ulaw.decode(ulaw.encode(once))

    assert np.array_equal(once, twice)


def test_round_trip_error_stays_within_mu_law_resolution():
    """μ-law는 손실 압축이다. 다만 상대 오차가 일정 수준 안이어야 한다."""
    rng = np.random.default_rng(1)
    original = rng.uniform(-1.0, 1.0, size=5000).astype(np.float32)
    recovered = ulaw.decode(ulaw.encode(original))

    # 작은 값은 절대 오차가 작고, 큰 값은 상대 오차가 작다(μ-law의 성질).
    loud = np.abs(original) > 0.05
    relative = np.abs(recovered[loud] - original[loud]) / np.abs(original[loud])
    assert relative.max() < 0.05


def test_out_of_range_input_clips_instead_of_wrapping():
    """범위를 넘는 입력이 반대 부호로 뒤집히면 굉음이 된다."""
    loud = np.array([5.0, -5.0], dtype=np.float32)
    recovered = ulaw.decode(ulaw.encode(loud))
    assert recovered[0] > 0.9
    assert recovered[1] < -0.9


def test_pcm16_bridge_matches_float_path():
    """CallSession은 바이트로 다루고 VAD는 float로 다룬다. 두 길이 같아야 한다."""
    payload = bytes(range(256))
    from_bytes = np.frombuffer(ulaw.decode_to_pcm16(payload), dtype="<i2")
    from_float = ulaw.decode(payload)
    assert np.allclose(from_float, from_bytes.astype(np.float32) / 32768.0)


def test_pcm16_round_trip():
    pcm = np.array([0, 1000, -1000, 32000, -32000], dtype="<i2").tobytes()
    recovered = np.frombuffer(
        ulaw.decode_to_pcm16(ulaw.encode_from_pcm16(pcm)), dtype="<i2"
    )
    assert len(recovered) == 5
    # μ-law 양자화 후에도 부호와 크기 순서는 보존된다.
    assert recovered[0] == 0
    assert recovered[1] > 0 and recovered[2] < 0
    assert recovered[3] > recovered[1]
