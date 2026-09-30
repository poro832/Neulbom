"""TranscriptStore 규약 — 두 구현에 같은 테스트를 돌린다.

같은 이유로 존재한다: tests/test_call_store_contract.py의 모듈 설명을 보라.
여기가 갈라지면 개발할 땐 30일 뒤 지워지는데 서버에선 안 지워지는 식으로
**약속만 조용히 깨진다.**

DATABASE_URL이 없으면 Postgres 쪽은 건너뛴다. 건너뛴 테스트는 아무것도 지키지 못한다.
"""

from __future__ import annotations

import os

import pytest

from app.api.transcript_store import InMemoryTranscriptStore

DATABASE_URL = os.getenv("DATABASE_URL")
DAY = 86400.0
START = 1_800_000_000.0


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
        yield InMemoryTranscriptStore(clock=clock), clock
        return

    from app.api.db import connect
    from app.api.postgres_outcome_store import PostgresOutcomeStore
    from app.api.postgres_transcript_store import PostgresTranscriptStore

    pool = connect(DATABASE_URL)
    # 전사는 통화에 매달린다(FK). 통화 껍데기 1~40번을 만들어 둔다.
    PostgresOutcomeStore(pool=pool).reset_for_tests()
    store = PostgresTranscriptStore(pool=pool, clock=clock)
    store.reset_for_tests()
    yield store, clock
    pool.close()


def test_a_saved_transcript_comes_back(setup):
    store, _ = setup

    store.save(10, "요즘 무릎이 좀 아파요")

    assert store.get(10) == "요즘 무릎이 좀 아파요"


def test_an_unknown_call_has_no_transcript(setup):
    store, _ = setup

    assert store.get(10) is None


def test_an_empty_transcript_is_kept_and_is_not_missing(setup):
    """'말을 안 했다'와 '전사를 안 했다'는 다르다. 앞쪽이 가장 위험한 통화다."""
    store, _ = setup

    store.save(10, "")

    assert store.get(10) == ""


def test_saving_again_replaces_the_text(setup):
    store, _ = setup

    store.save(10, "처음")
    store.save(10, "다시")

    assert store.get(10) == "다시"


def test_saving_again_does_not_extend_the_thirty_days(setup):
    """재분석 한 번으로 보관 기간이 연장되면 안 된다."""
    store, clock = setup

    store.save(10, "처음")
    clock.now = START + 29 * DAY
    store.save(10, "다시")

    removed = store.purge_older_than(START + 1)

    assert removed == 1
    assert store.get(10) is None


def test_purge_removes_only_what_is_old_enough(setup):
    store, clock = setup

    store.save(10, "오래된 통화")
    clock.now = START + 31 * DAY
    store.save(20, "최근 통화")

    removed = store.purge_older_than(clock.now - 30 * DAY)

    assert removed == 1
    assert store.get(10) is None
    assert store.get(20) == "최근 통화"


def test_purging_nothing_is_not_an_error(setup):
    store, _ = setup

    assert store.purge_older_than(START) == 0
