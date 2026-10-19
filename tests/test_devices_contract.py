"""DeviceStore 규약 — 메모리와 Postgres에 같은 테스트를 돌린다 (설계: 푸시 알림)."""

from __future__ import annotations

import os

import pytest

from app.api.devices import InMemoryDeviceStore
from app.api.guardian_auth import hash_key

DATABASE_URL = os.getenv("DATABASE_URL")
K1, K2, K3 = hash_key("k1"), hash_key("k2"), hash_key("k3")
T1, T2, T3 = "token-aaaaaaaaaaaaaaaaaaaa", "token-bbbbbbbbbbbbbbbbbbbb", "token-cccccccccccccccccccc"


@pytest.fixture(
    params=[
        "memory",
        pytest.param(
            "postgres",
            marks=pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL이 없다"),
        ),
    ]
)
def world(request):
    """(devices, add_key, revoke_key) — 열쇠가 살아 있는지는 구현마다 다른 방식으로 만든다."""
    if request.param == "memory":
        active: set[str] = set()
        yield InMemoryDeviceStore(is_key_active=active.__contains__), active.add, active.discard
        return

    from app.api.postgres_devices import PostgresDeviceStore
    from app.api.postgres_guardian_keys import PostgresGuardianKeyStore
    from tests.pg_helpers import pg_pool, seed_world

    pool = pg_pool()
    seed_world(pool)
    keys = PostgresGuardianKeyStore(pool=pool)

    def add_key(key_hash):
        keys.add(guardian_id=1, label="t", key_prefix=key_hash[:12], key_hash=key_hash)

    yield PostgresDeviceStore(pool=pool), add_key, keys.revoke_hash
    pool.close()


def test_registered_tokens_are_listed_for_the_guardian(world):
    devices, add_key, _ = world
    add_key(K1)
    devices.register(1, K1, T1)
    devices.register(1, K1, T2)
    assert sorted(devices.tokens_for(1)) == sorted([T1, T2])
    assert devices.tokens_for(2) == []


def test_registering_the_same_token_twice_keeps_one(world):
    devices, add_key, _ = world
    add_key(K1)
    devices.register(1, K1, T1)
    devices.register(1, K1, T1)
    assert devices.tokens_for(1) == [T1]


def test_a_token_registered_by_another_guardian_moves_to_them(world):
    devices, add_key, _ = world
    add_key(K1)
    add_key(K2)
    devices.register(1, K1, T1)
    devices.register(2, K2, T1)
    assert devices.tokens_for(1) == []
    assert devices.tokens_for(2) == [T1]


def test_tokens_of_a_revoked_key_are_not_listed(world):
    devices, add_key, revoke_key = world
    add_key(K1)
    add_key(K2)
    devices.register(1, K1, T1)
    devices.register(1, K2, T2)
    revoke_key(K1)
    assert devices.tokens_for(1) == [T2]


def test_unregister_removes_only_the_guardians_own_token(world):
    devices, add_key, _ = world
    add_key(K1)
    add_key(K2)
    devices.register(1, K1, T1)
    devices.register(2, K2, T2)
    assert devices.unregister(1, T2) is False  # 남의 토큰
    assert devices.tokens_for(2) == [T2]
    assert devices.unregister(1, T1) is True
    assert devices.unregister(1, T1) is False
    assert devices.tokens_for(1) == []


def test_remove_for_key_removes_that_keys_tokens_only(world):
    devices, add_key, _ = world
    add_key(K1)
    add_key(K2)
    devices.register(1, K1, T1)
    devices.register(1, K2, T2)
    assert devices.remove_for_key(K1) == 1
    assert devices.tokens_for(1) == [T2]


def test_remove_for_guardian_removes_every_phone_of_that_guardian_only(world):
    devices, add_key, revoke_key = world
    add_key(K1)
    add_key(K2)
    add_key(K3)
    devices.register(1, K1, T1)
    devices.register(1, K2, T2)
    revoke_key(K2)  # 폐기된 열쇠에 묶인 등록도 같이 지운다
    devices.register(2, K3, T3)

    assert devices.remove_for_guardian(1) == 2

    assert devices.tokens_for(1) == []
    assert devices.unregister(1, T1) is False and devices.unregister(1, T2) is False  # 행이 없다
    assert devices.tokens_for(2) == [T3]
    assert devices.remove_for_guardian(1) == 0


def test_remove_token_deletes_an_unknown_token_quietly(world):
    devices, add_key, _ = world
    add_key(K1)
    devices.register(1, K1, T1)
    devices.remove_token(T1)
    devices.remove_token(T3)
    assert devices.tokens_for(1) == []


def test_registering_clears_stale_rows_of_revoked_keys_for_that_guardian(world):
    devices, add_key, revoke_key = world
    add_key(K1)
    add_key(K2)
    devices.register(1, K1, T1)
    revoke_key(K1)  # 폐기된 열쇠의 옛 등록이 남아 있다
    devices.register(1, K2, T2)
    assert devices.unregister(1, T1) is False  # 이미 치워졌다
    assert devices.tokens_for(1) == [T2]


def test_cleanup_never_touches_other_guardians_rows(world):
    devices, add_key, revoke_key = world
    add_key(K1)
    add_key(K2)
    add_key(K3)
    devices.register(2, K3, T3)
    revoke_key(K3)
    devices.register(1, K1, T1)
    assert devices.unregister(2, T3) is True  # 보호자 2의 행은 보호자 1의 등록으로 지워지지 않는다



def test_register_returns_the_previous_owner_or_none(world):
    devices, add_key, _ = world
    add_key(K1)
    add_key(K2)
    assert devices.register(1, K1, T1) is None  # 처음 보는 토큰
    assert devices.register(1, K1, T1) == 1  # 같은 보호자가 다시 등록
    assert devices.register(2, K2, T1) == 1  # 다른 보호자에게서 넘어온 토큰


def test_registering_beyond_five_phones_removes_the_oldest(world):
    devices, add_key, _ = world
    add_key(K1)
    tokens = [f"token-{i:02d}" + "x" * 14 for i in range(7)]
    for t in tokens:
        devices.register(1, K1, t)
    assert sorted(devices.tokens_for(1)) == sorted(tokens[2:])  # 가장 오래된 둘이 밀려났다


def test_the_phone_limit_never_touches_other_guardians(world):
    devices, add_key, _ = world
    add_key(K1)
    add_key(K2)
    devices.register(2, K2, T3)
    for i in range(7):
        devices.register(1, K1, f"token-{i:02d}" + "x" * 14)
    assert devices.tokens_for(2) == [T3]
    assert len(devices.tokens_for(1)) == 5
