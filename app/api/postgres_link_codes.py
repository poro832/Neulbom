"""LinkCodeStore의 Postgres 구현 (`elder_link_codes` 표)."""

from __future__ import annotations

from psycopg.errors import UniqueViolation

from app.api.link_codes import CodeCollision


class PostgresLinkCodeStore:
    def __init__(self, *, pool) -> None:
        self._pool = pool

    def issue(self, elder_id: int, code_hash: str, code: str) -> None:
        try:
            with self._pool.connection() as conn:
                conn.execute(
                    "INSERT INTO elder_link_codes (elder_id, code_hash, code, created_at) "
                    "VALUES (%s, %s, %s, now()) "
                    "ON CONFLICT (elder_id) DO UPDATE SET code_hash = EXCLUDED.code_hash, "
                    "  code = EXCLUDED.code, expires_at = NULL, created_at = EXCLUDED.created_at",
                    (elder_id, code_hash, code),
                )
        except UniqueViolation as exc:
            # elder_id 충돌은 위에서 갱신으로 처리되므로 여기 오는 것은 code_hash 충돌이다.
            raise CodeCollision(code_hash[:8]) from exc

    def find(self, code_hash: str) -> int | None:
        # 원문이 없는 행은 만료되는 코드 시절의 것이다 — 고정 코드가 아니므로 쓰지 않는다.
        with self._pool.connection() as conn:
            row = conn.execute(
                "SELECT elder_id FROM elder_link_codes WHERE code_hash = %s AND code IS NOT NULL",
                (code_hash,),
            ).fetchone()
        return None if row is None else row[0]

    def code_of(self, elder_id: int) -> str | None:
        with self._pool.connection() as conn:
            row = conn.execute(
                "SELECT code FROM elder_link_codes WHERE elder_id = %s", (elder_id,)
            ).fetchone()
        return None if row is None else row[0]
