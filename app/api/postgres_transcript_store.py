"""전사 원문 저장소 — Postgres (`call_transcripts`, 통화당 한 행).

InMemoryTranscriptStore와 같은 규약이다. 둘이 갈라지지 않게
tests/test_transcript_store_contract.py가 같은 테스트를 양쪽에 돌린다.

저장 시각을 시계에서 받아 `to_timestamp`로 넣는다(PostgresCallStore와 같은
방식). DB의 now()에 맡기면 규약 테스트가 30일을 흉내낼 수 없다.
"""

from __future__ import annotations

import time
from collections.abc import Callable

from app.api.db import assert_local


class PostgresTranscriptStore:
    def __init__(self, *, pool, clock: Callable[[], float] = time.time) -> None:
        self._pool = pool
        self._clock = clock

    def save(self, call_id: int, text: str) -> None:
        # 다시 저장할 때 created_at은 건드리지 않는다. 재분석 한 번으로 30일
        # 보관 기간이 연장되면 안 된다.
        with self._pool.connection() as conn:
            conn.execute(
                "INSERT INTO call_transcripts (call_id, text, created_at) "
                "VALUES (%s, %s, to_timestamp(%s)) "
                "ON CONFLICT (call_id) DO UPDATE SET text = EXCLUDED.text",
                (call_id, text, self._clock()),
            )

    def get(self, call_id: int) -> str | None:
        with self._pool.connection() as conn:
            row = conn.execute(
                "SELECT text FROM call_transcripts WHERE call_id = %s", (call_id,)
            ).fetchone()
        return None if row is None else row[0]

    def purge_older_than(self, cutoff: float) -> int:
        with self._pool.connection() as conn:
            cursor = conn.execute(
                "DELETE FROM call_transcripts WHERE created_at < to_timestamp(%s)",
                (cutoff,),
            )
            return cursor.rowcount

    def reset_for_tests(self) -> None:
        """규약 테스트용. 원격 DB에서는 거부한다(app/api/db.py)."""
        assert_local()
        with self._pool.connection() as conn:
            conn.execute("TRUNCATE call_transcripts")
