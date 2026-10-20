"""어르신 탈퇴 — 요청하면 보호자에게 알리고, 보호자가 모두 승인해야 지워진다 (설계: 탈퇴·내 정보 삭제)."""

from __future__ import annotations

import logging

from app.api.withdrawals import WITHDRAWAL_TTL_SECONDS
from tests.app_data_helpers import make_app_kit

REQUEST = "/v1/me/withdrawal"
GUARDIAN_LIST = "/v1/guardian/withdrawals"
NO_REQUEST = {"detail": "탈퇴 요청이 없어요"}
NEED_APPROVAL = {"detail": "보호자의 승인이 필요해요"}


def current_id(kit, elder_id=12) -> int:
    """보호자 화면이 지금 보고 있는 요청의 번호. 요청이 없으면 아무 번호나(없는 요청은 어차피 404다)."""
    request = kit.data.withdrawals.get(elder_id)
    return 1 if request is None else request.request_id


def approve(kit, elder_id=12, headers=None, request_id=None):
    return kit.client.post(
        f"/v1/elders/{elder_id}/withdrawal/approve",
        json={"request_id": current_id(kit, elder_id) if request_id is None else request_id},
        headers=kit.guardian_headers if headers is None else headers,
    )


def reject(kit, elder_id=12, headers=None, request_id=None):
    return kit.client.post(
        f"/v1/elders/{elder_id}/withdrawal/reject",
        json={"request_id": current_id(kit, elder_id) if request_id is None else request_id},
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
    assert items[0]["request_id"] == kit.data.withdrawals.get(12).request_id
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


# ------------------------------------------------ 취소·재요청과 삭제 실패 복구 (Codex 검토)


def test_an_approval_from_an_old_card_never_approves_a_request_the_guardian_did_not_see():
    """보호자가 옛 카드를 보고 있는 사이 어르신이 취소하고 다시 요청했다. 그 승인은 새 요청에 붙지 않는다."""
    kit = make_app_kit()
    old_id = ask(kit).json() and current_id(kit)
    kit.client.delete(REQUEST, headers=kit.elder_headers(12))
    ask(kit)

    stale = approve(kit, request_id=old_id)

    assert stale.status_code == 404 and stale.json() == NO_REQUEST
    assert kit.data.elders.get(12) is not None
    assert kit.data.withdrawals.get(12).approved_by == frozenset()
    # 새 카드를 보고 누르면 그때 승인된다
    assert approve(kit).json() == {"status": "deleted"}
    assert kit.data.elders.get(12) is None


def test_a_rejection_from_an_old_card_never_rejects_a_newer_request():
    kit = make_app_kit()
    ask(kit)
    old_id = current_id(kit)
    kit.client.delete(REQUEST, headers=kit.elder_headers(12))
    ask(kit)

    stale = reject(kit, request_id=old_id)

    assert stale.status_code == 404
    assert not kit.data.withdrawals.get(12).rejected
    assert kit.client.get(REQUEST, headers=kit.elder_headers(12)).json()["status"] == "waiting"


def test_an_approval_needs_the_request_number():
    kit = make_app_kit()
    ask(kit)

    for body in ({}, {"request_id": "x"}, {"request_id": 0}):
        response = kit.client.post(
            "/v1/elders/12/withdrawal/approve", json=body, headers=kit.guardian_headers
        )
        assert response.status_code == 422
    assert kit.data.elders.get(12) is not None


def test_when_deleting_fails_the_approval_is_kept_and_the_next_read_finishes_the_job(monkeypatch):
    """전원이 승인했는데 지우다 실패했다. 승인은 남아 있고, 다음에 요청을 읽을 때 이어서 지운다 — 영원히 대기 상태로 남지 않는다."""
    kit = make_app_kit()
    ask(kit)
    real_delete = kit.data.elders.delete_elder
    attempts = []

    def flaky(elder_id):
        attempts.append(elder_id)
        if len(attempts) == 1:
            raise RuntimeError("저장소 오류")
        return real_delete(elder_id)

    monkeypatch.setattr(kit.data.elders, "delete_elder", flaky)

    failed = approve(kit)

    assert failed.status_code == 503
    assert kit.data.elders.get(12) is not None
    assert kit.data.withdrawals.get(12).approved_by == frozenset({1})  # 승인은 남았다

    items = kit.client.get(GUARDIAN_LIST, headers=kit.guardian_headers).json()["withdrawals"]

    assert items == []  # 읽는 김에 이어서 지웠다
    assert kit.data.elders.get(12) is None
    assert len(attempts) == 2
    assert kit.client.get("/v1/me/status", headers=kit.elder_headers(12)).status_code == 401


def test_the_elder_status_read_also_finishes_a_half_done_withdrawal(monkeypatch):
    kit = make_app_kit()
    ask(kit)
    real_delete = kit.data.elders.delete_elder
    calls = []

    def flaky(elder_id):
        calls.append(elder_id)
        if len(calls) == 1:
            raise RuntimeError("저장소 오류")
        return real_delete(elder_id)

    monkeypatch.setattr(kit.data.elders, "delete_elder", flaky)
    approve(kit)

    # 어르신 폰이 상태를 읽는다 — 이어서 지워지고, 폰은 열쇠가 끝났다는 401을 받는다
    headers = kit.elder_headers(12)  # 헬퍼는 부를 때마다 새 열쇠를 만든다 — 한 번만 만들어 같은 열쇠로 두 번 읽는다
    first = kit.client.get(REQUEST, headers=headers)
    assert first.status_code == 200 and first.json() == {"status": "none"}
    assert kit.data.elders.get(12) is None
    assert kit.client.get(REQUEST, headers=headers).status_code == 401


def test_approving_again_after_a_failure_finishes_it_too(monkeypatch):
    kit = make_app_kit()
    ask(kit)
    real_delete = kit.data.elders.delete_elder
    calls = []

    def flaky(elder_id):
        calls.append(elder_id)
        if len(calls) == 1:
            raise RuntimeError("저장소 오류")
        return real_delete(elder_id)

    monkeypatch.setattr(kit.data.elders, "delete_elder", flaky)
    request_id = current_id(kit)
    assert approve(kit, request_id=request_id).status_code == 503

    again = approve(kit, request_id=request_id)

    # 요청이 이미 이어서 지워졌거나 다시 승인으로 끝났다 — 어느 쪽이든 어르신은 지워진다
    assert again.status_code in (200, 404)
    assert kit.data.elders.get(12) is None
