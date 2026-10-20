"""WithdrawalStore의 Postgres 구현 (`elder_withdrawals`, `elder_withdrawal_approvals` 표)."""

from __future__ import annotations

from app.api.withdrawals import WithdrawalRequest


class PostgresWithdrawalStore:
    def __init__(self, *, pool) -> None:
        self._pool = pool

    def open(self, elder_id: int, now: float) -> WithdrawalRequest:
        # 거절된 이전 요청만 지우고 새로 만든다(한 연결 안이라 중간에 실패하면 되돌아간다). 번호는 새로 매겨진다.
        # 열린 요청(승인 대기·잠김)은 지우지 않는다: DELETE가 0행이면 INSERT가 PK 충돌하므로, 그때는 그 요청을 돌려준다.
        with self._pool.connection() as conn:
            conn.execute(
                "DELETE FROM elder_withdrawals "
                "WHERE elder_id = %s AND locked_at IS NULL AND rejected_at IS NOT NULL",
                (elder_id,),
            )
            row = conn.execute(
                "INSERT INTO elder_withdrawals (elder_id, requested_at) VALUES (%s, to_timestamp(%s)) "
                "ON CONFLICT (elder_id) DO NOTHING RETURNING request_id",
                (elder_id, now),
            ).fetchone()
        if row is None:
            existing = self.get(elder_id)
            if existing is not None:
                return existing
            return self.open(elder_id, now)  # 그 사이 지워졌다 — 다시 시도한다
        return WithdrawalRequest(elder_id=elder_id, request_id=row[0], requested_at=now)

    def get(self, elder_id: int) -> WithdrawalRequest | None:
        with self._pool.connection() as conn:
            row = conn.execute(
                "SELECT request_id, extract(epoch from requested_at)::float8, "
                "extract(epoch from rejected_at)::float8, extract(epoch from locked_at)::float8 "
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
            request_id=row[0],
            requested_at=row[1],
            rejected_at=row[2],
            locked_at=row[3],
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
                "WHERE elder_id = %s AND request_id = %s AND rejected_at IS NULL AND locked_at IS NULL",
                (now, elder_id, request_id),
            ).rowcount
        return updated == 1

    def lock(self, elder_id: int, request_id: int, now: float) -> bool:
        # 한 문장이다: 그 번호의 거절되지 않은 요청이 지금도 있을 때만 잠그고(이미 잠겼으면 그대로 두고) True.
        with self._pool.connection() as conn:
            row = conn.execute(
                "UPDATE elder_withdrawals SET locked_at = COALESCE(locked_at, to_timestamp(%s)) "
                "WHERE elder_id = %s AND request_id = %s AND rejected_at IS NULL RETURNING 1",
                (now, elder_id, request_id),
            ).fetchone()
        return row is not None

    def cancel(self, elder_id: int) -> bool:
        with self._pool.connection() as conn:
            return (
                conn.execute(
                    "DELETE FROM elder_withdrawals WHERE elder_id = %s AND locked_at IS NULL", (elder_id,)
                ).rowcount
                == 1
            )

    def remove_for_elder(self, elder_id: int) -> int:
        # 어르신이 지워진 뒤 정리다 — 잠긴 요청도 함께 지운다.
        with self._pool.connection() as conn:
            return conn.execute("DELETE FROM elder_withdrawals WHERE elder_id = %s", (elder_id,)).rowcount
