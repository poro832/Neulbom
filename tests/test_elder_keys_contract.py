"""ElderKeyStore 규약 + 인증기 — 구현마다 같은 테스트를 돌린다."""

from __future__ import annotations

import pytest

from app.api.elder_auth import (
    ELDER_KEY_LENGTH,
    ELDER_KEY_PREFIX,
    ElderKeyAuth,
    InMemoryElderKeyStore,
    elder_key_label,
    generate_elder_key,
)
from tests.pg_helpers import DATABASE_URL


class Clock:
    def __init__(self):
        self.now = 1_800_000_000.0

    def __call__(self):
        return self.now


def _memory(clock):
    return InMemoryElderKeyStore(wall_clock=clock)


def _postgres(clock):
    from app.api.postgres_elder_keys import PostgresElderKeyStore
    from tests.pg_helpers import pg_pool, seed_world

    pool = pg_pool()
    seed_world(pool)
    return PostgresElderKeyStore(pool=pool, clock=clock)


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


def add(store, elder_id=12):
    new = generate_elder_key()
    store.replace(elder_id=elder_id, key_prefix=new.key_prefix, key_hash=new.key_hash)
    return new


def test_a_generated_key_has_the_documented_shape():
    new = generate_elder_key()

    assert new.key.startswith(ELDER_KEY_PREFIX)
    assert len(new.key) == ELDER_KEY_LENGTH == 47
    assert new.key_prefix == new.key[:12]
    assert new.key not in new.key_hash


def test_a_new_key_finds_its_elder(make_store):
    store = make_store(Clock())
    new = add(store, 13)

    assert store.find_elder(new.key_hash) == 13


def test_an_unknown_hash_finds_nobody(make_store):
    assert make_store(Clock()).find_elder("0" * 64) is None


def test_replacing_revokes_the_old_key_of_the_same_elder_only(make_store):
    store = make_store(Clock())
    old = add(store, 12)
    other = add(store, 13)

    new = add(store, 12)

    assert store.find_elder(old.key_hash) is None
    assert store.find_elder(new.key_hash) == 12
    assert store.find_elder(other.key_hash) == 13


def test_finding_a_key_records_when_it_was_last_used(make_store):
    clock = Clock()
    store = make_store(clock)
    new = add(store)
    assert store.last_used_at(new.key_hash) is None

    clock.now += 60
    store.find_elder(new.key_hash)

    assert store.last_used_at(new.key_hash) == pytest.approx(clock.now)


def test_the_same_hash_cannot_be_added_twice(make_store):
    store = make_store(Clock())
    new = add(store)

    with pytest.raises(Exception):
        store.replace(elder_id=13, key_prefix=new.key_prefix, key_hash=new.key_hash)


class ExplodingStore:
    def find_elder(self, key_hash):
        raise AssertionError("저장소를 부르면 안 된다")


def test_a_malformed_key_never_reaches_the_store():
    auth = ElderKeyAuth(ExplodingStore())

    for header in (None, "Bearer", "Bearer short", "Bearer nle_tooshort", "Bearer nlb_" + "x" * 43, "Basic x"):
        assert auth.authenticate(header) is None


def test_the_authenticator_accepts_a_known_key_and_rejects_a_guardian_key():
    store = InMemoryElderKeyStore()
    new = add(store, 12)
    auth = ElderKeyAuth(store)

    assert auth.authenticate(f"Bearer {new.key}") == 12
    assert auth.authenticate(f"bearer  {new.key} ") == 12
    assert auth.authenticate("Bearer nlb_" + new.key[4:]) is None


def test_the_log_label_shows_at_most_the_prefix():
    new = generate_elder_key()

    assert elder_key_label(f"Bearer {new.key}") == new.key[:12]
    assert elder_key_label("Bearer nope") == "(형식 오류)"
    assert elder_key_label(None) == "(형식 오류)"
