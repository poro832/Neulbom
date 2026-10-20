"""LinkCodeStore 규약 — 메모리와 Postgres에 같은 테스트 (어르신마다 하나뿐인 고정 코드)."""

from __future__ import annotations

import os

import pytest

from app.api.link_codes import CodeCollision, InMemoryLinkCodeStore

DATABASE_URL = os.getenv("DATABASE_URL")


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
    if request.param == "memory":
        return InMemoryLinkCodeStore()
    from app.api.postgres_link_codes import PostgresLinkCodeStore
    from tests.pg_helpers import pg_pool, seed_world

    pool = pg_pool()
    seed_world(pool)  # 어르신 12·13·14
    return PostgresLinkCodeStore(pool=pool)


def test_find_returns_the_elder_and_none_for_unknown_codes(store):
    store.issue(12, "h1", "11112222")

    assert store.find("h1") == 12
    assert store.find("nope") is None


def test_the_plain_code_can_be_read_back_for_the_elder(store):
    assert store.code_of(12) is None

    store.issue(12, "h1", "11112222")

    assert store.code_of(12) == "11112222"
    assert store.code_of(13) is None


def test_finding_does_not_use_the_code_up(store):
    store.issue(12, "h1", "11112222")

    assert store.find("h1") == 12
    assert store.find("h1") == 12
    assert store.code_of(12) == "11112222"


def test_a_new_code_replaces_the_old_one(store):
    store.issue(12, "old", "11112222")
    store.issue(12, "new", "33334444")

    assert store.find("old") is None
    assert store.find("new") == 12
    assert store.code_of(12) == "33334444"


def test_the_same_hash_for_another_elder_is_a_collision(store):
    store.issue(12, "h1", "11112222")

    with pytest.raises(CodeCollision):
        store.issue(13, "h1", "11112222")
    assert store.find("h1") == 12
    assert store.code_of(13) is None


def test_reissuing_for_the_same_elder_with_the_same_hash_is_fine(store):
    store.issue(12, "h1", "11112222")
    store.issue(12, "h1", "11112222")

    assert store.find("h1") == 12


def test_codes_of_different_elders_are_independent(store):
    store.issue(12, "h1", "11112222")
    store.issue(13, "h2", "33334444")

    assert (store.find("h1"), store.find("h2")) == (12, 13)
    assert (store.code_of(12), store.code_of(13)) == ("11112222", "33334444")
