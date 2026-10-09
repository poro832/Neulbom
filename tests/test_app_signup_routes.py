"""보호자 코드로 어르신 가입 — 개인 코드, 가입, 승인, 거절, 내 상태."""

from __future__ import annotations

import logging

import pytest

from app.api.rate_limit import FailureLimiter
from tests.app_data_helpers import make_app_kit

INVITE = "/v1/guardian/invite"
SIGNUP = "/v1/signup"
BAD_SIGNUP = {"detail": "가입 코드를 확인해 주세요"}


def body(code, *, name="홍길동", phone="010-9999-1111", agreed=True):
    return {"code": code, "name": name, "phone": phone, "agreed": agreed}


def sign_up(kit, **kw):
    return kit.client.post(SIGNUP, json=body(kit.issue_invite(), **kw))


def wrong_code(code):
    return "00000000" if code != "00000000" else "11111111"


# ------------------------------------------------ 개인 코드 발급


def test_a_guardian_gets_an_eight_digit_code():
    kit = make_app_kit()

    response = kit.client.post(INVITE, headers=kit.guardian_headers)

    assert response.status_code == 200
    code = response.json()["code"]
    assert len(code) == 8 and code.isdigit()


def test_a_new_code_revokes_the_old_one():
    kit = make_app_kit()
    first = kit.client.post(INVITE, headers=kit.guardian_headers).json()["code"]
    second = kit.client.post(INVITE, headers=kit.guardian_headers).json()["code"]

    assert kit.client.post(SIGNUP, json=body(first)).status_code == 401
    assert kit.client.post(SIGNUP, json=body(second)).status_code == 200


def test_issuing_a_code_needs_a_guardian_key():
    kit = make_app_kit()

    assert kit.client.post(INVITE).status_code == 401
    assert kit.client.post(INVITE, headers=kit.elder_headers(12)).status_code == 401


def test_issuing_never_logs_the_code(caplog):
    kit = make_app_kit()

    with caplog.at_level(logging.DEBUG):
        code = kit.client.post(INVITE, headers=kit.guardian_headers).json()["code"]

    assert code not in caplog.text


# ------------------------------------------------ 가입


def test_a_signup_creates_a_pending_elder_without_consent():
    """가입은 전화를 거는 허락이 아니다. consent_at은 보호자 승인에서만 채워진다."""
    kit = make_app_kit()

    response = sign_up(kit)

    assert response.status_code == 200
    result = response.json()
    assert result["status"] == "pending"
    assert result["elder_key"].startswith("nle_") and len(result["elder_key"]) == 47
    pending = [e for e in kit.data.elders.elders_of(1) if e.status == "pending"]
    assert len(pending) == 1 and pending[0].name == "홍길동"
    access = kit.data.elders.get(pending[0].elder_id)
    assert access.consenting is False and access.agreed is True


def test_a_pending_elder_appears_in_the_guardians_list_with_the_phone():
    kit = make_app_kit()
    sign_up(kit, phone="010-9999-1111")

    elders = kit.client.get("/v1/guardian/elders", headers=kit.guardian_headers).json()["elders"]

    pending = [e for e in elders if e["status"] == "pending"]
    assert len(pending) == 1 and pending[0]["phone"] == "010-9999-1111"
    assert all(e["phone"] is None for e in elders if e["status"] != "pending")


def test_the_new_elder_can_read_only_its_status_while_pending():
    kit = make_app_kit()
    headers = {"Authorization": f"Bearer {sign_up(kit).json()['elder_key']}"}

    status = kit.client.get("/v1/me/status", headers=headers)
    assert status.status_code == 200
    assert status.json() == {"status": "pending", "name": "홍길동"}

    waiting = {"detail": "보호자 승인을 기다리고 있어요"}
    for method, path, kwargs in (
        ("get", "/v1/me/calls", {}),
        ("get", "/v1/me/contacts", {}),
        ("post", "/v1/me/contacts", {"json": {"name": "가", "phone": "111-1111"}}),
        ("delete", "/v1/me/contacts/1", {}),
    ):
        response = getattr(kit.client, method)(path, headers=headers, **kwargs)
        assert response.status_code == 403, path
        assert response.json() == waiting


