"""AlertStore 규약 — 구현마다 같은 테스트를 돌린다."""

from __future__ import annotations

import pytest

from app.api.alerts import InMemoryAlertStore
from tests.pg_helpers import DATABASE_URL


class Clock:
    def __init__(self):
        self.now = 1_800_000_000.0

    def __call__(self):
        return self.now


def _memory(clock):
    return InMemoryAlertStore(clock=clock), None


def _postgres(clock):
    from app.api.postgres_alerts import PostgresAlertStore
    from tests.pg_helpers import insert_call, pg_pool, seed_world

    pool = pg_pool()
    seed_world(pool)
    insert_call(pool, call_id=1, elder_id=12, status="completed", created_at=clock.now)
    insert_call(pool, call_id=2, elder_id=12, status="completed", created_at=clock.now)
    return PostgresAlertStore(pool=pool, clock=clock), pool


@pytest.fixture(
    params=[
        "memory",
        pytest.param(
            "postgres",
            marks=pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL이 없다"),
        ),
    ]
)
def make(request):
    return _memory if request.param == "memory" else _postgres


def raise_one(store, *, elder_id=12, guardian_id=1, call_id=None, alert_type="risk_rise", severity="warning"):
    return store.raise_alert(
        elder_id=elder_id,
        guardian_id=guardian_id,
        call_id=call_id,
        alert_type=alert_type,
        severity=severity,
        message="문구",
    )


def test_a_raised_alert_is_listed_for_its_guardian_newest_first(make):
    clock = Clock()
    store, _ = make(clock)
    raise_one(store, alert_type="no_answer", severity="info")
    clock.now += 60
    raise_one(store, alert_type="risk_rise", severity="critical")

    listed = store.recent_for_guardian(1, 10)

    assert [a.alert_type for a in listed] == ["risk_rise", "no_answer"]
    assert listed[0].severity == "critical" and listed[0].message == "문구"
    assert listed[0].created_at == pytest.approx(clock.now)


def test_another_guardian_does_not_see_it(make):
    store, _ = make(Clock())
    raise_one(store)

    assert store.recent_for_guardian(2, 10) == []


def test_the_limit_caps_the_list(make):
    store, _ = make(Clock())
    for _ in range(5):
        raise_one(store)

    assert len(store.recent_for_guardian(1, 3)) == 3


def test_the_same_call_gets_one_alert_per_type(make):
    store, _ = make(Clock())

    first = raise_one(store, call_id=1, alert_type="risk_rise")
    again = raise_one(store, call_id=1, alert_type="risk_rise")
    other_type = raise_one(store, call_id=1, alert_type="no_answer", severity="info")
    other_call = raise_one(store, call_id=2, alert_type="risk_rise")

    assert (first, again, other_type, other_call) == (True, False, True, True)
    assert len(store.recent_for_guardian(1, 10)) == 3


def test_alerts_without_a_call_are_never_deduplicated(make):
    store, _ = make(Clock())

    assert raise_one(store) is True
    assert raise_one(store) is True


def test_count_since_counts_only_that_elders_recent_alerts(make):
    clock = Clock()
    store, _ = make(clock)
    raise_one(store, elder_id=12)
    clock.now += 100
    raise_one(store, elder_id=12)
    raise_one(store, elder_id=13)

    assert store.count_since(12, clock.now - 50) == 1
    assert store.count_since(12, clock.now - 500) == 2
    assert store.count_since(13, clock.now - 500) == 1
