"""LinkCodeStore의 Postgres 구현 (`elder_link_codes` 표)."""

from __future__ import annotations

import time
from collections.abc import Callable

from psycopg.errors import UniqueViolation

from app.api.link_codes import LINK_CODE_TTL_SECONDS, CodeCollision


class PostgresLinkCodeStore:
    def __init__(
        self,
        *,
        pool,
        clock: Callable[[], float] = time.time,
        ttl_seconds: float = LINK_CODE_TTL_SECONDS,
    ) -> None:
        self._pool = pool
        self._clock = clock
        self._ttl = ttl_seconds

    def issue(self, elder_id: int, code_hash: str) -> float:
        now = self._clock()
        expires_at = now + self._ttl
        try:
            with self._pool.connection() as conn:
                conn.execute(
                    "INSERT INTO elder_link_codes (elder_id, code_hash, expires_at, created_at) "
                    "VALUES (%s, %s, to_timestamp(%s), to_timestamp(%s)) "
                    "ON CONFLICT (elder_id) DO UPDATE SET code_hash = EXCLUDED.code_hash, "
                    "  expires_at = EXCLUDED.expires_at, created_at = EXCLUDED.created_at",
                    (elder_id, code_hash, expires_at, now),
                )
        except UniqueViolation as exc:
            # elder_id 충돌은 위에서 갱신으로 처리되므로 여기 오는 것은 code_hash 충돌이다.
            raise CodeCollision(code_hash[:8]) from exc
        return expires_at

    def find(self, code_hash: str) -> int | None:
        with self._pool.connection() as conn:
            row = conn.execute(
                "SELECT elder_id FROM elder_link_codes "
                "WHERE code_hash = %s AND expires_at > to_timestamp(%s)",
                (code_hash, self._clock()),
            ).fetchone()
        return None if row is None else row[0]

    def consume(self, code_hash: str) -> int | None:
        # DELETE ... RETURNING 한 문장이라 같은 코드로 동시에 와도 한 쪽만 행을 얻는다.
        with self._pool.connection() as conn:
            row = conn.execute(
                "DELETE FROM elder_link_codes "
                "WHERE code_hash = %s AND expires_at > to_timestamp(%s) RETURNING elder_id",
                (code_hash, self._clock()),
            ).fetchone()
        return None if row is None else row[0]
