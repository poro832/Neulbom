"""CallContentStore 규약 — 두 구현에 같은 테스트를 돌린다.

갈라지면 개발할 땐 30일 뒤 지워지는데 서버에선 안 지워지는 식으로 약속이 조용히 깨진다
(tests/test_call_store_contract.py의 모듈 설명과 같은 이유).
DATABASE_URL이 없으면 Postgres 쪽은 건너뛴다.
"""

from __future__ import annotations

import os

import pytest

from app.api.call_content import InMemoryCallContent

DATABASE_URL = os.getenv("DATABASE_URL")
DAY = 86400.0
START = 1_800_000_000.0
CALL = 1


class Clock:
    def __init__(self):
        self.now = START

    def __call__(self):
        return self.now


@pytest.fixture(
    params=[
        "memory",
        pytest.param(
            "postgres",
            marks=pytest.mark.skipif(
                not DATABASE_URL,
                reason="DATABASE_URL이 없다 — Postgres 규약 테스트를 건너뛴다.",
            ),
        ),
    ]
)
def setup(request):
    clock = Clock()
    if request.param == "memory":
        store = InMemoryCallContent(clock=clock)
        store.set_owner(CALL, 12)
        yield store, clock
        return

    from app.api.postgres_call_content import PostgresCallContent
    from tests.pg_helpers import insert_call, pg_pool, seed_world

    pool = pg_pool()
    seed_world(pool)
    insert_call(pool, call_id=CALL, elder_id=12, status="completed", created_at=START)
    yield PostgresCallContent(pool=pool, clock=clock), clock
    pool.close()


def test_turns_round_trip_in_order(setup):
    store, _ = setup
    store.save_turns(CALL, [("ai", "안녕하세요"), ("elder", "네 안녕하세요")])
    assert [(t.speaker, t.text) for t in store.turns(CALL)] == [
        ("ai", "안녕하세요"),
        ("elder", "네 안녕하세요"),
    ]


def test_save_turns_twice_replaces(setup):
    store, _ = setup
    store.save_turns(CALL, [("ai", "a")])
    store.save_turns(CALL, [("ai", "b"), ("elder", "c")])
    assert [t.text for t in store.turns(CALL)] == ["b", "c"]


def test_unknown_call_has_no_turns(setup):
    store, _ = setup
    assert store.turns(999) == []
    assert store.calls_with_turns([CALL, 999]) == set()


def test_calls_with_turns_finds_saved_ones(setup):
    store, _ = setup
    store.save_turns(CALL, [("ai", "a")])
    assert store.calls_with_turns([CALL, 999]) == {CALL}


def test_summary_round_trip(setup):
    store, _ = setup
    store.save_summary(CALL, "점심을 드셨어요.", "HCX-DASH-002")
    assert store.summaries([CALL, 999]) == {CALL: "점심을 드셨어요."}
    assert store.summaries([]) == {}


def test_elder_of_call(setup):
    store, _ = setup
    assert store.elder_of_call(CALL) == 12
    assert store.elder_of_call(999) is None


def test_share_consent_defaults_false_and_sticks(setup):
    store, _ = setup
    assert store.share_agreed(12) is False
    store.agree_share(12)
    store.agree_share(12)  # 두 번 해도 같다
    assert store.share_agreed(12) is True
    assert store.share_agreed(13) is False


def test_views_are_counted(setup):
    store, _ = setup
    store.record_view(CALL, 1)
    store.record_view(CALL, 1)
    assert store.view_count(CALL) == 2


def test_purge_removes_old_turns_and_summaries_only(setup):
    store, clock = setup
    store.save_turns(CALL, [("ai", "a"), ("elder", "b")])
    store.save_summary(CALL, "요약", "m")
    clock.now += 31 * DAY
    assert store.purge_older_than(clock.now - 30 * DAY) == 3
    assert store.turns(CALL) == []
    assert store.summaries([CALL]) == {}
    store.record_view(CALL, 1)  # 열람 기록은 남는 기록이라 지우지 않는다
    assert store.view_count(CALL) == 1


def test_purge_keeps_recent_rows(setup):
    store, clock = setup
    store.save_turns(CALL, [("ai", "a")])
    clock.now += 10 * DAY
    assert store.purge_older_than(clock.now - 30 * DAY) == 0
    assert len(store.turns(CALL)) == 1
