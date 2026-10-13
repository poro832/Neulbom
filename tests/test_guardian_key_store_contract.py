"""GuardianKeyStore 규약 — 구현마다 같은 테스트를 돌린다.

다른 저장소 규약 파일과 같은 이유다: 두 구현이 갈라지면 개발할 땐 폐기가
먹는데 서버에서는 안 먹는 식으로 약속만 조용히 깨진다.
"""

from __future__ import annotations

import os

import pytest

from app.api.guardian_auth import AmbiguousPrefix, InMemoryGuardianKeyStore, generate_key

DATABASE_URL = os.getenv("DATABASE_URL")


class Clock:
    def __init__(self):
        self.now = 1_800_000_000.0

    def __call__(self):
        return self.now


def _memory(clock=None):
    return InMemoryGuardianKeyStore(wall_clock=clock or Clock())


def _postgres(clock=None):
    from app.api.db import assert_local, connect
    from app.api.postgres_guardian_keys import PostgresGuardianKeyStore

    assert_local()
    pool = connect(DATABASE_URL)
    with pool.connection() as conn:
        for guardian_id in (1, 2, 3):
            conn.execute(
                "INSERT INTO guardians (guardian_id, name, email, password_hash, phone_number) "
                "VALUES (%s, 'g', %s, 'not-a-login', '000') ON CONFLICT (guardian_id) DO NOTHING",
                (guardian_id, f"g{guardian_id}@example.invalid"),
            )
    store = PostgresGuardianKeyStore(pool=pool, clock=clock or Clock())
    store.reset_for_tests()
    return store


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


@pytest.fixture
def store(make_store):
    return make_store()


def add(store, guardian_id=1, label="폰"):
    new = generate_key()
    key_id = store.add(
        guardian_id=guardian_id, label=label, key_prefix=new.key_prefix, key_hash=new.key_hash
    )
    return key_id, new


def test_an_added_key_finds_its_guardian(store):
    _, new = add(store, guardian_id=3)

    assert store.find_guardian(new.key_hash) == 3


def test_an_unknown_hash_finds_nobody(store):
    assert store.find_guardian("0" * 64) is None


def test_finding_a_key_records_when_it_was_last_used(make_store):
    clock = Clock()
    store = make_store(clock)
    _, new = add(store)
    assert store.list_keys()[0].last_used_at is None

    clock.now += 60
    store.find_guardian(new.key_hash)

    assert store.list_keys()[0].last_used_at == pytest.approx(clock.now)


def test_revoking_blocks_the_key_and_a_second_revoke_does_nothing(store):
    _, new = add(store)

    assert store.revoke(new.key_prefix) == 1
    assert store.find_guardian(new.key_hash) is None
    assert store.revoke(new.key_prefix) == 0


def test_a_revoked_key_stays_in_the_list_with_its_revoke_time(store):
    _, new = add(store)
    store.revoke(new.key_prefix)

    (info,) = store.list_keys()

    assert info.revoked_at is not None
    assert info.key_prefix == new.key_prefix


def test_a_prefix_shared_by_two_keys_is_refused(store):
    store.add(guardian_id=1, label="a", key_prefix="nlb_aaaaaaaa", key_hash="1" * 64)
    store.add(guardian_id=1, label="b", key_prefix="nlb_aaaaaaab", key_hash="2" * 64)

    with pytest.raises(AmbiguousPrefix):
        store.revoke("nlb_aaaaaaa")

    assert store.find_guardian("1" * 64) == 1
    assert store.find_guardian("2" * 64) == 1


def test_a_prefix_that_is_too_short_is_refused(store):
    add(store)

    with pytest.raises(ValueError):
        store.revoke("nlb_")


def test_the_same_hash_cannot_be_added_twice(store):
    _, new = add(store)

    with pytest.raises(Exception):
        store.add(guardian_id=2, label="x", key_prefix=new.key_prefix, key_hash=new.key_hash)


def test_the_list_never_contains_the_hash_or_the_full_key(store):
    _, new = add(store)

    dumped = repr(store.list_keys())

    assert new.key_hash not in dumped
    assert new.key not in dumped


# ------------------------------------------------ 로그아웃·비밀번호 변경용 폐기


def test_revoke_hash_blocks_only_that_key(store):
    _, mine = add(store, guardian_id=1, label="폰1")
    _, other = add(store, guardian_id=1, label="폰2")

    assert store.revoke_hash(mine.key_hash) is True

    assert store.find_guardian(mine.key_hash) is None
    assert store.find_guardian(other.key_hash) == 1


def test_revoke_hash_twice_or_unknown_is_false(store):
    _, mine = add(store)
    assert store.revoke_hash(mine.key_hash) is True
    assert store.revoke_hash(mine.key_hash) is False
    assert store.revoke_hash("0" * 64) is False


def test_revoke_others_keeps_only_the_kept_key(store):
    _, keep = add(store, guardian_id=1, label="이 폰")
    _, a = add(store, guardian_id=1, label="다른 폰")
    _, b = add(store, guardian_id=1, label="또 다른 폰")
    _, stranger = add(store, guardian_id=2, label="남의 폰")

    assert store.revoke_others(1, keep.key_hash) == 2

    assert store.find_guardian(keep.key_hash) == 1
    assert store.find_guardian(a.key_hash) is None
    assert store.find_guardian(b.key_hash) is None
    assert store.find_guardian(stranger.key_hash) == 2  # 다른 보호자의 열쇠는 건드리지 않는다


def test_revoke_others_with_nothing_else_is_zero(store):
    _, keep = add(store, guardian_id=1)
    assert store.revoke_others(1, keep.key_hash) == 0


def test_is_active_is_true_until_the_key_is_revoked(store):
    _, new = add(store)
    assert store.is_active(new.key_hash) is True
    store.revoke_hash(new.key_hash)
    assert store.is_active(new.key_hash) is False


def test_is_active_is_false_for_an_unknown_hash(store):
    assert store.is_active("0" * 64) is False


def test_is_active_does_not_touch_last_used(store):
    _, new = add(store)
    store.is_active(new.key_hash)
    (info,) = [i for i in store.list_keys() if i.key_prefix == new.key_prefix]
    assert info.last_used_at is None
