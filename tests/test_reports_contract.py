"""Reports 규약 — 구현마다 같은 테스트를 돌린다."""

from __future__ import annotations

from datetime import date, datetime

import pytest

from app.api.alerts import InMemoryAlertStore
from app.api.elder_directory import ElderAccess, InMemoryElderDirectory
from app.api.reports import InMemoryReports, kst_week_start, sunday_on_or_before
from app.scheduler import KST
from tests.pg_helpers import DATABASE_URL

SUNDAY = date(2026, 10, 4)  # 2026-10-04는 일요일이다


def kst(*args) -> float:
    return datetime(*args, tzinfo=KST).timestamp()


class World:
    """두 구현에 같은 통화를 심는 도우미."""

    def __init__(self, reports, add_call, add_alert):
        self.reports = reports
        self.add_call = add_call
        self.add_alert = add_alert


def _memory():
    directory = InMemoryElderDirectory(
        {
            12: ElderAccess(1, True, "어르신 12"),
            13: ElderAccess(1, True, "어르신 13"),
            14: ElderAccess(2, True, "어르신 14"),
        }
    )
    alerts = InMemoryAlertStore(clock=lambda: kst(2026, 10, 7, 12))
    reports = InMemoryReports(directory, alerts)

    def add_call(**kw):
        kw.setdefault("trigger_type", "scheduled")
        reports.add_call(**kw)

    def add_alert(elder_id, guardian_id):
        alerts.raise_alert(
            elder_id=elder_id, guardian_id=guardian_id, call_id=None,
            alert_type="risk_rise", severity="warning", message="m",
        )

    return World(reports, add_call, add_alert)


def _postgres():
    from app.api.postgres_alerts import PostgresAlertStore
    from app.api.postgres_reports import PostgresReports
    from tests.pg_helpers import insert_call, pg_pool, seed_world

    pool = pg_pool()
    seed_world(pool)
    alerts = PostgresAlertStore(pool=pool, clock=lambda: kst(2026, 10, 7, 12))

    def add_call(*, call_id, elder_id, status, created_at, trigger_type="scheduled", score=None, duration_ms=None):
        insert_call(
            pool, call_id=call_id, elder_id=elder_id, status=status, created_at=created_at,
            trigger_type=trigger_type, score=score,
            level=None if score is None else "normal", duration_ms=duration_ms,
        )

    def add_alert(elder_id, guardian_id):
        alerts.raise_alert(
            elder_id=elder_id, guardian_id=guardian_id, call_id=None,
            alert_type="risk_rise", severity="warning", message="m",
        )

    return World(PostgresReports(pool=pool), add_call, add_alert)


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
    return _memory() if request.param == "memory" else _postgres()


# ------------------------------------------------ 한국시간 주 경계


def test_the_week_starts_on_sunday_in_korea_time():
    assert kst_week_start(kst(2026, 10, 4, 0, 0, 0)) == SUNDAY      # 일요일 0시
    assert kst_week_start(kst(2026, 10, 10, 23, 59, 59)) == SUNDAY  # 토요일 밤
    assert kst_week_start(kst(2026, 10, 11, 0, 0, 0)) == date(2026, 10, 11)
    assert kst_week_start(kst(2026, 10, 7, 12)) == SUNDAY


def test_a_utc_clock_would_get_sunday_morning_wrong():
    """일요일 오전 8시(한국)는 UTC로는 토요일 23시다. UTC로 주를 세면 전주로 샌다."""
    assert kst_week_start(kst(2026, 10, 4, 8, 0, 0)) == SUNDAY


def test_sunday_on_or_before_snaps_any_day_to_its_week():
    assert sunday_on_or_before(date(2026, 10, 7)) == SUNDAY
    assert sunday_on_or_before(SUNDAY) == SUNDAY
    assert sunday_on_or_before(date(2026, 10, 10)) == SUNDAY


# ------------------------------------------------ 주간


def test_weekly_always_returns_seven_days_sunday_to_saturday(world):
    days = world.reports.weekly(12, SUNDAY)

    assert [d.date for d in days] == [f"2026-10-{n:02d}" for n in range(4, 11)]
    assert all(d.calls == 0 and d.avg_score is None for d in days)


