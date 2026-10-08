"""ElderDirectory와 DirectoryAdmin 규약 — 두 구현에 같은 테스트."""

from __future__ import annotations

import os

import pytest

from app.api.elder_directory import ElderAccess, InMemoryElderDirectory

DATABASE_URL = os.getenv("DATABASE_URL")


def _memory():
    return InMemoryElderDirectory(
        {12: ElderAccess(guardian_id=1, consenting=False), 13: ElderAccess(guardian_id=1, consenting=True)}
    )


def _postgres():
    from app.api.db import assert_local, connect
    from app.api.postgres_elder_directory import PostgresElderDirectory

    assert_local()
    pool = connect(DATABASE_URL)
    with pool.connection() as conn:
        conn.execute("TRUNCATE guardian_keys, calls, elders, guardians RESTART IDENTITY CASCADE")
        conn.execute(
            "INSERT INTO guardians (guardian_id, name, email, password_hash, phone_number) "
            "VALUES (1, '임시', 'placeholder@example.invalid', 'not-a-login', '000')"
        )
        conn.execute(
            "INSERT INTO elders (elder_id, guardian_id, name, phone_number, consent_at) VALUES "
            "(12, 1, '어르신 12', '070-0000-0012', NULL), "
            "(13, 1, '어르신 13', '070-0000-0013', now())"
        )
        # seed_elders는 임시 보호자를 id=1로 **직접** 넣어 시퀀스가 앞서가지 않는다.
        # 실제 서버와 같은 상태를 만든다.
        conn.execute(
            "SELECT setval(pg_get_serial_sequence('guardians','guardian_id'), 1, false)"
        )
    return PostgresElderDirectory(pool=pool)


@pytest.fixture(
    params=[
        "memory",
        pytest.param(
            "postgres",
            marks=pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL이 없다"),
        ),
    ]
)
def directory(request):
    return _memory() if request.param == "memory" else _postgres()


def test_an_unknown_elder_is_none(directory):
    assert directory.get(4242) is None


def test_it_reports_the_guardian_and_whether_consent_was_given(directory):
    assert directory.get(12) == ElderAccess(guardian_id=1, consenting=False)
    assert directory.get(13) == ElderAccess(guardian_id=1, consenting=True)


def test_a_new_guardian_gets_a_fresh_id_even_when_id_1_was_inserted_by_hand(directory):
    """seed_elders가 id=1을 직접 넣어 시퀀스가 뒤처져 있다. 그대로 INSERT하면
    중복 키로 실패한다."""
    first = directory.add_guardian("시연 보호자", "010-1111-2222")
    second = directory.add_guardian("다른 보호자", "010-3333-4444")

    assert first >= 2
    assert second == first + 1
    assert directory.guardian_exists(first)
    assert not directory.guardian_exists(99999)


def test_assigning_an_elder_moves_it_and_keeps_its_consent(directory):
    guardian = directory.add_guardian("시연 보호자", "010-1111-2222")

    assert directory.assign_elder(13, guardian) is True

    assert directory.get(13) == ElderAccess(guardian_id=guardian, consenting=True)
    assert directory.get(12).guardian_id == 1


def test_assigning_to_a_missing_guardian_or_elder_fails(directory):
    assert directory.assign_elder(13, 99999) is False
    guardian = directory.add_guardian("시연 보호자", "010-1111-2222")
    assert directory.assign_elder(4242, guardian) is False
    assert directory.get(13).guardian_id == 1
