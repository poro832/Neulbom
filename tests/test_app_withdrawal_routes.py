"""어르신 탈퇴 — 요청하면 보호자에게 알리고, 보호자가 모두 승인해야 지워진다 (설계: 탈퇴·내 정보 삭제)."""

from __future__ import annotations

import logging

from app.api.withdrawals import WITHDRAWAL_TTL_SECONDS
from tests.app_data_helpers import make_app_kit

REQUEST = "/v1/me/withdrawal"
GUARDIAN_LIST = "/v1/guardian/withdrawals"
NO_REQUEST = {"detail": "탈퇴 요청이 없어요"}
NEED_APPROVAL = {"detail": "보호자의 승인이 필요해요"}


def approve(kit, elder_id=12, headers=None):
    return kit.client.post(
        f"/v1/elders/{elder_id}/withdrawal/approve",
        headers=kit.guardian_headers if headers is None else headers,
    )


def reject(kit, elder_id=12, headers=None):
    return kit.client.post(
        f"/v1/elders/{elder_id}/withdrawal/reject",
        headers=kit.guardian_headers if headers is None else headers,
    )


def ask(kit, elder_id=12):
    return kit.client.post(REQUEST, json={"confirm": True}, headers=kit.elder_headers(elder_id))


class FakeNotifier:
    def __init__(self, explode=False):
        self.calls: list[tuple[int, int]] = []
        self.explode = explode

    def notify_withdrawal(self, guardian_id, elder_id):
        self.calls.append((guardian_id, elder_id))
        if self.explode:
            raise RuntimeError("푸시 서버 오류")


# ------------------------------------------------ 어르신이 요청한다


def test_asking_to_withdraw_waits_for_the_guardian_and_deletes_nothing():
    kit = make_app_kit()

    response = ask(kit)

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "waiting" and body["approved"] == 0 and body["total"] == 1
    assert kit.data.elders.get(12) is not None
    assert kit.client.get("/v1/me/status", headers=kit.elder_headers(12)).status_code == 200


def test_a_linked_elder_cannot_skip_the_approval_with_the_old_delete():
    kit = make_app_kit()

    response = kit.client.request("DELETE", "/v1/me", json={"confirm": True}, headers=kit.elder_headers(12))

    assert response.status_code == 409 and response.json() == NEED_APPROVAL
    assert kit.data.elders.get(12) is not None


def test_an_elder_without_a_guardian_withdraws_at_once():
    kit = make_app_kit()
    signed = kit.client.post(
        "/v1/elders/signup", json={"name": "홍길동", "phone": "010-7777-8888", "agreed": True}
    ).json()
    headers = {"Authorization": f"Bearer {signed['elder_key']}"}

    response = kit.client.post(REQUEST, json={"confirm": True}, headers=headers)

    assert response.status_code == 200 and response.json() == {"status": "deleted"}
    assert kit.client.get("/v1/me/status", headers=headers).status_code == 401


def test_an_unlinked_elder_can_also_use_the_plain_delete():
    kit = make_app_kit()
    signed = kit.client.post(
        "/v1/elders/signup", json={"name": "홍길동", "phone": "010-7777-8888", "agreed": True}
    ).json()
    headers = {"Authorization": f"Bearer {signed['elder_key']}"}

    response = kit.client.request("DELETE", "/v1/me", json={"confirm": True}, headers=headers)

    assert response.status_code == 204


def test_asking_twice_keeps_the_same_request_and_tells_the_guardian_once():
    kit = make_app_kit()
    kit.data.notifier = FakeNotifier()

    first = ask(kit).json()
    second = ask(kit).json()

    assert first["requested_at"] == second["requested_at"]
    assert kit.data.notifier.calls == [(1, 12)]


def test_the_guardian_is_told_by_push():
    kit = make_app_kit()
    kit.data.notifier = FakeNotifier()

    ask(kit)

    assert kit.data.notifier.calls == [(1, 12)]


def test_a_broken_push_never_stops_the_request():
    kit = make_app_kit()
    kit.data.notifier = FakeNotifier(explode=True)

    assert ask(kit).status_code == 202
    assert kit.client.get(GUARDIAN_LIST, headers=kit.guardian_headers).json()["withdrawals"]


def test_confirm_must_be_exactly_true():
    kit = make_app_kit()

    for body in ({}, {"confirm": False}, {"confirm": "true"}, {"confirm": 1}):
        assert kit.client.post(REQUEST, json=body, headers=kit.elder_headers(12)).status_code == 422
    assert kit.client.get(REQUEST, headers=kit.elder_headers(12)).json() == {"status": "none"}


def test_requests_need_an_elder_key():
    kit = make_app_kit()

    assert kit.client.post(REQUEST, json={"confirm": True}).status_code == 401
    assert kit.client.post(REQUEST, json={"confirm": True}, headers=kit.guardian_headers).status_code == 401
    assert kit.client.get(REQUEST).status_code == 401
    assert kit.client.delete(REQUEST).status_code == 401


# ------------------------------------------------ 어르신이 상태를 본다


def test_the_elder_sees_none_then_waiting():
    kit = make_app_kit()
    assert kit.client.get(REQUEST, headers=kit.elder_headers(12)).json() == {"status": "none"}

    ask(kit)

    body = kit.client.get(REQUEST, headers=kit.elder_headers(12)).json()
    assert body["status"] == "waiting" and body["approved"] == 0 and body["total"] == 1


