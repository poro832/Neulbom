"""ElderDirectory와 DirectoryAdmin 규약 — 두 구현에 같은 테스트."""

from __future__ import annotations

import os

import pytest

from app.api.elder_directory import ElderAccess, GuardianProfile, InMemoryElderDirectory

DATABASE_URL = os.getenv("DATABASE_URL")


def _memory():
    return InMemoryElderDirectory(
        {
            12: ElderAccess(guardian_id=1, consenting=False, name="어르신 12"),
            13: ElderAccess(guardian_id=1, consenting=True, name="어르신 13"),
        },
        phones={12: "070-0000-0012", 13: "070-0000-0013"},
        guardians={1: GuardianProfile(name="임시", phone="000")},
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
    assert directory.get(12) == ElderAccess(guardian_id=1, consenting=False, name="어르신 12")
    assert directory.get(13) == ElderAccess(guardian_id=1, consenting=True, name="어르신 13")


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

    assert directory.get(13) == ElderAccess(guardian_id=guardian, consenting=True, name="어르신 13")
    assert directory.get(12).guardian_id == 1


def test_assigning_to_a_missing_guardian_or_elder_fails(directory):
    assert directory.assign_elder(13, 99999) is False
    guardian = directory.add_guardian("시연 보호자", "010-1111-2222")
    assert directory.assign_elder(4242, guardian) is False
    assert directory.get(13).guardian_id == 1


def test_an_elder_is_found_by_the_digits_of_the_phone_number(directory):
    assert directory.find_by_phone("07000000012") == 12
    assert directory.find_by_phone("070-0000-0012") == 12
    assert directory.find_by_phone("070 0000 0012") == 12
    assert directory.find_by_phone("07099999999") is None
    assert directory.find_by_phone("") is None


def test_elders_of_lists_only_that_guardians_elders_in_id_order(directory):
    other = directory.add_guardian("다른 보호자", "010-3333-4444")

    assert [(e.elder_id, e.name) for e in directory.elders_of(1)] == [(12, "어르신 12"), (13, "어르신 13")]
    assert directory.elders_of(other) == []
    assert directory.elders_of(99999) == []


def test_a_guardian_profile_has_name_and_phone(directory):
    assert directory.guardian_profile(1) == GuardianProfile(name="임시", phone="000")
    created = directory.add_guardian("홍길동", "010-1111-2222")
    assert directory.guardian_profile(created) == GuardianProfile(name="홍길동", phone="010-1111-2222")
    assert directory.guardian_profile(99999) is None


# ------------------------------------------------ 가입 · 승인 · 거절


from app.api.elder_directory import PendingLimit, PhoneTaken  # noqa: E402


def make_pending(directory, guardian_id=1, name="새 어르신", phone="010-9999-1111", max_pending=5):
    return directory.create_pending(
        guardian_id=guardian_id, name=name, phone=phone, max_pending=max_pending
    )


def test_a_signup_makes_a_pending_elder_that_is_not_consenting(directory):
    elder_id = make_pending(directory)

    access = directory.get(elder_id)

    assert access.guardian_id == 1 and access.name == "새 어르신"
    assert access.consenting is False and access.agreed is True
    assert access.status == "pending"
    assert directory.find_by_phone("01099991111") == elder_id


def test_existing_elders_have_active_or_unconsented_status(directory):
    assert directory.get(13).status == "active"        # 동의가 있다
    assert directory.get(12).status == "unconsented"   # 운영자 등록, 동의 전


def test_a_number_already_registered_is_refused_in_any_format(directory):
    make_pending(directory, phone="010-9999-1111")

    for phone in ("010-9999-1111", "01099991111", "010 9999 1111", "070-0000-0012", "07000000012"):
        with pytest.raises(PhoneTaken):
            make_pending(directory, phone=phone, name="중복")


def test_a_guardian_cannot_hold_more_pending_elders_than_the_limit(directory):
    make_pending(directory, phone="010-1000-0001", max_pending=2)
    make_pending(directory, phone="010-1000-0002", max_pending=2)

    with pytest.raises(PendingLimit):
        make_pending(directory, phone="010-1000-0003", max_pending=2)

    other = directory.add_guardian("다른 보호자", "010-3333-4444")
    assert make_pending(directory, guardian_id=other, phone="010-1000-0004", max_pending=2)


def test_elders_of_shows_status_and_the_phone_only_while_pending(directory):
    pending = make_pending(directory, phone="010-9999-1111")

    by_id = {e.elder_id: e for e in directory.elders_of(1)}

    assert by_id[pending].status == "pending" and by_id[pending].phone == "010-9999-1111"
    assert by_id[13].status == "active" and by_id[13].phone is None
    assert by_id[12].status == "unconsented" and by_id[12].phone is None


def test_approving_makes_the_elder_active(directory):
    elder_id = make_pending(directory)

    assert directory.approve(elder_id, 1) is True

    access = directory.get(elder_id)
    assert access.consenting is True and access.status == "active"
    assert directory.approve(elder_id, 1) is False  # 이미 활성이다


def test_only_the_owning_guardian_can_approve_or_reject(directory):
    elder_id = make_pending(directory)
    other = directory.add_guardian("다른 보호자", "010-3333-4444")

    assert directory.approve(elder_id, other) is False
    assert directory.reject(elder_id, other) is False
    assert directory.get(elder_id).status == "pending"


def test_only_pending_elders_can_be_approved_or_rejected(directory):
    assert directory.approve(13, 1) is False   # 이미 활성
    assert directory.reject(13, 1) is False
    assert directory.approve(12, 1) is False   # 운영자 등록(동의 전)은 앱에서 승인할 수 없다
    assert directory.reject(12, 1) is False
    assert directory.get(12).status == "unconsented" and directory.get(13).status == "active"
    assert directory.approve(424242, 1) is False


def test_rejecting_deletes_the_pending_elder_and_frees_the_number(directory):
    elder_id = make_pending(directory, phone="010-9999-1111")

    assert directory.reject(elder_id, 1) is True

    assert directory.get(elder_id) is None
    assert directory.find_by_phone("01099991111") is None
    assert make_pending(directory, phone="010-9999-1111")  # 같은 번호로 다시 가입할 수 있다
