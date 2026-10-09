"""어르신 조회·연락처 주소 — 내 통화 기록, 비상 연락처."""

from __future__ import annotations

import pytest

from tests.app_data_helpers import kst, make_app_kit


# ------------------------------------------------ 내 통화 기록


def test_my_calls_show_finished_calls_newest_first():
    kit = make_app_kit()
    kit.reports.add_call(call_id=1, elder_id=12, status="completed", created_at=kst(2026, 10, 5, 9), duration_ms=52_000)
    kit.reports.add_call(call_id=2, elder_id=12, status="no_answer", created_at=kst(2026, 10, 6, 9))
    kit.reports.add_call(call_id=3, elder_id=13, status="completed", created_at=kst(2026, 10, 6, 9))

    response = kit.client.get("/v1/me/calls", headers=kit.elder_headers(12))

    assert response.status_code == 200
    calls = response.json()["calls"]
    assert [(c["call_id"], c["status"]) for c in calls] == [(2, "no_answer"), (1, "completed")]
    assert calls[1] == {
        "call_id": 1,
        "started_at": "2026-10-05T09:00:00+09:00",
        "duration_s": 52,
        "status": "completed",
    }
    assert calls[0]["duration_s"] is None


def test_my_calls_respect_the_limit_and_validate_it():
    kit = make_app_kit()
    for n in range(1, 6):
        kit.reports.add_call(call_id=n, elder_id=12, status="completed", created_at=kst(2026, 10, 5, n))
    headers = kit.elder_headers(12)

    assert len(kit.client.get("/v1/me/calls?limit=2", headers=headers).json()["calls"]) == 2
    assert kit.client.get("/v1/me/calls?limit=0", headers=headers).status_code == 422
    assert kit.client.get("/v1/me/calls?limit=101", headers=headers).status_code == 422


def test_elder_routes_need_an_elder_key_and_reject_a_guardian_key():
    kit = make_app_kit()

    for path in ("/v1/me/calls", "/v1/me/contacts"):
        assert kit.client.get(path).status_code == 401
        assert kit.client.get(path, headers=kit.guardian_headers).status_code == 401
        assert kit.client.get(path, headers={"Authorization": "Bearer nle_short"}).status_code == 401


# ------------------------------------------------ 비상 연락처


def test_the_contact_list_has_my_guardian_and_what_i_added():
    kit = make_app_kit()
    headers = kit.elder_headers(12)
    created = kit.client.post(
        "/v1/me/contacts",
        json={"name": "이웃 김씨", "relation": "이웃", "phone": "010-1234-5678"},
        headers=headers,
    )
    assert created.status_code == 201
    contact = created.json()
    assert contact["name"] == "이웃 김씨" and isinstance(contact["contact_id"], int)

    body = kit.client.get("/v1/me/contacts", headers=headers).json()

    assert body["guardians"] == [{"name": "보호자1", "relation": "보호자", "phone": "010-0000-0001"}]
    assert body["contacts"] == [
        {"contact_id": contact["contact_id"], "name": "이웃 김씨", "relation": "이웃", "phone": "010-1234-5678"}
    ]


def test_each_elder_sees_their_own_guardian_and_contacts():
    kit = make_app_kit()
    kit.client.post(
        "/v1/me/contacts", json={"name": "가", "relation": "", "phone": "111-1111"}, headers=kit.elder_headers(12)
    )

    body = kit.client.get("/v1/me/contacts", headers=kit.elder_headers(14)).json()

    assert body["contacts"] == []
    assert body["guardians"][0]["name"] == "보호자2"


def test_a_contact_can_be_deleted_by_its_owner():
    kit = make_app_kit()
    headers = kit.elder_headers(12)
    contact_id = kit.client.post(
        "/v1/me/contacts", json={"name": "가", "relation": "", "phone": "111-1111"}, headers=headers
    ).json()["contact_id"]

    deleted = kit.client.delete(f"/v1/me/contacts/{contact_id}", headers=headers)

    assert deleted.status_code == 204
    assert kit.client.get("/v1/me/contacts", headers=headers).json()["contacts"] == []


def test_deleting_another_elders_contact_is_404_and_deletes_nothing():
    kit = make_app_kit()
    mine = kit.client.post(
        "/v1/me/contacts", json={"name": "가", "relation": "", "phone": "111-1111"}, headers=kit.elder_headers(12)
    ).json()["contact_id"]

    attempt = kit.client.delete(f"/v1/me/contacts/{mine}", headers=kit.elder_headers(13))
    missing = kit.client.delete("/v1/me/contacts/424242", headers=kit.elder_headers(13))

    assert attempt.status_code == missing.status_code == 404
    assert attempt.json() == missing.json() == {"detail": "없는 연락처입니다"}
    assert len(kit.client.get("/v1/me/contacts", headers=kit.elder_headers(12)).json()["contacts"]) == 1


def test_the_twenty_first_contact_is_refused_with_a_clear_message():
    kit = make_app_kit()
    headers = kit.elder_headers(12)
    for i in range(20):
        assert kit.client.post(
            "/v1/me/contacts", json={"name": f"c{i}", "relation": "", "phone": "111-1111"}, headers=headers
        ).status_code == 201

    over = kit.client.post(
        "/v1/me/contacts", json={"name": "넘침", "relation": "", "phone": "111-1111"}, headers=headers
    )

    assert over.status_code == 400
    assert over.json() == {"detail": "연락처는 20개까지 둘 수 있습니다"}


@pytest.mark.parametrize(
    "body",
    [
        {"name": "", "relation": "", "phone": "111-1111"},
        {"name": "가" * 31, "relation": "", "phone": "111-1111"},
        {"name": "가", "relation": "나" * 21, "phone": "111-1111"},
        {"name": "가", "relation": "", "phone": "abc"},
        {"name": "가", "relation": "", "phone": "1234"},
        {"name": "가", "relation": "", "phone": "1" * 21},
        {"relation": "", "phone": "111-1111"},
        {},
    ],
)
def test_a_malformed_contact_is_422_never_500(body):
    kit = make_app_kit()

    assert kit.client.post("/v1/me/contacts", json=body, headers=kit.elder_headers(12)).status_code == 422


def test_the_relation_may_be_left_out():
    kit = make_app_kit()

    created = kit.client.post(
        "/v1/me/contacts", json={"name": "가", "phone": "111-1111"}, headers=kit.elder_headers(12)
    )

    assert created.status_code == 201 and created.json()["relation"] == ""


class ExplodingContacts:
    def list(self, elder_id):
        raise RuntimeError("DB 끊김")

    def add(self, elder_id, **kwargs):
        raise RuntimeError("DB 끊김")

    def remove(self, elder_id, contact_id):
        raise RuntimeError("DB 끊김")


def test_a_broken_contact_store_is_503():
    kit = make_app_kit()
    kit.data.contacts = ExplodingContacts()
    headers = kit.elder_headers(12)

    assert kit.client.get("/v1/me/contacts", headers=headers).status_code == 503
    assert kit.client.post(
        "/v1/me/contacts", json={"name": "가", "phone": "111-1111"}, headers=headers
    ).status_code == 503
