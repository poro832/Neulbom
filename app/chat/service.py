"""AI 채팅 서비스 — 어르신의 글 말동무 대화, 위급한 말 알림, 보호자에게 보일 요약.

세 가지를 지킨다.
  1. **위급한 말의 알림은 AI 모델에도, 하루 한도에도, 글 길이 제한에도 기대지 않는다.** 규칙(`urgent.py`)이 찾고,
     한도·모델 상태를 보기 **전에** 먼저 알린다. 모델이 느리거나 죽어도, 오늘 한도를 다 썼어도 알림과 안내는 나간다.
     (한도를 넘은 위급한 말은 모델을 부르지 않고 안내 문장만 돌려준다 — 요금은 늘지 않는다.)
  2. **보호자에게는 요약만 보인다.** 원문은 보이지 않고 30일 뒤 지운다. 지우기는 대화가 없어도 돈다(`start`).
     요약은 어르신이 공유에 동의하고 보호자가 열 때 처음 만든다 — 동의하지 않은 대화는 요약하지도 않는다.
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
MAX_MESSAGE_CHARS = 300  # 저장하고 모델에 보내는 길이. 위급한 말 찾기는 자르기 전 글 전체에서 한다
MAX_REQUEST_CHARS = 2000  # 이보다 긴 글만 거절한다(앱은 300자까지만 받는다)
MAX_REPLY_CHARS = 600
# 하루 한도를 넘은 뒤에도 위급한 말은 알리고 안내하지만, 저장하는 양에는 상한이 있다. 이 예비분을 넘으면 같은 분류가
# 이미 알려진 말은 저장하지 않고 안내만 돌려준다(저장 용량과, 그 글이 들어갈 요약 모델 요금을 한없이 늘리지 못하게).
URGENT_RESERVE = 20
# 예비분을 넘은 뒤에도 '아직 알리지 못한 분류'의 말은 알림 표시를 남기려고 몇 번 더 저장할 수 있다(알림이 실패하면 표시가
# 남지 않아 다시 시도해야 하므로). 하지만 알림이 계속 실패해도 저장량이 늘지 못하도록, 한도 + 예비분 + 이 수가 절대 상한이다.
URGENT_MARKER_ALLOWANCE = 8
# 요약 모델에 넣는 대화의 상한. 대화가 아무리 길어도 최근 것만 이만큼 넣는다.
SUMMARY_MAX_TURNS = 60
SUMMARY_MAX_CHARS = 8000
URGENT_ALERT_WINDOW_SECONDS = 24 * 3600  # 같은 어르신께 같은 분류의 위급 알림은 하루 한 번
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


# (어르신 번호, 분류) -> 보호자 한 명 이상에게 알림을 남겼는가. 한 명에게도 못 남겼으면 False를 돌려주어야 한다.
UrgentAlerter = Callable[[int, str], bool]


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
        self._stopping = threading.Event()
        self._thread: threading.Thread | None = None
        self._locks: dict[int, threading.Lock] = {}
        self._locks_guard = threading.Lock()

    @property
    def available(self) -> bool:
        return self._model is not None

    def send(self, elder_id: int, text: str) -> ChatReply:
        text = text.strip()
        if not text:
            raise ValueError("빈 말")
        now = self._clock()
        # 위급한 말은 잘리기 전의 글 전체에서 찾는다(긴 글 속에 있어도 놓치지 않는다).
        urgent = detect_urgent(text)

        # '개수 읽기 → 한도와 비교 → 저장'이 한 덩어리여야 한다. 같은 어르신의 요청이 겹쳐도 모두 같은 개수를 보고
        # 통과하지 못하도록 어르신별로 이 구간만 직렬화한다(느린 모델 호출은 자물쇠 밖에서 한다).
        with self._elder_lock(elder_id):
            sent_today = self._store.elder_messages_since(elder_id, now - 86400)
            over_limit = sent_today >= DAILY_LIMIT
            no_model = self._model is None
            if urgent is None:
                if over_limit:
                    raise ChatLimitReached()
                if no_model:
                    raise ChatUnavailable("모델 없음")
            elif sent_today >= DAILY_LIMIT + URGENT_RESERVE:
                # 예비분까지 다 썼다. 이 분류를 이미 알렸거나, 알림이 실패해 표시를 남기려는 시도마저 다 썼다면(절대 상한)
                # 저장도 모델 호출도 알림 시도도 하지 않고 안내만 돌려준다.
                exhausted = sent_today >= DAILY_LIMIT + URGENT_RESERVE + URGENT_MARKER_ALLOWANCE
                if exhausted or self._store.alerted_since(elder_id, now - URGENT_ALERT_WINDOW_SECONDS, urgent.category):
                    return ChatReply(reply=safety_notice(urgent.category), urgent=urgent.category)

            session = self._store.session_for(elder_id, now, SESSION_IDLE_SECONDS)
            message_id = self._store.add_message(
                session, "elder", text[:MAX_MESSAGE_CHARS], now, urgent.category if urgent else None
            )
            if urgent is not None:
                self._alert_guardians(elder_id, message_id, urgent.category, now)

        if urgent is not None and (over_limit or no_model):
            reply = safety_notice(urgent.category)  # 모델을 부르지 않는다 — 안내만 나간다
        else:
            reply = self._ask_model(session)
            if urgent is not None:
                # 안내는 서버가 직접 붙인다 — 모델이 빠뜨리거나 실패해도 어르신은 이 말을 듣는다.
                reply = f"{reply} {safety_notice(urgent.category)}".strip()
            elif not reply:
                raise ChatUnavailable("빈 응답")
        self._store.add_message(session, "ai", reply, self._clock())
        return ChatReply(reply=reply, urgent=urgent.category if urgent else None)

    def _elder_lock(self, elder_id: int) -> threading.Lock:
        with self._locks_guard:
            lock = self._locks.get(elder_id)
            if lock is None:
                lock = self._locks[elder_id] = threading.Lock()
            return lock

    def summaries(self, elder_id: int, *, limit: int = 10) -> list[ChatSummary]:
        """보호자에게 보일 요약(동의 확인은 호출자가 한다). 끝난 대화 덩이가 아직 요약 전이면 지금 만든다."""
        now = self._clock()
        if self._summarizer is not None:
            for session_id in self._store.sessions_to_summarize(elder_id, now - SESSION_IDLE_SECONDS, SUMMARIZE_PER_REQUEST):
                try:
                    summary = self._summarizer.summarize(_limit_for_summary(self._store.transcript(session_id)))
                except Exception:
                    # 실패는 '시도했다'로 표시하지 않는다 — 다음에 열 때 다시 해 본다. 말 내용은 로그에 남기지 않는다.
                    logger.exception("채팅 요약 실패 session_id=%s", session_id)
                    continue
                self._store.save_summary(session_id, summary, getattr(self._summarizer, "model_id", ""), now)
        return self._store.summaries(elder_id, limit)

    def remove_for_elder(self, elder_id: int) -> int:
        return self._store.remove_for_elder(elder_id)

    # ------------------------------------------------------------------ 원문 지우기

    def purge_expired(self) -> int:
        """30일이 지난 대화 원문을 지운다(요약은 남는다). 지운 수. 실패해도 예외를 내지 않는다."""
        try:
            removed = self._store.purge_messages_before(self._clock() - PURGE_AFTER_SECONDS)
        except Exception:
            logger.exception("채팅 원문 정리 실패")
            return 0
        if removed:
            logger.info("30일이 지난 채팅 원문을 지웠다 수=%s", removed)
        return removed

    def start(self) -> None:
        """서버가 뜬 뒤 한 시간마다 원문을 지운다. 대화가 없어도 돈다 — 채팅을 그만둔 어르신의 원문도 30일에 지워야 한다."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stopping.clear()
        self._thread = threading.Thread(target=self._run, name="chat-purger", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stopping.set()
        thread = self._thread
        if thread is None:
            return
        thread.join(timeout=timeout)
        if not thread.is_alive():
            self._thread = None

    def _run(self) -> None:
        while not self._stopping.is_set():
            self.purge_expired()
            self._stopping.wait(PURGE_EVERY_SECONDS)

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
        # 같은 분류는 하루 한 번만 — 다른 분류(예: 가슴 통증 뒤의 자살 표현)는 따로 알린다.
        if self._store.alerted_since(elder_id, now - URGENT_ALERT_WINDOW_SECONDS, category):
            return
        try:
            delivered = self._on_urgent(elder_id, category)
        except Exception:
            logger.exception("위급 알림 실패 elder_id=%s", elder_id)
            return
        if not delivered:
            # 한 보호자에게도 남기지 못했다 — '알렸다'로 표시하지 않아 다음 말에서 다시 시도한다.
            logger.warning("위급 알림을 한 명에게도 남기지 못했다 elder_id=%s category=%s", elder_id, category)
            return
        self._store.mark_alerted(message_id, now)
        logger.info("채팅 위급 알림을 보냈다 elder_id=%s category=%s", elder_id, category)


def _limit_for_summary(turns: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """요약 모델에 넣을 대화: 최근 것부터 SUMMARY_MAX_TURNS개, SUMMARY_MAX_CHARS 글자까지(오래된 것을 버린다)."""
    kept: list[tuple[str, str]] = []
    total = 0
    for speaker, text in reversed(turns[-SUMMARY_MAX_TURNS:]):
        if kept and total + len(text) > SUMMARY_MAX_CHARS:
            break
        kept.append((speaker, text[:SUMMARY_MAX_CHARS]))
        total += len(text)
    kept.reverse()
    return kept
