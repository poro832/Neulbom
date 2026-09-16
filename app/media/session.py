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

        # 다음 프레임이 시작해야 할 시각. 실제 타임스탬프가 이보다 뒤면
        # 그 사이가 유실이다. 바이트 수로 세면 유실만큼 오디오가 짧아져
        # 뒤의 모든 발화 구간이 앞으로 당겨진다.
        self._next_timestamp_ms = 0
        self._last_timestamp_ms = 0

    @property
    def call_id(self) -> str:
        return self._call_id

    def push_audio(self, pcm: bytes, timestamp_ms: int) -> list[Outgoing]:
        """PCM16 LE 한 덩이를 그 시작 시각과 함께 밀어 넣는다.

        시각은 전송 계층이 준 것을 그대로 쓴다. 벽시계를 쓰면 네트워크
        지연이 섞여 들어가 같은 통화를 다시 분석해도 다른 값이 나온다.
        """
        gap_ms = timestamp_ms - self._next_timestamp_ms
        if gap_ms > 0:
            filler = b"\x00" * self._bytes_for(gap_ms)
            self._recorded.extend(filler)
            self._pending += filler
        elif gap_ms < 0:
            # 중복이거나 순서가 뒤집혔다. 되감으면 이미 쓴 오디오를 덮어쓴다.
            logger.warning(
                "타임스탬프가 뒤로 갔다 — 무시한다 call_id=%s gap=%dms",
                self._call_id,
                gap_ms,
            )

        self._recorded.extend(pcm)
        self._pending += pcm

        duration_ms = len(pcm) * 1000 // (self._sample_rate * _BYTES_PER_SAMPLE)
        if gap_ms < 0:
            # 중복/역순이어도 pcm은 방금 그대로 덧붙였다 — 되감지 않고 이어붙였을
            # 뿐이므로, 시계는 (틀렸을 수 있는) timestamp_ms가 아니라 실제로
            # 늘어난 바이트만큼만 앞으로 간다.
            self._next_timestamp_ms += duration_ms
        else:
            self._next_timestamp_ms = timestamp_ms + duration_ms
        self._last_timestamp_ms = self._next_timestamp_ms

        outgoing: list[Outgoing] = []
        while len(self._pending) >= self._frame_bytes:
            chunk = self._pending[: self._frame_bytes]
            self._pending = self._pending[self._frame_bytes :]
            ended = self._vad.push(_to_float32(chunk))
            if ended is not None:
                outgoing.extend(self._on_speech_end(ended.start_ms, ended.end_ms))
        return outgoing

    @property
    def stream_duration_ms(self) -> int:
        """스트림이 흐른 시간. 지표의 분모다.

        ClawOps의 통화 길이와 다르다 — 어르신이 받고 나서 Connect가 붙기까지
        틈이 있다. 지표에는 이쪽을 쓴다(설계 3.2).
        """
        return self._last_timestamp_ms

    def _bytes_for(self, duration_ms: int) -> int:
        """프레임 경계에 맞춰 바이트 수를 낸다."""
        samples = int(self._sample_rate * duration_ms / 1000)
        return samples * _BYTES_PER_SAMPLE

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

        # start_ms/end_ms는 StreamingVad가 frame_ms의 배수로만 내놓으므로,
        # sample_rate로 다시 환산하지 않고 frame_length(= vad가 실제로 자른
        # 프레임의 샘플 수)로 프레임 인덱스를 바이트로 되돌린다. 그래야
        # sample_rate * frame_ms / 1000이 정수가 아닌 레이트(예: 11025Hz)에서도
        # push_audio가 실제로 슬라이스한 바이트와 어긋나지 않는다.
        start = (start_ms // self._vad.frame_ms) * self._frame_bytes
        end = (end_ms // self._vad.frame_ms) * self._frame_bytes
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
