"""Reports의 Postgres 구현 (calls · call_metrics · alerts · elders)."""

from __future__ import annotations

from datetime import date

from app.api.reports import CallLine, DayStat, ElderSummary, week_bounds

_FINISHED = ["completed", "no_answer", "failed"]


class PostgresReports:
    def __init__(self, *, pool) -> None:
        self._pool = pool

    def elder_summaries(self, guardian_id: int, week_start: date) -> list[ElderSummary]:
        lo, hi = week_bounds(week_start)
        with self._pool.connection() as conn:
            rows = conn.execute(
                """
                SELECT e.elder_id, e.name,
                  (SELECT extract(epoch from c.created_at)::float8 FROM calls c
                    WHERE c.elder_id = e.elder_id ORDER BY c.call_id DESC LIMIT 1),
                  (SELECT c.status FROM calls c
                    WHERE c.elder_id = e.elder_id ORDER BY c.call_id DESC LIMIT 1),
                  (SELECT count(*) FROM calls c
                    WHERE c.elder_id = e.elder_id AND c.status = 'completed'
                      AND c.created_at >= to_timestamp(%(lo)s) AND c.created_at < to_timestamp(%(hi)s)),
                  (SELECT avg(m.risk_score)::float8 FROM calls c
                    JOIN call_metrics m ON m.call_id = c.call_id
                    WHERE c.elder_id = e.elder_id AND c.status = 'completed'
                      AND c.created_at >= to_timestamp(%(lo)s) AND c.created_at < to_timestamp(%(hi)s)),
                  (SELECT count(*) FROM alerts a
                    WHERE a.elder_id = e.elder_id AND a.created_at >= to_timestamp(%(lo)s)),
                  CASE WHEN e.consent_at IS NOT NULL THEN 'active'
                       WHEN e.agreed_at IS NOT NULL THEN 'pending'
                       ELSE 'unconsented' END,
                  CASE WHEN e.consent_at IS NULL AND e.agreed_at IS NOT NULL
                       THEN e.phone_number END
                FROM elders e WHERE e.guardian_id = %(g)s ORDER BY e.elder_id
                """,
                {"lo": lo, "hi": hi, "g": guardian_id},
            ).fetchall()
        return [ElderSummary(*row) for row in rows]

    def weekly(self, elder_id: int, week_start: date) -> list[DayStat]:
        with self._pool.connection() as conn:
            rows = conn.execute(
                """
                SELECT d::date,
                       count(c.call_id),
                       avg(m.risk_score)::float8
                FROM generate_series(%(start)s::date, %(start)s::date + 6, interval '1 day') AS d
                LEFT JOIN calls c
                       ON c.elder_id = %(e)s AND c.status = 'completed'
                      AND (c.created_at AT TIME ZONE 'Asia/Seoul')::date = d::date
                LEFT JOIN call_metrics m ON m.call_id = c.call_id
                GROUP BY d ORDER BY d
                """,
                {"start": week_start, "e": elder_id},
            ).fetchall()
        return [DayStat(date=row[0].isoformat(), calls=row[1], avg_score=row[2]) for row in rows]

    def call_lines(self, elder_id: int, limit: int) -> list[CallLine]:
        with self._pool.connection() as conn:
            rows = conn.execute(
                """
                SELECT c.call_id, extract(epoch from c.created_at)::float8, c.status,
                       m.call_duration_ms
                FROM calls c LEFT JOIN call_metrics m ON m.call_id = c.call_id
                WHERE c.elder_id = %s AND c.status = ANY(%s)
                ORDER BY c.call_id DESC LIMIT %s
                """,
                (elder_id, _FINISHED, limit),
            ).fetchall()
        return [
            CallLine(
                call_id=row[0],
                started_at=row[1],
                duration_s=None if row[3] is None else row[3] // 1000,
                status=row[2],
            )
            for row in rows
        ]
