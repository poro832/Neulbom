"""탈퇴 요청의 모든 (상태 × 사건) 조합 — 빠진 분기가 없는지 표로 확인한다.

상태: 없음(none) · 승인 대기(waiting) · 거절됨(rejected) · 잠김(locked: 전원이 승인했지만 삭제가 실패해 남았다).
사건: 어르신의 요청·상태 조회·취소, 보호자의 승인(본 요청의 번호/옛 번호)·거절·목록, 7일 경과.
보호자는 한 명이다(보호자 1, 어르신 12). 잠김 상태는 삭제가 첫 번째만 실패하고 그다음에는 성공하는 저장소로 만든다.
"""

from __future__ import annotations

import pytest

from app.api.withdrawals import WITHDRAWAL_TTL_SECONDS
from tests.app_data_helpers import make_app_kit
from tests.test_app_withdrawal_routes import (
    GUARDIAN_LIST,
    NO_REQUEST,
    REQUEST,
    approve,
    current_id,
    reject,
)

LOCKED_MESSAGE = {"detail": "보호자가 이미 승인해서 곧 탈퇴돼요"}


class World:
    def __init__(self, state: str, monkeypatch):
        self.kit = make_app_kit()
        self.elder = self.kit.elder_headers(12)  # 열쇠는 한 번만 만든다(부를 때마다 새로 만들어진다)
        self.state = state
        self.request_id = None
        if state == "none":
            return
        assert self.elder_asks().status_code == 202
        self.request_id = current_id(self.kit)
        if state == "rejected":
            assert reject(self.kit).status_code == 204
        elif state == "locked":
            real_delete = self.kit.data.elders.delete_elder
            calls = []

            def flaky(elder_id):
                calls.append(elder_id)
                if len(calls) == 1:
                    raise RuntimeError("저장소 오류")
                return real_delete(elder_id)

            monkeypatch.setattr(self.kit.data.elders, "delete_elder", flaky)
            assert approve(self.kit).status_code == 503
            assert self.kit.data.withdrawals.get(12).locked

    @property
    def elder_alive(self) -> bool:
        return self.kit.data.elders.get(12) is not None

    @property
    def request(self):
        return self.kit.data.withdrawals.get(12)

    # 사건들
    def elder_asks(self):
        return self.kit.client.post(REQUEST, json={"confirm": True}, headers=self.elder)

    def elder_reads(self):
        return self.kit.client.get(REQUEST, headers=self.elder)

    def elder_cancels(self):
        return self.kit.client.delete(REQUEST, headers=self.elder)

    def guardian_approves(self):
        return approve(self.kit, request_id=self.request_id)

    def guardian_approves_with_an_old_number(self):
        return approve(self.kit, request_id=(self.request_id or 1) + 100)

    def guardian_rejects(self):
        return reject(self.kit, request_id=self.request_id)

    def guardian_lists(self):
        return self.kit.client.get(GUARDIAN_LIST, headers=self.kit.guardian_headers)

    def a_week_passes(self):
        self.kit.clock.now += WITHDRAWAL_TTL_SECONDS + 60


@pytest.fixture
def world(request, monkeypatch):
    return World(request.param, monkeypatch)


def worlds(*states):
    return pytest.mark.parametrize("world", states, indirect=True)


# ------------------------------------------------ 없음


@worlds("none")
def test_none_elder_asks_starts_a_waiting_request(world):
    r = world.elder_asks()
    assert r.status_code == 202 and r.json()["status"] == "waiting"
    assert world.request is not None and world.elder_alive


@worlds("none")
def test_none_elder_reads_none_and_cancel_is_harmless(world):
    assert world.elder_reads().json() == {"status": "none"}
    assert world.elder_cancels().status_code == 204
    assert world.request is None and world.elder_alive


@worlds("none")
def test_none_guardian_cannot_approve_or_reject_and_lists_nothing(world):
    assert world.guardian_approves().status_code == 404
    assert world.guardian_rejects().status_code == 404
    assert world.guardian_lists().json() == {"withdrawals": []}
    assert world.elder_alive


# ------------------------------------------------ 승인 대기


@worlds("waiting")
def test_waiting_asking_again_keeps_the_same_request(world):
    r = world.elder_asks()
    assert r.status_code == 202 and r.json()["status"] == "waiting"
    assert world.request.request_id == world.request_id


