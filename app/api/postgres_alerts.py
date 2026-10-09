"""AlertStore의 Postgres 구현 (`alerts` 표)."""

from __future__ import annotations

import time
from collections.abc import Callable

from app.api.alerts import AlertRecord


class PostgresAlertStore:
    def __init__(self, *, pool, clock: Callable[[], float] = time.time) -> None:
        self._pool = pool
        self._clock = clock

    def raise_alert(
        self,
        *,
        elder_id: int,
        guardian_id: int,
        call_id: int | None,
        alert_type: str,
        severity: str,
        message: str,
    ) -> bool:
        # call_id가 있으면 부분 유니크 인덱스(alerts_call_type_idx)가 중복을 막는다.
        with self._pool.connection() as conn:
            row = conn.execute(
                "INSERT INTO alerts (elder_id, guardian_id, call_id, alert_type, severity, "
                "                    message, created_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, to_timestamp(%s)) "
                "ON CONFLICT (call_id, alert_type) WHERE call_id IS NOT NULL DO NOTHING "
                "RETURNING alert_id",
                (elder_id, guardian_id, call_id, alert_type, severity, message, self._clock()),
            ).fetchone()
        return row is not None

    def recent_for_guardian(self, guardian_id: int, limit: int) -> list[AlertRecord]:
        with self._pool.connection() as conn:
            rows = conn.execute(
                "SELECT alert_id, elder_id, guardian_id, call_id, alert_type, severity, message, "
                "       extract(epoch from created_at)::float8 "
                "FROM alerts WHERE guardian_id = %s ORDER BY alert_id DESC LIMIT %s",
                (guardian_id, limit),
            ).fetchall()
        return [AlertRecord(*row) for row in rows]

    def count_since(self, elder_id: int, since: float) -> int:
        with self._pool.connection() as conn:
            row = conn.execute(
                "SELECT count(*) FROM alerts WHERE elder_id = %s AND created_at >= to_timestamp(%s)",
                (elder_id, since),
            ).fetchone()
        return row[0]
