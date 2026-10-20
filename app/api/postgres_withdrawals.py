"""WithdrawalStore의 Postgres 구현 (`elder_withdrawals`, `elder_withdrawal_approvals` 표)."""

from __future__ import annotations

from app.api.withdrawals import WithdrawalRequest


class PostgresWithdrawalStore:
    def __init__(self, *, pool) -> None:
        self._pool = pool

    def open(self, elder_id: int, now: float) -> WithdrawalRequest:
        # 한 연결 안에서 이전 기록을 지우고 새로 만든다 — 중간에 실패하면 둘 다 되돌아간다.
        with self._pool.connection() as conn:
            conn.execute("DELETE FROM elder_withdrawals WHERE elder_id = %s", (elder_id,))
            conn.execute(
                "INSERT INTO elder_withdrawals (elder_id, requested_at) VALUES (%s, to_timestamp(%s))",
                (elder_id, now),
            )
        return WithdrawalRequest(elder_id=elder_id, requested_at=now)

    def get(self, elder_id: int) -> WithdrawalRequest | None:
        with self._pool.connection() as conn:
            row = conn.execute(
                "SELECT extract(epoch from requested_at)::float8, extract(epoch from rejected_at)::float8 "
                "FROM elder_withdrawals WHERE elder_id = %s",
                (elder_id,),
            ).fetchone()
            if row is None:
                return None
            approved = conn.execute(
                "SELECT guardian_id FROM elder_withdrawal_approvals WHERE elder_id = %s", (elder_id,)
            ).fetchall()
        return WithdrawalRequest(
            elder_id=elder_id,
            requested_at=row[0],
            rejected_at=row[1],
            approved_by=frozenset(item[0] for item in approved),
        )

    def approve(self, elder_id: int, guardian_id: int) -> WithdrawalRequest | None:
        # 열린 요청이 있을 때만 더한다 — 거절됐거나 없는 요청에 승인이 쌓이면 안 된다.
        with self._pool.connection() as conn:
            conn.execute(
                "INSERT INTO elder_withdrawal_approvals (elder_id, guardian_id) "
                "SELECT %s, %s WHERE EXISTS ("
                "  SELECT 1 FROM elder_withdrawals WHERE elder_id = %s AND rejected_at IS NULL"
                ") ON CONFLICT DO NOTHING",
                (elder_id, guardian_id, elder_id),
            )
        request = self.get(elder_id)
        if request is None or request.rejected:
            return None
        return request

    def reject(self, elder_id: int, now: float) -> bool:
        with self._pool.connection() as conn:
            updated = conn.execute(
                "UPDATE elder_withdrawals SET rejected_at = to_timestamp(%s) "
                "WHERE elder_id = %s AND rejected_at IS NULL",
                (now, elder_id),
            ).rowcount
        return updated == 1

    def cancel(self, elder_id: int) -> bool:
        with self._pool.connection() as conn:
            return conn.execute("DELETE FROM elder_withdrawals WHERE elder_id = %s", (elder_id,)).rowcount == 1

    def remove_for_elder(self, elder_id: int) -> int:
        return 1 if self.cancel(elder_id) else 0