def test_not_agreeing_is_refused_and_creates_nothing():
    kit = make_app_kit()

    response = sign_up(kit, agreed=False)

    assert response.status_code == 400
    assert response.json() == {"detail": "안부 전화를 받는 데 동의해야 가입할 수 있어요"}
    assert [e for e in kit.data.elders.elders_of(1) if e.status == "pending"] == []


def test_every_code_failure_looks_exactly_the_same():
    kit = make_app_kit()
    code = kit.issue_invite()
    old = kit.issue_invite()  # 위 코드를 폐기한다
    for n in range(5):
        kit.data.elders.create_pending(
            guardian_id=1, name=f"대기{n}", phone=f"010-1000-000{n}", max_pending=5
        )

    unknown = kit.client.post(SIGNUP, json=body(wrong_code(old)))
    revoked = kit.client.post(SIGNUP, json=body(code))
    over_limit = kit.client.post(SIGNUP, json=body(old, phone="010-7777-7777"))

    for response in (unknown, revoked, over_limit):
        assert response.status_code == 401
        assert response.json() == BAD_SIGNUP


def test_a_number_already_registered_is_409_in_any_format():
    kit = make_app_kit()

    same = sign_up(kit, phone="070 1111 2222")      # 어르신 12번 번호
    again = sign_up(kit, phone="07011112222")

    for response in (same, again):
        assert response.status_code == 409
        assert response.json() == {"detail": "이미 등록된 번호예요"}


def test_a_guardian_holds_at_most_five_pending_elders():
    kit = make_app_kit()
    code = kit.issue_invite()

    codes = [
        kit.client.post(SIGNUP, json=body(code, phone=f"010-2000-000{n}")).status_code
        for n in range(6)
    ]

    assert codes == [200] * 5 + [401]


def test_too_many_wrong_codes_block_even_the_right_one_for_a_while():
    kit = make_app_kit()
    kit.data.signup_limiter = FailureLimiter(limit=3, clock=kit.clock)
    code = kit.issue_invite()
    for _ in range(3):
        assert kit.client.post(SIGNUP, json=body(wrong_code(code))).status_code == 401

    blocked = kit.client.post(SIGNUP, json=body(code))
    assert blocked.status_code == 429
    assert blocked.json() == {"detail": "잠시 뒤에 다시 해 주세요"}

    kit.clock.now += 61
    assert kit.client.post(SIGNUP, json=body(code)).status_code == 200


def test_right_codes_never_count_against_the_limit():
    kit = make_app_kit()
    kit.data.signup_limiter = FailureLimiter(limit=2, clock=kit.clock)
    code = kit.issue_invite()

    results = [
        kit.client.post(SIGNUP, json=body(code, phone=f"010-3000-000{n}")).status_code
        for n in range(4)
    ]

    assert results == [200] * 4


@pytest.mark.parametrize(
    "payload",
    [
        {"code": "1234567", "name": "가", "phone": "010-1234-5678", "agreed": True},
        {"code": "123456789", "name": "가", "phone": "010-1234-5678", "agreed": True},
        {"code": "1234567a", "name": "가", "phone": "010-1234-5678", "agreed": True},
        {"code": "12345678", "name": "", "phone": "010-1234-5678", "agreed": True},
        {"code": "12345678", "name": "가" * 31, "phone": "010-1234-5678", "agreed": True},
        {"code": "12345678", "name": "가", "phone": "abc", "agreed": True},
        {"code": "12345678", "name": "가", "phone": "1234", "agreed": True},
        {"code": "12345678", "name": "가", "phone": "010-1234-5678"},
        {},
    ],
)
def test_a_malformed_signup_is_422_never_500(payload):
    kit = make_app_kit()

    assert kit.client.post(SIGNUP, json=payload).status_code == 422


def test_signup_never_logs_the_code_the_phone_or_the_key(caplog):
    kit = make_app_kit()
    code = kit.issue_invite()

    with caplog.at_level(logging.DEBUG):
        key = kit.client.post(SIGNUP, json=body(code, phone="010-9999-1111")).json()["elder_key"]

    assert code not in caplog.text and key not in caplog.text
    assert "010-9999-1111" not in caplog.text and "01099991111" not in caplog.text


