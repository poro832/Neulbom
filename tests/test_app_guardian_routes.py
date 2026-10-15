"""보호자 조회 주소 — 어르신 목록, 주간 통계, 최근 알림."""

from __future__ import annotations

import pytest

from tests.app_data_helpers import kst, make_app_kit


def seed(kit):
    kit.reports.add_call(call_id=1, elder_id=12, status="completed", created_at=kst(2026, 10, 5, 9), score=10)
    kit.reports.add_call(call_id=2, elder_id=12, status="completed", created_at=kst(2026, 10, 6, 9), score=30)
    kit.reports.add_call(call_id=3, elder_id=12, status="no_answer", created_at=kst(2026, 10, 7, 9))
    kit.reports.add_call(call_id=4, elder_id=14, status="completed", created_at=kst(2026, 10, 5, 9), score=99)


# ------------------------------------------------ 어르신 목록


def test_the_elder_list_shows_only_my_elders_with_week_numbers():
    kit = make_app_kit()
    seed(kit)
    kit.alerts.raise_alert(
        elder_id=12, guardian_id=1, call_id=None, alert_type="risk_rise", severity="warning", message="m"
    )

    response = kit.client.get("/v1/guardian/elders", headers=kit.guardian_headers)

    assert response.status_code == 200
    body = response.json()
    assert body["week_start"] == "2026-10-04"
    assert [e["elder_id"] for e in body["elders"]] == [12, 13]
    twelve = body["elders"][0]
    assert twelve["name"] == "어르신 12"
    assert twelve["week_calls"] == 2 and twelve["week_avg_score"] == 20.0
    assert twelve["last_status"] == "no_answer"
    assert twelve["last_call_at"] == "2026-10-07T09:00:00+09:00"
    assert twelve["week_alerts"] == 1
    thirteen = body["elders"][1]
    assert thirteen["last_call_at"] is None and thirteen["week_avg_score"] is None


def test_the_elder_list_needs_a_guardian_key():
    kit = make_app_kit()

    assert kit.client.get("/v1/guardian/elders").status_code == 401
    assert kit.client.get("/v1/guardian/elders", headers=kit.elder_headers(12)).status_code == 401
    assert kit.client.get("/v1/guardian/elders", headers={"Authorization": "Bearer nlb_short"}).status_code == 401


# ------------------------------------------------ 주간


def test_weekly_returns_seven_days_and_a_summary():
    kit = make_app_kit()
    seed(kit)

    response = kit.client.get("/v1/elders/12/weekly", headers=kit.guardian_headers)

    assert response.status_code == 200
    body = response.json()
    assert body["week_start"] == "2026-10-04"
    assert [d["date"] for d in body["days"]] == [f"2026-10-{n:02d}" for n in range(4, 11)]
    by_date = {d["date"]: d for d in body["days"]}
    assert (by_date["2026-10-05"]["calls"], by_date["2026-10-05"]["avg_score"]) == (1, 10.0)
    assert (by_date["2026-10-06"]["calls"], by_date["2026-10-06"]["avg_score"]) == (1, 30.0)
    assert body["total_calls"] == 2
    assert body["avg_score"] == 20.0


def test_weekly_for_a_week_without_scores_has_null_average():
    kit = make_app_kit()

    body = kit.client.get("/v1/elders/12/weekly", headers=kit.guardian_headers).json()

    assert body["total_calls"] == 0 and body["avg_score"] is None


def test_weekly_snaps_any_date_to_its_sundays_week():
    kit = make_app_kit()
    seed(kit)

    body = kit.client.get("/v1/elders/12/weekly?week_start=2026-10-08", headers=kit.guardian_headers).json()
    previous = kit.client.get("/v1/elders/12/weekly?week_start=2026-09-30", headers=kit.guardian_headers).json()

    assert body["week_start"] == "2026-10-04"
    assert previous["week_start"] == "2026-09-27" and previous["total_calls"] == 0


@pytest.mark.parametrize("value", ["abc", "2026-13-40", "2026/10/04"])
def test_weekly_with_a_bad_date_is_422(value):
    kit = make_app_kit()

    assert kit.client.get(f"/v1/elders/12/weekly?week_start={value}", headers=kit.guardian_headers).status_code == 422


