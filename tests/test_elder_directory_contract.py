"""ElderDirectory와 DirectoryAdmin 규약 — 두 구현에 같은 테스트."""

from __future__ import annotations

import os
from datetime import time

import pytest

from app.api.elder_directory import (
    ElderAccess,
    GuardianProfile,
    InMemoryElderDirectory,
    PhoneTaken,
    mask_phone,
)

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


def test_an_unlinked_signup_has_no_guardian_and_no_consent(directory):
    elder_id = directory.create_unlinked(name="홍길동", phone="010-9999-1111")

    access = directory.get(elder_id)
    assert access == ElderAccess(guardian_id=None, consenting=False, name="홍길동", agreed=True)
    assert access.status == "unlinked"
    assert directory.phone_of(elder_id) == "010-9999-1111"


def test_an_unknown_elder_has_no_phone(directory):
    assert directory.phone_of(4242) is None


def test_an_unlinked_signup_refuses_a_number_already_registered(directory):
    with pytest.raises(PhoneTaken):
        directory.create_unlinked(name="가", phone="070 0000 0012")


def test_linking_fills_guardian_and_consent_exactly_once(directory):
    elder_id = directory.create_unlinked(name="홍길동", phone="010-9999-1111")

    assert directory.link(elder_id, 1) is True

    access = directory.get(elder_id)
    assert access.guardian_id == 1 and access.consenting and access.status == "active"
    assert directory.link(elder_id, 1) is False  # 같은 보호자가 또 연결해도 달라지지 않는다


def test_linking_an_unknown_elder_is_false(directory):
    assert directory.link(4242, 1) is False


def test_unlinked_elders_are_in_nobodys_list(directory):
    elder_id = directory.create_unlinked(name="홍길동", phone="010-9999-1111")

    assert elder_id not in [ref.elder_id for ref in directory.elders_of(1)]


def test_mask_phone_hides_the_middle_digits():
    assert mask_phone("010-9999-1111") == "010-****-1111"
    assert mask_phone("01099991111") == "010-****-1111"
    assert mask_phone("12345") == "****"


def test_discarding_an_unlinked_elder_deletes_it_and_frees_the_number(directory):
    elder_id = directory.create_unlinked(name="홍길동", phone="010-9999-1111")

    assert directory.discard_unlinked(elder_id) is True

    assert directory.get(elder_id) is None
    assert directory.phone_of(elder_id) is None
    assert directory.create_unlinked(name="홍길동", phone="010-9999-1111") > 0


def test_discarding_refuses_a_linked_elder_and_an_unknown_id(directory):
    elder_id = directory.create_unlinked(name="홍길동", phone="010-9999-1111")
    assert directory.link(elder_id, 1) is True

    assert directory.discard_unlinked(elder_id) is False
    assert directory.get(elder_id) is not None
    assert directory.discard_unlinked(4242) is False
    assert directory.discard_unlinked(1) is False  # 시드 어르신은 보호자가 있다


# ------------------------------------------------ 안부 전화 시간


def test_the_call_time_defaults_to_nine(directory):
    assert directory.call_time_of(12) == time(9, 0)
    assert directory.call_time_of(13) == time(9, 0)


def test_a_changed_call_time_is_read_back_and_touches_only_that_elder(directory):
    assert directory.set_call_time(13, 1, time(7, 30)) is True

    assert directory.call_time_of(13) == time(7, 30)
    assert directory.call_time_of(12) == time(9, 0)
    assert directory.set_call_time(13, 1, time(21, 0)) is True
    assert directory.call_time_of(13) == time(21, 0)


def test_another_guardian_cannot_change_the_call_time(directory):
    other = directory.add_guardian("다른 보호자", "010-3333-4444")

    assert directory.set_call_time(13, other, time(10, 0)) is False

    assert directory.call_time_of(13) == time(9, 0)


def test_an_unknown_elder_has_no_call_time_and_cannot_get_one(directory):
    assert directory.call_time_of(4242) is None
    assert directory.set_call_time(4242, 1, time(10, 0)) is False
    assert directory.call_time_of(4242) is None


