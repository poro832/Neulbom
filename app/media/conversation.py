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
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Protocol

import numpy as np

logger = logging.getLogger(__name__)


class TooShortSound(Exception):
    """인식기가 '소리가 너무 짧다'고 거절했다.

    **못 알아들은 것과 다르다.** 숨소리나 기침 같은 짧은 소리는 말이 아니라
    소음이고, 거기에 "죄송해요, 잘 못 들었어요"라고 되묻는 건 어르신께
    이상하다. 되묻지 않고 조용히 넘기며 실패 횟수에도 세지 않는다.
    """

# 전사가 비었을 때 되묻는 말. 연속 실패 횟수에 따라 단계가 오르고, 매번 다르다.
#
# 한 번도 안 되물으면 어르신은 무시당했다고 느끼고, 같은 문장을 반복하면 고장 난
# 기계가 된다(2026-10-06 실통화에서 '연속 5회 못 알아들었다'까지 갔고, 3회째부터
# 침묵해서 어르신이 '고장'으로 느꼈다). 그래서 단계마다 다르게 말한다.
#   1단계: 가볍게 다시 청한다.
#   2단계: 실제로 도움이 되는 안내를 한다 — 전화기를 입 가까이 대고 천천히.
#   3단계: 기다리겠다고 말한다. 이후로는 더 말하지 않고, 어르신이 다시 말을 걸면
#          그때 정상 흐름으로 돌아온다.
# 단계 수(3)에 근거는 없다 — 실제 통화를 들어 보고 정할 숫자다. 대화 예절이라
# 틀려도 점수가 틀리지는 않는다.
RETRY_PROMPTS = (
    "죄송해요, 잘 못 들었어요. 다시 말씀해 주시겠어요?",
    "전화기를 입 가까이 대고 천천히 말씀해 주시겠어요?",
    "괜찮아요, 편하실 때 말씀해 주세요. 기다리고 있을게요.",
)

# 전화를 받으면 AI가 먼저 건네는 말. 어르신의 "여보세요"를 기다려 인식하지 않는다 —
# 0.6초짜리 짧은 소리라 전화 음질에서 잘 안 읽히고(2026-10-08 실통화), 그러면 첫
# 마디부터 "잘 못 들었어요"가 나가 통화가 어색하게 시작한다. 같은 문장이라 TTS
# 캐시가 걸려 글자 수 한도(Prosody Free 월 1만 자)도 첫 통화 한 번만 쓴다.
# 열린 질문으로 끝내는 이유: 어르신이 말을 이어 가게 해 발화 비율이 재어진다.
GREETING = "안녕하세요, 어르신. 늘봄에서 안부 전화 드렸어요. 오늘 하루는 어떻게 보내고 계세요?"


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
        retry_prompts: Sequence[str] = RETRY_PROMPTS,
        greeting: str = GREETING,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        # 주입한 협력자는 공개한다 — 조립부가 무엇을 끼웠는지 확인할 수
        # 있어야 TTS 벤더를 바꿔도 조립부만 손대면 된다는 것을 테스트로
        # 고정할 수 있다.
        self.stt = stt
        self.chat = chat
        self.voice = voice
        self._retry_prompts = tuple(retry_prompts)
        self._greeting = greeting
        # 단계별 걸린 시간을 재는 시계. 점수 계산에는 닿지 않고 로그에만 쓴다.
        self._clock = clock
        self.history: list[Turn] = []
        self._consecutive_failures = 0

    def greet(self, sample_rate: int) -> bytes:
        """통화가 연결되면 어르신보다 먼저 건네는 인사.

        들려주지 못했으면 기록에 넣지 않는다 — 넣으면 모델이 어르신이 듣지도
        못한 인사를 한 줄 알고 첫 대답에서 다시 인사하거나 엉뚱하게 이어받는다.
        """
        audio_out = self._speak(self._greeting, sample_rate)
        if audio_out:
            self.history.append(Turn("ai", self._greeting))
        return audio_out

    def respond(self, audio: np.ndarray, sample_rate: int) -> bytes:
        started = self._clock()
        try:
            said = self.stt.transcribe(audio, sample_rate).strip()
        except TooShortSound:
            logger.info(
                "너무 짧은 소리 — 되묻지 않고 넘긴다 오디오=%.1f초",
                audio.size / sample_rate,
            )
            return b""
        except Exception:
            logger.exception("전사 실패 — 이 턴은 넘어간다")
            return b""

        # 몇 초를 보내 몇 글자가 돌아왔는지만 남긴다. 내용은 남기지 않는다 —
        # 어르신의 말이고, 로그는 오래 남고 넓게 읽힌다. 되묻기가 나왔을 때
        # "소리가 너무 짧았나, 작았나, 인식이 비었나"를 가르려면 이 숫자가 필요하다.
        logger.info(
            "턴 인식 오디오=%.1f초 글자=%d", audio.size / sample_rate, len(said)
        )

        if not said:
            return self._ask_again(sample_rate)

        self._consecutive_failures = 0
        # 어르신 발화를 먼저 넣어야 모델이 방금 한 말을 보고 답한다.
        self.history.append(Turn("elder", said))
        transcribed = self._clock()

        try:
            reply = self.chat.reply(self.history).strip()
        except Exception:
            logger.exception("응답 생성 실패 — 이 턴은 침묵한다")
            return b""

        if not reply:
            return b""
        generated = self._clock()

        audio_out = self._speak(reply, sample_rate)
        spoken = self._clock()
        # 말이 끝난 뒤 AI가 입을 열기까지의 대기 중 우리가 쓰는 시간이다(여기에
        # 말 끝 판정 0.8초와 전화망 재생 지연이 더해진다). 줄일 곳을 찾으려면
        # 어느 단계가 긴지 알아야 한다.
        logger.info(
            "턴 처리 시간 인식=%dms 생성=%dms 합성=%dms",
            (transcribed - started) * 1000,
            (generated - transcribed) * 1000,
            (spoken - generated) * 1000,
        )
        if audio_out:
            # 들려주지 못한 말은 기록에 넣지 않는다. 넣으면 모델이 어르신이
            # 듣지도 못한 문장을 이어받아 다음 말을 만들고, 대화가 어긋난다.
            self.history.append(Turn("ai", reply))
        return audio_out

    def _ask_again(self, sample_rate: int) -> bytes:
        """못 알아들었다. 연속 실패 횟수에 맞는 단계의 말을 한다."""
        self._consecutive_failures += 1
        if self._consecutive_failures > len(self._retry_prompts):
            # 안내를 끝까지 했다. 더 말하는 것보다 조용히 기다리는 편이 낫다.
            logger.warning(
                "연속 %d회 못 알아들었다 — 안내를 마치고 기다린다",
                self._consecutive_failures,
            )
            return b""
        return self._speak(
            self._retry_prompts[self._consecutive_failures - 1], sample_rate
        )

    def _speak(self, text: str, sample_rate: int) -> bytes:
        try:
            return self.voice.synthesize(text, sample_rate)
        except Exception:
            # 통화를 끊지 않는다. 한 턴 침묵하는 것과 전화가 죽는 것은 다르다.
            # AI의 말에는 어르신이 한 말의 내용이 묻어 있다("아침 잘 챙겨 드셔서요").
            # 로그는 오래 남고 넓게 읽히므로 길이만 남긴다.
            logger.exception("음성 합성 실패 — 이 턴은 침묵한다 길이=%d", len(text))
            return b""
