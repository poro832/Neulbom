"""LinkCodeStore 규약 — 메모리와 Postgres에 같은 테스트."""

from __future__ import annotations

import os
import threading

import pytest

from app.api.link_codes import LINK_CODE_TTL_SECONDS, CodeCollision, InMemoryLinkCodeStore

DATABASE_URL = os.getenv("DATABASE_URL")


class Clock:
    def __init__(self, now: float = 1_000_000.0):
        self.now = now

    def __call__(self) -> float:
        return self.now


@pytest.fixture(
    params=[
        "memory",
        pytest.param(
            "postgres",
            marks=pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL이 없다"),
        ),
    ]
)
def kit(request):
    clock = Clock()
    if request.param == "memory":
        return InMemoryLinkCodeStore(clock=clock), clock
    from app.api.postgres_link_codes import PostgresLinkCodeStore
    from tests.pg_helpers import pg_pool, seed_world

    pool = pg_pool()
    seed_world(pool)  # 어르신 12·13·14
    return PostgresLinkCodeStore(pool=pool, clock=clock), clock


def test_issue_returns_the_expiry_24_hours_ahead(kit):
    store, clock = kit
    assert store.issue(12, "h1") == clock.now + LINK_CODE_TTL_SECONDS


def test_find_returns_the_elder_for_a_live_code_and_none_otherwise(kit):
    store, _ = kit
    store.issue(12, "h1")

    assert store.find("h1") == 12
    assert store.find("nope") is None


def test_a_new_code_replaces_the_old_one(kit):
    store, _ = kit
    store.issue(12, "old")
    store.issue(12, "new")

    assert store.find("old") is None
    assert store.find("new") == 12


def test_a_code_expires(kit):
    store, clock = kit
    store.issue(12, "h1")
    clock.now += LINK_CODE_TTL_SECONDS + 1

    assert store.find("h1") is None
    assert store.consume("h1") is None


def test_consume_works_exactly_once(kit):
    store, _ = kit
    store.issue(12, "h1")

    assert store.consume("h1") == 12
    assert store.consume("h1") is None
    assert store.find("h1") is None


def test_two_threads_consuming_the_same_code_get_one_winner(kit):
    store, _ = kit
    store.issue(12, "h1")
    results: list[int | None] = []
    barrier = threading.Barrier(2)

    def worker():
        barrier.wait()
        results.append(store.consume("h1"))

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert sorted(results, key=lambda r: r is None) == [12, None]


def test_the_same_hash_for_another_elder_is_a_collision(kit):
    store, _ = kit
    store.issue(12, "h1")

    with pytest.raises(CodeCollision):
        store.issue(13, "h1")
    assert store.find("h1") == 12


def test_reissuing_for_the_same_elder_with_the_same_hash_is_fine(kit):
    store, _ = kit
    store.issue(12, "h1")
    store.issue(12, "h1")

    assert store.find("h1") == 12
