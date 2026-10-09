"""ElderKeyStore의 Postgres 구현 (`elder_keys` 표)."""

from __future__ import annotations

import time
from collections.abc import Callable

from app.api.db import assert_local


class PostgresElderKeyStore:
    def __init__(self, *, pool, clock: Callable[[], float] = time.time) -> None:
        self._pool = pool
        self._clock = clock

    def replace(self, *, elder_id: int, key_prefix: str, key_hash: str) -> None:
        # 한 연결 안에서 폐기와 추가를 같이 한다 — 중간에 실패하면 둘 다 되돌아간다.
        with self._pool.connection() as conn:
            conn.execute(
                "UPDATE elder_keys SET revoked_at = to_timestamp(%s) "
                "WHERE elder_id = %s AND revoked_at IS NULL",
                (self._clock(), elder_id),
            )
            conn.execute(
                "INSERT INTO elder_keys (elder_id, key_prefix, key_hash, created_at) "
                "VALUES (%s, %s, %s, to_timestamp(%s))",
                (elder_id, key_prefix, key_hash, self._clock()),
            )

    def find_elder(self, key_hash: str) -> int | None:
        with self._pool.connection() as conn:
            row = conn.execute(
                "UPDATE elder_keys SET last_used_at = to_timestamp(%s) "
                "WHERE key_hash = %s AND revoked_at IS NULL RETURNING elder_id",
                (self._clock(), key_hash),
            ).fetchone()
        return None if row is None else row[0]

    def last_used_at(self, key_hash: str) -> float | None:
        with self._pool.connection() as conn:
            row = conn.execute(
                "SELECT extract(epoch from last_used_at)::float8 FROM elder_keys WHERE key_hash = %s",
                (key_hash,),
            ).fetchone()
        return None if row is None else row[0]

    def reset_for_tests(self) -> None:
        """규약 테스트용. 원격 DB에서는 거부한다(app/api/db.py)."""
        assert_local()
        with self._pool.connection() as conn:
            conn.execute("TRUNCATE elder_keys RESTART IDENTITY")
