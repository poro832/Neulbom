"""AI 채팅 서비스 — 어르신의 글 말동무 대화, 위급한 말 알림, 보호자에게 보일 요약.

세 가지를 지킨다.
  1. **위급한 말의 알림은 AI 모델에 기대지 않는다.** 규칙(`urgent.py`)이 찾고, 모델 호출보다 **먼저** 알린다.
     모델이 느리거나 죽어도 알림과 안내는 나간다.
  2. **보호자에게는 요약만 보인다.** 원문은 보이지 않고 30일 뒤 지운다. 요약은 어르신이 공유에 동의하고
     보호자가 열 때 처음 만든다 — 동의하지 않은 대화는 요약하지도 않는다.
  3. **점수에 닿지 않는다.** 이 대화는 위험 점수 계산에 들어가지 않는다.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from app.chat.store import ChatStore, ChatSummary
from app.chat.urgent import detect_urgent, safety_notice
from app.media.conversation import ChatModel, Turn

logger = logging.getLogger(__name__)

SESSION_IDLE_SECONDS = 30 * 60  # 마지막 말 뒤 30분 조용하면 대화가 끝난 것이다
HISTORY_LIMIT = 20  # 모델에게 보이는 최근 말의 수(비용과 길이를 막는다)
DAILY_LIMIT = 200  # 어르신 한 명이 하루에 보낼 수 있는 말(Bedrock 요금 사고를 막는 안전망)
MAX_MESSAGE_CHARS = 300
MAX_REPLY_CHARS = 600
URGENT_ALERT_WINDOW_SECONDS = 24 * 3600  # 같은 어르신께 위급 알림은 하루 한 번
SUMMARIZE_PER_REQUEST = 3  # 보호자가 한 번 열 때 새로 요약하는 대화 덩이의 최대 수
PURGE_AFTER_SECONDS = 30 * 24 * 3600
PURGE_EVERY_SECONDS = 3600


class ChatUnavailable(Exception):
    """대화를 만들 수 없다(모델이 없거나 응답하지 못했다)."""


class ChatLimitReached(Exception):
    """오늘 보낼 수 있는 말을 다 썼다."""


@dataclass(frozen=True)
class ChatReply:
    reply: str
    urgent: str | None  # 위급한 표현으로 잡힌 분류. 없으면 None


UrgentAlerter = Callable[[int, str], None]


class ChatService:
    def __init__(
        self,
        *,
        store: ChatStore,
        model: ChatModel | None,
        summarizer=None,
        on_urgent: UrgentAlerter | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._store = store
        self._model = model
        self._summarizer = summarizer
        self._on_urgent = on_urgent
        self._clock = clock
        self._last_purge = 0.0
        self._purge_lock = threading.Lock()

    @property
    def available(self) -> bool:
        return self._model is not None

    def send(self, elder_id: int, text: str) -> ChatReply:
        text = text.strip()
        if not text:
            raise ValueError("빈 말")
        if self._model is None:
            raise ChatUnavailable("모델 없음")
        now = self._clock()
        self._purge_if_due(now)
        if self._store.elder_messages_since(elder_id, now - 86400) >= DAILY_LIMIT:
            raise ChatLimitReached()

        urgent = detect_urgent(text)
        session = self._store.session_for(elder_id, now, SESSION_IDLE_SECONDS)
        message_id = self._store.add_message(session, "elder", text, now, urgent.category if urgent else None)
        if urgent is not None:
            self._alert_guardians(elder_id, message_id, urgent.category, now)

        reply = self._ask_model(session)
        if urgent is not None:
            # 안내는 서버가 직접 붙인다 — 모델이 빠뜨리거나 실패해도 어르신은 이 말을 듣는다.
            reply = f"{reply} {safety_notice(urgent.category)}".strip()
        elif not reply:
            raise ChatUnavailable("빈 응답")
        self._store.add_message(session, "ai", reply, self._clock())
        return ChatReply(reply=reply, urgent=urgent.category if urgent else None)

    def summaries(self, elder_id: int, *, limit: int = 10) -> list[ChatSummary]:
        """보호자에게 보일 요약(동의 확인은 호출자가 한다). 끝난 대화 덩이가 아직 요약 전이면 지금 만든다."""
        now = self._clock()
        if self._summarizer is not None:
            for session_id in self._store.sessions_to_summarize(elder_id, now - SESSION_IDLE_SECONDS, SUMMARIZE_PER_REQUEST):
                try:
                    summary = self._summarizer.summarize(self._store.transcript(session_id))
                except Exception:
                    # 실패는 '시도했다'로 표시하지 않는다 — 다음에 열 때 다시 해 본다. 말 내용은 로그에 남기지 않는다.
                    logger.exception("채팅 요약 실패 session_id=%s", session_id)
                    continue
                self._store.save_summary(session_id, summary, getattr(self._summarizer, "model_id", ""), now)
        return self._store.summaries(elder_id, limit)

    def remove_for_elder(self, elder_id: int) -> None:
        self._store.remove_for_elder(elder_id)

    # ------------------------------------------------------------------ 안쪽

    def _ask_model(self, session_id: int) -> str:
        turns = [Turn(m.role, m.text) for m in self._store.history(session_id, HISTORY_LIMIT)]
        try:
            reply = self._model.reply(turns)  # type: ignore[union-attr]
        except Exception:
            # 말 내용은 로그에 남기지 않는다(어르신의 사적인 대화다).
            logger.exception("채팅 응답 생성 실패 session_id=%s", session_id)
            return ""
        reply = (reply or "").strip()
        return reply[:MAX_REPLY_CHARS]

    def _alert_guardians(self, elder_id: int, message_id: int, category: str, now: float) -> None:
        if self._on_urgent is None:
            return
        if self._store.alerted_since(elder_id, now - URGENT_ALERT_WINDOW_SECONDS):
            return  # 오늘 이미 알렸다 — 같은 말이 반복돼도 알림이 쌓이지 않는다
        try:
            self._on_urgent(elder_id, category)
        except Exception:
            logger.exception("위급 알림 실패 elder_id=%s", elder_id)
            return
        self._store.mark_alerted(message_id, now)
        logger.info("채팅 위급 알림을 보냈다 elder_id=%s category=%s", elder_id, category)

    def _purge_if_due(self, now: float) -> None:
        with self._purge_lock:
            if now - self._last_purge < PURGE_EVERY_SECONDS:
                return
            self._last_purge = now
        try:
            removed = self._store.purge_messages_before(now - PURGE_AFTER_SECONDS)
            if removed:
                logger.info("30일이 지난 채팅 원문을 지웠다 수=%s", removed)
        except Exception:
            logger.exception("채팅 원문 정리 실패")
