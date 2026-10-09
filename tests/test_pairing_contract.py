"""PairingStore 규약 — 구현마다 같은 테스트를 돌린다."""

from __future__ import annotations

import pytest

from app.api.pairing import (
    CODE_TTL_SECONDS,
    MAX_FAILED_ATTEMPTS,
    InMemoryPairingStore,
    hash_code,
    new_code,
)
from tests.pg_helpers import DATABASE_URL


class Clock:
    def __init__(self):
        self.now = 1_800_000_000.0

    def __call__(self):
        return self.now


def _memory(clock):
    return InMemoryPairingStore(clock=clock)


def _postgres(clock):
    from app.api.postgres_pairing import PostgresPairingStore
    from tests.pg_helpers import pg_pool, seed_world

    pool = pg_pool()
    seed_world(pool)
    return PostgresPairingStore(pool=pool, clock=clock)


@pytest.fixture(
    params=[
        "memory",
        pytest.param(
            "postgres",
            marks=pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL이 없다"),
        ),
    ]
)
def make_store(request):
    return _memory if request.param == "memory" else _postgres


def test_a_generated_code_is_always_six_digits_even_with_leading_zeros():
    codes = {new_code() for _ in range(300)}

    assert all(len(code) == 6 and code.isdigit() for code in codes)
    assert hash_code("000123") != hash_code("123")
    assert hash_code("000123") == hash_code("000123")


def test_the_right_code_works_once(make_store):
    store = make_store(Clock())
    store.issue(12, hash_code("000123"))

    assert store.redeem(12, hash_code("000123")) is True
    assert store.redeem(12, hash_code("000123")) is False


def test_issue_returns_the_expiry_time(make_store):
    clock = Clock()
    store = make_store(clock)

    assert store.issue(12, hash_code("111111")) == pytest.approx(clock.now + CODE_TTL_SECONDS)


def test_a_wrong_code_fails_but_the_right_one_still_works_below_the_limit(make_store):
    store = make_store(Clock())
    store.issue(12, hash_code("111111"))

    for _ in range(MAX_FAILED_ATTEMPTS - 1):
        assert store.redeem(12, hash_code("999999")) is False

    assert store.redeem(12, hash_code("111111")) is True


def test_too_many_wrong_codes_lock_the_pairing_even_for_the_right_code(make_store):
    store = make_store(Clock())
    store.issue(12, hash_code("111111"))

    for _ in range(MAX_FAILED_ATTEMPTS):
        assert store.redeem(12, hash_code("999999")) is False

    assert store.redeem(12, hash_code("111111")) is False


def test_issuing_again_unlocks_and_invalidates_the_old_code(make_store):
    store = make_store(Clock())
    store.issue(12, hash_code("111111"))
    for _ in range(MAX_FAILED_ATTEMPTS):
        store.redeem(12, hash_code("999999"))

    store.issue(12, hash_code("222222"))

    assert store.redeem(12, hash_code("111111")) is False
    assert store.redeem(12, hash_code("222222")) is True


def test_an_expired_code_is_refused(make_store):
    clock = Clock()
    store = make_store(clock)
    store.issue(12, hash_code("111111"))

    clock.now += CODE_TTL_SECONDS + 1

    assert store.redeem(12, hash_code("111111")) is False


def test_a_code_is_valid_just_before_it_expires(make_store):
    clock = Clock()
    store = make_store(clock)
    store.issue(12, hash_code("111111"))

    clock.now += CODE_TTL_SECONDS - 1

    assert store.redeem(12, hash_code("111111")) is True


def test_a_code_only_works_for_its_own_elder(make_store):
    store = make_store(Clock())
    store.issue(12, hash_code("111111"))

    assert store.redeem(13, hash_code("111111")) is False
    assert store.redeem(12, hash_code("111111")) is True


def test_an_elder_without_a_code_cannot_redeem(make_store):
    assert make_store(Clock()).redeem(12, hash_code("111111")) is False
