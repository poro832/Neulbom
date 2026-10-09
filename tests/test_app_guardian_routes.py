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


def test_a_broken_reports_store_is_503():
    kit = make_app_kit()
    kit.data.reports = ExplodingReports()

    assert kit.client.get("/v1/guardian/elders", headers=kit.guardian_headers).status_code == 503
    assert kit.client.get("/v1/elders/12/weekly", headers=kit.guardian_headers).status_code == 503
