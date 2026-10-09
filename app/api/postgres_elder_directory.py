"""ElderDirectory와 DirectoryAdmin의 Postgres 구현."""

from __future__ import annotations

import secrets

from app.api.elder_directory import (
    ElderAccess,
    ElderRef,
    GuardianProfile,
    PendingLimit,
    PhoneTaken,
    digits_of,
)


class PostgresElderDirectory:
    def __init__(self, *, pool) -> None:
        self._pool = pool

    def get(self, elder_id: int) -> ElderAccess | None:
        with self._pool.connection() as conn:
            row = conn.execute(
                "SELECT guardian_id, consent_at IS NOT NULL, name, agreed_at IS NOT NULL "
                "FROM elders WHERE elder_id = %s",
                (elder_id,),
            ).fetchone()
        if row is None:
            return None
        return ElderAccess(guardian_id=row[0], consenting=row[1], name=row[2], agreed=row[3])

    def find_by_phone(self, phone: str) -> int | None:
        wanted = digits_of(phone)
        if not wanted:
            return None
        with self._pool.connection() as conn:
            row = conn.execute(
                "SELECT elder_id FROM elders "
                "WHERE regexp_replace(phone_number, '[^0-9]', '', 'g') = %s "
                "ORDER BY elder_id LIMIT 1",
                (wanted,),
            ).fetchone()
        return None if row is None else row[0]

    def elders_of(self, guardian_id: int) -> list[ElderRef]:
        with self._pool.connection() as conn:
            rows = conn.execute(
                "SELECT elder_id, name, "
                "  CASE WHEN consent_at IS NOT NULL THEN 'active' "
                "       WHEN agreed_at IS NOT NULL THEN 'pending' "
                "       ELSE 'unconsented' END, "
                "  CASE WHEN consent_at IS NULL AND agreed_at IS NOT NULL THEN phone_number END "
                "FROM elders WHERE guardian_id = %s ORDER BY elder_id",
                (guardian_id,),
            ).fetchall()
        return [ElderRef(elder_id=r[0], name=r[1], status=r[2], phone=r[3]) for r in rows]

    def guardian_profile(self, guardian_id: int) -> GuardianProfile | None:
        with self._pool.connection() as conn:
            row = conn.execute(
                "SELECT name, phone_number FROM guardians WHERE guardian_id = %s",
                (guardian_id,),
            ).fetchone()
        return None if row is None else GuardianProfile(name=row[0], phone=row[1])

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

    def create_pending(
        self, *, guardian_id: int, name: str, phone: str, max_pending: int
    ) -> int:
        from psycopg import errors

        wanted = digits_of(phone)
        try:
            with self._pool.connection() as conn:
                taken = conn.execute(
                    "SELECT 1 FROM elders "
                    "WHERE regexp_replace(phone_number, '[^0-9]', '', 'g') = %s LIMIT 1",
                    (wanted,),
                ).fetchone()
                if taken:
                    raise PhoneTaken(wanted)
                # 대기 수 확인과 추가를 한 문장으로 — 동시에 와도 한도를 넘지 않는다.
                # consent_at은 넣지 않는다: 가입은 전화를 거는 허락이 아니다.
                row = conn.execute(
                    "INSERT INTO elders (guardian_id, name, phone_number, agreed_at) "
                    "SELECT %s, %s, %s, now() "
                    "WHERE (SELECT count(*) FROM elders "
                    "       WHERE guardian_id = %s AND agreed_at IS NOT NULL "
                    "         AND consent_at IS NULL) < %s "
                    "RETURNING elder_id",
                    (guardian_id, name, phone, guardian_id, max_pending),
                ).fetchone()
        except errors.UniqueViolation as exc:
            raise PhoneTaken(wanted) from exc
        if row is None:
            raise PendingLimit(guardian_id)
        return row[0]

    def approve(self, elder_id: int, guardian_id: int) -> bool:
        with self._pool.connection() as conn:
            updated = conn.execute(
                "UPDATE elders SET consent_at = now() "
                "WHERE elder_id = %s AND guardian_id = %s "
                "  AND agreed_at IS NOT NULL AND consent_at IS NULL",
                (elder_id, guardian_id),
            ).rowcount
        return updated == 1

    def reject(self, elder_id: int, guardian_id: int) -> bool:
        with self._pool.connection() as conn:
            deleted = conn.execute(
                "DELETE FROM elders "
                "WHERE elder_id = %s AND guardian_id = %s "
                "  AND agreed_at IS NOT NULL AND consent_at IS NULL",
                (elder_id, guardian_id),
            ).rowcount
        return deleted == 1
