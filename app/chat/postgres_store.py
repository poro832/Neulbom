"""ChatStore의 Postgres 구현 (`chat_sessions`, `chat_messages` 표)."""

from __future__ import annotations

from app.chat.store import ChatMessage, ChatSummary


class PostgresChatStore:
    def __init__(self, *, pool) -> None:
        self._pool = pool

    def session_for(self, elder_id: int, now: float, idle_seconds: float) -> int:
        with self._pool.connection() as conn:
            row = conn.execute(
                "SELECT session_id FROM chat_sessions "
                "WHERE elder_id = %s AND extract(epoch from last_message_at) >= %s "
                "ORDER BY last_message_at DESC LIMIT 1",
                (elder_id, now - idle_seconds),
            ).fetchone()
            if row is not None:
                return row[0]
            return conn.execute(
                "INSERT INTO chat_sessions (elder_id, started_at, last_message_at) "
                "VALUES (%s, to_timestamp(%s), to_timestamp(%s)) RETURNING session_id",
                (elder_id, now, now),
            ).fetchone()[0]

    def add_message(self, session_id: int, role: str, text: str, now: float, urgent: str | None = None) -> int:
        with self._pool.connection() as conn:
            message_id = conn.execute(
                "INSERT INTO chat_messages (session_id, role, content, urgent, created_at) "
                "VALUES (%s, %s, %s, %s, to_timestamp(%s)) RETURNING message_id",
                (session_id, role, text, urgent, now),
            ).fetchone()[0]
            conn.execute(
                "UPDATE chat_sessions SET last_message_at = to_timestamp(%s) WHERE session_id = %s",
                (now, session_id),
            )
        return message_id

    def history(self, session_id: int, limit: int) -> list[ChatMessage]:
        with self._pool.connection() as conn:
            rows = conn.execute(
                "SELECT role, content, extract(epoch from created_at)::float8 FROM ("
                "  SELECT role, content, created_at, message_id FROM chat_messages "
                "  WHERE session_id = %s ORDER BY message_id DESC LIMIT %s"
                ") t ORDER BY message_id",
                (session_id, limit),
            ).fetchall()
        return [ChatMessage(*row) for row in rows]

    def elder_messages_since(self, elder_id: int, since: float) -> int:
        with self._pool.connection() as conn:
            return conn.execute(
                "SELECT count(*) FROM chat_messages m JOIN chat_sessions s USING (session_id) "
                "WHERE s.elder_id = %s AND m.role = 'elder' AND m.created_at >= to_timestamp(%s)",
                (elder_id, since),
            ).fetchone()[0]

    def alerted_since(self, elder_id: int, since: float) -> bool:
        with self._pool.connection() as conn:
            return (
                conn.execute(
                    "SELECT 1 FROM chat_messages m JOIN chat_sessions s USING (session_id) "
                    "WHERE s.elder_id = %s AND m.alerted_at >= to_timestamp(%s) LIMIT 1",
                    (elder_id, since),
                ).fetchone()
                is not None
            )

    def mark_alerted(self, message_id: int, now: float) -> None:
        with self._pool.connection() as conn:
            conn.execute(
                "UPDATE chat_messages SET alerted_at = to_timestamp(%s) WHERE message_id = %s", (now, message_id)
            )

    def sessions_to_summarize(self, elder_id: int, idle_before: float, limit: int) -> list[int]:
        with self._pool.connection() as conn:
            rows = conn.execute(
                "SELECT s.session_id FROM chat_sessions s "
                "WHERE s.elder_id = %s AND s.summarized_at IS NULL "
                "  AND extract(epoch from s.last_message_at) <= %s "
                "  AND EXISTS (SELECT 1 FROM chat_messages m WHERE m.session_id = s.session_id AND m.role = 'elder') "
                "ORDER BY s.last_message_at DESC LIMIT %s",
                (elder_id, idle_before, limit),
            ).fetchall()
        return [row[0] for row in rows]

    def transcript(self, session_id: int) -> list[tuple[str, str]]:
        with self._pool.connection() as conn:
            rows = conn.execute(
                "SELECT role, content FROM chat_messages WHERE session_id = %s ORDER BY message_id", (session_id,)
            ).fetchall()
        return [(row[0], row[1]) for row in rows]

    def save_summary(self, session_id: int, summary: str | None, model_id: str, now: float) -> None:
        with self._pool.connection() as conn:
            conn.execute(
                "UPDATE chat_sessions SET summary = %s, summary_model = %s, summarized_at = to_timestamp(%s) "
                "WHERE session_id = %s",
                (summary, model_id, now, session_id),
            )

    def summaries(self, elder_id: int, limit: int) -> list[ChatSummary]:
        with self._pool.connection() as conn:
            rows = conn.execute(
                "SELECT session_id, extract(epoch from started_at)::float8, summary FROM chat_sessions "
                "WHERE elder_id = %s AND summary IS NOT NULL ORDER BY started_at DESC LIMIT %s",
                (elder_id, limit),
            ).fetchall()
        return [ChatSummary(*row) for row in rows]

    def purge_messages_before(self, cutoff: float) -> int:
        with self._pool.connection() as conn:
            return conn.execute(
                "DELETE FROM chat_messages WHERE created_at < to_timestamp(%s)", (cutoff,)
            ).rowcount

    def remove_for_elder(self, elder_id: int) -> int:
        with self._pool.connection() as conn:
            removed = conn.execute(
                "DELETE FROM chat_messages WHERE session_id IN (SELECT session_id FROM chat_sessions WHERE elder_id = %s)",
                (elder_id,),
            ).rowcount
            conn.execute("DELETE FROM chat_sessions WHERE elder_id = %s", (elder_id,))
        return removed