def test_an_unlinked_elder_has_no_guardian_to_change_the_call_time(directory):
    elder_id = directory.create_unlinked(name="홍길동", phone="010-9999-1111")

    assert directory.call_time_of(elder_id) == time(9, 0)
    assert directory.set_call_time(elder_id, 1, time(10, 0)) is False
    assert directory.call_time_of(elder_id) == time(9, 0)


# ------------------------------------------------ 탈퇴: 연결 해제 · 어르신 삭제 · 녹음 키


def seed_audio(directory, elder_id, key):
    """그 어르신 통화의 녹음 키를 심는다. 메모리는 직접, Postgres는 통화 행으로."""
    if isinstance(directory, InMemoryElderDirectory):
        directory.add_audio_key(elder_id, key)
        return
    with directory._pool.connection() as conn:
        conn.execute(
            "INSERT INTO calls (elder_id, status, audio_key) VALUES (%s, 'completed', %s)", (elder_id, key)
        )


def test_detaching_a_guardians_elders_unlinks_them_and_keeps_their_data(directory):
    other = directory.add_guardian("다른 보호자", "010-3333-4444")
    theirs = make_pending(directory, guardian_id=other, phone="010-9999-2222")
    directory.set_call_time(13, 1, time(7, 30))

    assert directory.detach_all_from(1) == [12, 13]  # 푼 어르신 번호(오름차순) — 그 어르신들의 안 쓴 연결 코드를 지운다

    for elder_id, name in ((12, "어르신 12"), (13, "어르신 13")):
        access = directory.get(elder_id)
        assert access.guardian_id is None and access.consenting is False and access.status == "unlinked"
        assert access.name == name
    assert directory.phone_of(13) == "070-0000-0013"
    assert directory.call_time_of(13) == time(7, 30)
    assert directory.elders_of(1) == []
    # 다른 보호자의 어르신은 그대로다
    assert directory.get(theirs).guardian_id == other and directory.get(theirs).status == "pending"
    assert directory.detach_all_from(1) == []
    assert directory.detach_all_from(99999) == []


def test_a_detached_elder_who_agreed_can_be_linked_by_another_guardian(directory):
    elder_id = directory.create_unlinked(name="홍길동", phone="010-9999-1111")
    assert directory.link(elder_id, 1) is True
    other = directory.add_guardian("다른 보호자", "010-3333-4444")

    directory.detach_all_from(1)

    access = directory.get(elder_id)
    assert access.status == "unlinked" and access.agreed is True
    assert directory.link(elder_id, other) is True
    assert directory.get(elder_id).guardian_id == other and directory.get(elder_id).status == "active"


def test_deleting_an_elder_removes_it_and_frees_the_number(directory):
    directory.set_call_time(13, 1, time(7, 30))

    assert directory.delete_elder(13) is True

    assert directory.get(13) is None
    assert directory.phone_of(13) is None and directory.find_by_phone("070-0000-0013") is None
    assert directory.call_time_of(13) is None
    assert [e.elder_id for e in directory.elders_of(1)] == [12]
    assert directory.get(12) == ElderAccess(guardian_id=1, consenting=False, name="어르신 12")
    assert directory.delete_elder(13) is False
    assert directory.delete_elder(4242) is False
    again = directory.create_unlinked(name="다시", phone="070-0000-0013")
    assert again != 13  # 지운 어르신의 번호는 다시 쓰지 않는다(다른 저장소에 남은 옛 기록이 붙지 않게)


def test_deleting_works_for_unlinked_and_pending_elders_too(directory):
    unlinked = directory.create_unlinked(name="홍길동", phone="010-9999-1111")
    pending = make_pending(directory, phone="010-9999-2222")

    assert directory.delete_elder(unlinked) is True
    assert directory.delete_elder(pending) is True

    assert directory.get(unlinked) is None and directory.get(pending) is None


def test_audio_keys_are_listed_per_elder_and_go_with_the_elder(directory):
    assert directory.audio_keys_of(12) == []
    seed_audio(directory, 12, "12-a.wav")
    seed_audio(directory, 12, "12-b.wav")
    seed_audio(directory, 13, "13-a.wav")

    assert sorted(directory.audio_keys_of(12)) == ["12-a.wav", "12-b.wav"]
    assert directory.audio_keys_of(13) == ["13-a.wav"]
    assert directory.audio_keys_of(4242) == []

    directory.delete_elder(12)

    assert directory.audio_keys_of(12) == []
    assert directory.audio_keys_of(13) == ["13-a.wav"]


@pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL이 없다")
def test_calls_without_a_recording_have_no_audio_key():
    directory = _postgres()
    with directory._pool.connection() as conn:
        conn.execute("INSERT INTO calls (elder_id, status) VALUES (12, 'no_answer')")
        conn.execute("INSERT INTO calls (elder_id, status, audio_key) VALUES (12, 'completed', '12-a.wav')")

    assert directory.audio_keys_of(12) == ["12-a.wav"]


@pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL이 없다")
def test_detaching_clears_only_the_guardian_and_the_call_consent_columns():
    """보호자 탈퇴는 전화 동의만 비운다. 가입 동의·공유 동의·통화 시각·통화 기록은 그대로다."""
    directory = _postgres()
    with directory._pool.connection() as conn:
        conn.execute("UPDATE elders SET agreed_at = now(), share_agreed_at = now() WHERE elder_id = 13")
        conn.execute("INSERT INTO calls (elder_id, status, audio_key) VALUES (13, 'completed', '13-a.wav')")

    directory.detach_all_from(1)

    with directory._pool.connection() as conn:
        row = conn.execute(
            "SELECT guardian_id, consent_at, agreed_at IS NOT NULL, share_agreed_at IS NOT NULL, "
            "(SELECT count(*) FROM calls WHERE elder_id = 13) FROM elders WHERE elder_id = 13"
        ).fetchone()
    assert row == (None, None, True, True, 1)


@pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL이 없다")
def test_the_new_call_time_lands_in_the_column_the_scheduler_reads():
    """스케줄러의 명부(PostgresRoster)는 elders.call_time을 매분 읽는다. 바꾼 값이 그 칸에 실제로 들어가야 바로 적용된다."""
    from app.api.postgres_store import PostgresRoster

    directory = _postgres()

    assert directory.set_call_time(13, 1, time(18, 30)) is True

    with directory._pool.connection() as conn:
        rows = conn.execute(
            "SELECT elder_id, call_time FROM elders WHERE elder_id IN (12, 13) ORDER BY elder_id"
        ).fetchall()
    assert rows == [(12, time(9, 0)), (13, time(18, 30))]
    # 동의한 어르신(13)만 명부에 나오고, 새 시간으로 나온다
    entries = PostgresRoster(pool=directory._pool).entries()
    assert [(e.elder_id, e.call_time) for e in entries] == [(13, time(18, 30))]


# ------------------------------------------------ 전화번호 바꾸기


def test_the_guardian_can_change_the_phone_and_the_old_number_stops_matching(directory):
    assert directory.set_phone(13, 1, "010-7777-1313") is True

    assert directory.phone_of(13) == "010-7777-1313"
    assert directory.find_by_phone("010-7777-1313") == 13
    assert directory.find_by_phone("070-0000-0013") is None
    assert directory.phone_of(12) == "070-0000-0012"  # 다른 어르신은 그대로


def test_a_number_another_elder_uses_cannot_be_taken(directory):
    from app.api.elder_directory import PhoneTaken

    with pytest.raises(PhoneTaken):
        directory.set_phone(13, 1, "070 0000 0012")  # 숫자만 비교한다

    assert directory.phone_of(13) == "070-0000-0013"


def test_changing_to_ones_own_number_again_is_allowed(directory):
    assert directory.set_phone(13, 1, "070-0000-0013") is True
    assert directory.set_phone(13, 1, "07000000013") is True
    assert directory.find_by_phone("070-0000-0013") == 13


def test_another_guardian_or_an_unknown_elder_cannot_change_the_phone(directory):
    other = directory.add_guardian("다른 보호자", "010-3333-4444")

    assert directory.set_phone(13, other, "010-7777-1313") is False
    assert directory.set_phone(4242, 1, "010-7777-1313") is False
    assert directory.phone_of(13) == "070-0000-0013"


