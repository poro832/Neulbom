"""통화 속 약 복용 확인 — 어르신이 한 말을 셋으로만 나눈다 (설계: 약 복용 확인).

**진단이 아니다.** 어르신이 약을 먹었다/안 먹었다고 직접 말했는지만 가린다. 약 이야기가
없거나 모호하면 `unknown`이고, 모델이 셋 밖의 말을 해도 `unknown`으로만 저장한다.
점수·경보에는 닿지 않는다(설계 3.2).
"""

from __future__ import annotations

import os
from collections.abc import Sequence

from app.api.call_content import MEDICATION_STATUSES
from app.media.conversation import ChatModel, Turn

UNKNOWN = "unknown"

MEDICATION_SYSTEM_PROMPT = """당신은 어르신과 AI의 안부 통화 기록에서 한 가지만 가려내는 기록자입니다.
어르신이 오늘 약을 먹었다고 직접 말했으면 taken, 먹지 않았다고(깜빡했다, 아직이다 등) 직접 말했으면 not_taken, 약 이야기가 없거나 분명하지 않으면 unknown 이라고만 답합니다.
- 영어 단어 하나(taken, not_taken, unknown)만 쓰고 다른 말은 쓰지 않습니다.
- 추측하지 않습니다. 어르신이 한 말만 근거로 삼고, AI가 한 말은 근거로 삼지 않습니다.
- 건강이나 병에 대한 판단을 하지 않습니다."""


def _normalize(answer: str) -> str:
    word = answer.strip().strip(".\"'`").lower()
    return word if word in MEDICATION_STATUSES else UNKNOWN


class MedicationClassifier:
    def __init__(self, chat: ChatModel, model_id: str) -> None:
        self._chat = chat
        self.model_id = model_id

    def classify(self, turns: Sequence[tuple[str, str]]) -> str | None:
        """taken | not_taken | unknown. 어르신 발화가 없으면 None(저장하지 않는다).

        모델 호출 실패는 그대로 올린다 — 호출자(ConversationRecorder)가 격리한다.
        """
        if not any(speaker == "elder" and text.strip() for speaker, text in turns):
            return None
        label = {"ai": "AI", "elder": "어르신"}
        dialogue = "\n".join(f"{label.get(s, s)}: {t}" for s, t in turns)
        return _normalize(self._chat.reply([Turn("elder", dialogue)]))


def classifier_from_env() -> MedicationClassifier | None:
    """CLOVA Studio 자격 증명이 있으면 분류기를, 없으면 None(복용 확인 없이 턴·요약만 저장)."""
    from app.media.clova_chat import ClovaChat

    api_key = os.getenv("CLOVA_STUDIO_API_KEY")
    base_url = os.getenv("CLOVA_STUDIO_BASE_URL")
    if not api_key or not base_url:
        return None
    # 답은 영어 단어 하나라 토큰을 아주 작게, 흔들리지 않게 온도를 낮게 둔다.
    chat = ClovaChat(
        api_key, base_url, system_prompt=MEDICATION_SYSTEM_PROMPT, max_tokens=12, temperature=0.1
    )
    return MedicationClassifier(chat, chat.model)
