"""ContactStore의 Postgres 구현 (`contacts` 표)."""

from __future__ import annotations

from app.api.contacts import MAX_CONTACTS, Contact, TooManyContacts


class PostgresContactStore:
    def __init__(self, *, pool) -> None:
        self._pool = pool

    def list(self, elder_id: int) -> list[Contact]:
        with self._pool.connection() as conn:
            rows = conn.execute(
                "SELECT contact_id, name, relation, phone_number FROM contacts "
                "WHERE elder_id = %s ORDER BY contact_id",
                (elder_id,),
            ).fetchall()
        return [Contact(*row) for row in rows]

    def add(self, elder_id: int, *, name: str, relation: str, phone: str) -> Contact:
        # 개수 확인과 추가를 한 문장으로 — 두 요청이 동시에 와도 20개를 넘지 않는다.
        with self._pool.connection() as conn:
            row = conn.execute(
                "INSERT INTO contacts (elder_id, name, relation, phone_number) "
                "SELECT %s, %s, %s, %s "
                "WHERE (SELECT count(*) FROM contacts WHERE elder_id = %s) < %s "
                "RETURNING contact_id",
                (elder_id, name, relation, phone, elder_id, MAX_CONTACTS),
            ).fetchone()
        if row is None:
            raise TooManyContacts(elder_id)
        return Contact(row[0], name, relation, phone)

    def remove(self, elder_id: int, contact_id: int) -> bool:
        with self._pool.connection() as conn:
            deleted = conn.execute(
                "DELETE FROM contacts WHERE elder_id = %s AND contact_id = %s",
                (elder_id, contact_id),
            ).rowcount
        return deleted == 1
