"""CallContentStore 규약 — 두 구현에 같은 테스트를 돌린다.

갈라지면 개발할 땐 30일 뒤 지워지는데 서버에선 안 지워지는 식으로 약속이 조용히 깨진다
(tests/test_call_store_contract.py의 모듈 설명과 같은 이유).
DATABASE_URL이 없으면 Postgres 쪽은 건너뛴다.
"""

from __future__ import annotations

import os

import pytest

from app.api.call_content import InMemoryCallContent, Mention

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


def test_medication_round_trip_and_overwrite(setup):
    store, _ = setup
    assert store.medication([CALL, 999]) == {}
    store.save_medication(CALL, "unknown", "HCX-DASH-002")
    store.save_medication(CALL, "taken", "HCX-DASH-002")
    assert store.medication([CALL, 999]) == {CALL: "taken"}
    assert store.medication([]) == {}


def test_medication_rejects_unknown_status(setup):
    store, _ = setup
    with pytest.raises(ValueError):
        store.save_medication(CALL, "diagnosed", "m")
    assert store.medication([CALL]) == {}


def test_purge_removes_old_medication_and_keeps_recent(setup):
    store, clock = setup
    store.save_medication(CALL, "not_taken", "m")
    clock.now += 10 * DAY
    assert store.purge_older_than(clock.now - 30 * DAY) == 0
    assert store.medication([CALL]) == {CALL: "not_taken"}
    clock.now += 21 * DAY
    assert store.purge_older_than(clock.now - 30 * DAY) == 1
    assert store.medication([CALL]) == {}


@pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL이 없다 — Postgres 규약 테스트를 건너뛴다.")
@pytest.mark.parametrize("missing", ["call_medication", "call_mentions"])
def test_purge_still_deletes_turns_and_summaries_when_a_side_table_is_missing(missing):
    """배포 순서가 어긋나 call_medication·call_mentions 표가 없어도 30일 보관 약속은 지켜진다.

    스키마는 건드리지 않는다. 풀 대리자가 SQL 속 표 이름만 없는 이름으로 바꿔 보낸다.
    """
    from contextlib import contextmanager

    from app.api.postgres_call_content import PostgresCallContent
    from tests.pg_helpers import insert_call, pg_pool, seed_world

    class RenamingConn:
        def __init__(self, real):
            self._real = real

        def execute(self, sql, *args, **kwargs):
            return self._real.execute(
                sql.replace(missing, missing + "_absent"), *args, **kwargs
            )

    class RenamingPool:
        def __init__(self, real):
            self._real = real

        @contextmanager
        def connection(self, *args, **kwargs):
            with self._real.connection(*args, **kwargs) as conn:
                yield RenamingConn(conn)

    pool = pg_pool()
    try:
        seed_world(pool)
        insert_call(pool, call_id=CALL, elder_id=12, status="completed", created_at=START)
        clock = Clock()
        real = PostgresCallContent(pool=pool, clock=clock)
        real.save_turns(CALL, [("ai", "a"), ("elder", "b")])
        real.save_summary(CALL, "s", "m")
        clock.now += 31 * DAY

        broken = PostgresCallContent(pool=RenamingPool(pool), clock=clock)
        assert broken.purge_older_than(clock.now - 30 * DAY) == 3
        assert real.turns(CALL) == [] and real.summaries([CALL]) == {}
    finally:
        pool.close()


M_BODY = Mention("body", "bad", "허리가 아파요")
M_SLEEP = Mention("sleep", "bad", "잠을 못 잤어")
M_MEAL = Mention("meal", "good", "밥 맛있게 먹었어")


def test_mentions_round_trip_in_order_and_overwrite(setup):
    store, _ = setup
    store.save_mentions(CALL, [M_BODY, M_SLEEP], "m1")
    assert store.mentions([CALL]) == {CALL: [M_BODY, M_SLEEP]}

    store.save_mentions(CALL, [M_MEAL], "m2")  # 통째로 바뀐다
    assert store.mentions([CALL]) == {CALL: [M_MEAL]}

    store.save_mentions(CALL, [], "m2")  # 빈 목록은 지운다
    assert store.mentions([CALL]) == {}


def test_mentions_for_unknown_calls_and_no_ids(setup):
    store, _ = setup
    assert store.mentions([]) == {}
    assert store.mentions([999]) == {}


def test_mentions_reject_values_outside_the_rules_and_change_nothing(setup):
    store, _ = setup
    store.save_mentions(CALL, [M_BODY], "m1")
    for bad in (
        Mention("heart", "bad", "x"),
        Mention("body", "awful", "x"),
        Mention("body", "bad", ""),
        Mention("body", "bad", "가" * 81),
    ):
        with pytest.raises(ValueError):
            store.save_mentions(CALL, [M_SLEEP, bad], "m2")
    assert store.mentions([CALL]) == {CALL: [M_BODY]}


def own_call(store, call_id, elder_id):
    """그 어르신의 통화를 하나 더 만든다. 메모리는 주인만 적고, Postgres는 통화 행을 넣는다."""
    if isinstance(store, InMemoryCallContent):
        store.set_owner(call_id, elder_id)
        return
    from tests.pg_helpers import insert_call

    insert_call(store._pool, call_id=call_id, elder_id=elder_id, status="completed", created_at=START)


def test_removing_an_elders_content_leaves_other_elders(setup):
    store, _ = setup
    other = 2
    own_call(store, other, 13)
    for call_id in (CALL, other):
        store.save_turns(call_id, [("ai", "a"), ("elder", "b")])
        store.save_summary(call_id, "요약", "m")
        store.save_medication(call_id, "taken", "m")
        store.save_mentions(call_id, [M_BODY], "m")
        store.record_view(call_id, 1)
    store.agree_share(12)
    store.agree_share(13)

    # 대화 2줄 + 요약 + 복용 확인 + 언급 1개 + 열람 1번
    assert store.remove_for_elder(12) == 6

    assert store.turns(CALL) == [] and store.calls_with_turns([CALL]) == set()
    assert store.summaries([CALL]) == {} and store.medication([CALL]) == {} and store.mentions([CALL]) == {}
    assert store.view_count(CALL) == 0
    assert store.share_agreed(12) is False
    assert len(store.turns(other)) == 2 and store.summaries([other]) == {other: "요약"}
    assert store.medication([other]) == {other: "taken"} and store.mentions([other]) == {other: [M_BODY]}
    assert store.view_count(other) == 1 and store.share_agreed(13) is True
    assert store.remove_for_elder(12) == 0


def test_purge_removes_old_mentions_and_keeps_recent(setup):
    store, clock = setup
    store.save_mentions(CALL, [M_BODY, M_SLEEP], "m")
    clock.now += 10 * DAY
    assert store.purge_older_than(clock.now - 30 * DAY) == 0
    assert store.mentions([CALL]) != {}
    clock.now += 21 * DAY
    assert store.purge_older_than(clock.now - 30 * DAY) == 2
    assert store.mentions([CALL]) == {}
