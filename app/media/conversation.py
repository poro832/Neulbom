"""자율 대화 — 한 턴을 STT · LLM · TTS로 엮는다 (Responder 규약 구현).

셋 다 규약으로만 받는다. CLOVA든 AWS든 무엇을 쓰든 이 파일은 안 바뀌고,
계정도 키도 없이 대화의 규칙 전체가 테스트로 검증된다. 고정 응답
(CannedResponder)은 계정이 없는 동안의 임시방편이지 제품이 아니다 —
제품은 여기다.

**여기서 모으는 전사는 점수에 쓰지 않는다.** 실시간 전사는 프레임이 어떻게
잘렸느냐에 따라 달라지므로, 같은 통화를 다시 돌리면 다른 글이 나오고 그러면
부정 표현 개수가 흔들려 점수가 재현되지 않는다. 점수용 전사는 통화가 끝난
뒤 저장된 녹음으로 다시 만든다(설계 3.2 — 스트리밍 VAD 판정을 쓰지 않는
것과 같은 이유다). 여기 쌓이는 기록은 보호자에게 보여줄 대화 내용이다.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

import numpy as np

logger = logging.getLogger(__name__)

# 전사가 비었을 때 되묻는 횟수. 한 번도 안 되물으면 어르신은 무시당했다고
# 느끼고, 계속 되물으면 같은 문장만 반복하는 고장난 기계가 된다.
#
# 2라는 값에 근거는 없다 — 실제 통화를 들어 보고 정해야 하는 숫자다. 지금
# 정하는 이유는 판정 기준이 아니라 대화 예절이라서다. 점수에 쓰이는 임계값과
# 달리 이건 틀려도 숫자가 틀리지 않는다.
MAX_RETRIES = 2

RETRY_PROMPT = "죄송해요, 잘 못 들었어요. 다시 말씀해 주시겠어요?"


@dataclass(frozen=True)
class Turn:
    speaker: str  # elder | ai
    text: str


class SpeechToText(Protocol):
    def transcribe(self, audio: np.ndarray, sample_rate: int) -> str:
        """한 턴의 발화를 글로 옮긴다. 못 알아들었으면 빈 문자열."""
        ...


class ChatModel(Protocol):
    def reply(self, history: Sequence[Turn]) -> str:
        """지금까지의 대화를 보고 다음 말을 만든다."""
        ...


class VoiceSynthesizer(Protocol):
    def synthesize(self, text: str, sample_rate: int) -> bytes:
        """텍스트를 PCM16 LE 바이트로. 빈 바이트는 들려줄 것이 없다는 뜻."""
        ...


class ConversationResponder:
    """Responder 규약 구현. CallSession은 이 클래스의 존재를 모른다."""

    def __init__(
        self,
        *,
        stt: SpeechToText,
        chat: ChatModel,
        voice: VoiceSynthesizer,
        max_retries: int = MAX_RETRIES,
        retry_prompt: str = RETRY_PROMPT,
    ) -> None:
        self._stt = stt
        self._chat = chat
        self._voice = voice
        self._max_retries = max_retries
        self._retry_prompt = retry_prompt
        self.history: list[Turn] = []
        self._consecutive_failures = 0

    def respond(self, audio: np.ndarray, sample_rate: int) -> bytes:
        try:
            said = self._stt.transcribe(audio, sample_rate).strip()
        except Exception:
            logger.exception("전사 실패 — 이 턴은 넘어간다")
            return b""

        if not said:
            return self._ask_again(sample_rate)

        self._consecutive_failures = 0
        # 어르신 발화를 먼저 넣어야 모델이 방금 한 말을 보고 답한다.
        self.history.append(Turn("elder", said))

        try:
            reply = self._chat.reply(self.history).strip()
        except Exception:
            logger.exception("응답 생성 실패 — 이 턴은 침묵한다")
            return b""

        if not reply:
            return b""

        audio_out = self._speak(reply, sample_rate)
        if audio_out:
            # 들려주지 못한 말은 기록에 넣지 않는다. 넣으면 모델이 어르신이
            # 듣지도 못한 문장을 이어받아 다음 말을 만들고, 대화가 어긋난다.
            self.history.append(Turn("ai", reply))
        return audio_out

    def _ask_again(self, sample_rate: int) -> bytes:
        """못 알아들었다. 몇 번까지만 되묻는다."""
        self._consecutive_failures += 1
        if self._consecutive_failures > self._max_retries:
            # 같은 문장을 계속 반복하느니 잠자코 있는 편이 낫다. 어르신이
            # 다시 말을 걸면 그때 정상 흐름으로 돌아온다.
            logger.warning(
                "연속 %d회 못 알아들었다 — 되묻기를 멈춘다",
                self._consecutive_failures,
            )
            return b""
        return self._speak(self._retry_prompt, sample_rate)

    def _speak(self, text: str, sample_rate: int) -> bytes:
        try:
            return self._voice.synthesize(text, sample_rate)
        except Exception:
            # 통화를 끊지 않는다. 한 턴 침묵하는 것과 전화가 죽는 것은 다르다.
            logger.exception("음성 합성 실패 — 이 턴은 침묵한다 text=%r", text[:60])
            return b""
