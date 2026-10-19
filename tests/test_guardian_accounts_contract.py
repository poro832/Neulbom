"""GuardianAccounts 규약 — 메모리와 Postgres에 같은 테스트를 돌린다."""

from __future__ import annotations

import os

import pytest

from app.api.guardian_accounts import EmailTaken, InMemoryGuardianAccounts, normalize_email

DATABASE_URL = os.getenv("DATABASE_URL")


def _memory():
    return InMemoryGuardianAccounts()


def _postgres():
    from app.api.postgres_guardian_accounts import PostgresGuardianAccounts
    from tests.pg_helpers import pg_pool, seed_world

    pool = pg_pool()
    seed_world(pool)
    return PostgresGuardianAccounts(pool=pool)


@pytest.fixture(
    params=[
        "memory",
        pytest.param("postgres", marks=pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL이 없다")),
    ]
)
def accounts(request):
    return _memory() if request.param == "memory" else _postgres()


def test_normalize_email_lowers_and_strips():
    assert normalize_email("  Kim@Example.COM ") == "kim@example.com"


def test_create_then_find_by_email_ignores_case_and_spaces(accounts):
    gid = accounts.create("김보호", "Kim@Example.com", "010-1111-2222", "HASH")
    found = accounts.find_by_email("  kim@example.COM")
    assert found is not None
    assert (found.guardian_id, found.name, found.email, found.phone, found.password_hash) == (
        gid, "김보호", "kim@example.com", "010-1111-2222", "HASH")


def test_unknown_email_is_none(accounts):
    assert accounts.find_by_email("nobody@example.com") is None


def test_same_email_in_other_case_is_taken(accounts):
    accounts.create("가", "a@example.com", "010-1", "H")
    with pytest.raises(EmailTaken):
        accounts.create("나", "A@EXAMPLE.com ", "010-2", "H2")


def test_profile_by_id(accounts):
    gid = accounts.create("가", "a@example.com", "010-1", "H")
    p = accounts.profile(gid)
    assert (p.name, p.email, p.phone) == ("가", "a@example.com", "010-1")
    assert accounts.profile(999_999) is None


def test_set_password_replaces_the_hash(accounts):
    gid = accounts.create("가", "a@example.com", "010-1", "OLD")
    accounts.set_password(gid, "NEW")
    assert accounts.find_by_email("a@example.com").password_hash == "NEW"


def test_set_login_gives_an_existing_guardian_an_email_and_password(accounts):
    gid = accounts.create("가", "placeholder@no-login.invalid", "010-1", "not-a-login")
    assert accounts.set_login(gid, "Real@Example.com", "HASH") is True
    assert accounts.find_by_email("real@example.com").guardian_id == gid
    assert accounts.find_by_email("placeholder@no-login.invalid") is None


def test_set_login_for_a_missing_guardian_is_false(accounts):
    assert accounts.set_login(999_999, "x@example.com", "H") is False


def test_set_login_with_a_taken_email_raises_and_changes_nothing(accounts):
    accounts.create("가", "a@example.com", "010-1", "H")
    gid = accounts.create("나", "b@example.com", "010-2", "H2")
    with pytest.raises(EmailTaken):
        accounts.set_login(gid, "a@example.com", "NEW")
    assert accounts.find_by_email("b@example.com").password_hash == "H2"


def test_new_accounts_wait_for_the_operator_until_activated(accounts):
    gid = accounts.create("가", "a@example.com", "010-1", "H")
    assert accounts.profile(gid).activated is False
    assert [a.guardian_id for a in accounts.pending()] == [gid]

    assert accounts.activate(gid) is True
    assert accounts.profile(gid).activated is True
    assert accounts.pending() == []
    assert accounts.activate(999_999) is False


def test_create_can_open_an_account_at_once(accounts):
    gid = accounts.create("가", "a@example.com", "010-1", "H", activated=True)
    assert accounts.profile(gid).activated is True


def test_set_login_opens_the_account(accounts):
    gid = accounts.create("가", "placeholder@no-login.invalid", "010-1", "not-a-login")
    accounts.set_login(gid, "real@example.com", "HASH")
    assert accounts.profile(gid).activated is True


def test_a_new_app_account_is_unverified_until_marked(accounts):
    gid = accounts.create("가", "v1@example.com", "010-1", "H")
    assert accounts.profile(gid).email_verified is False

    assert accounts.mark_email_verified(gid) is True

    assert accounts.profile(gid).email_verified is True
    assert accounts.find_by_email("v1@example.com").email_verified is True
    assert accounts.mark_email_verified(999_999) is False


def test_an_account_opened_by_the_operator_is_verified_by_default(accounts):
    gid = accounts.create("가", "v2@example.com", "010-1", "H", activated=True)
    assert accounts.profile(gid).email_verified is True


def test_the_verified_flag_can_be_set_explicitly(accounts):
    gid = accounts.create("가", "v3@example.com", "010-1", "H", activated=True, email_verified=False)
    assert accounts.profile(gid).email_verified is False


def test_set_login_marks_the_email_verified(accounts):
    gid = accounts.create("가", "v4@example.com", "010-1", "H")
    assert accounts.set_login(gid, "v4-new@example.com", "H2") is True
    assert accounts.profile(gid).email_verified is True


def test_deleting_an_account_removes_it_and_frees_the_email(accounts):
    gid = accounts.create("가", "del@example.com", "010-1", "H")
    other = accounts.create("나", "keep@example.com", "010-2", "H2")

    assert accounts.delete(gid) is True

    assert accounts.profile(gid) is None
    assert accounts.find_by_email("del@example.com") is None
    assert gid not in [a.guardian_id for a in accounts.pending()]
    assert accounts.profile(other).email == "keep@example.com"
    assert accounts.delete(gid) is False
    assert accounts.delete(999_999) is False
    again = accounts.create("가", "del@example.com", "010-1", "H")  # 같은 이메일로 다시 가입할 수 있다
    assert again != gid


@pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL이 없다")
def test_postgres_refuses_to_delete_a_guardian_who_still_has_elders():
    """elders.guardian_id가 ON DELETE CASCADE라 그냥 지우면 어르신까지 지워진다. 연결을 먼저 풀어야만 지운다."""
    from app.api.postgres_elder_directory import PostgresElderDirectory

    accounts = _postgres()  # 보호자 1에게 어르신 12·13이 있다
    pool = accounts._pool

    assert accounts.delete(1) is False

    assert accounts.profile(1) is not None
    with pool.connection() as conn:
        assert conn.execute("SELECT count(*) FROM elders WHERE elder_id IN (12, 13)").fetchone()[0] == 2

    assert PostgresElderDirectory(pool=pool).detach_all_from(1) == [12, 13]
    assert accounts.delete(1) is True
    with pool.connection() as conn:
        assert conn.execute("SELECT count(*) FROM elders WHERE elder_id IN (12, 13)").fetchone()[0] == 2
        assert conn.execute("SELECT count(*) FROM guardians WHERE guardian_id = 1").fetchone()[0] == 0


def test_pending_reports_the_real_verification_state(accounts):
    gid = accounts.create("가", "v5@example.com", "010-1", "H")
    assert [(a.guardian_id, a.email_verified) for a in accounts.pending() if a.guardian_id == gid] == [(gid, False)]

    accounts.mark_email_verified(gid)

    assert [(a.guardian_id, a.email_verified) for a in accounts.pending() if a.guardian_id == gid] == [(gid, True)]
