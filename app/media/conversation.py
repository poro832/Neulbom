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
import re
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
# 되묻기는 최대한 하지 않는다(2026-10-20 엑스포 현장 피드백). 시끄러운 곳에서는 소음이 빈 전사로 이어지는 일이
# 잦은데, 그때마다 "잘 못 들었어요"를 하면 AI가 어르신 말 위에 얹혀 통화가 더 엉킨다. 그래서 연속으로
# RETRY_AFTER_FAILURES번 못 알아들었을 때만 한 문장으로 되묻고, 한 통화에서 RETRY_PROMPTS의 개수만큼만 한다.
# 그 사이에는 조용히 기다린다 — 어르신이 다시 말하면 정상 흐름으로 돌아온다.
RETRY_AFTER_FAILURES = 3
RETRY_PROMPTS = (
    "죄송한데 잘 못 들었어요, 다시 말씀해 주시겠어요?",
    "전화기를 입 가까이 대고 천천히 말씀해 주시겠어요?",
)

# 전화를 받으면 AI가 먼저 건네는 말. 어르신의 "여보세요"를 기다려 인식하지 않는다 —
# 0.6초짜리 짧은 소리라 전화 음질에서 잘 안 읽히고(2026-10-08 실통화), 그러면 첫
# 마디부터 "잘 못 들었어요"가 나가 통화가 어색하게 시작한다. 같은 문장이라 TTS
# 캐시가 걸려 글자 수 한도(Prosody Free 월 1만 자)도 첫 통화 한 번만 쓴다.
# 열린 질문으로 끝내는 이유: 어르신이 말을 이어 가게 해 발화 비율이 재어진다.
# 한 문장이다. 문장 사이에 음성 합성이 무음을 넣는데, 시끄러운 곳에서는 어르신이 그 틈에 말을 시작해
# 인사와 겹친다(2026-10-20 엑스포 현장 피드백). 질문은 끝에 둔다 — 어르신이 곧바로 대답할 자리다.
GREETING = "안녕하세요 어르신, 늘봄에서 안부 전화 드렸는데 오늘 하루는 어떠세요?"


# 전화를 받자마자 하는 "여보세요?". 첫 인사가 이미 나가고 있으므로 이 말에는 따로 답하지 않는다.
_PICKUP_GREETING = re.compile(r"^(여보세[요여용오]+|여부세요|여보시오|여보)+$")


def _is_pickup_greeting(text: str) -> bool:
    return _PICKUP_GREETING.match(re.sub(r"[\s.,!?~…]+", "", text)) is not None


@dataclass(frozen=True)
class Turn:
    speaker: str  # elder | ai
    text: str
    # 어르신이 AI의 말이 끝나기 전에 끼어들어 답한 턴이다. 모델에게만 알린다(저장되는 기록은 따로 만든다).
    interrupted: bool = False


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
        self._retries_spoken = 0
        # 어르신이 첫 인사에 "여보세요"만 한 횟수. 대본 인사 말고는 아무 말도 하지 않는 데 쓴다.
        self._pickup_greetings = 0

    def greet(self, sample_rate: int) -> bytes:
        """통화가 연결되면 어르신보다 먼저 건네는 인사.

        들려주지 못했으면 기록에 넣지 않는다 — 넣으면 모델이 어르신이 듣지도
        못한 인사를 한 줄 알고 첫 대답에서 다시 인사하거나 엉뚱하게 이어받는다.
        """
        audio_out = self._speak(self._greeting, sample_rate)
        if audio_out:
            self.history.append(Turn("ai", self._greeting))
        return audio_out

    def respond(self, audio: np.ndarray, sample_rate: int, interrupted: bool = False) -> bytes:
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
        if self._pickup_only(said):
            return self._script_greeting_only(sample_rate)
        # 어르신 발화를 먼저 넣어야 모델이 방금 한 말을 보고 답한다.
        self.history.append(Turn("elder", said, interrupted))
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

    def _pickup_only(self, said: str) -> bool:
        """어르신이 전화를 받으며 '여보세요?'만 했는가 — 첫 인사가 나간 뒤, 본격적으로 말하기 전에."""
        if not _is_pickup_greeting(said):
            return False
        if self._pickup_greetings >= 2:
            return False  # 두 번 응했는데도 "여보세요"만 하신다 — 이제는 모델이 받는다
        spoke_greeting = any(turn.speaker == "ai" for turn in self.history)
        elder_said_something = any(turn.speaker == "elder" for turn in self.history)
        return spoke_greeting and not elder_said_something

    def _script_greeting_only(self, sample_rate: int) -> bytes:
        """'여보세요?'에는 모델이 답하지 않는다. 짜여 있는 첫 인사만 들려준다.

        첫 인사는 이미 나갔거나 나가는 중이므로 처음 한 번은 조용히 있는다. 어르신이 인사를 못 들어 한 번 더
        '여보세요?'를 하셨다면 같은 대본을 한 번 다시 들려준다. 그 뒤로는 일반 대화로 넘긴다(계속 같은 말만
        하면 고장 난 것으로 보인다). 기록에는 넣지 않는다 — 인사는 이미 대화 기록에 있다.
        """
        self._pickup_greetings += 1
        logger.info("전화를 받으며 하신 인사에는 대본 인사로만 답한다 횟수=%d", self._pickup_greetings)
        if self._pickup_greetings == 2:
            return self._speak(self._greeting, sample_rate)
        return b""

    def _ask_again(self, sample_rate: int) -> bytes:
        """못 알아들었다. 되묻기는 최대한 하지 않는다 — 연속으로 여러 번 못 알아들었을 때만 한 문장으로 되묻는다."""
        self._consecutive_failures += 1
        if self._consecutive_failures < RETRY_AFTER_FAILURES:
            logger.info("못 알아들었지만 되묻지 않고 기다린다 연속=%d", self._consecutive_failures)
            return b""
        if self._retries_spoken >= len(self._retry_prompts):
            # 되물을 만큼 물었다. 더 말하는 것보다 조용히 기다리는 편이 낫다.
            logger.warning("연속 %d회 못 알아들었다 — 되물음을 마치고 기다린다", self._consecutive_failures)
            return b""
        prompt = self._retry_prompts[self._retries_spoken]
        self._retries_spoken += 1
        # 되물은 뒤에는 다시 처음부터 센다. 곧바로 또 되묻지 않는다.
        self._consecutive_failures = 0
        return self._speak(prompt, sample_rate)

    def _speak(self, text: str, sample_rate: int) -> bytes:
        try:
            return self.voice.synthesize(text, sample_rate)
        except Exception:
            # 통화를 끊지 않는다. 한 턴 침묵하는 것과 전화가 죽는 것은 다르다.
            # AI의 말에는 어르신이 한 말의 내용이 묻어 있다("아침 잘 챙겨 드셔서요").
            # 로그는 오래 남고 넓게 읽히므로 길이만 남긴다.
            logger.exception("음성 합성 실패 — 이 턴은 침묵한다 길이=%d", len(text))
            return b""
