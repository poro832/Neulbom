"""명부 질의 — 실제 Postgres에서만 확인할 수 있는 것들.

`due_elders`의 판정 논리는 `tests/test_scheduler.py`가 DB 없이 검증한다.
여기서 보는 건 **질의가 맞는 행을 집어 오는가** 하나다. 특히 동의 필터는
코드가 아니라 SQL에 있어서, 가짜 구현으로는 절대 검증되지 않는다.

DATABASE_URL이 없으면 건너뛴다. 건너뛴 테스트는 아무것도 지키지 못한다.
"""

from __future__ import annotations

import os
from datetime import time

import pytest

DATABASE_URL = os.getenv("DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="DATABASE_URL이 없다 — 명부 질의를 확인할 DB가 없다.",
)


@pytest.fixture
def roster():
    from app.api.db import connect
    from app.api.postgres_store import PostgresRoster

    pool = connect(DATABASE_URL)
    with pool.connection() as conn:
        conn.execute("TRUNCATE calls, elders, guardians RESTART IDENTITY CASCADE")
        conn.execute(
            "INSERT INTO guardians (guardian_id, name, email, password_hash,"
            " phone_number) VALUES (1, '보호자', 'g@example.invalid', 'x', '010-0-0')"
        )
    yield PostgresRoster(pool=pool), pool
    pool.close()


def add_elder(pool, elder_id, *, consented, call_time="09:00"):
    with pool.connection() as conn:
        conn.execute(
            "INSERT INTO elders (elder_id, guardian_id, name, phone_number,"
            " call_time, consent_at) VALUES (%s, 1, %s, %s, %s, %s)",
            (elder_id, f"어르신 {elder_id}", f"070-{elder_id:04d}", call_time,
             "now()" if consented else None),
        )
        if consented:
            conn.execute(
                "UPDATE elders SET consent_at = now() WHERE elder_id = %s", (elder_id,)
            )


def test_an_elder_without_consent_never_appears(roster):
    """동의는 발신 자격의 유일한 조건이고, 그 확인이 이 질의에만 있다.

    여기서 새면 아무도 동의하지 않은 어르신께 매일 아침 전화가 나간다.
    """
    reader, pool = roster
    add_elder(pool, 1, consented=False)

    assert reader.entries() == []


def test_a_consenting_elder_appears_with_their_call_time(roster):
    reader, pool = roster
    add_elder(pool, 1, consented=True, call_time="08:30")

    entries = reader.entries()

    assert len(entries) == 1
    assert entries[0].elder_id == 1
    assert entries[0].call_time == time(8, 30)
    assert entries[0].last_scheduled_at is None


def test_the_last_scheduled_call_comes_back(roster):
    """'오늘 이미 걸었나'를 이 값으로 판정한다. 안 오면 하루 두 번 건다."""
    reader, pool = roster
    add_elder(pool, 1, consented=True)
    with pool.connection() as conn:
        conn.execute(
            "INSERT INTO calls (elder_id, trigger_type, status, audio_key) "
            "VALUES (1, 'scheduled', 'completed', '1.wav')"
        )

    assert reader.entries()[0].last_scheduled_at is not None


def test_a_requested_call_does_not_count_as_scheduled(roster):
    """어르신이 앱에서 부른 통화는 예약 통화가 아니다.

    이걸 섞으면, 아침에 어르신이 먼저 전화를 요청한 날은 예약 통화가
    건너뛰어진다 — 그리고 그 사실이 어디에도 안 남는다.
    """
    reader, pool = roster
    add_elder(pool, 1, consented=True)
    with pool.connection() as conn:
        conn.execute(
            "INSERT INTO calls (elder_id, trigger_type, status, audio_key) "
            "VALUES (1, 'requested', 'completed', '1.wav')"
        )

    assert reader.entries()[0].last_scheduled_at is None


def test_the_newest_scheduled_call_wins(roster):
    reader, pool = roster
    add_elder(pool, 1, consented=True)
    with pool.connection() as conn:
        conn.execute(
            "INSERT INTO calls (elder_id, trigger_type, status, audio_key,"
            " created_at) VALUES "
            "(1, 'scheduled', 'completed', 'a.wav', now() - interval '2 days'),"
            "(1, 'scheduled', 'completed', 'b.wav', now() - interval '1 day')"
        )

    newest = reader.entries()[0].last_scheduled_at

    with pool.connection() as conn:
        expected = conn.execute(
            "SELECT max(created_at) FROM calls WHERE trigger_type = 'scheduled'"
        ).fetchone()[0]

    assert newest == expected
