"""ElderDirectory와 DirectoryAdmin의 Postgres 구현."""

from __future__ import annotations

import secrets

from app.api.elder_directory import ElderAccess


class PostgresElderDirectory:
    def __init__(self, *, pool) -> None:
        self._pool = pool

    def get(self, elder_id: int) -> ElderAccess | None:
        with self._pool.connection() as conn:
            row = conn.execute(
                "SELECT guardian_id, consent_at IS NOT NULL FROM elders WHERE elder_id = %s",
                (elder_id,),
            ).fetchone()
        return None if row is None else ElderAccess(guardian_id=row[0], consenting=row[1])

    def guardian_exists(self, guardian_id: int) -> bool:
        with self._pool.connection() as conn:
            row = conn.execute(
                "SELECT 1 FROM guardians WHERE guardian_id = %s", (guardian_id,)
            ).fetchone()
        return row is not None

    def add_guardian(self, name: str, phone: str) -> int:
        """열쇠 전용 보호자를 만든다.

        seed_elders가 임시 보호자를 guardian_id=1로 직접 넣어 시퀀스가 앞서가지
        않는다. 그대로 INSERT하면 중복 키로 실패하므로 먼저 최댓값에 맞춘다.
        이메일 칸이 NOT NULL UNIQUE라 보호자마다 다른 가짜 값을 넣고, 비밀번호
        칸은 seed_elders와 같은 표시값('not-a-login')이라 어떤 비밀번호로도
        로그인되지 않는다.
        """
        with self._pool.connection() as conn:
            conn.execute(
                "SELECT setval(pg_get_serial_sequence('guardians','guardian_id'), "
                "GREATEST((SELECT COALESCE(MAX(guardian_id), 0) FROM guardians), 1))"
            )
            row = conn.execute(
                "INSERT INTO guardians (name, email, password_hash, phone_number) "
                "VALUES (%s, %s, 'not-a-login', %s) RETURNING guardian_id",
                (name, f"key-{secrets.token_hex(8)}@no-login.invalid", phone),
            ).fetchone()
        return row[0]

    def assign_elder(self, elder_id: int, guardian_id: int) -> bool:
        if not self.guardian_exists(guardian_id):
            return False
        with self._pool.connection() as conn:
            updated = conn.execute(
                "UPDATE elders SET guardian_id = %s WHERE elder_id = %s",
                (guardian_id, elder_id),
            ).rowcount
        return updated == 1