def test_the_elder_sees_that_the_guardian_refused_and_can_ask_again():
    kit = make_app_kit()
    ask(kit)
    assert reject(kit).status_code == 204

    assert kit.client.get(REQUEST, headers=kit.elder_headers(12)).json()["status"] == "rejected"
    again = ask(kit)

    assert again.status_code == 202 and again.json()["status"] == "waiting"
    assert kit.client.get(REQUEST, headers=kit.elder_headers(12)).json()["status"] == "waiting"


def test_the_elder_can_cancel_the_request():
    kit = make_app_kit()
    ask(kit)

    assert kit.client.delete(REQUEST, headers=kit.elder_headers(12)).status_code == 204

    assert kit.client.get(REQUEST, headers=kit.elder_headers(12)).json() == {"status": "none"}
    assert approve(kit).status_code == 404 and approve(kit).json() == NO_REQUEST
    assert kit.data.elders.get(12) is not None


def test_a_request_expires_after_seven_days():
    kit = make_app_kit()
    ask(kit)
    kit.clock.now += WITHDRAWAL_TTL_SECONDS + 1

    assert kit.client.get(REQUEST, headers=kit.elder_headers(12)).json() == {"status": "none"}
    assert approve(kit).status_code == 404
    assert kit.client.get(GUARDIAN_LIST, headers=kit.guardian_headers).json() == {"withdrawals": []}
    assert kit.data.elders.get(12) is not None


def test_a_request_is_still_open_just_before_seven_days():
    kit = make_app_kit()
    ask(kit)
    kit.clock.now += WITHDRAWAL_TTL_SECONDS - 60

    assert kit.client.get(REQUEST, headers=kit.elder_headers(12)).json()["status"] == "waiting"


# ------------------------------------------------ 보호자가 본다·승인한다·거절한다


def test_the_guardian_sees_the_open_request_of_their_elder_only():
    kit = make_app_kit()
    ask(kit, 12)
    ask(kit, 14)  # 보호자 2의 어르신

    items = kit.client.get(GUARDIAN_LIST, headers=kit.guardian_headers).json()["withdrawals"]

    assert [item["elder_id"] for item in items] == [12]
    assert items[0]["name"] == "어르신 12"
    assert items[0]["approved_by_me"] is False and items[0]["approved"] == 0 and items[0]["total"] == 1


def test_approving_deletes_the_elder_when_every_guardian_has_approved():
    kit = make_app_kit()
    ask(kit)

    response = approve(kit)

    assert response.status_code == 200 and response.json() == {"status": "deleted"}
    assert kit.data.elders.get(12) is None
    assert kit.client.get("/v1/me/status", headers=kit.elder_headers(12)).status_code == 401
    assert kit.data.withdrawals.get(12) is None
    # 다른 어르신은 그대로다
    assert kit.data.elders.get(13) is not None and kit.data.elders.get(14) is not None
    assert kit.client.get(GUARDIAN_LIST, headers=kit.guardian_headers).json() == {"withdrawals": []}


def test_rejecting_keeps_the_elder_and_hides_the_request_from_the_guardian_list():
    kit = make_app_kit()
    ask(kit)

    assert reject(kit).status_code == 204

    assert kit.data.elders.get(12) is not None
    assert kit.client.get(GUARDIAN_LIST, headers=kit.guardian_headers).json() == {"withdrawals": []}
    assert approve(kit).status_code == 404  # 거절된 요청은 승인할 수 없다
    assert kit.data.elders.get(12) is not None


def test_approving_or_rejecting_without_a_request_is_not_found():
    kit = make_app_kit()

    assert approve(kit).status_code == 404 and approve(kit).json() == NO_REQUEST
    assert reject(kit).status_code == 404 and reject(kit).json() == NO_REQUEST


def test_another_guardian_cannot_approve_or_reject_someone_elses_elder():
    kit = make_app_kit()
    ask(kit)

    # 어르신 12의 보호자는 1이다. 보호자 1의 열쇠로 보호자 2의 어르신 14를 건드릴 수 없다.
    ask(kit, 14)
    assert approve(kit, 14).status_code == 404
    assert reject(kit, 14).status_code == 404
    assert kit.data.elders.get(14) is not None
    assert kit.data.withdrawals.get(14).approved_by == frozenset()


def test_approve_and_reject_need_a_guardian_key():
    kit = make_app_kit()
    ask(kit)

    for call in (approve, reject):
        assert call(kit, headers={}).status_code == 401
        assert call(kit, headers=kit.elder_headers(12)).status_code == 401  # 어르신 열쇠로는 못 한다
    assert kit.client.get(GUARDIAN_LIST).status_code == 401
    assert kit.data.elders.get(12) is not None


def test_the_logs_have_ids_and_counts_but_no_names_or_numbers(caplog):
    kit = make_app_kit()

    with caplog.at_level(logging.DEBUG):
        ask(kit)
        reject(kit)
        ask(kit)
        approve(kit)

    assert "어르신이 탈퇴를 요청했다 elder_id=12" in caplog.text
    assert "어르신이 탈퇴했다 elder_id=12" in caplog.text
    for secret in ("어르신 12", "070-1111-2222", "07011112222"):
        assert secret not in caplog.text
