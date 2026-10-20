"""WithdrawalStore 규약 — 메모리와 Postgres에 같은 테스트 (어르신 탈퇴 요청과 보호자 승인)."""

from __future__ import annotations

import os

import pytest

from app.api.withdrawals import InMemoryWithdrawalStore

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
        return InMemoryWithdrawalStore()
    from app.api.postgres_withdrawals import PostgresWithdrawalStore
    from tests.pg_helpers import pg_pool, seed_world

    pool = pg_pool()
    seed_world(pool)  # 어르신 12·13·14, 보호자 1·2
    return PostgresWithdrawalStore(pool=pool)


def test_there_is_no_request_until_one_is_opened(store):
    assert store.get(12) is None


def test_opening_a_request_starts_with_no_approvals(store):
    opened = store.open(12, 1000.0)

    assert opened.elder_id == 12 and opened.requested_at == 1000.0
    assert opened.approved_by == frozenset() and not opened.rejected
    assert store.get(12) == opened


def test_each_guardian_approves_once(store):
    store.open(12, 1000.0)

    first = store.approve(12, 1)
    again = store.approve(12, 1)
    both = store.approve(12, 2)

    assert first.approved_by == frozenset({1})
    assert again.approved_by == frozenset({1})
    assert both.approved_by == frozenset({1, 2})
    assert store.get(12).approved_by == frozenset({1, 2})


def test_approving_without_a_request_does_nothing(store):
    assert store.approve(12, 1) is None
    assert store.get(12) is None


def test_a_rejected_request_takes_no_more_approvals_and_shows_as_rejected(store):
    store.open(12, 1000.0)
    store.approve(12, 1)

    assert store.reject(12, 2000.0) is True

    request = store.get(12)
    assert request.rejected and request.rejected_at == 2000.0
    assert request.approved_by == frozenset({1})
    assert store.approve(12, 2) is None
    assert store.get(12).approved_by == frozenset({1})
    assert store.reject(12, 3000.0) is False  # 이미 거절됐다


def test_rejecting_without_a_request_changes_nothing(store):
    assert store.reject(12, 1000.0) is False


def test_a_new_request_replaces_a_rejected_one_and_clears_approvals(store):
    store.open(12, 1000.0)
    store.approve(12, 1)
    store.reject(12, 2000.0)

    fresh = store.open(12, 3000.0)

    assert fresh.requested_at == 3000.0 and not fresh.rejected and fresh.approved_by == frozenset()
    assert store.get(12) == fresh


def test_cancelling_removes_the_request(store):
    store.open(12, 1000.0)
    store.approve(12, 1)

    assert store.cancel(12) is True

    assert store.get(12) is None
    assert store.cancel(12) is False
    assert store.open(12, 5000.0).approved_by == frozenset()  # 옛 승인이 남지 않는다


def test_requests_of_different_elders_are_independent(store):
    store.open(12, 1000.0)
    store.open(13, 1500.0)
    store.approve(12, 1)

    assert store.get(13).approved_by == frozenset()
    store.reject(13, 2000.0)
    assert not store.get(12).rejected


def test_removing_for_an_elder_clears_only_that_elders_request(store):
    store.open(12, 1000.0)
    store.open(13, 1000.0)

    assert store.remove_for_elder(12) == 1
    assert store.remove_for_elder(12) == 0

    assert store.get(12) is None and store.get(13) is not None
