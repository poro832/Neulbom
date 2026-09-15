"""G.711 μ-law 코덱 (전화망 설계 4.1).

표준 라이브러리 audioop이 Python 3.13에서 제거돼 직접 만든다.

디코드는 표준 G.711 알고리즘으로 256엔트리 표를 만들고, 인코드는 그 표에서
가장 가까운 값을 찾는다. 인코드를 따로 구현하지 않는 이유는 두 벌이
갈라지지 않게 하기 위해서다 — 같은 표를 쓰면 왕복이 정의상 멱등이 된다.
"""

from __future__ import annotations

import numpy as np

SAMPLE_RATE = 8000

# 20ms. μ-law는 샘플당 1바이트라 160샘플 = 160바이트다.
FRAME_BYTES = 160

_BIAS = 0x84
_INT16_FULL_SCALE = 32768.0


def _build_decode_table() -> np.ndarray:
    """μ-law 바이트 → int16. ITU-T G.711 정의 그대로다.

    바이트는 보수로 저장되므로 먼저 뒤집는다. 지수/가수를 분리해 크기를
    복원하고 바이어스를 뺀다.
    """
    table = np.empty(256, dtype=np.int16)
    for byte in range(256):
        value = ~byte & 0xFF
        magnitude = (((value & 0x0F) << 3) + _BIAS) << ((value & 0x70) >> 4)
        linear = magnitude - _BIAS
        table[byte] = -linear if value & 0x80 else linear
    return table


_DECODE = _build_decode_table()

# 인코드용. 표를 값 순으로 세워 두고 이웃 사이의 중점을 경계로 쓴다.
_ORDER = np.argsort(_DECODE, kind="stable").astype(np.uint8)
_SORTED = _DECODE[_ORDER].astype(np.float32)
_BOUNDARIES = (_SORTED[:-1] + _SORTED[1:]) / 2.0


def decode(payload: bytes) -> np.ndarray:
    """μ-law 바이트를 float32 [-1, 1)로."""
    return _DECODE[np.frombuffer(payload, dtype=np.uint8)].astype(
        np.float32
    ) / _INT16_FULL_SCALE


def encode(samples: np.ndarray) -> bytes:
    """float32를 μ-law 바이트로. 범위를 넘으면 자른다.

    뒤집히면 굉음이 되므로 clip이 먼저다.
    """
    scaled = np.clip(
        np.asarray(samples, dtype=np.float32) * _INT16_FULL_SCALE, -32768.0, 32767.0
    )
    return _ORDER[np.searchsorted(_BOUNDARIES, scaled)].tobytes()


def decode_to_pcm16(payload: bytes) -> bytes:
    """μ-law → PCM16 LE. CallSession이 바이트로 다루므로 float를 거치지 않는다."""
    return _DECODE[np.frombuffer(payload, dtype=np.uint8)].astype("<i2").tobytes()


def encode_from_pcm16(pcm: bytes) -> bytes:
    """PCM16 LE → μ-law. Responder가 돌려주는 형식이 PCM16이다."""
    samples = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / _INT16_FULL_SCALE
    return encode(samples)
