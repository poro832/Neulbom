"""WithdrawalStore의 Postgres 구현 (`elder_withdrawals`, `elder_withdrawal_approvals` 표)."""

from __future__ import annotations

from app.api.withdrawals import WithdrawalRequest


class PostgresWithdrawalStore:
    def __init__(self, *, pool) -> None:
        self._pool = pool

    def open(self, elder_id: int, now: float) -> WithdrawalRequest:
        # 한 연결 안에서 이전 기록을 지우고 새로 만든다 — 중간에 실패하면 둘 다 되돌아간다. 번호는 새로 매겨진다.
        with self._pool.connection() as conn:
            conn.execute("DELETE FROM elder_withdrawals WHERE elder_id = %s", (elder_id,))
            row = conn.execute(
                "INSERT INTO elder_withdrawals (elder_id, requested_at) VALUES (%s, to_timestamp(%s)) "
                "RETURNING request_id",
                (elder_id, now),
            ).fetchone()
        return WithdrawalRequest(elder_id=elder_id, request_id=row[0], requested_at=now)

    def get(self, elder_id: int) -> WithdrawalRequest | None:
        with self._pool.connection() as conn:
            row = conn.execute(
                "SELECT request_id, extract(epoch from requested_at)::float8, "
                "extract(epoch from rejected_at)::float8 FROM elder_withdrawals WHERE elder_id = %s",
                (elder_id,),
            ).fetchone()
            if row is None:
                return None
            approved = conn.execute(
                "SELECT guardian_id FROM elder_withdrawal_approvals WHERE elder_id = %s", (elder_id,)
            ).fetchall()
        return WithdrawalRequest(
            elder_id=elder_id,
            request_id=row[0],
            requested_at=row[1],
            rejected_at=row[2],
            approved_by=frozenset(item[0] for item in approved),
        )

    def approve(self, elder_id: int, guardian_id: int, request_id: int) -> WithdrawalRequest | None:
        # 보호자가 본 요청(번호가 같은 요청)이 지금도 열려 있을 때만 더한다 — 취소 뒤 다시 요청된 새 요청이나
        # 거절됐거나 없는 요청에 승인이 쌓이면 안 된다.
        with self._pool.connection() as conn:
            conn.execute(
                "INSERT INTO elder_withdrawal_approvals (elder_id, guardian_id) "
                "SELECT %s, %s WHERE EXISTS ("
                "  SELECT 1 FROM elder_withdrawals "
                "  WHERE elder_id = %s AND request_id = %s AND rejected_at IS NULL"
                ") ON CONFLICT DO NOTHING",
                (elder_id, guardian_id, elder_id, request_id),
            )
        request = self.get(elder_id)
        if request is None or request.rejected or request.request_id != request_id:
            return None
        return request

    def reject(self, elder_id: int, now: float, request_id: int) -> bool:
        with self._pool.connection() as conn:
            updated = conn.execute(
                "UPDATE elder_withdrawals SET rejected_at = to_timestamp(%s) "
                "WHERE elder_id = %s AND request_id = %s AND rejected_at IS NULL",
                (now, elder_id, request_id),
            ).rowcount
        return updated == 1

    def cancel(self, elder_id: int) -> bool:
        with self._pool.connection() as conn:
            return conn.execute("DELETE FROM elder_withdrawals WHERE elder_id = %s", (elder_id,)).rowcount == 1

    def remove_for_elder(self, elder_id: int) -> int:
        return 1 if self.cancel(elder_id) else 0