def test_weekly_counts_completed_calls_and_averages_their_scores(world):
    world.add_call(call_id=1, elder_id=12, status="completed", created_at=kst(2026, 10, 5, 9), score=10)
    world.add_call(call_id=2, elder_id=12, status="completed", created_at=kst(2026, 10, 5, 15), score=20)
    world.add_call(call_id=3, elder_id=12, status="no_answer", created_at=kst(2026, 10, 6, 9))
    world.add_call(call_id=4, elder_id=12, status="completed", created_at=kst(2026, 10, 7, 9))  # 점수 없음

    days = {d.date: d for d in world.reports.weekly(12, SUNDAY)}

    assert (days["2026-10-05"].calls, days["2026-10-05"].avg_score) == (2, 15.0)
    assert (days["2026-10-06"].calls, days["2026-10-06"].avg_score) == (0, None)  # 안 받음은 통화가 아니다
    assert (days["2026-10-07"].calls, days["2026-10-07"].avg_score) == (1, None)


def test_a_saturday_night_call_and_a_sunday_dawn_call_fall_in_different_weeks(world):
    world.add_call(call_id=1, elder_id=12, status="completed", created_at=kst(2026, 10, 3, 23, 59, 59), score=40)
    world.add_call(call_id=2, elder_id=12, status="completed", created_at=kst(2026, 10, 4, 0, 0, 1), score=8)

    this_week = {d.date: d for d in world.reports.weekly(12, SUNDAY)}
    last_week = {d.date: d for d in world.reports.weekly(12, date(2026, 9, 27))}

    assert this_week["2026-10-04"].calls == 1 and this_week["2026-10-04"].avg_score == 8.0
    assert last_week["2026-10-03"].calls == 1 and last_week["2026-10-03"].avg_score == 40.0


def test_weekly_ignores_other_elders(world):
    world.add_call(call_id=1, elder_id=13, status="completed", created_at=kst(2026, 10, 5, 9), score=50)

    assert all(d.calls == 0 for d in world.reports.weekly(12, SUNDAY))


# ------------------------------------------------ 어르신 요약


def test_summaries_list_only_that_guardians_elders_with_week_numbers(world):
    world.add_call(call_id=1, elder_id=12, status="completed", created_at=kst(2026, 10, 5, 9), score=10)
    world.add_call(call_id=2, elder_id=12, status="completed", created_at=kst(2026, 10, 6, 9), score=30)
    world.add_call(call_id=3, elder_id=12, status="no_answer", created_at=kst(2026, 10, 7, 9))
    world.add_alert(12, 1)

    by_id = {s.elder_id: s for s in world.reports.elder_summaries(1, SUNDAY)}

    assert sorted(by_id) == [12, 13]
    twelve = by_id[12]
    assert twelve.name == "어르신 12"
    assert twelve.week_calls == 2 and twelve.week_avg_score == 20.0
    assert twelve.last_status == "no_answer"
    assert twelve.last_call_at == pytest.approx(kst(2026, 10, 7, 9))
    assert twelve.week_alerts == 1
    thirteen = by_id[13]
    assert (thirteen.last_call_at, thirteen.last_status, thirteen.week_calls, thirteen.week_avg_score, thirteen.week_alerts) == (
        None, None, 0, None, 0,
    )


def test_summaries_of_a_guardian_with_no_elders_is_empty(world):
    assert world.reports.elder_summaries(99999, SUNDAY) == []


# ------------------------------------------------ 어르신 통화 줄


def test_call_lines_show_finished_calls_newest_first_with_duration(world):
    world.add_call(call_id=1, elder_id=12, status="completed", created_at=kst(2026, 10, 5, 9), score=5, duration_ms=52_400)
    world.add_call(call_id=2, elder_id=12, status="no_answer", created_at=kst(2026, 10, 6, 9))
    world.add_call(call_id=3, elder_id=12, status="failed", created_at=kst(2026, 10, 7, 9))

    lines = world.reports.call_lines(12, 10)

    assert [(l.call_id, l.status) for l in lines] == [(3, "failed"), (2, "no_answer"), (1, "completed")]
    assert lines[2].duration_s == 52
    assert lines[1].duration_s is None
    assert lines[2].started_at == pytest.approx(kst(2026, 10, 5, 9))


def test_call_lines_respect_the_limit_and_the_elder(world):
    for n in range(1, 6):
        world.add_call(call_id=n, elder_id=12, status="completed", created_at=kst(2026, 10, 5, n))
    world.add_call(call_id=9, elder_id=13, status="completed", created_at=kst(2026, 10, 5, 9))

    lines = world.reports.call_lines(12, 3)

    assert [l.call_id for l in lines] == [5, 4, 3]