def test_an_unlinked_elder_has_no_guardian_to_change_the_phone(directory):
    elder_id = directory.create_unlinked(name="홍길동", phone="010-9999-1111")

    assert directory.set_phone(elder_id, 1, "010-7777-1313") is False
    assert directory.phone_of(elder_id) == "010-9999-1111"


# ------------------------------------------------ 새 폰 로그인 열기·쓰기


def test_a_window_opened_by_the_guardian_lets_the_number_in_exactly_once(directory):
    assert directory.open_new_phone_login(13, 1, 2000.0) is True

    assert directory.claim_new_phone("070-0000-0013", 1000.0) == 13
    assert directory.claim_new_phone("070-0000-0013", 1000.0) is None  # 한 번뿐이다


def test_a_number_without_an_open_window_is_not_let_in(directory):
    assert directory.claim_new_phone("070-0000-0013", 1000.0) is None
    assert directory.claim_new_phone("010-4040-4040", 1000.0) is None  # 모르는 번호
    assert directory.claim_new_phone("", 1000.0) is None


def test_an_expired_window_lets_nobody_in_and_is_closed(directory):
    directory.open_new_phone_login(13, 1, 2000.0)

    assert directory.claim_new_phone("070-0000-0013", 2000.5) is None
    assert directory.claim_new_phone("070-0000-0013", 1000.0) is None  # 이미 닫혔다


def test_the_number_is_compared_by_its_digits(directory):
    directory.open_new_phone_login(13, 1, 2000.0)

    assert directory.claim_new_phone("07000000013", 1000.0) == 13


def test_only_the_guardian_of_the_elder_can_open_a_window(directory):
    other = directory.add_guardian("다른 보호자", "010-3333-4444")

    assert directory.open_new_phone_login(13, other, 2000.0) is False
    assert directory.open_new_phone_login(4242, 1, 2000.0) is False
    assert directory.claim_new_phone("070-0000-0013", 1000.0) is None


def test_an_unlinked_elder_has_no_guardian_to_open_a_window(directory):
    elder_id = directory.create_unlinked(name="홍길동", phone="010-9999-1111")

    assert directory.open_new_phone_login(elder_id, 1, 2000.0) is False


def test_reopening_after_use_lets_the_number_in_again(directory):
    directory.open_new_phone_login(13, 1, 2000.0)
    directory.claim_new_phone("070-0000-0013", 1000.0)
    directory.open_new_phone_login(13, 1, 3000.0)

    assert directory.claim_new_phone("070-0000-0013", 2500.0) == 13


def test_a_window_is_independent_per_elder(directory):
    directory.open_new_phone_login(13, 1, 2000.0)

    assert directory.claim_new_phone("070-0000-0012", 1000.0) is None  # 어르신 12는 열린 적 없다
    assert directory.claim_new_phone("070-0000-0013", 1000.0) == 13


def test_two_phones_using_the_same_open_window_get_one_winner(directory):
    import threading

    directory.open_new_phone_login(13, 1, 2000.0)
    results: list[int | None] = []
    barrier = threading.Barrier(2)

    def worker():
        barrier.wait()
        results.append(directory.claim_new_phone("070-0000-0013", 1000.0))

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sorted(results, key=lambda r: r is None) == [13, None]


# ------------------------------------------------ 여러 보호자가 한 어르신을 함께 본다


def linked_elder(directory, phone="010-9999-1111"):
    elder_id = directory.create_unlinked(name="홍길동", phone=phone)
    assert directory.link(elder_id, 1) is True
    return elder_id


def test_a_second_guardian_joins_without_changing_the_first_or_the_consent(directory):
    elder_id = linked_elder(directory)
    second = directory.add_guardian("둘째", "010-3333-4444")

    assert directory.link(elder_id, second) is True

    access = directory.get(elder_id)
    assert access.guardian_id == 1 and access.consenting and access.status == "active"
    assert access.guardian_ids == (1, second)
    assert directory.guardians_of(elder_id) == [1, second]
    assert directory.link(elder_id, second) is False  # 이미 보호자다


def test_both_guardians_list_the_elder_with_the_count_and_not_the_names(directory):
    elder_id = linked_elder(directory)
    second = directory.add_guardian("둘째", "010-3333-4444")
    directory.link(elder_id, second)

    for guardian in (1, second):
        ref = next(r for r in directory.elders_of(guardian) if r.elder_id == elder_id)
        assert ref.status == "active" and ref.guardian_count == 2


