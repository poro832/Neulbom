"""한 통화의 상태. 전송 수단을 모른다 (앱 통화 설계 3장).

바이트를 받아 나가야 할 메시지를 돌려주는 구조라 소켓 없이 테스트된다.
전화망 채널(Asterisk AudioSocket)이 붙을 때도 프레임 출처만 다르고
이 클래스는 그대로 재사용된다.
"""

from __future__ import annotations

import logging
import wave
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from app.analysis.vad_segmenter import DEFAULT_FRAME_MS
from app.media.responder import Responder
from app.media.streaming_vad import StreamingVad

logger = logging.getLogger(__name__)

_BYTES_PER_SAMPLE = 2
_INT16_FULL_SCALE = 32768.0


@dataclass(frozen=True)
class TextMessage:
    """제어 신호. 소켓에서는 텍스트 프레임으로 나간다."""

    payload: dict


@dataclass(frozen=True)
class AudioMessage:
    """재생할 오디오. 소켓에서는 바이너리 프레임으로 나간다."""

    pcm: bytes


Outgoing = TextMessage | AudioMessage


class CallSession:
    def __init__(
        self,
        call_id: str,
        sample_rate: int,
        responder: Responder,
        frame_ms: int = DEFAULT_FRAME_MS,
    ) -> None:
        self._call_id = call_id
        self._sample_rate = sample_rate
        self._responder = responder
        self._vad = StreamingVad(sample_rate, frame_ms=frame_ms)
        self._frame_bytes = self._vad.frame_length * _BYTES_PER_SAMPLE

        # 640바이트에 못 미치는 꼬리. 버리면 오디오에 구멍이 생긴다.
        self._pending = b""
        self._recorded = bytearray()

    @property
    def call_id(self) -> str:
        return self._call_id

    def push_audio(self, data: bytes) -> list[Outgoing]:
        self._recorded.extend(data)
        self._pending += data

        outgoing: list[Outgoing] = []
        while len(self._pending) >= self._frame_bytes:
            chunk = self._pending[: self._frame_bytes]
            self._pending = self._pending[self._frame_bytes :]
            ended = self._vad.push(_to_float32(chunk))
            if ended is not None:
                outgoing.extend(self._on_speech_end(ended.start_ms, ended.end_ms))
        return outgoing

    def finish(self, directory: Path) -> Path:
        """누적한 원본을 wav로 남긴다.

        앱이 갑자기 끊겨도 호출된다. 통화 기록이 사라지면 안 된다.
        """
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{self._call_id}.wav"
        with wave.open(str(path), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(_BYTES_PER_SAMPLE)
            wav.setframerate(self._sample_rate)
            wav.writeframes(bytes(self._recorded))
        return path

    def _on_speech_end(self, start_ms: int, end_ms: int) -> list[Outgoing]:
        outgoing: list[Outgoing] = [TextMessage({"type": "speech_end"})]

        start = int(start_ms * self._sample_rate / 1000) * _BYTES_PER_SAMPLE
        end = int(end_ms * self._sample_rate / 1000) * _BYTES_PER_SAMPLE
        turn = _to_float32(bytes(self._recorded[start:end]))

        try:
            reply = self._responder.respond(turn, self._sample_rate)
        except Exception:
            # 응답 하나 실패했다고 통화를 끊으면 어르신은 영문을 모른다.
            logger.exception("응답 생성 실패 — 통화는 유지한다 call_id=%s", self._call_id)
            return outgoing

        if reply:
            outgoing.append(AudioMessage(reply))
        return outgoing


def _to_float32(pcm: bytes) -> np.ndarray:
    return np.frombuffer(pcm, dtype="<i2").astype(np.float32) / _INT16_FULL_SCALE
