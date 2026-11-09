"""채팅 저장소 규약과 메모리 구현. Postgres 구현은 `postgres_store.py` — 같은 규약 테스트를 통과해야 한다."""

from __future__ import annotations

import itertools
import threading
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ChatMessage:
    role: str  # elder | ai
    text: str
    created_at: float


@dataclass(frozen=True)
class ChatSummary:
    session_id: int
    started_at: float
    summary: str


class ChatStore(Protocol):
    def session_for(self, elder_id: int, now: float, idle_seconds: float) -> int:
        """이어 갈 대화 덩이의 번호. 마지막 말이 idle_seconds 안쪽이면 그 덩이, 아니면 새로 만든다."""
        ...

    def add_message(self, session_id: int, role: str, text: str, now: float, urgent: str | None = None) -> int:
        """말을 저장하고 번호를 돌려준다. 덩이의 마지막 말 시각도 갱신한다."""
        ...

    def history(self, session_id: int, limit: int) -> list[ChatMessage]:
        """그 덩이의 마지막 limit개, 오래된 것부터."""
        ...

    def elder_messages_since(self, elder_id: int, since: float) -> int:
        """since 이후 그 어르신이 보낸 말의 수(하루 한도에 쓴다)."""
        ...

    def alerted_since(self, elder_id: int, since: float, category: str) -> bool:
        """since 이후 그 어르신의 그 분류(urgent) 때문에 위급 알림을 이미 보냈는가."""
        ...

    def mark_alerted(self, message_id: int, now: float) -> None: ...

    def sessions_to_summarize(self, elder_id: int, idle_before: float, limit: int) -> list[int]:
        """끝난(마지막 말이 idle_before 이전) 덩이 중 아직 요약을 시도하지 않았고 어르신의 말이 있는 것."""
        ...

    def transcript(self, session_id: int) -> list[tuple[str, str]]:
        """(화자, 말) 목록. 요약기에게만 준다."""
        ...

    def save_summary(self, session_id: int, summary: str | None, model_id: str, now: float) -> None:
        """요약(없으면 None)을 저장하고 '시도했다'고 표시한다 — None이어도 다시 시도하지 않는다."""
        ...

    def summaries(self, elder_id: int, limit: int) -> list[ChatSummary]:
        """요약이 있는 덩이, 최신순."""
        ...

    def purge_messages_before(self, cutoff: float) -> int:
        """cutoff 이전에 쓴 말(원문)을 지운다. 요약은 남긴다. 지운 수."""
        ...

    def remove_for_elder(self, elder_id: int) -> int:
        """그 어르신의 대화를 모두 지운다. Postgres에서는 CASCADE도 같은 일을 한다."""
        ...


@dataclass
class _Session:
    session_id: int
    elder_id: int
    started_at: float
    last_message_at: float
    summary: str | None = None
    summary_model: str | None = None
    summarized_at: float | None = None


@dataclass
class _Message:
    message_id: int
    session_id: int
    role: str
    text: str
    created_at: float
    urgent: str | None = None
    alerted_at: float | None = None


class InMemoryChatStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._session_ids = itertools.count(1)
        self._message_ids = itertools.count(1)
        self._sessions: dict[int, _Session] = {}
        self._messages: list[_Message] = []

    def session_for(self, elder_id: int, now: float, idle_seconds: float) -> int:
        with self._lock:
            mine = [s for s in self._sessions.values() if s.elder_id == elder_id]
            latest = max(mine, key=lambda s: s.last_message_at, default=None)
            if latest is not None and now - latest.last_message_at <= idle_seconds:
                return latest.session_id
            session = _Session(next(self._session_ids), elder_id, now, now)
            self._sessions[session.session_id] = session
            return session.session_id

    def add_message(self, session_id: int, role: str, text: str, now: float, urgent: str | None = None) -> int:
        with self._lock:
            message = _Message(next(self._message_ids), session_id, role, text, now, urgent)
            self._messages.append(message)
            self._sessions[session_id].last_message_at = now
            return message.message_id

    def history(self, session_id: int, limit: int) -> list[ChatMessage]:
        with self._lock:
            rows = [m for m in self._messages if m.session_id == session_id]
        return [ChatMessage(m.role, m.text, m.created_at) for m in rows[-limit:]]

    def _elder_of(self, session_id: int) -> int:
        return self._sessions[session_id].elder_id

    def elder_messages_since(self, elder_id: int, since: float) -> int:
        with self._lock:
            return sum(
                1
                for m in self._messages
                if m.role == "elder" and m.created_at >= since and self._elder_of(m.session_id) == elder_id
            )

    def alerted_since(self, elder_id: int, since: float, category: str) -> bool:
        with self._lock:
            return any(
                m.alerted_at is not None
                and m.alerted_at >= since
                and m.urgent == category
                and self._elder_of(m.session_id) == elder_id
                for m in self._messages
            )

    def mark_alerted(self, message_id: int, now: float) -> None:
        with self._lock:
            for m in self._messages:
                if m.message_id == message_id:
                    m.alerted_at = now

    def sessions_to_summarize(self, elder_id: int, idle_before: float, limit: int) -> list[int]:
        with self._lock:
            ids = [
                s.session_id
                for s in sorted(self._sessions.values(), key=lambda s: s.last_message_at, reverse=True)
                if s.elder_id == elder_id
                and s.summarized_at is None
                and s.last_message_at <= idle_before
                and any(m.session_id == s.session_id and m.role == "elder" for m in self._messages)
            ]
        return ids[:limit]

    def transcript(self, session_id: int) -> list[tuple[str, str]]:
        with self._lock:
            return [(m.role, m.text) for m in self._messages if m.session_id == session_id]

    def save_summary(self, session_id: int, summary: str | None, model_id: str, now: float) -> None:
        with self._lock:
            session = self._sessions[session_id]
            session.summary = summary
            session.summary_model = model_id
            session.summarized_at = now

    def summaries(self, elder_id: int, limit: int) -> list[ChatSummary]:
        with self._lock:
            rows = [
                s
                for s in sorted(self._sessions.values(), key=lambda s: s.started_at, reverse=True)
                if s.elder_id == elder_id and s.summary
            ]
        return [ChatSummary(s.session_id, s.started_at, s.summary or "") for s in rows[:limit]]

    def purge_messages_before(self, cutoff: float) -> int:
        with self._lock:
            before = len(self._messages)
            self._messages = [m for m in self._messages if m.created_at >= cutoff]
            return before - len(self._messages)

    def remove_for_elder(self, elder_id: int) -> int:
        with self._lock:
            gone = {s.session_id for s in self._sessions.values() if s.elder_id == elder_id}
            before = len(self._messages)
            self._messages = [m for m in self._messages if m.session_id not in gone]
            for session_id in gone:
                del self._sessions[session_id]
            return before - len(self._messages)
