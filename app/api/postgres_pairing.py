"""PairingStore의 Postgres 구현 (`elder_pairings` 표)."""

from __future__ import annotations

import hmac
import time
from collections.abc import Callable

from app.api.pairing import CODE_TTL_SECONDS, MAX_FAILED_ATTEMPTS


class PostgresPairingStore:
    def __init__(
        self,
        *,
        pool,
        clock: Callable[[], float] = time.time,
        ttl_seconds: float = CODE_TTL_SECONDS,
        max_failed: int = MAX_FAILED_ATTEMPTS,
    ) -> None:
        self._pool = pool
        self._clock = clock
        self._ttl = ttl_seconds
        self._max_failed = max_failed

    def issue(self, elder_id: int, code_hash: str) -> float:
        now = self._clock()
        expires_at = now + self._ttl
        with self._pool.connection() as conn:
            conn.execute(
                "UPDATE elder_pairings SET used_at = to_timestamp(%s) "
                "WHERE elder_id = %s AND used_at IS NULL",
                (now, elder_id),
            )
            conn.execute(
                "INSERT INTO elder_pairings (elder_id, code_hash, expires_at, created_at) "
                "VALUES (%s, %s, to_timestamp(%s), to_timestamp(%s))",
                (elder_id, code_hash, expires_at, now),
            )
        return expires_at

    def redeem(self, elder_id: int, code_hash: str) -> bool:
        now = self._clock()
        with self._pool.connection() as conn:
            # FOR UPDATE: 같은 코드로 동시에 두 번 들어와도 한 번만 성공한다.
            row = conn.execute(
                "SELECT pairing_id, code_hash FROM elder_pairings "
                "WHERE elder_id = %s AND used_at IS NULL AND expires_at > to_timestamp(%s) "
                "  AND failed_attempts < %s "
                "ORDER BY pairing_id DESC LIMIT 1 FOR UPDATE",
                (elder_id, now, self._max_failed),
            ).fetchone()
            if row is None:
                return False
            pairing_id, stored = row
            if hmac.compare_digest(stored, code_hash):
                conn.execute(
                    "UPDATE elder_pairings SET used_at = to_timestamp(%s) WHERE pairing_id = %s",
                    (now, pairing_id),
                )
                return True
            conn.execute(
                "UPDATE elder_pairings SET failed_attempts = failed_attempts + 1 "
                "WHERE pairing_id = %s",
                (pairing_id,),
            )
            return False
