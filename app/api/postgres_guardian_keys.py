"""GuardianKeyStore의 Postgres 구현 (`guardian_keys` 표)."""

from __future__ import annotations

import time
from collections.abc import Callable

from app.api.db import assert_local
from app.api.guardian_auth import AmbiguousPrefix, KeyInfo, check_prefix


class PostgresGuardianKeyStore:
    def __init__(self, *, pool, clock: Callable[[], float] = time.time) -> None:
        self._pool = pool
        self._clock = clock

    def add(self, *, guardian_id: int, label: str, key_prefix: str, key_hash: str) -> int:
        with self._pool.connection() as conn:
            row = conn.execute(
                "INSERT INTO guardian_keys (guardian_id, key_prefix, key_hash, label, created_at) "
                "VALUES (%s, %s, %s, %s, to_timestamp(%s)) RETURNING key_id",
                (guardian_id, key_prefix, key_hash, label, self._clock()),
            ).fetchone()
        return row[0]

    def find_guardian(self, key_hash: str) -> int | None:
        # 찾으면서 마지막 사용 시각을 갱신한다. 폐기된 열쇠는 조건에서 빠진다.
        with self._pool.connection() as conn:
            row = conn.execute(
                "UPDATE guardian_keys SET last_used_at = to_timestamp(%s) "
                "WHERE key_hash = %s AND revoked_at IS NULL RETURNING guardian_id",
                (self._clock(), key_hash),
            ).fetchone()
        return None if row is None else row[0]

    def list_keys(self) -> list[KeyInfo]:
        with self._pool.connection() as conn:
            rows = conn.execute(
                "SELECT key_id, guardian_id, key_prefix, label, "
                "  extract(epoch from created_at)::float8, "
                "  extract(epoch from revoked_at)::float8, "
                "  extract(epoch from last_used_at)::float8 "
                "FROM guardian_keys ORDER BY key_id"
            ).fetchall()
        return [KeyInfo(*row) for row in rows]

    def revoke(self, prefix: str) -> int:
        check_prefix(prefix)
        with self._pool.connection() as conn:
            # starts_with를 쓴다. LIKE는 열쇠에 흔한 '_'를 와일드카드로 읽는다.
            rows = conn.execute(
                "SELECT key_id FROM guardian_keys "
                "WHERE revoked_at IS NULL AND starts_with(key_prefix, %s)",
                (prefix,),
            ).fetchall()
            if len(rows) > 1:
                raise AmbiguousPrefix(prefix)
            if not rows:
                return 0
            conn.execute(
                "UPDATE guardian_keys SET revoked_at = to_timestamp(%s) WHERE key_id = %s",
                (self._clock(), rows[0][0]),
            )
        return 1

    def reset_for_tests(self) -> None:
        """규약 테스트용. 원격 DB에서는 거부한다(app/api/db.py)."""
        assert_local()
        with self._pool.connection() as conn:
            conn.execute("TRUNCATE guardian_keys RESTART IDENTITY")
