"""ElderDirectory와 DirectoryAdmin의 Postgres 구현."""

from __future__ import annotations

import secrets
from datetime import time

from psycopg.errors import UniqueViolation

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
        않는다. 그대로 INSERT하면 중복 키로 실패하므로, 그때만 최댓값에 맞추고 다시 한다.
        이메일 칸이 NOT NULL UNIQUE라 보호자마다 다른 가짜 값을 넣고, 비밀번호
        칸은 seed_elders와 같은 표시값('not-a-login')이라 어떤 비밀번호로도
        로그인되지 않는다.
        """
        email = f"key-{secrets.token_hex(8)}@no-login.invalid"
        insert = (
            "INSERT INTO guardians (name, email, password_hash, phone_number, activated_at) "
            "VALUES (%s, %s, 'not-a-login', %s, now()) RETURNING guardian_id"
        )
        try:
            with self._pool.connection() as conn:
                row = conn.execute(insert, (name, email, phone)).fetchone()
        except UniqueViolation:
            # 시퀀스가 뒤처졌다(seed가 id를 직접 넣었다). 그때만 최댓값에 맞추고 한 번 다시 한다.
            # 매번 맞추면 서버에서 동시에 가입하는 사람의 번호와 겹칠 수 있다.
            with self._pool.connection() as conn:
                conn.execute(
                    "SELECT setval(pg_get_serial_sequence('guardians','guardian_id'), "
                    "GREATEST((SELECT COALESCE(MAX(guardian_id), 0) FROM guardians), 1))"
                )
            with self._pool.connection() as conn:
                row = conn.execute(insert, (name, email, phone)).fetchone()
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

    def phone_of(self, elder_id: int) -> str | None:
        with self._pool.connection() as conn:
            row = conn.execute(
                "SELECT phone_number FROM elders WHERE elder_id = %s", (elder_id,)
            ).fetchone()
        return None if row is None else row[0]

    def create_unlinked(self, *, name: str, phone: str) -> int:
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
                # guardian_id와 consent_at은 넣지 않는다: 보호자가 연결을 확인하기 전에는 전화가 나가지 않는다.
                row = conn.execute(
                    "INSERT INTO elders (name, phone_number, agreed_at) "
                    "VALUES (%s, %s, now()) RETURNING elder_id",
                    (name, phone),
                ).fetchone()
        except errors.UniqueViolation as exc:
            raise PhoneTaken(wanted) from exc
        return row[0]

    def discard_unlinked(self, elder_id: int) -> bool:
        with self._pool.connection() as conn:
            deleted = conn.execute(
                "DELETE FROM elders "
                "WHERE elder_id = %s AND guardian_id IS NULL AND consent_at IS NULL",
                (elder_id,),
            ).rowcount
        return deleted == 1

    def link(self, elder_id: int, guardian_id: int) -> bool:
        with self._pool.connection() as conn:
            updated = conn.execute(
                "UPDATE elders SET guardian_id = %s, consent_at = now() "
                "WHERE elder_id = %s AND guardian_id IS NULL AND agreed_at IS NOT NULL",
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

    def call_time_of(self, elder_id: int) -> time | None:
        with self._pool.connection() as conn:
            row = conn.execute(
                "SELECT call_time FROM elders WHERE elder_id = %s", (elder_id,)
            ).fetchone()
        return None if row is None else row[0]

    def set_call_time(self, elder_id: int, guardian_id: int, value: time) -> bool:
        # 스케줄러의 명부가 이 칸을 매분 새로 읽는다 — 저장하면 다음 확인부터 적용된다.
        with self._pool.connection() as conn:
            updated = conn.execute(
                "UPDATE elders SET call_time = %s WHERE elder_id = %s AND guardian_id = %s",
                (value, elder_id, guardian_id),
            ).rowcount
        return updated == 1

    def set_phone(self, elder_id: int, guardian_id: int, phone: str) -> bool:
        from psycopg import errors

        wanted = digits_of(phone)
        try:
            with self._pool.connection() as conn:
                taken = conn.execute(
                    "SELECT 1 FROM elders "
                    "WHERE regexp_replace(phone_number, '[^0-9]', '', 'g') = %s AND elder_id <> %s LIMIT 1",
                    (wanted, elder_id),
                ).fetchone()
                if taken:
                    raise PhoneTaken(wanted)
                updated = conn.execute(
                    "UPDATE elders SET phone_number = %s WHERE elder_id = %s AND guardian_id = %s",
                    (phone, elder_id, guardian_id),
                ).rowcount
        except errors.UniqueViolation as exc:
            raise PhoneTaken(wanted) from exc
        return updated == 1

    def guardians_of(self, elder_id: int) -> list[int]:
        with self._pool.connection() as conn:
            row = conn.execute(
                "SELECT guardian_id FROM elders WHERE elder_id = %s", (elder_id,)
            ).fetchone()
        return [] if row is None or row[0] is None else [row[0]]

    def open_new_phone_login(self, elder_id: int, guardian_id: int, until: float) -> bool:
        with self._pool.connection() as conn:
            updated = conn.execute(
                "UPDATE elders SET phone_claim_until = to_timestamp(%s) "
                "WHERE elder_id = %s AND guardian_id = %s",
                (until, elder_id, guardian_id),
            ).rowcount
        return updated == 1

    def claim_new_phone(self, phone: str, now: float) -> int | None:
        wanted = digits_of(phone)
        if not wanted:
            return None
        # 한 문장이라 같은 번호로 동시에 와도 한 쪽만 행을 얻는다(FOR UPDATE가 다른 쪽을 기다리게 하고, 기다린 쪽은
        # 이미 닫힌 창을 본다). 만료됐으면 닫아 두기만 하고 None이다. RETURNING의 열은 바뀐 값이라 옛 시각은 하위 질의에서 읽는다.
        with self._pool.connection() as conn:
            row = conn.execute(
                "UPDATE elders SET phone_claim_until = NULL FROM ("
                "  SELECT elder_id, phone_claim_until AS until FROM elders "
                "  WHERE regexp_replace(phone_number, '[^0-9]', '', 'g') = %s "
                "    AND phone_claim_until IS NOT NULL FOR UPDATE"
                ") AS opened WHERE elders.elder_id = opened.elder_id "
                "RETURNING elders.elder_id, opened.until > to_timestamp(%s)",
                (wanted, now),
            ).fetchone()
        if row is None or not row[1]:
            return None
        return row[0]

    def detach_all_from(self, guardian_id: int) -> list[int]:
        # 보호자 행을 지우기 **전에** 부른다. elders.guardian_id가 ON DELETE CASCADE라 그대로 지우면 어르신까지
        # 지워진다. consent_at을 비우면 스케줄러 명부(consent_at IS NOT NULL)에서 빠져 안부 전화가 멈춘다.
        # agreed_at·share_agreed_at·call_time과 통화 기록은 건드리지 않는다.
        with self._pool.connection() as conn:
            rows = conn.execute(
                "UPDATE elders SET guardian_id = NULL, consent_at = NULL WHERE guardian_id = %s RETURNING elder_id",
                (guardian_id,),
            ).fetchall()
        return sorted(row[0] for row in rows)

    def delete_elder(self, elder_id: int) -> bool:
        # calls(→ call_metrics·call_transcripts·call_turns·call_reports·call_medication·call_mentions·
        # transcript_views)·alerts·contacts·elder_keys·elder_pairings·elder_link_codes가 ON DELETE CASCADE로
        # 같이 지워진다(db/schema.sql). S3 녹음은 남으므로 호출부가 먼저 지운다.
        with self._pool.connection() as conn:
            deleted = conn.execute("DELETE FROM elders WHERE elder_id = %s", (elder_id,)).rowcount
        return deleted == 1

    def audio_keys_of(self, elder_id: int) -> list[str]:
        with self._pool.connection() as conn:
            rows = conn.execute(
                "SELECT audio_key FROM calls WHERE elder_id = %s AND audio_key IS NOT NULL ORDER BY call_id",
                (elder_id,),
            ).fetchall()
        return [row[0] for row in rows]
