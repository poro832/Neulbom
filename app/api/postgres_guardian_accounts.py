"""GuardianAccounts의 Postgres 구현 (`guardians` 표)."""

from __future__ import annotations

from app.api.guardian_accounts import Account, EmailTaken, normalize_email


class PostgresGuardianAccounts:
    def __init__(self, *, pool) -> None:
        self._pool = pool

    def create(self, name: str, email: str, phone: str, password_hash: str) -> int:
        email = normalize_email(email)
        with self._pool.connection() as conn:
            # 운영 도구가 id를 직접 넣은 보호자가 있어 시퀀스가 뒤처질 수 있다.
            conn.execute(
                "SELECT setval(pg_get_serial_sequence('guardians','guardian_id'), "
                "GREATEST((SELECT COALESCE(MAX(guardian_id), 0) FROM guardians), 1))"
            )
            row = conn.execute(
                "INSERT INTO guardians (name, email, password_hash, phone_number) "
                "VALUES (%s, %s, %s, %s) ON CONFLICT (email) DO NOTHING RETURNING guardian_id",
                (name, email, password_hash, phone),
            ).fetchone()
        if row is None:
            raise EmailTaken(email)
        return row[0]

    def _account(self, where: str, arg) -> Account | None:
        with self._pool.connection() as conn:
            row = conn.execute(
                "SELECT guardian_id, name, email, phone_number, password_hash FROM guardians WHERE "
                + where,
                (arg,),
            ).fetchone()
        return None if row is None else Account(*row)

    def find_by_email(self, email: str) -> Account | None:
        return self._account("email = %s", normalize_email(email))

    def profile(self, guardian_id: int) -> Account | None:
        return self._account("guardian_id = %s", guardian_id)

    def set_password(self, guardian_id: int, password_hash: str) -> None:
        with self._pool.connection() as conn:
            conn.execute(
                "UPDATE guardians SET password_hash = %s WHERE guardian_id = %s",
                (password_hash, guardian_id),
            )

    def set_login(self, guardian_id: int, email: str, password_hash: str) -> bool:
        email = normalize_email(email)
        with self._pool.connection() as conn:
            taken = conn.execute(
                "SELECT 1 FROM guardians WHERE email = %s AND guardian_id <> %s", (email, guardian_id)
            ).fetchone()
            if taken:
                raise EmailTaken(email)
            cur = conn.execute(
                "UPDATE guardians SET email = %s, password_hash = %s WHERE guardian_id = %s",
                (email, password_hash, guardian_id),
            )
            return cur.rowcount == 1