def test_weekly_for_someone_elses_or_a_missing_elder_is_404_with_the_same_body():
    kit = make_app_kit()
    seed(kit)

    theirs = kit.client.get("/v1/elders/14/weekly", headers=kit.guardian_headers)
    missing = kit.client.get("/v1/elders/999/weekly", headers=kit.guardian_headers)

    assert theirs.status_code == missing.status_code == 404
    assert theirs.json() == missing.json() == {"detail": "등록되지 않은 어르신입니다"}


@pytest.mark.parametrize("elder_id", [0, -1, 10**30])
def test_weekly_with_an_out_of_range_id_is_422(elder_id):
    kit = make_app_kit()

    assert kit.client.get(f"/v1/elders/{elder_id}/weekly", headers=kit.guardian_headers).status_code == 422


def test_weekly_needs_a_guardian_key():
    kit = make_app_kit()

    assert kit.client.get("/v1/elders/12/weekly").status_code == 401
    assert kit.client.get("/v1/elders/12/weekly", headers=kit.elder_headers(12)).status_code == 401


def test_weekly_says_how_many_calls_the_usual_baseline_rests_on():
    kit = make_app_kit()
    assert kit.client.get("/v1/elders/12/weekly", headers=kit.guardian_headers).json()["baseline_calls"] == 0

    seed(kit)  # 12번: 점수 있는 통화 2, 안 받음 1
    kit.reports.add_call(call_id=5, elder_id=12, status="completed", created_at=kst(2026, 9, 20, 9), degraded=True)

    body = kit.client.get("/v1/elders/12/weekly?week_start=2026-09-27", headers=kit.guardian_headers).json()
    assert body["baseline_calls"] == 2  # 보는 주와 상관없이 지금까지의 최근 통화로 센다


# ------------------------------------------------ 월간


def month_days(body) -> list[str]:
    return [d["date"] for d in body["days"]]


def test_monthly_returns_every_day_of_the_month_and_a_summary():
    kit = make_app_kit()
    seed(kit)

    response = kit.client.get("/v1/elders/12/monthly?month=2026-10", headers=kit.guardian_headers)

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"month", "days", "total_calls", "avg_score", "baseline_calls"}
    assert body["month"] == "2026-10"
    assert month_days(body) == [f"2026-10-{n:02d}" for n in range(1, 32)]
    assert set(body["days"][0]) == {"date", "calls", "avg_score"}
    by_date = {d["date"]: d for d in body["days"]}
    assert (by_date["2026-10-05"]["calls"], by_date["2026-10-05"]["avg_score"]) == (1, 10.0)
    assert (by_date["2026-10-06"]["calls"], by_date["2026-10-06"]["avg_score"]) == (1, 30.0)
    assert (by_date["2026-10-07"]["calls"], by_date["2026-10-07"]["avg_score"]) == (0, None)  # 안 받음
    assert body["total_calls"] == 2
    assert body["avg_score"] == 20.0
    assert body["baseline_calls"] == 2


def test_monthly_average_is_the_mean_of_daily_means_like_weekly():
    kit = make_app_kit()
    kit.reports.add_call(call_id=1, elder_id=12, status="completed", created_at=kst(2026, 10, 5, 9), score=10)
    kit.reports.add_call(call_id=2, elder_id=12, status="completed", created_at=kst(2026, 10, 5, 15), score=20)
    kit.reports.add_call(call_id=3, elder_id=12, status="completed", created_at=kst(2026, 10, 20, 9), score=45)

    body = kit.client.get("/v1/elders/12/monthly?month=2026-10", headers=kit.guardian_headers).json()

    assert body["total_calls"] == 3
    assert body["avg_score"] == 30.0  # (15 + 45) / 2 — 통화 평균(25)이 아니다


def test_a_month_without_calls_has_zero_calls_and_a_null_average():
    kit = make_app_kit()

    body = kit.client.get("/v1/elders/12/monthly?month=2026-10", headers=kit.guardian_headers).json()

    assert body["total_calls"] == 0 and body["avg_score"] is None
    assert all(d["calls"] == 0 and d["avg_score"] is None for d in body["days"])


