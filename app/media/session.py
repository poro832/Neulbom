"""한 통화의 상태. 전송 수단을 모른다 (앱 통화 설계 3장).

바이트를 받아 나가야 할 메시지를 돌려주는 구조라 소켓 없이 테스트된다.
전화망 채널(Asterisk AudioSocket)이 붙을 때도 프레임 출처만 다르고
이 클래스는 그대로 재사용된다.
"""

from __future__ import annotations

import logging
import re
import secrets
import wave
from dataclasses import dataclass
from datetime import datetime, timezone
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

        # 유실을 메우려고 지어낸 침묵의 총량. 녹음에 들어 있지만 우리가 실제로
        # 받은 오디오는 아니다 — 지표의 분모에는 들어가면서 분자에는 안 들어가,
        # 이 값이 커질수록 발화 비율이 조용히 0으로 끌려간다. 그래서 따로 센다.
        self._filled_gap_ms = 0

        # AI 발화 구간을 mark 왕복으로 잡는다(설계 3.2). turn_index로 이름을
        # 지어 begin/end를 짝짓고, 짝이 안 맞으면 지어내지 않고 세기만 한다.
        self._turn_index = 0
        self._mark_times: dict[str, int] = {}
        # 결론이 난 mark 이름들 — 성공적으로 짝지어졌거나(둘 다) 끝내 짝을
        # 찾지 못해 unmatched로 센 쪽(end만). 통신망은 mark를 다시 보낼 수
        # 있으므로, 이미 처리한 이름이 또 오면 새 정보로 취급하지 않는다.
        self._resolved_marks: set[str] = set()
        self._ai_turns: list[VadSegment] = []
        self._unmatched_marks = 0

        # 녹음 파일 이름을 여기서 한 번만 정한다. finish가 언제 불리든 같은
        # 파일을 가리켜야 하기 때문이다.
        self._recording_name = _recording_name(call_id)

    @property
    def call_id(self) -> str:
        return self._call_id

    def push_audio(self, pcm: bytes, timestamp_ms: int) -> list[Outgoing]:
        """PCM16 LE 한 덩이를 그 시작 시각과 함께 밀어 넣는다.

        시각은 전송 계층이 준 것을 그대로 쓴다. 벽시계를 쓰면 네트워크
        지연이 섞여 들어가 같은 통화를 다시 분석해도 다른 값이 나온다.

        timestamp_ms는 이미 검증된 값이어야 한다. 아래에서 갭만큼 침묵을
        할당하므로, 검사 없이 사업자가 준 값을 그대로 흘려보내면 프레임
        하나로 메모리를 통째로 요구하게 된다 — 그 문은 호출부인
        stream_server._push가 지킨다(MAX_GAP_MS).
        """
        gap_ms = timestamp_ms - self._next_timestamp_ms
        if gap_ms < 0:
            # 중복이거나 순서가 뒤집혔다 — 이 바이트가 가리키는 시간대는 이미
            # 버퍼에 있다. 그런데도 붙이면 녹음이 통화보다 길어져 그 뒤 모든
            # 위치가 밀린다('샘플 위치 = 통화 내 시각'이 이 프로젝트의 전제).
            # 게다가 시계를 버퍼 길이에서 매번 다시 구하는 구조라, 붙이는
            # 순간 시계가 실제보다 앞서가 버려 바로 뒤에 오는 진짜 갭을
            # 실제보다 작게 계산해 덜 채우게 된다(R10 번복 — 조용히 붙이지
            # 않고 통째로 버린다).
            logger.warning(
                "타임스탬프가 뒤로 갔다 — 버린다 call_id=%s gap=%dms",
                self._call_id,
                gap_ms,
            )
            return []

        if gap_ms > 0:
            filler = b"\x00" * self._bytes_for(gap_ms)
            self._recorded.extend(filler)
            self._pending += filler
            self._filled_gap_ms += gap_ms

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
    def filled_gap_ms(self) -> int:
        """이 통화에서 지어낸 침묵의 총량.

        호출부가 상한을 걸 수 있게 내놓는다. 프레임 하나의 갭에만 상한이
        있으면 매 프레임이 다시 상한만큼 앞설 수 있어 총량은 얼마든지
        걸어 올릴 수 있다 — 상한이 총량에 붙어야 상한이다.
        """
        return self._filled_gap_ms

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

        그래서 파일 이름이 call_id만이어서는 안 됐다. call_id는 메모리
        저장소의 itertools.count(1)에서 나오고 그 카운터는 프로세스가
        재시작하면 1부터 다시 센다 — 이튿날 첫 통화가 전날 첫 통화의 녹음을
        말없이 덮어썼다. 지워진 것은 어제 어르신의 통화다.
        """
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / self._recording_name
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
        start_offset = (start_ms // self._vad.frame_ms) * self._frame_bytes
        end_offset = (end_ms // self._vad.frame_ms) * self._frame_bytes
        turn = _to_float32(bytes(self._recorded[start_offset:end_offset]))

        try:
            reply = self._responder.respond(turn, self._sample_rate)
        except Exception:
            # 응답 하나 실패했다고 통화를 끊으면 어르신은 영문을 모른다.
            logger.exception("응답 생성 실패 — 통화는 유지한다 call_id=%s", self._call_id)
            return outgoing

        if reply:
            self._turn_index += 1
            begin_mark = f"turn{self._turn_index}-begin"
            end_mark = f"turn{self._turn_index}-end"
            # 오디오 앞뒤로 표식을 건다. 플랫폼이 순서대로 재생하므로
            # begin이 돌아온 시점이 재생 시작, end가 돌아온 시점이 종료다.
            outgoing.append(MarkMessage(begin_mark))
            outgoing.append(AudioMessage(reply))
            outgoing.append(MarkMessage(end_mark))
        return outgoing

    def on_mark(self, name: str) -> None:
        """표식이 돌아왔다. 시각은 직전 inbound media의 것을 쓴다.

        mark 이벤트에는 타임스탬프가 없고, 벽시계를 쓰면 재현성이 깨진다.
        """
        if name in self._resolved_marks:
            # 이미 결론이 난 mark(짝이 맞아 구간으로 확정됐거나, 끝내 짝을
            # 못 찾아 unmatched로 이미 센 것)가 다시 왔다. 통신망 재전송은
            # 새로운 사실이 아니므로 여기서 또 세면 멀쩡히 잡힌 턴이 조용히
            # '열화'로 잘못 표시된다 — 그래서 조용히 버린다.
            return

        if name in self._mark_times:
            # 짝(-end)이 오기 전에 같은 mark가 또 왔다. 나중 시각으로
            # 덮어쓰면 시작/종료 시각이 조용히 틀려도 아무 신호가 없다 —
            # 이 프로젝트가 절대 하지 않기로 한, 모르는 값을 지어내는 것과
            # 같다. 그래서 먼저 온 시각을 지키고, 대신 이상 신호는
            # unmatched_marks로 드러낸다.
            self._unmatched_marks += 1
            return

        self._mark_times[name] = self._last_timestamp_ms
        if not name.endswith("-end"):
            return

        begin = name[: -len("-end")] + "-begin"
        self._resolved_marks.add(name)
        start_ms = self._mark_times.pop(begin, None)
        end_ms = self._mark_times.pop(name)
        if start_ms is None:
            # begin이 유실됐다. 구간을 지어내면 응답 지연이 조용히 틀린다.
            self._unmatched_marks += 1
            return
        self._resolved_marks.add(begin)
        # end_ms가 start_ms보다 앞설 수 없다: 시계는 recorded 버퍼 길이에서만
        # 구해지고 그 버퍼는 절대 줄지 않으므로, begin을 찍은 뒤에 늘어난
        # 시계로만 end를 찍을 수 있다. VadSegment 자체는 이를 강제하지
        # 않으므로 그 근거를 여기 남긴다.
        self._ai_turns.append(VadSegment(start_ms=start_ms, end_ms=end_ms))

    @property
    def ai_turns(self) -> list[VadSegment]:
        """begin/end가 둘 다 돌아온 AI 발화 구간."""
        return list(self._ai_turns)

    @property
    def unmatched_marks(self) -> int:
        """짝이 안 맞은 표식 수. 크면 degraded로 표시한다(설계 8장)."""
        return self._unmatched_marks + len(self._mark_times)


def _recording_name(call_id: str) -> str:
    """이 통화의 녹음 파일 이름. 프로세스 수명에 기대지 않고 유일하다.

    UTC 시각이 날짜가 다른 통화를 가르고, 짧은 난수가 같은 초에 시작한
    통화(재시작 직후 같은 call_id가 다시 나오는 경우)까지 가른다. 시각을
    앞에 두지 않고 call_id를 앞에 두는 이유는, 사람이 파일 목록에서 통화를
    call_id로 찾기 때문이다.
    """
    # call_id는 레지스트리가 준 문자열이다. 지금은 우리 API가 넣은 숫자뿐이지만
    # 파일 이름에 그대로 넣는 값이므로 경로로 해석될 수 있는 문자는 지운다.
    safe_id = re.sub(r"[^A-Za-z0-9_-]", "_", call_id) or "unknown"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    return f"{safe_id}-{stamp}-{secrets.token_hex(3)}.wav"


def _to_float32(pcm: bytes) -> np.ndarray:
    return np.frombuffer(pcm, dtype="<i2").astype(np.float32) / _INT16_FULL_SCALE
