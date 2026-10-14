"""DeviceStore의 Postgres 구현 (`guardian_devices` 표)."""

from __future__ import annotations

from app.api.devices import MAX_DEVICES_PER_GUARDIAN


class PostgresDeviceStore:
    def __init__(self, *, pool) -> None:
        self._pool = pool

    def register(self, guardian_id: int, key_hash: str, token: str) -> int | None:
        with self._pool.connection() as conn:
            row = conn.execute(
                "SELECT guardian_id FROM guardian_devices WHERE token = %s FOR UPDATE", (token,)
            ).fetchone()
            previous = None if row is None else row[0]
            conn.execute(
                "INSERT INTO guardian_devices (token, guardian_id, key_hash) VALUES (%s, %s, %s) "
                "ON CONFLICT (token) DO UPDATE SET guardian_id = EXCLUDED.guardian_id, "
                "key_hash = EXCLUDED.key_hash, updated_at = now()",
                (token, guardian_id, key_hash),
            )
            # 이 보호자의 폐기된 열쇠에 묶인 옛 등록을 같이 치운다 — 따로 청소하는 곳이 없어도 쌓이지 않게.
            conn.execute(
                "DELETE FROM guardian_devices d WHERE d.guardian_id = %s AND d.token <> %s "
                "AND NOT EXISTS (SELECT 1 FROM guardian_keys k "
                "WHERE k.key_hash = d.key_hash AND k.revoked_at IS NULL)",
                (guardian_id, token),
            )
            # 이 보호자의 폰이 상한을 넘으면 가장 오래된 등록부터 지운다.
            conn.execute(
                "DELETE FROM guardian_devices WHERE guardian_id = %s AND token NOT IN ("
                "SELECT token FROM guardian_devices WHERE guardian_id = %s "
                "ORDER BY updated_at DESC, created_at DESC, token DESC LIMIT %s)",
                (guardian_id, guardian_id, MAX_DEVICES_PER_GUARDIAN),
            )
            return previous

    def unregister(self, guardian_id: int, token: str) -> bool:
        with self._pool.connection() as conn:
            cur = conn.execute(
                "DELETE FROM guardian_devices WHERE token = %s AND guardian_id = %s",
                (token, guardian_id),
            )
            return cur.rowcount == 1

    def remove_for_key(self, key_hash: str) -> int:
        with self._pool.connection() as conn:
            return conn.execute(
                "DELETE FROM guardian_devices WHERE key_hash = %s", (key_hash,)
            ).rowcount

    def tokens_for(self, guardian_id: int) -> list[str]:
        with self._pool.connection() as conn:
            rows = conn.execute(
                "SELECT d.token FROM guardian_devices d "
                "JOIN guardian_keys k ON k.key_hash = d.key_hash "
                "WHERE d.guardian_id = %s AND k.revoked_at IS NULL ORDER BY d.created_at, d.token",
                (guardian_id,),
            ).fetchall()
        return [r[0] for r in rows]

    def remove_token(self, token: str) -> None:
        with self._pool.connection() as conn:
            conn.execute("DELETE FROM guardian_devices WHERE token = %s", (token,))