@pytest.mark.parametrize(
    ("month", "length"), [("2026-10", 31), ("2026-09", 30), ("2026-02", 28), ("2028-02", 29)]
)
def test_monthly_has_as_many_days_as_the_month(month, length):
    kit = make_app_kit()

    body = kit.client.get(f"/v1/elders/12/monthly?month={month}", headers=kit.guardian_headers).json()

    assert body["month"] == month
    assert len(body["days"]) == length
    assert body["days"][0]["date"] == f"{month}-01"
    assert body["days"][-1]["date"] == f"{month}-{length:02d}"


def test_a_month_that_starts_on_sunday_keeps_the_previous_saturday_out():
    """2026-11-01은 일요일이다 — 첫 주가 바로 그 달에서 시작한다."""
    kit = make_app_kit()
    kit.reports.add_call(call_id=1, elder_id=12, status="completed", created_at=kst(2026, 10, 31, 23, 59, 59), score=40)
    kit.reports.add_call(call_id=2, elder_id=12, status="completed", created_at=kst(2026, 11, 1, 0, 0, 1), score=8)

    body = kit.client.get("/v1/elders/12/monthly?month=2026-11", headers=kit.guardian_headers).json()

    assert month_days(body) == [f"2026-11-{n:02d}" for n in range(1, 31)]
    assert body["days"][0] == {"date": "2026-11-01", "calls": 1, "avg_score": 8.0}
    assert body["total_calls"] == 1 and body["avg_score"] == 8.0


def test_weeks_that_straddle_the_month_edge_give_each_month_only_its_own_days():
    """2026-09-27(일) 주와 2026-10-25(일) 주는 두 달에 걸친다. 한국 날짜로 나눈다."""
    kit = make_app_kit()
    kit.reports.add_call(call_id=1, elder_id=12, status="completed", created_at=kst(2026, 9, 30, 23, 59, 59), score=70)
    kit.reports.add_call(call_id=2, elder_id=12, status="completed", created_at=kst(2026, 10, 1, 0, 0, 1), score=10)
    kit.reports.add_call(call_id=3, elder_id=12, status="completed", created_at=kst(2026, 10, 31, 8), score=20)
    kit.reports.add_call(call_id=4, elder_id=12, status="completed", created_at=kst(2026, 11, 1, 8), score=90)

    october = kit.client.get("/v1/elders/12/monthly?month=2026-10", headers=kit.guardian_headers).json()
    september = kit.client.get("/v1/elders/12/monthly?month=2026-09", headers=kit.guardian_headers).json()

    assert october["total_calls"] == 2 and october["avg_score"] == 15.0
    assert [d["date"] for d in october["days"] if d["calls"]] == ["2026-10-01", "2026-10-31"]
    assert september["total_calls"] == 1 and september["avg_score"] == 70.0
    assert september["days"][-1] == {"date": "2026-09-30", "calls": 1, "avg_score": 70.0}


def test_monthly_without_a_month_is_this_month_in_korea_time():
    """2026-11-01 0시 30분(한국)은 UTC로 아직 10월 31일이다. UTC로 정하면 지난달이 나온다."""
    kit = make_app_kit(now=kst(2026, 11, 1, 0, 30))

    body = kit.client.get("/v1/elders/12/monthly", headers=kit.guardian_headers).json()

    assert body["month"] == "2026-11"
    assert len(body["days"]) == 30


@pytest.mark.parametrize(
    "value", ["2026-13", "2026-00", "2026-1", "26-10", "2026/10", "2026-10-01", "abc", "", "0000-01", "9999-12"]
)
def test_monthly_with_a_bad_month_is_422(value):
    kit = make_app_kit()

    assert kit.client.get(f"/v1/elders/12/monthly?month={value}", headers=kit.guardian_headers).status_code == 422


def test_monthly_for_someone_elses_or_a_missing_elder_is_404_with_the_same_body():
    kit = make_app_kit()
    seed(kit)

    theirs = kit.client.get("/v1/elders/14/monthly?month=2026-10", headers=kit.guardian_headers)
    missing = kit.client.get("/v1/elders/999/monthly?month=2026-10", headers=kit.guardian_headers)

    assert theirs.status_code == missing.status_code == 404
    assert theirs.json() == missing.json() == {"detail": "등록되지 않은 어르신입니다"}