def test_every_guardian_can_change_the_call_time_and_the_phone(directory):
    elder_id = linked_elder(directory)
    second = directory.add_guardian("둘째", "010-3333-4444")
    directory.link(elder_id, second)

    assert directory.set_call_time(elder_id, second, time(6, 45)) is True
    assert directory.call_time_of(elder_id) == time(6, 45)
    assert directory.set_phone(elder_id, second, "010-8888-7777") is True
    assert directory.phone_of(elder_id) == "010-8888-7777"
    assert directory.open_new_phone_login(elder_id, second, 5000.0) is True
    assert directory.claim_new_phone("010-8888-7777", 1000.0) == elder_id


def test_a_stranger_still_cannot_change_anything(directory):
    elder_id = linked_elder(directory)
    stranger = directory.add_guardian("남", "010-5555-6666")

    assert directory.set_call_time(elder_id, stranger, time(6, 45)) is False
    assert directory.set_phone(elder_id, stranger, "010-8888-7777") is False
    assert directory.open_new_phone_login(elder_id, stranger, 5000.0) is False
    assert directory.elders_of(stranger) == []


def test_the_limit_of_guardians_per_elder_is_enforced(directory):
    elder_id = linked_elder(directory)
    joined = [directory.add_guardian(f"보호자 {i}", f"010-0000-00{i:02d}") for i in range(2, 5)]
    for guardian in joined:
        assert directory.link(elder_id, guardian, 4) is True
    extra = directory.add_guardian("다섯째", "010-0000-0099")

    assert directory.link(elder_id, extra, 4) is False  # 4명이 가득 찼다
    assert directory.link(elder_id, extra, 5) is True
    assert directory.guardians_of(elder_id) == sorted([1, *joined, extra])


def test_a_pending_elder_cannot_be_joined_by_another_guardian(directory):
    other = directory.add_guardian("다른 보호자", "010-3333-4444")

    assert directory.link(12, other) is False  # 어르신 12는 보호자 1의 승인 대기다


def test_one_guardian_leaving_keeps_the_elder_for_the_others(directory):
    elder_id = linked_elder(directory)
    second = directory.add_guardian("둘째", "010-3333-4444")
    directory.link(elder_id, second)

    assert directory.detach_all_from(second) == [elder_id]

    access = directory.get(elder_id)
    assert access.guardian_ids == (1,) and access.consenting and access.status == "active"
    assert directory.elders_of(second) == []


def test_the_primary_leaving_hands_the_role_to_the_smallest_remaining_id(directory):
    elder_id = linked_elder(directory)
    second = directory.add_guardian("둘째", "010-3333-4444")
    third = directory.add_guardian("셋째", "010-5555-6666")
    directory.link(elder_id, third)
    directory.link(elder_id, second)

    assert elder_id in directory.detach_all_from(1)

    access = directory.get(elder_id)
    assert access.guardian_id == second and access.guardian_ids == (second, third)
    assert access.consenting and access.status == "active"  # 안부 전화는 계속 나간다


def test_the_last_guardian_leaving_unlinks_the_elder(directory):
    elder_id = linked_elder(directory)
    second = directory.add_guardian("둘째", "010-3333-4444")
    directory.link(elder_id, second)

    directory.detach_all_from(1)
    directory.detach_all_from(second)

    access = directory.get(elder_id)
    assert access.guardian_id is None and access.consenting is False and access.status == "unlinked"
    assert directory.guardians_of(elder_id) == []
    assert directory.link(elder_id, 1) is True  # 새 보호자가 다시 이어받는다


def test_an_admin_assignment_replaces_the_guardians(directory):
    elder_id = linked_elder(directory)
    second = directory.add_guardian("둘째", "010-3333-4444")
    directory.link(elder_id, second)
    third = directory.add_guardian("셋째", "010-5555-6666")

    assert directory.assign_elder(elder_id, third) is True

    assert directory.get(elder_id).guardian_ids == (third,)
    assert directory.guardians_of(elder_id) == [third]
