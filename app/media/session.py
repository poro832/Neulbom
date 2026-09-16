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

from app.analysis.segments import VadSegment
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


@dataclass(frozen=True)
class MarkMessage:
    """재생 완료를 확인받기 위한 표식.

    우리는 응답 오디오를 한 번에 밀어 넣지만 플랫폼은 20ms씩 재생한다.
    보낸 시각으로 응답 지연을 재면 늘 짧게 나오므로, 앞뒤로 표식을 걸고
    되돌아오는 시점을 AI 발화 구간으로 삼는다(설계 3.2).
    """

    name: str


Outgoing = TextMessage | AudioMessage | MarkMessage


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

        # AI 발화 구간을 mark 왕복으로 잡는다(설계 3.2). turn_index로 이름을
        # 지어 begin/end를 짝짓고, 짝이 안 맞으면 지어내지 않고 세기만 한다.
        self._turn_index = 0
        self._mark_times: dict[str, int] = {}
        self._ai_turns: list[VadSegment] = []
        self._unmatched_marks = 0

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

        # 시계는 recorded 버퍼 길이에서 매번 새로 구한다 — 누적으로 더하면
        # 조각이 작아 duration_ms가 0으로 내림되는 경우(8kHz에서 16바이트,
        # 즉 1ms 미만 조각) 버퍼는 계속 자라는데 시계만 멈춰서, 다음
        # 프레임에서 있지도 않은 갭이 생겼다고 오판하게 된다. 버퍼는 갭까지
        # 이미 침묵으로 채운 실제 오디오이므로 그 길이 자체가 흐른 시간의
        # 진실이고, 매번 거기서 다시 계산하면 어긋날 수가 없다.
        self._next_timestamp_ms = len(self._recorded) * 1000 // (
            self._sample_rate * _BYTES_PER_SAMPLE
        )
        # next_timestamp_ms와 항상 같은 값이지만, 다음 태스크가 재생 마크를
        # 찍는 시각으로 이 이름을 따로 참조하므로 남겨둔다.
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

        recorded 버퍼 길이에서 직접 구한다. 갭은 이미 침묵으로 채워 그
        버퍼에 들어 있으므로 버퍼 길이 자체가 흐른 시간의 진실이다 — 별도로
        누적한 값이면 반올림이 쌓여 버퍼와 어긋날 수 있지만, 이건 매번 같은
        버퍼에서 다시 재는 것이라 어긋날 수가 없다.
        """
        return len(self._recorded) * 1000 // (self._sample_rate * _BYTES_PER_SAMPLE)

    def _bytes_for(self, duration_ms: int) -> int:
        """프레임 경계에 맞춰 바이트 수를 낸다.

        sample_rate가 1000의 배수(8000/16000)면 이 나눗셈이 정확히 떨어진다.
        11025Hz처럼 그렇지 않은 레이트에서는 내림 때문에 gap_ms만큼을 정확히
        채우지 못할 수 있다 — 지금은 지원 레이트가 8000/16000뿐이라 해당
        없지만, 다른 레이트를 추가할 때는 이 지점부터 다시 봐야 한다.
        """
        samples = self._sample_rate * duration_ms // 1000
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
            self._turn_index += 1
            begin = f"turn{self._turn_index}-begin"
            end = f"turn{self._turn_index}-end"
            # 오디오 앞뒤로 표식을 건다. 플랫폼이 순서대로 재생하므로
            # begin이 돌아온 시점이 재생 시작, end가 돌아온 시점이 종료다.
            outgoing.append(MarkMessage(begin))
            outgoing.append(AudioMessage(reply))
            outgoing.append(MarkMessage(end))
        return outgoing

    def on_mark(self, name: str) -> None:
        """표식이 돌아왔다. 시각은 직전 inbound media의 것을 쓴다.

        mark 이벤트에는 타임스탬프가 없고, 벽시계를 쓰면 재현성이 깨진다.
        """
        self._mark_times[name] = self._last_timestamp_ms
        if not name.endswith("-end"):
            return

        begin = name[: -len("-end")] + "-begin"
        start_ms = self._mark_times.pop(begin, None)
        end_ms = self._mark_times.pop(name)
        if start_ms is None:
            # begin이 유실됐다. 구간을 지어내면 응답 지연이 조용히 틀린다.
            self._unmatched_marks += 1
            return
        self._ai_turns.append(VadSegment(start_ms=start_ms, end_ms=end_ms))

    @property
    def ai_turns(self) -> list[VadSegment]:
        """begin/end가 둘 다 돌아온 AI 발화 구간."""
        return list(self._ai_turns)

    @property
    def unmatched_marks(self) -> int:
        """짝이 안 맞은 표식 수. 크면 degraded로 표시한다(설계 8장)."""
        return self._unmatched_marks + len(self._mark_times)


def _to_float32(pcm: bytes) -> np.ndarray:
    return np.frombuffer(pcm, dtype="<i2").astype(np.float32) / _INT16_FULL_SCALE
