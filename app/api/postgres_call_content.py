"""통화 내용 저장소 — Postgres.

InMemoryCallContent와 같은 규약이다. 둘이 갈라지지 않게 tests/test_call_content_contract.py가
같은 테스트를 양쪽에 돌린다. 저장 시각은 시계에서 받아 `to_timestamp`로 넣는다(규약 테스트가
31일을 흉내낼 수 있게).
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Sequence

from app.api.call_content import MEDICATION_STATUSES, Mention, StoredTurn, check_mentions

logger = logging.getLogger(__name__)


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

    def save_medication(self, call_id: int, status: str, model_id: str) -> None:
        if status not in MEDICATION_STATUSES:
            raise ValueError(f"알 수 없는 복용 확인 값: {status!r}")
        with self._pool.connection() as conn:
            conn.execute(
                "INSERT INTO call_medication (call_id, status, model_id, created_at) "
                "VALUES (%s, %s, %s, to_timestamp(%s)) "
                "ON CONFLICT (call_id) DO UPDATE "
                "SET status = EXCLUDED.status, model_id = EXCLUDED.model_id",
                (call_id, status, model_id, self._clock()),
            )

    def medication(self, call_ids: Sequence[int]) -> dict[int, str]:
        if not call_ids:
            return {}
        with self._pool.connection() as conn:
            rows = conn.execute(
                "SELECT call_id, status FROM call_medication WHERE call_id = ANY(%s)",
                (list(call_ids),),
            ).fetchall()
        return {c: s for c, s in rows}

    def save_mentions(self, call_id: int, mentions: Sequence[Mention], model_id: str) -> None:
        check_mentions(mentions)  # 규칙 밖이면 DB를 건드리기 전에 거절한다
        with self._pool.connection() as conn:
            # 한 연결 안에서 지우고 넣는다 — 중간에 실패하면 둘 다 되돌아간다.
            conn.execute("DELETE FROM call_mentions WHERE call_id = %s", (call_id,))
            for m in mentions:
                conn.execute(
                    "INSERT INTO call_mentions (call_id, category, said, quote, model_id, created_at) "
                    "VALUES (%s, %s, %s, %s, %s, to_timestamp(%s))",
                    (call_id, m.category, m.said, m.quote, model_id, self._clock()),
                )

    def mentions(self, call_ids: Sequence[int]) -> dict[int, list[Mention]]:
        if not call_ids:
            return {}
        with self._pool.connection() as conn:
            rows = conn.execute(
                "SELECT call_id, category, said, quote FROM call_mentions "
                "WHERE call_id = ANY(%s) ORDER BY mention_id",
                (list(call_ids),),
            ).fetchall()
        found: dict[int, list[Mention]] = {}
        for call_id, category, said, quote in rows:
            found.setdefault(call_id, []).append(Mention(category, said, quote))
        return found

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
        # 약 복용 표는 따로 지운다 — 표가 아직 없는 배포 순서에서도 턴·요약의 30일 보관이
        # 이 표에 기대지 않게 하려는 것이다. 위 삭제는 이미 확정되었다.
        medication = 0
        try:
            with self._pool.connection() as conn:
                medication = conn.execute(
                    "DELETE FROM call_medication WHERE created_at < to_timestamp(%s)", (cutoff,)
                ).rowcount
        except Exception:
            logger.exception("약 복용 확인 기록 삭제에 실패했다")
        # 건강·기분 언급 표도 같은 이유로 따로 지운다.
        mentions_removed = 0
        try:
            with self._pool.connection() as conn:
                mentions_removed = conn.execute(
                    "DELETE FROM call_mentions WHERE created_at < to_timestamp(%s)", (cutoff,)
                ).rowcount
        except Exception:
            logger.exception("건강·기분 언급 삭제에 실패했다")
        return turns + reports + medication + mentions_removed

    def remove_for_elder(self, elder_id: int) -> int:
        # 탈퇴 순서에서는 어르신 행이 먼저 지워져 CASCADE가 이미 비웠다 — 메모리 저장소와 같은 규약을 지키려는 것이다.
        of_elder = "call_id IN (SELECT call_id FROM calls WHERE elder_id = %s)"
        with self._pool.connection() as conn:
            removed = sum(
                conn.execute(f"DELETE FROM {table} WHERE {of_elder}", (elder_id,)).rowcount
                for table in ("call_turns", "call_reports", "transcript_views")
            )
            conn.execute("UPDATE elders SET share_agreed_at = NULL WHERE elder_id = %s", (elder_id,))
        # 약 복용·언급 표는 따로 지운다 — 표가 아직 없는 배포 순서에서도 위 삭제는 확정되게(purge_older_than과 같은 이유).
        for table in ("call_medication", "call_mentions"):
            try:
                with self._pool.connection() as conn:
                    removed += conn.execute(f"DELETE FROM {table} WHERE {of_elder}", (elder_id,)).rowcount
            except Exception:
                logger.exception("탈퇴한 어르신의 %s 행을 지우지 못했다 elder_id=%s", table, elder_id)
        return removed