@worlds("waiting")
def test_waiting_elder_reads_waiting_and_can_cancel(world):
    assert world.elder_reads().json()["status"] == "waiting"
    assert world.elder_cancels().status_code == 204
    assert world.request is None and world.elder_alive


@worlds("waiting")
def test_waiting_the_last_approval_deletes_the_elder(world):
    r = world.guardian_approves()
    assert r.status_code == 200 and r.json() == {"status": "deleted"}
    assert not world.elder_alive and world.request is None


@worlds("waiting")
def test_waiting_an_approval_with_an_old_number_changes_nothing(world):
    assert world.guardian_approves_with_an_old_number().status_code == 404
    assert world.elder_alive and world.request.approved_by == frozenset()


@worlds("waiting")
def test_waiting_a_rejection_keeps_the_elder_and_shows_rejected(world):
    assert world.guardian_rejects().status_code == 204
    assert world.elder_reads().json()["status"] == "rejected"
    assert world.guardian_lists().json() == {"withdrawals": []}
    assert world.elder_alive


@worlds("waiting")
def test_waiting_the_guardian_sees_the_card(world):
    items = world.guardian_lists().json()["withdrawals"]
    assert [item["request_id"] for item in items] == [world.request_id]


@worlds("waiting")
def test_waiting_a_week_later_the_request_is_gone_and_the_elder_stays(world):
    world.a_week_passes()
    assert world.elder_reads().json() == {"status": "none"}
    assert world.elder_alive and world.request is None


# ------------------------------------------------ 거절됨


@worlds("rejected")
def test_rejected_asking_again_starts_a_new_request(world):
    r = world.elder_asks()
    assert r.status_code == 202 and r.json()["status"] == "waiting"
    assert world.request.request_id != world.request_id and not world.request.rejected


@worlds("rejected")
def test_rejected_elder_reads_rejected_and_can_clear_it(world):
    assert world.elder_reads().json()["status"] == "rejected"
    assert world.elder_cancels().status_code == 204
    assert world.elder_reads().json() == {"status": "none"}


@worlds("rejected")
def test_rejected_the_guardian_can_neither_approve_nor_reject_again(world):
    assert world.guardian_approves().status_code == 404
    assert world.guardian_rejects().status_code == 404
    assert world.guardian_lists().json() == {"withdrawals": []}
    assert world.elder_alive


# ------------------------------------------------ 잠김 (전원 승인 + 삭제 실패)


@worlds("locked")
def test_locked_the_elder_cannot_cancel(world):
    r = world.elder_cancels()
    assert r.status_code == 409 and r.json() == LOCKED_MESSAGE
    assert world.request is not None and world.request.locked


@worlds("locked")
def test_locked_asking_again_finishes_the_deletion_and_says_deleted(world):
    r = world.elder_asks()
    assert r.status_code == 200 and r.json() == {"status": "deleted"}
    assert not world.elder_alive and world.request is None


@worlds("locked")
def test_locked_the_next_read_finishes_the_deletion(world):
    assert world.elder_reads().json() == {"status": "deleted"}
    assert not world.elder_alive


@worlds("locked")
def test_locked_the_guardians_list_finishes_the_deletion(world):
    assert world.guardian_lists().json() == {"withdrawals": []}
    assert not world.elder_alive


@worlds("locked")
def test_locked_retrying_the_approval_finishes_and_says_deleted(world):
    r = world.guardian_approves()
    assert r.status_code == 200 and r.json() == {"status": "deleted"}
    assert not world.elder_alive


@worlds("locked")
def test_locked_a_rejection_cannot_undo_it(world):
    r = world.guardian_rejects()
    assert r.status_code == 404
    assert not world.elder_alive  # 읽는 김에 이어서 지워졌다


@worlds("locked")
def test_locked_a_week_later_it_still_finishes(world):
    world.a_week_passes()
    assert world.elder_reads().json() == {"status": "deleted"}
    assert not world.elder_alive


@worlds("locked")
def test_locked_it_finishes_even_when_the_guardian_left(world):
    world.kit.data.elders.detach_all_from(1)
    assert world.elder_reads().json() == {"status": "deleted"}
    assert not world.elder_alive
