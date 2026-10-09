"""AlertRules — 언제 알림을 만들고 언제 만들지 않는가."""

from __future__ import annotations

import logging

from app.api.alert_rules import AlertRules
from app.api.alerts import NO_ANSWER_MESSAGE, RISK_MESSAGES, InMemoryAlertStore
from app.api.elder_directory import ElderAccess, InMemoryElderDirectory
from app.api.store import CallRecord


def make(entries=None):
    alerts = InMemoryAlertStore()
    directory = InMemoryElderDirectory(entries or {12: ElderAccess(1, True, "어르신 12")})
    return AlertRules(alerts=alerts, elders=directory), alerts


def call(trigger="scheduled", call_id=7, elder_id=12):
    return CallRecord(call_id=call_id, elder_id=elder_id, trigger_type=trigger, status="no_answer")


def test_a_watch_judgement_raises_a_warning():
    rules, alerts = make()

    rules.on_risk(call_id=7, elder_id=12, risk_level="watch")

    (alert,) = alerts.recent_for_guardian(1, 10)
    assert (alert.alert_type, alert.severity, alert.message) == ("risk_rise", "warning", RISK_MESSAGES["watch"])
    assert alert.call_id == 7 and alert.elder_id == 12


def test_an_alert_judgement_raises_a_critical():
    rules, alerts = make()

    rules.on_risk(call_id=7, elder_id=12, risk_level="alert")

    (alert,) = alerts.recent_for_guardian(1, 10)
    assert (alert.severity, alert.message) == ("critical", RISK_MESSAGES["alert"])


def test_a_normal_judgement_raises_nothing():
    rules, alerts = make()

    rules.on_risk(call_id=7, elder_id=12, risk_level="normal")

    assert alerts.recent_for_guardian(1, 10) == []


def test_a_missed_scheduled_call_raises_an_info_alert():
    rules, alerts = make()

    rules.on_no_answer(call("scheduled"))

    (alert,) = alerts.recent_for_guardian(1, 10)
    assert (alert.alert_type, alert.severity, alert.message) == ("no_answer", "info", NO_ANSWER_MESSAGE)


def test_a_missed_requested_call_raises_nothing():
    """버튼을 누르고 전화기를 못 찾은 것일 뿐이다. 위험 점수와 같은 규칙이다."""
    rules, alerts = make()

    rules.on_no_answer(call("requested"))

    assert alerts.recent_for_guardian(1, 10) == []


def test_a_repeated_webhook_does_not_duplicate_the_alert():
    rules, alerts = make()

    rules.on_no_answer(call("scheduled"))
    rules.on_no_answer(call("scheduled"))
    rules.on_risk(call_id=8, elder_id=12, risk_level="watch")
    rules.on_risk(call_id=8, elder_id=12, risk_level="watch")

    assert len(alerts.recent_for_guardian(1, 10)) == 2


def test_an_unknown_elder_is_logged_and_ignored(caplog):
    rules, alerts = make()

    with caplog.at_level(logging.WARNING, logger="app.api.alert_rules"):
        rules.on_risk(call_id=7, elder_id=999, risk_level="alert")

    assert alerts.recent_for_guardian(1, 10) == []
    assert "알림" in caplog.text


class BrokenAlerts:
    def raise_alert(self, **kwargs):
        raise RuntimeError("DB 끊김")


def test_a_store_failure_never_escapes(caplog):
    """알림 하나 못 만들었다고 점수 저장이나 통화 종료가 막히면 어르신이 잠긴다."""
    directory = InMemoryElderDirectory({12: ElderAccess(1, True, "어르신 12")})
    rules = AlertRules(alerts=BrokenAlerts(), elders=directory)

    with caplog.at_level(logging.ERROR, logger="app.api.alert_rules"):
        rules.on_risk(call_id=7, elder_id=12, risk_level="alert")
        rules.on_no_answer(call("scheduled"))

    assert "알림 생성 실패" in caplog.text


class BrokenDirectory:
    def get(self, elder_id):
        raise RuntimeError("DB 끊김")


def test_a_directory_failure_never_escapes():
    rules = AlertRules(alerts=InMemoryAlertStore(), elders=BrokenDirectory())

    rules.on_risk(call_id=7, elder_id=12, risk_level="alert")
    rules.on_no_answer(call("scheduled"))
