"""통화 내용 저장소 — Postgres.

InMemoryCallContent와 같은 규약이다. 둘이 갈라지지 않게 tests/test_call_content_contract.py가
같은 테스트를 양쪽에 돌린다. 저장 시각은 시계에서 받아 `to_timestamp`로 넣는다(규약 테스트가
31일을 흉내낼 수 있게).
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence

from app.api.call_content import StoredTurn


class PostgresCallContent:
    def __init__(self, *, pool, clock: Callable[[], float] = time.time) -> None:
        self._pool = pool
        self._clock = clock

    def save_turns(self, call_id: int, turns: Sequence[tuple[str, str]]) -> None:
        now = self._clock()
        with self._pool.connection() as conn:
            conn.execute("DELETE FROM call_turns WHERE call_id = %s", (call_id,))
            for seq, (speaker, text) in enumerate(turns):
                conn.execute(
                    "INSERT INTO call_turns (call_id, seq, speaker, text, created_at) "
                    "VALUES (%s, %s, %s, %s, to_timestamp(%s))",
                    (call_id, seq, speaker, text, now),
                )

    def turns(self, call_id: int) -> list[StoredTurn]:
        with self._pool.connection() as conn:
            rows = conn.execute(
                "SELECT speaker, text FROM call_turns WHERE call_id = %s ORDER BY seq",
                (call_id,),
            ).fetchall()
        return [StoredTurn(s, t) for s, t in rows]

    def save_summary(self, call_id: int, summary: str, model_id: str) -> None:
        with self._pool.connection() as conn:
            conn.execute(
                "INSERT INTO call_reports (call_id, summary, model_id, created_at) "
                "VALUES (%s, %s, %s, to_timestamp(%s)) "
                "ON CONFLICT (call_id) DO UPDATE "
                "SET summary = EXCLUDED.summary, model_id = EXCLUDED.model_id",
                (call_id, summary, model_id, self._clock()),
            )

    def summaries(self, call_ids: Sequence[int]) -> dict[int, str]:
        if not call_ids:
            return {}
        with self._pool.connection() as conn:
            rows = conn.execute(
                "SELECT call_id, summary FROM call_reports WHERE call_id = ANY(%s)",
                (list(call_ids),),
            ).fetchall()
        return {c: s for c, s in rows}

    def calls_with_turns(self, call_ids: Sequence[int]) -> set[int]:
        if not call_ids:
            return set()
        with self._pool.connection() as conn:
            rows = conn.execute(
                "SELECT DISTINCT call_id FROM call_turns WHERE call_id = ANY(%s)",
                (list(call_ids),),
            ).fetchall()
        return {r[0] for r in rows}

    def elder_of_call(self, call_id: int) -> int | None:
        with self._pool.connection() as conn:
            row = conn.execute(
                "SELECT elder_id FROM calls WHERE call_id = %s", (call_id,)
            ).fetchone()
        return None if row is None else row[0]

    def record_view(self, call_id: int, guardian_id: int) -> None:
        with self._pool.connection() as conn:
            conn.execute(
                "INSERT INTO transcript_views (call_id, guardian_id) VALUES (%s, %s)",
                (call_id, guardian_id),
            )

    def view_count(self, call_id: int) -> int:
        with self._pool.connection() as conn:
            return conn.execute(
                "SELECT count(*) FROM transcript_views WHERE call_id = %s", (call_id,)
            ).fetchone()[0]

    def share_agreed(self, elder_id: int) -> bool:
        with self._pool.connection() as conn:
            row = conn.execute(
                "SELECT share_agreed_at IS NOT NULL FROM elders WHERE elder_id = %s",
                (elder_id,),
            ).fetchone()
        return bool(row and row[0])

    def agree_share(self, elder_id: int) -> None:
        with self._pool.connection() as conn:
            conn.execute(
                "UPDATE elders SET share_agreed_at = COALESCE(share_agreed_at, now()) "
                "WHERE elder_id = %s",
                (elder_id,),
            )

    def purge_older_than(self, cutoff: float) -> int:
        with self._pool.connection() as conn:
            turns = conn.execute(
                "DELETE FROM call_turns WHERE created_at < to_timestamp(%s)", (cutoff,)
            ).rowcount
            reports = conn.execute(
                "DELETE FROM call_reports WHERE created_at < to_timestamp(%s)", (cutoff,)
            ).rowcount
        return turns + reports