@pytest.mark.parametrize("elder_id", [0, -1, 10**30])
def test_monthly_with_an_out_of_range_id_is_422(elder_id):
    kit = make_app_kit()

    assert kit.client.get(f"/v1/elders/{elder_id}/monthly", headers=kit.guardian_headers).status_code == 422


def test_monthly_needs_a_guardian_key():
    kit = make_app_kit()

    assert kit.client.get("/v1/elders/12/monthly").status_code == 401
    assert kit.client.get("/v1/elders/12/monthly?month=2026-10").status_code == 401
    assert kit.client.get("/v1/elders/12/monthly", headers=kit.elder_headers(12)).status_code == 401


# ------------------------------------------------ 알림


def test_alerts_are_listed_newest_first_with_the_elders_name():
    kit = make_app_kit()
    kit.alerts.raise_alert(
        elder_id=12, guardian_id=1, call_id=None, alert_type="no_answer", severity="info", message="첫째"
    )
    kit.clock.now += 3600
    kit.alerts.raise_alert(
        elder_id=13, guardian_id=1, call_id=None, alert_type="risk_rise", severity="critical", message="둘째"
    )
    kit.alerts.raise_alert(
        elder_id=14, guardian_id=2, call_id=None, alert_type="risk_rise", severity="warning", message="남의 것"
    )

    response = kit.client.get("/v1/guardian/alerts", headers=kit.guardian_headers)

    assert response.status_code == 200
    alerts = response.json()["alerts"]
    assert [a["message"] for a in alerts] == ["둘째", "첫째"]
    assert alerts[0]["elder_name"] == "어르신 13"
    assert (alerts[0]["type"], alerts[0]["severity"]) == ("risk_rise", "critical")
    assert alerts[0]["created_at"] == "2026-10-08T10:00:00+09:00"


def test_alerts_respect_the_limit():
    kit = make_app_kit()
    for _ in range(5):
        kit.alerts.raise_alert(
            elder_id=12, guardian_id=1, call_id=None, alert_type="risk_rise", severity="warning", message="m"
        )

    body = kit.client.get("/v1/guardian/alerts?limit=2", headers=kit.guardian_headers).json()

    assert len(body["alerts"]) == 2


@pytest.mark.parametrize("limit", [0, 101, -1, "x"])
def test_alerts_with_a_bad_limit_is_422(limit):
    kit = make_app_kit()

    assert kit.client.get(f"/v1/guardian/alerts?limit={limit}", headers=kit.guardian_headers).status_code == 422


def test_alerts_need_a_guardian_key():
    kit = make_app_kit()

    assert kit.client.get("/v1/guardian/alerts").status_code == 401


class ExplodingReports:
    def elder_summaries(self, guardian_id, week_start):
        raise RuntimeError("DB 끊김")

    def weekly(self, elder_id, week_start):
        raise RuntimeError("DB 끊김")

    def call_lines(self, elder_id, limit):
        raise RuntimeError("DB 끊김")

    def baseline_calls(self, elder_id):
        raise RuntimeError("DB 끊김")


def test_a_broken_reports_store_is_503():
    kit = make_app_kit()
    kit.data.reports = ExplodingReports()

    assert kit.client.get("/v1/guardian/elders", headers=kit.guardian_headers).status_code == 503
    assert kit.client.get("/v1/elders/12/weekly", headers=kit.guardian_headers).status_code == 503
    assert kit.client.get("/v1/elders/12/monthly", headers=kit.guardian_headers).status_code == 503


def test_a_broken_baseline_count_hides_only_that_hint():
    """기준 통화 수는 안내 한 줄용 덤이다. 그것만 못 읽어도 통계는 보여 주고 null로 둔다(앱은 안내를 숨긴다)."""
    kit = make_app_kit()
    seed(kit)

    def explode(elder_id):
        raise RuntimeError("DB 끊김")

    kit.reports.baseline_calls = explode

    weekly = kit.client.get("/v1/elders/12/weekly", headers=kit.guardian_headers)
    monthly = kit.client.get("/v1/elders/12/monthly?month=2026-10", headers=kit.guardian_headers)

    assert weekly.status_code == monthly.status_code == 200
    assert weekly.json()["baseline_calls"] is None and weekly.json()["total_calls"] == 2
    assert monthly.json()["baseline_calls"] is None and monthly.json()["total_calls"] == 2
