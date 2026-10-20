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
    assert opened.request_id >= 1
    assert store.get(12) == opened


def test_each_guardian_approves_once(store):
    rid = store.open(12, 1000.0).request_id

    first = store.approve(12, 1, rid)
    again = store.approve(12, 1, rid)
    both = store.approve(12, 2, rid)

    assert first.approved_by == frozenset({1})
    assert again.approved_by == frozenset({1})
    assert both.approved_by == frozenset({1, 2})
    assert store.get(12).approved_by == frozenset({1, 2})


def test_approving_without_a_request_does_nothing(store):
    assert store.approve(12, 1, 1) is None
    assert store.get(12) is None


def test_a_rejected_request_takes_no_more_approvals_and_shows_as_rejected(store):
    rid = store.open(12, 1000.0).request_id
    store.approve(12, 1, rid)

    assert store.reject(12, 2000.0, rid) is True

    request = store.get(12)
    assert request.rejected and request.rejected_at == 2000.0
    assert request.approved_by == frozenset({1})
    assert store.approve(12, 2, rid) is None
    assert store.get(12).approved_by == frozenset({1})
    assert store.reject(12, 3000.0, rid) is False  # 이미 거절됐다


def test_rejecting_without_a_request_changes_nothing(store):
    assert store.reject(12, 1000.0, 1) is False


def test_a_new_request_replaces_a_rejected_one_and_clears_approvals(store):
    rid = store.open(12, 1000.0).request_id
    store.approve(12, 1, rid)
    store.reject(12, 2000.0, rid)

    fresh = store.open(12, 3000.0)

    assert fresh.requested_at == 3000.0 and not fresh.rejected and fresh.approved_by == frozenset()
    assert fresh.request_id != rid
    assert store.get(12) == fresh


def test_cancelling_removes_the_request(store):
    rid = store.open(12, 1000.0).request_id
    store.approve(12, 1, rid)

    assert store.cancel(12) is True

    assert store.get(12) is None
    assert store.cancel(12) is False
    assert store.open(12, 5000.0).approved_by == frozenset()  # 옛 승인이 남지 않는다


def test_an_approval_for_a_cancelled_request_never_lands_on_the_new_one(store):
    """보호자가 옛 카드를 보고 있는 사이 어르신이 취소하고 다시 요청했다 — 그 승인은 새 요청에 붙지 않는다."""
    old = store.open(12, 1000.0).request_id
    store.cancel(12)
    new = store.open(12, 2000.0)

    assert store.approve(12, 1, old) is None
    assert store.get(12).approved_by == frozenset()
    assert store.get(12).request_id == new.request_id
    assert store.approve(12, 1, new.request_id).approved_by == frozenset({1})


def test_a_rejection_for_a_cancelled_request_never_lands_on_the_new_one(store):
    old = store.open(12, 1000.0).request_id
    store.cancel(12)
    new = store.open(12, 2000.0)

    assert store.reject(12, 3000.0, old) is False
    assert not store.get(12).rejected
    assert store.reject(12, 3000.0, new.request_id) is True


def test_requests_of_different_elders_are_independent(store):
    a = store.open(12, 1000.0).request_id
    b = store.open(13, 1500.0).request_id
    store.approve(12, 1, a)

    assert store.get(13).approved_by == frozenset()
    store.reject(13, 2000.0, b)
    assert not store.get(12).rejected
    assert store.approve(13, 1, a) is None  # 다른 어르신 요청의 번호로는 닿지 않는다


def test_removing_for_an_elder_clears_only_that_elders_request(store):
    store.open(12, 1000.0)
    store.open(13, 1000.0)

    assert store.remove_for_elder(12) == 1
    assert store.remove_for_elder(12) == 0

    assert store.get(12) is None and store.get(13) is not None


# ------------------------------------------------ 마지막 승인이 요청을 잠근다


def test_locking_a_live_request_works_and_is_idempotent(store):
    request = store.open(12, 1000.0)

    assert store.lock(12, request.request_id, 1500.0) is True
    assert store.lock(12, request.request_id, 1600.0) is True  # 이미 잠겼다
    locked = store.get(12)
    assert locked.locked and locked.locked_at == 1500.0  # 처음 잠근 시각이 남는다


def test_locking_needs_the_same_request_number(store):
    old = store.open(12, 1000.0).request_id
    store.cancel(12)
    new = store.open(12, 2000.0)

    assert store.lock(12, old, 3000.0) is False  # 옛 승인으로는 새 요청을 잠글 수 없다
    assert not store.get(12).locked
    assert store.lock(12, new.request_id, 3000.0) is True


def test_a_missing_or_rejected_request_cannot_be_locked(store):
    assert store.lock(12, 1, 1000.0) is False
    rid = store.open(12, 1000.0).request_id
    store.reject(12, 1500.0, rid)

    assert store.lock(12, rid, 2000.0) is False


def test_a_locked_request_cannot_be_cancelled_rejected_or_replaced(store):
    request = store.open(12, 1000.0)
    store.approve(12, 1, request.request_id)
    store.lock(12, request.request_id, 1500.0)

    assert store.cancel(12) is False
    assert store.reject(12, 2000.0, request.request_id) is False
    assert store.open(12, 3000.0) == store.get(12)  # 새 요청이 아니라 잠긴 그 요청을 돌려준다
    still = store.get(12)
    assert still.request_id == request.request_id and still.locked and not still.rejected
    assert still.approved_by == frozenset({1})


def test_removing_for_the_elder_clears_even_a_locked_request(store):
    rid = store.open(12, 1000.0).request_id
    store.lock(12, rid, 1500.0)

    assert store.remove_for_elder(12) == 1

    assert store.get(12) is None


def test_two_threads_locking_the_same_request_both_succeed_once_locked(store):
    import threading

    rid = store.open(12, 1000.0).request_id
    results: list[bool] = []
    barrier = threading.Barrier(2)

    def worker():
        barrier.wait()
        results.append(store.lock(12, rid, 1500.0))

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert results == [True, True]
    assert store.get(12).locked
