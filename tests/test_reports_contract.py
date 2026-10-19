"""Reports 규약 — 구현마다 같은 테스트를 돌린다."""

from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path

import pytest

from app.analysis.baseline import BASELINE_MIN_CALLS, BASELINE_WINDOW
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

    def add_call(
        *, call_id, elder_id, status, created_at, trigger_type="scheduled", score=None, duration_ms=None,
        degraded=False,
    ):
        insert_call(
            pool, call_id=call_id, elder_id=elder_id, status=status, created_at=created_at,
            trigger_type=trigger_type, score=score,
            level=None if score is None else "normal", duration_ms=duration_ms, degraded=degraded,
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


# ------------------------------------------------ 평소 기준에 쓸 수 있는 통화 수


def test_baseline_calls_is_zero_without_calls(world):
    assert world.reports.baseline_calls(12) == 0


def test_baseline_calls_counts_completed_calls_with_usable_metrics(world):
    world.add_call(call_id=1, elder_id=12, status="completed", created_at=kst(2026, 10, 1, 9), score=10)
    world.add_call(call_id=2, elder_id=12, status="completed", created_at=kst(2026, 10, 2, 9), degraded=True)
    world.add_call(call_id=3, elder_id=12, status="completed", created_at=kst(2026, 10, 3, 9))  # 지표 없음
    world.add_call(call_id=4, elder_id=12, status="no_answer", created_at=kst(2026, 10, 4, 9))
    world.add_call(call_id=5, elder_id=13, status="completed", created_at=kst(2026, 10, 5, 9), score=10)
    world.add_call(call_id=6, elder_id=12, status="completed", created_at=kst(2026, 10, 6, 9), score=20)

    assert world.reports.baseline_calls(12) == 2  # 1번과 6번만. degraded·지표 없음·안 받음·남의 통화는 빠진다


def test_baseline_calls_looks_at_most_at_the_latest_window(world):
    for n in range(1, BASELINE_WINDOW + 6):
        world.add_call(call_id=n, elder_id=12, status="completed", created_at=kst(2026, 9, n, 9), score=10)

    assert world.reports.baseline_calls(12) == BASELINE_WINDOW == 14


def test_baseline_calls_cuts_the_window_before_dropping_degraded(world):
    """기준선과 같은 순서다: 창을 먼저 자르고 degraded를 뺀다. 거꾸로 하면 오래전 통화가 '평소'가 된다."""
    for n in range(1, 6):
        world.add_call(call_id=n, elder_id=12, status="completed", created_at=kst(2026, 9, n, 9), score=10)
    for n in range(6, 6 + BASELINE_WINDOW):
        world.add_call(call_id=n, elder_id=12, status="completed", created_at=kst(2026, 9, n, 9), degraded=True)

    assert world.reports.baseline_calls(12) == 0


def test_unanswered_calls_do_not_take_a_window_slot(world):
    for n in range(1, BASELINE_WINDOW + 1):
        world.add_call(call_id=n, elder_id=12, status="completed", created_at=kst(2026, 9, n, 9), score=10)
    for n in range(20, 25):
        world.add_call(call_id=n, elder_id=12, status="no_answer", created_at=kst(2026, 9, n, 9))

    assert world.reports.baseline_calls(12) == BASELINE_WINDOW


def test_the_app_hint_uses_the_same_baseline_numbers():
    """앱의 '평소 기준 쌓는 중' 안내는 3통·14통을 직접 쓴다. 서버 상수만 바꾸면 안내가 조용히 틀린다."""
    screen = (
        Path(__file__).resolve().parent.parent / "client" / "lib" / "screens" / "elderly_detail_screen.dart"
    ).read_text(encoding="utf-8")

    assert re.search(rf"const int baselineMinCalls = {BASELINE_MIN_CALLS};", screen)
    assert re.search(rf"const int baselineWindow = {BASELINE_WINDOW};", screen)


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


def test_removing_an_elders_calls_leaves_other_elders(world):
    world.add_call(call_id=1, elder_id=12, status="completed", created_at=kst(2026, 10, 5, 9), score=10)
    world.add_call(call_id=2, elder_id=12, status="no_answer", created_at=kst(2026, 10, 6, 9))
    world.add_call(call_id=3, elder_id=13, status="completed", created_at=kst(2026, 10, 5, 9), score=50)

    assert world.reports.remove_for_elder(12) == 2

    assert world.reports.call_lines(12, 10) == []
    assert all(d.calls == 0 for d in world.reports.weekly(12, SUNDAY))
    assert world.reports.baseline_calls(12) == 0
    assert [l.call_id for l in world.reports.call_lines(13, 10)] == [3]
    assert world.reports.remove_for_elder(12) == 0


# ------------------------------------------------ 상태와 대기 번호


def test_summaries_carry_a_status_and_no_phone_for_non_pending_elders(world):
    summaries = world.reports.elder_summaries(1, SUNDAY)

    assert summaries and all(s.status in ("active", "unconsented") for s in summaries)
    assert all(s.phone is None for s in summaries)


@pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL이 없다")
def test_postgres_summaries_show_a_pending_elders_phone_and_hide_others():
    world = _postgres()
    pool = world.reports._pool
    with pool.connection() as conn:
        conn.execute(
            "INSERT INTO elders (elder_id, guardian_id, name, phone_number, agreed_at) "
            "VALUES (20, 1, '대기 어르신', '010-9999-1111', now())"
        )

    by_id = {s.elder_id: s for s in world.reports.elder_summaries(1, SUNDAY)}

    assert by_id[20].status == "pending" and by_id[20].phone == "010-9999-1111"
    assert by_id[12].status == "active" and by_id[12].phone is None  # 시드는 동의가 있다


def test_in_memory_summaries_show_a_pending_elders_phone():
    directory = InMemoryElderDirectory(
        {12: ElderAccess(1, True, "어르신 12")}, phones={12: "070-0000-0012"}
    )
    pending = directory.create_pending(
        guardian_id=1, name="대기 어르신", phone="010-9999-1111", max_pending=5
    )
    reports = InMemoryReports(directory, InMemoryAlertStore())

    by_id = {s.elder_id: s for s in reports.elder_summaries(1, SUNDAY)}

    assert by_id[pending].status == "pending" and by_id[pending].phone == "010-9999-1111"
    assert by_id[12].status == "active" and by_id[12].phone is None
