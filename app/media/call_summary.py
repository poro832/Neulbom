"""통화 요약 — 보호자 앱에 보일 한두 문장 (설계: 통화 요약·원문 공개).

**설명용이다.** 점수·경보는 숫자 규칙만 정하고 이 요약은 거기에 닿지 않는다(설계 3.2).
어르신이 한 말을 전하는 문장만 허용하고, 진단·병명 표현이 섞이면 저장하지 않는다 —
앱이 "무엇이 의심된다"고 말하는 순간 우리가 의사 노릇을 하는 것이다.
"""

from __future__ import annotations

import os
from collections.abc import Sequence

from app.media.conversation import ChatModel, Turn

FORBIDDEN_WORDS = ("우울", "치매", "진단", "증세")

SUMMARY_SYSTEM_PROMPT = """당신은 어르신과 AI의 안부 통화 기록을 보호자에게 전하는 기록자입니다.
- 어르신이 실제로 한 말만 한두 문장으로 전합니다. 팔십 자 안팎, 존댓말("~하셨어요", "~라고 하셨어요").
- 추측, 평가, 조언, 병이나 마음 상태의 판단을 쓰지 않습니다. 무엇이 의심된다고 말하지 않습니다.
- 어르신이 거의 말씀하지 않으셨으면 "통화는 이어졌지만 말씀이 많지 않았어요."라고만 씁니다.
- 이모지, 목록, 따옴표 없이 문장만 씁니다."""


class CallSummarizer:
    def __init__(self, chat: ChatModel, model_id: str) -> None:
        self._chat = chat
        self.model_id = model_id

    def summarize(self, turns: Sequence[tuple[str, str]]) -> str | None:
        """요약 문장. 어르신 발화가 없거나 응답이 비었거나 금지어가 있으면 None.

        모델 호출 실패는 그대로 올린다 — 호출자(ConversationRecorder)가 격리한다.
        """
        if not any(speaker == "elder" and text.strip() for speaker, text in turns):
            return None
        label = {"ai": "AI", "elder": "어르신"}
        dialogue = "\n".join(f"{label.get(s, s)}: {t}" for s, t in turns)
        answer = self._chat.reply([Turn("elder", dialogue)]).strip()
        if not answer or any(word in answer for word in FORBIDDEN_WORDS):
            return None
        return answer


def summarizer_from_env() -> CallSummarizer | None:
    """CLOVA Studio 자격 증명이 있으면 요약기를, 없으면 None(요약 없이 턴만 저장)."""
    from app.media.clova_chat import ClovaChat

    api_key = os.getenv("CLOVA_STUDIO_API_KEY")
    base_url = os.getenv("CLOVA_STUDIO_BASE_URL")
    if not api_key or not base_url:
        return None
    chat = ClovaChat(api_key, base_url, system_prompt=SUMMARY_SYSTEM_PROMPT, max_tokens=160)
    return CallSummarizer(chat, chat.model)
