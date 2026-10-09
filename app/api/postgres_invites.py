"""InviteStore의 Postgres 구현 (`guardian_invites` 표)."""

from __future__ import annotations


class PostgresInviteStore:
    def __init__(self, *, pool) -> None:
        self._pool = pool

    def issue(self, guardian_id: int, code_hash: str) -> None:
        # 한 연결 안에서 폐기와 추가를 같이 한다 — 중간에 실패하면 둘 다 되돌아간다.
        with self._pool.connection() as conn:
            conn.execute(
                "UPDATE guardian_invites SET revoked_at = now() "
                "WHERE guardian_id = %s AND revoked_at IS NULL",
                (guardian_id,),
            )
            conn.execute(
                "INSERT INTO guardian_invites (guardian_id, code_hash) VALUES (%s, %s)",
                (guardian_id, code_hash),
            )

    def find_guardian(self, code_hash: str) -> int | None:
        with self._pool.connection() as conn:
            row = conn.execute(
                "SELECT guardian_id FROM guardian_invites "
                "WHERE code_hash = %s AND revoked_at IS NULL",
                (code_hash,),
            ).fetchone()
        return None if row is None else row[0]
