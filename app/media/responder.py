"""어르신의 발화를 받아 들려줄 오디오를 돌려주는 자리.

골격에서는 고정 응답(beep)이다. CLOVA Speech → Studio → Voice로 가는
ClovaResponder가 같은 규약을 구현하면 CallSession은 한 글자도 안 바뀐다.
"""

from __future__ import annotations

import math
import struct
from collections.abc import Sequence
from typing import Protocol

import numpy as np


class Responder(Protocol):
    def respond(self, audio: np.ndarray, sample_rate: int) -> bytes:
        """한 턴의 발화를 받아 재생할 PCM16 LE 바이트를 돌려준다.

        빈 바이트는 "들려줄 것이 없음"을 뜻하며 오류가 아니다.
        """
        ...


def beep(duration_ms: int, sample_rate: int, frequency_hz: int = 660) -> bytes:
    """골격이 소리를 내는지 귀로 확인하기 위한 톤.

    실제 응답 음성은 ClovaResponder가 만든다. 여기서 wav 자산을 준비하면
    골격 단계에 불필요한 파일 의존이 생긴다.
    """
    count = int(sample_rate * duration_ms / 1000)
    amplitude = 8000  # 최대치(32767)의 약 1/4 — 놀라지 않을 크기
    samples = [
        int(amplitude * math.sin(2 * math.pi * frequency_hz * i / sample_rate))
        for i in range(count)
    ]
    return struct.pack(f"<{count}h", *samples)


class CannedResponder:
    """clips를 순환하며 돌려준다. 매번 같은 소리면 기계처럼 들린다."""

    def __init__(self, clips: Sequence[bytes]) -> None:
        self._clips = list(clips)
        self._index = 0

    def respond(self, audio: np.ndarray, sample_rate: int) -> bytes:
        if not self._clips:
            return b""
        clip = self._clips[self._index % len(self._clips)]
        self._index += 1
        return clip
