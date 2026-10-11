"""통화 요약·원문 — 동의 전에는 어떤 경로로도 나가지 않는다 (설계: 통화 요약·원문 공개)."""

from __future__ import annotations

import logging

from tests.app_data_helpers import kst, make_app_kit

NOW = kst(2026, 10, 8, 9, 0, 0)


def seed(kit, call_id=1, elder_id=12, agreed=True):
    kit.reports.add_call(
        call_id=call_id, elder_id=elder_id, status="completed",
        created_at=NOW - 3600, score=10, duration_ms=60000,
    )
    kit.data.content.set_owner(call_id, elder_id)
    kit.data.content.save_turns(call_id, [("ai", "안녕하세요"), ("elder", "네 안녕하세요")])
    kit.data.content.save_summary(call_id, "안부를 나누셨어요.", "m")
    if agreed:
        kit.data.content.agree_share(elder_id)


def test_list_shows_summaries_when_agreed():
    kit = make_app_kit(NOW)
    seed(kit)
    body = kit.client.get("/v1/elders/12/calls", headers=kit.guardian_headers).json()
    assert body["share_agreed"] is True
    assert body["calls"][0]["summary"] == "안부를 나누셨어요."
    assert body["calls"][0]["has_turns"] is True
    assert body["calls"][0]["call_id"] == 1


def test_list_marks_calls_without_content():
    kit = make_app_kit(NOW)
    kit.reports.add_call(call_id=2, elder_id=12, status="no_answer", created_at=NOW - 60)
    kit.data.content.agree_share(12)
    call = kit.client.get("/v1/elders/12/calls", headers=kit.guardian_headers).json()["calls"][0]
    assert call["summary"] is None and call["has_turns"] is False


def test_list_hides_everything_before_elder_agrees():
    kit = make_app_kit(NOW)
    seed(kit, agreed=False)
    body = kit.client.get("/v1/elders/12/calls", headers=kit.guardian_headers).json()
    assert body == {"share_agreed": False, "calls": []}


def test_turns_before_agreement_is_404_and_not_logged_as_a_view():
    kit = make_app_kit(NOW)
    seed(kit, agreed=False)
    r = kit.client.get("/v1/calls/1/turns", headers=kit.guardian_headers)
    assert r.status_code == 404
    assert "안녕하세요" not in r.text
    assert kit.data.content.view_count(1) == 0


def test_turns_returns_dialogue_and_logs_every_view():
    kit = make_app_kit(NOW)
    seed(kit)
    r = kit.client.get("/v1/calls/1/turns", headers=kit.guardian_headers)
    assert r.status_code == 200
    assert r.json() == {
        "call_id": 1,
        "turns": [
            {"speaker": "ai", "text": "안녕하세요"},
            {"speaker": "elder", "text": "네 안녕하세요"},
        ],
    }
    kit.client.get("/v1/calls/1/turns", headers=kit.guardian_headers)
    assert kit.data.content.view_count(1) == 2


def test_viewing_never_logs_the_conversation(caplog):
    kit = make_app_kit(NOW)
    seed(kit)
    with caplog.at_level(logging.DEBUG):
        kit.client.get("/v1/calls/1/turns", headers=kit.guardian_headers)
    assert "안녕하세요" not in caplog.text


def test_other_guardians_elder_is_404_for_both():
    kit = make_app_kit(NOW)
    seed(kit, call_id=5, elder_id=14)  # 어르신 14는 보호자 2의 어르신이다
    assert kit.client.get("/v1/elders/14/calls", headers=kit.guardian_headers).status_code == 404
    r = kit.client.get("/v1/calls/5/turns", headers=kit.guardian_headers)
    assert r.status_code == 404
    # 없는 통화와 같은 응답이라 존재 여부가 드러나지 않는다
    assert r.json() == kit.client.get("/v1/calls/99/turns", headers=kit.guardian_headers).json()
    assert kit.data.content.view_count(5) == 0


def test_keys_are_required():
    kit = make_app_kit(NOW)
    seed(kit)
    assert kit.client.get("/v1/calls/1/turns").status_code == 401
    assert kit.client.get("/v1/elders/12/calls").status_code == 401
    assert kit.client.get("/v1/calls/1/turns", headers=kit.elder_headers(12)).status_code == 401


def test_elder_can_agree_to_share():
    kit = make_app_kit(NOW)
    headers = kit.elder_headers(12)
    assert kit.client.get("/v1/me/status", headers=headers).json()["share_agreed"] is False
    r = kit.client.post("/v1/me/share-consent", headers=headers)
    assert r.status_code == 200 and r.json() == {"share_agreed": True}
    assert kit.client.get("/v1/me/status", headers=headers).json()["share_agreed"] is True
    assert kit.client.post("/v1/me/share-consent").status_code == 401
    assert kit.client.post("/v1/me/share-consent", headers=kit.guardian_headers).status_code == 401