# ------------------------------------------------ 승인과 거절


def pending_id(kit):
    return next(e.elder_id for e in kit.data.elders.elders_of(1) if e.status == "pending")


def test_approving_makes_the_elder_active_and_opens_the_elder_routes():
    kit = make_app_kit()
    key = sign_up(kit).json()["elder_key"]
    headers = {"Authorization": f"Bearer {key}"}
    elder_id = pending_id(kit)

    approved = kit.client.post(f"/v1/elders/{elder_id}/approve", headers=kit.guardian_headers)

    assert approved.status_code == 200 and approved.json() == {"status": "active"}
    assert kit.data.elders.get(elder_id).consenting is True
    assert kit.client.get("/v1/me/status", headers=headers).json()["status"] == "active"
    assert kit.client.get("/v1/me/calls", headers=headers).status_code == 200
    assert kit.client.get("/v1/me/contacts", headers=headers).status_code == 200


def test_approve_and_reject_are_404_for_someone_elses_or_a_missing_elder():
    kit = make_app_kit()
    sign_up(kit)

    for action in ("approve", "reject"):
        theirs = kit.client.post(f"/v1/elders/14/{action}", headers=kit.guardian_headers)
        missing = kit.client.post(f"/v1/elders/999/{action}", headers=kit.guardian_headers)
        assert theirs.status_code == missing.status_code == 404
        assert theirs.json() == missing.json() == {"detail": "등록되지 않은 어르신입니다"}


def test_approving_or_rejecting_an_elder_that_is_not_pending_is_409_and_changes_nothing():
    kit = make_app_kit()

    for action in ("approve", "reject"):
        response = kit.client.post(f"/v1/elders/12/{action}", headers=kit.guardian_headers)
        assert response.status_code == 409
        assert response.json() == {"detail": "승인 대기 중인 어르신이 아니에요"}
    assert kit.data.elders.get(12).status == "active"


def test_approve_and_reject_need_a_guardian_key():
    kit = make_app_kit()
    sign_up(kit)
    elder_id = pending_id(kit)

    for action in ("approve", "reject"):
        assert kit.client.post(f"/v1/elders/{elder_id}/{action}").status_code == 401
        assert kit.client.post(
            f"/v1/elders/{elder_id}/{action}", headers=kit.elder_headers(12)
        ).status_code == 401
    assert kit.data.elders.get(elder_id).status == "pending"


def test_rejecting_deletes_the_elder_and_kills_the_phones_key():
    kit = make_app_kit()
    key = sign_up(kit).json()["elder_key"]
    headers = {"Authorization": f"Bearer {key}"}
    elder_id = pending_id(kit)

    rejected = kit.client.post(f"/v1/elders/{elder_id}/reject", headers=kit.guardian_headers)

    assert rejected.status_code == 200 and rejected.json() == {"status": "rejected"}
    assert kit.data.elders.get(elder_id) is None
    # 열쇠 행은 어르신이 지워질 때 함께 지워지지만, 메모리 저장소는 어르신 조회로 거른다.
    assert kit.client.get("/v1/me/status", headers=headers).status_code in (401, 404)


# ------------------------------------------------ 닫힌 쪽이 기본


def test_me_status_needs_an_elder_key():
    kit = make_app_kit()

    assert kit.client.get("/v1/me/status").status_code == 401
    assert kit.client.get("/v1/me/status", headers=kit.guardian_headers).status_code == 401


class ExplodingInvites:
    def issue(self, guardian_id, code_hash):
        raise RuntimeError("DB 끊김")

    def find_guardian(self, code_hash):
        raise RuntimeError("DB 끊김")


def test_a_broken_invite_store_is_503_not_open():
    kit = make_app_kit()
    kit.data.invites = ExplodingInvites()

    assert kit.client.post(INVITE, headers=kit.guardian_headers).status_code == 503
    assert kit.client.post(SIGNUP, json=body("12345678")).status_code == 503
