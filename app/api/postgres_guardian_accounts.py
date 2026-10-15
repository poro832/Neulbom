"""GuardianAccounts의 Postgres 구현 (`guardians` 표)."""

from __future__ import annotations

from app.api.guardian_accounts import Account, EmailTaken, normalize_email


class PostgresGuardianAccounts:
    def __init__(self, *, pool) -> None:
        self._pool = pool
        self.sync_sequence()

    def sync_sequence(self) -> None:
        """운영 도구가 id를 직접 넣은 보호자가 있어 시퀀스가 뒤처질 수 있다.

        가입 때마다 하면 동시 가입이 같은 번호를 받을 수 있어 시작할 때 한 번만 맞춘다.
        """
        with self._pool.connection() as conn:
            conn.execute(
                "SELECT setval(pg_get_serial_sequence('guardians','guardian_id'), "
                "GREATEST((SELECT COALESCE(MAX(guardian_id), 0) FROM guardians), 1))"
            )

    def create(
        self,
        name: str,
        email: str,
        phone: str,
        password_hash: str,
        *,
        activated: bool = False,
        email_verified: bool | None = None,
    ) -> int:
        email = normalize_email(email)
        verified = activated if email_verified is None else email_verified
        with self._pool.connection() as conn:
            row = conn.execute(
                "INSERT INTO guardians (name, email, password_hash, phone_number, activated_at, email_verified_at) "
                "VALUES (%s, %s, %s, %s, CASE WHEN %s THEN now() ELSE NULL END, CASE WHEN %s THEN now() ELSE NULL END) "
                "ON CONFLICT (email) DO NOTHING RETURNING guardian_id",
                (name, email, password_hash, phone, activated, verified),
            ).fetchone()
        if row is None:
            raise EmailTaken(email)
        return row[0]

    def _account(self, where: str, arg) -> Account | None:
        with self._pool.connection() as conn:
            row = conn.execute(
                "SELECT guardian_id, name, email, phone_number, password_hash, activated_at IS NOT NULL, "
                "email_verified_at IS NOT NULL "
                "FROM guardians WHERE "
                + where,
                (arg,),
            ).fetchone()
        return None if row is None else Account(*row)

    def activate(self, guardian_id: int) -> bool:
        with self._pool.connection() as conn:
            cur = conn.execute(
                "UPDATE guardians SET activated_at = COALESCE(activated_at, now()) WHERE guardian_id = %s",
                (guardian_id,),
            )
            return cur.rowcount == 1

    def mark_email_verified(self, guardian_id: int) -> bool:
        with self._pool.connection() as conn:
            cur = conn.execute(
                "UPDATE guardians SET email_verified_at = COALESCE(email_verified_at, now()) WHERE guardian_id = %s",
                (guardian_id,),
            )
            return cur.rowcount == 1

    def pending(self) -> list[Account]:
        with self._pool.connection() as conn:
            rows = conn.execute(
                "SELECT guardian_id, name, email, phone_number, password_hash, false, email_verified_at IS NOT NULL FROM guardians "
                "WHERE activated_at IS NULL ORDER BY guardian_id"
            ).fetchall()
        return [Account(*row) for row in rows]

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
                "UPDATE guardians SET email = %s, password_hash = %s, "
                "activated_at = COALESCE(activated_at, now()), "
                "email_verified_at = COALESCE(email_verified_at, now()) WHERE guardian_id = %s",
                (email, password_hash, guardian_id),
            )
            return cur.rowcount == 1
