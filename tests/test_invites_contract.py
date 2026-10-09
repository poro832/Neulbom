"""InviteStore 규약 — 구현마다 같은 테스트를 돌린다."""

from __future__ import annotations

import pytest

from app.api.invites import (
    INVITE_DIGITS,
    InMemoryInviteStore,
    hash_invite_code,
    new_invite_code,
)
from tests.pg_helpers import DATABASE_URL


def _memory():
    return InMemoryInviteStore()


def _postgres():
    from app.api.postgres_invites import PostgresInviteStore
    from tests.pg_helpers import pg_pool, seed_world

    pool = pg_pool()
    seed_world(pool)
    return PostgresInviteStore(pool=pool)


@pytest.fixture(
    params=[
        "memory",
        pytest.param(
            "postgres",
            marks=pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL이 없다"),
        ),
    ]
)
def store(request):
    return _memory() if request.param == "memory" else _postgres()


def test_a_generated_code_is_always_eight_digits_even_with_leading_zeros():
    codes = {new_invite_code() for _ in range(300)}

    assert INVITE_DIGITS == 8
    assert all(len(code) == 8 and code.isdigit() for code in codes)
    assert hash_invite_code("00001234") != hash_invite_code("1234")


def test_an_issued_code_finds_its_guardian(store):
    store.issue(1, hash_invite_code("00001234"))

    assert store.find_guardian(hash_invite_code("00001234")) == 1
    assert store.find_guardian(hash_invite_code("99999999")) is None


def test_the_code_can_be_used_by_many_signups(store):
    store.issue(1, hash_invite_code("11112222"))

    assert store.find_guardian(hash_invite_code("11112222")) == 1
    assert store.find_guardian(hash_invite_code("11112222")) == 1


def test_issuing_again_revokes_the_previous_code_of_the_same_guardian_only(store):
    store.issue(1, hash_invite_code("11111111"))
    store.issue(2, hash_invite_code("22222222"))

    store.issue(1, hash_invite_code("33333333"))

    assert store.find_guardian(hash_invite_code("11111111")) is None
    assert store.find_guardian(hash_invite_code("33333333")) == 1
    assert store.find_guardian(hash_invite_code("22222222")) == 2


def test_the_same_hash_cannot_be_issued_twice(store):
    store.issue(1, hash_invite_code("11111111"))

    with pytest.raises(Exception):
        store.issue(2, hash_invite_code("11111111"))
