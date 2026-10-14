"""어르신 먼저 가입 + 연결 코드 — 가입, 코드 발급, 보호자 미리보기·연결."""

from __future__ import annotations

import logging

from app.api.app_data import iso_kst
from app.api.invites import hash_invite_code
from app.api.link_codes import LINK_CODE_TTL_SECONDS
from app.api.rate_limit import FailureLimiter
from tests.app_data_helpers import make_app_kit

SIGNUP = "/v1/elders/signup"
LINK_CODE = "/v1/me/link-code"
PREVIEW = "/v1/guardian/link/preview"
LINK = "/v1/guardian/link"
BAD_LINK = {"detail": "연결 코드를 확인해 주세요"}
PHONE = "010-9999-1111"


def sign_up(kit, *, name="홍길동", phone=PHONE, agreed=True):
    return kit.client.post(SIGNUP, json={"name": name, "phone": phone, "agreed": agreed})


def elder_headers_of(response) -> dict:
    return {"Authorization": f"Bearer {response.json()['elder_key']}"}


def new_link_code(kit, headers) -> str:
    response = kit.client.post(LINK_CODE, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["code"]


def unlinked_elder(kit):
    """가입한 어르신의 (열쇠 머리글, 연결 코드)."""
    headers = elder_headers_of(sign_up(kit))
    return headers, new_link_code(kit, headers)


def wrong_code(code: str) -> str:
    return "00000000" if code != "00000000" else "11111111"


def pending_guardian_kit():
    """가입만 하고 운영자 확인을 못 받은 보호자의 열쇠가 있는 kit."""
    from app.api.passwords import NO_LOGIN

    kit = make_app_kit()
    for n in (1, 2):
        kit.data.accounts.create("자리", f"placeholder{n}@no-login.invalid", "010-0", NO_LOGIN)
    signup = kit.client.post(
        "/v1/guardian/signup",
        json={"name": "김보호", "email": "kim@example.com", "phone": "010-1111-2222", "password": "correct-horse-1"},
    ).json()
    return kit, {"Authorization": f"Bearer {signup['key']}"}


# ------------------------------------------------ 어르신 가입


def test_an_elder_can_sign_up_without_a_guardian_and_stays_unlinked():
    kit = make_app_kit()

    response = sign_up(kit)

    assert response.status_code == 200
    assert response.json()["status"] == "unlinked"
    status = kit.client.get("/v1/me/status", headers=elder_headers_of(response)).json()
    assert status == {"status": "unlinked", "name": "홍길동", "share_agreed": True}


def test_signup_needs_the_agreement():
    kit = make_app_kit()

    assert sign_up(kit, agreed=False).status_code == 400


def test_signup_refuses_a_number_that_is_already_registered():
    kit = make_app_kit()

    response = sign_up(kit, phone="070-1111-2222")  # 어르신 12

    assert response.status_code == 409
    assert response.json() == {"detail": "이미 등록된 번호예요"}


def test_signup_attempts_are_limited():
    kit = make_app_kit()
    kit.data.elder_signup_attempts = FailureLimiter(limit=2)

    assert sign_up(kit, phone="010-9999-0001").status_code == 200
    assert sign_up(kit, phone="010-9999-0002").status_code == 200
    assert sign_up(kit, phone="010-9999-0003").status_code == 429


def test_an_unlinked_elder_is_kept_out_of_the_endpoints_that_need_a_guardian():
    kit = make_app_kit()
    headers = elder_headers_of(sign_up(kit))

    response = kit.client.get("/v1/me/contacts", headers=headers)

    assert response.status_code == 403
    assert response.json() == {"detail": "보호자 연결을 기다리고 있어요"}


# ------------------------------------------------ 연결 코드 발급


def test_a_link_code_is_eight_digits_and_lasts_a_day():
    kit = make_app_kit()
    headers = elder_headers_of(sign_up(kit))

    response = kit.client.post(LINK_CODE, headers=headers)

    body = response.json()
    assert response.status_code == 200
    assert len(body["code"]) == 8 and body["code"].isdigit()
    assert body["expires_at"] == iso_kst(kit.clock.now + LINK_CODE_TTL_SECONDS)


def test_a_new_link_code_revokes_the_old_one():
    kit = make_app_kit()
    headers = elder_headers_of(sign_up(kit))
    first = new_link_code(kit, headers)
    second = new_link_code(kit, headers)

    assert kit.client.post(PREVIEW, json={"code": first}, headers=kit.guardian_headers).status_code == 401
    assert kit.client.post(PREVIEW, json={"code": second}, headers=kit.guardian_headers).status_code == 200


def test_issuing_needs_an_elder_key():
    kit = make_app_kit()

    assert kit.client.post(LINK_CODE).status_code == 401
    assert kit.client.post(LINK_CODE, headers=kit.guardian_headers).status_code == 401


def test_an_elder_who_already_has_a_guardian_cannot_get_a_link_code():
    kit = make_app_kit()

    response = kit.client.post(LINK_CODE, headers=kit.elder_headers(12))

    assert response.status_code == 409
    assert response.json() == {"detail": "이미 보호자가 연결돼 있어요"}


# ------------------------------------------------ 보호자 미리보기와 연결


def test_preview_shows_the_name_and_a_masked_number_and_changes_nothing():
    kit = make_app_kit()
    headers, code = unlinked_elder(kit)

    response = kit.client.post(PREVIEW, json={"code": code}, headers=kit.guardian_headers)

    assert response.status_code == 200
    assert response.json() == {"name": "홍길동", "phone_masked": "010-****-1111"}
    assert kit.client.get("/v1/me/status", headers=headers).json()["status"] == "unlinked"
    assert kit.data.links.find(hash_invite_code(code)) is not None


def test_linking_connects_the_elder_and_records_consent_in_one_step():
    kit = make_app_kit()
    headers, code = unlinked_elder(kit)

    response = kit.client.post(LINK, json={"code": code}, headers=kit.guardian_headers)

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "홍길동" and body["status"] == "active"
    access = kit.data.elders.get(body["elder_id"])
    assert access.guardian_id == 1 and access.consenting
    assert kit.client.get("/v1/me/status", headers=headers).json()["status"] == "active"
    assert "홍길동" in [ref.name for ref in kit.data.elders.elders_of(1)]


def test_a_link_code_works_once():
    kit = make_app_kit()
    _, code = unlinked_elder(kit)
    kit.client.post(LINK, json={"code": code}, headers=kit.guardian_headers)

    again = kit.client.post(LINK, json={"code": code}, headers=kit.guardian_headers)

    assert again.status_code == 401 and again.json() == BAD_LINK


def test_wrong_expired_and_used_codes_get_the_same_answer():
    kit = make_app_kit()
    headers, code = unlinked_elder(kit)
    wrong = kit.client.post(PREVIEW, json={"code": wrong_code(code)}, headers=kit.guardian_headers)
    kit.clock.now += LINK_CODE_TTL_SECONDS + 1
    expired = kit.client.post(PREVIEW, json={"code": code}, headers=kit.guardian_headers)

    assert (wrong.status_code, wrong.json()) == (401, BAD_LINK)
    assert (expired.status_code, expired.json()) == (401, BAD_LINK)


def test_failed_attempts_are_limited_even_for_the_right_code():
    kit = make_app_kit()
    kit.data.link_attempts = FailureLimiter(limit=2)
    _, code = unlinked_elder(kit)
    for _ in range(2):
        kit.client.post(PREVIEW, json={"code": wrong_code(code)}, headers=kit.guardian_headers)

    response = kit.client.post(PREVIEW, json={"code": code}, headers=kit.guardian_headers)

    assert response.status_code == 429


def test_a_guardian_waiting_for_the_operator_cannot_preview_or_link_and_the_code_survives():
    kit, headers = pending_guardian_kit()
    _, code = unlinked_elder(kit)

    preview = kit.client.post(PREVIEW, json={"code": code}, headers=headers)
    link = kit.client.post(LINK, json={"code": code}, headers=headers)

    assert preview.status_code == 403 and link.status_code == 403
    assert preview.json() == {"detail": "운영자 확인 후 사용할 수 있어요"}
    assert kit.data.links.find(hash_invite_code(code)) is not None


def test_linking_stops_at_the_per_guardian_limit_and_keeps_the_code(monkeypatch):
    import app.api.app_data as app_data

    monkeypatch.setattr(app_data, "MAX_ELDERS_PER_GUARDIAN", 2)  # 보호자 1은 어르신 12·13이 있다
    kit = make_app_kit()
    _, code = unlinked_elder(kit)

    response = kit.client.post(LINK, json={"code": code}, headers=kit.guardian_headers)

    assert response.status_code == 409
    assert response.json() == {"detail": "더 이상 어르신을 연결할 수 없어요"}
    assert kit.data.links.find(hash_invite_code(code)) is not None


def test_link_and_preview_need_a_guardian_key():
    kit = make_app_kit()
    _, code = unlinked_elder(kit)

    for path in (PREVIEW, LINK):
        assert kit.client.post(path, json={"code": code}).status_code == 401
        assert kit.client.post(path, json={"code": code}, headers=kit.elder_headers(12)).status_code == 401


def test_bad_code_shapes_are_rejected():
    kit = make_app_kit()

    for code in ("1234567", "123456789", "abcdefgh"):
        assert kit.client.post(PREVIEW, json={"code": code}, headers=kit.guardian_headers).status_code == 422


def test_the_whole_flow_never_logs_codes_numbers_or_names(caplog):
    kit = make_app_kit()

    with caplog.at_level(logging.DEBUG):
        headers, code = unlinked_elder(kit)
        kit.client.post(PREVIEW, json={"code": wrong_code(code)}, headers=kit.guardian_headers)
        kit.client.post(PREVIEW, json={"code": code}, headers=kit.guardian_headers)
        kit.client.post(LINK, json={"code": code}, headers=kit.guardian_headers)

    for secret in (code, "010-9999-1111", "01099991111", "홍길동"):
        assert secret not in caplog.text


# ------------------------------------------------ 가입 도중 저장소 오류


def _break(monkeypatch, target, name):
    def boom(*args, **kwargs):
        raise RuntimeError("저장소 오류")

    monkeypatch.setattr(target, name, boom)


def test_a_failed_key_save_rolls_the_signup_back_so_a_retry_works(monkeypatch):
    kit = make_app_kit()
    with monkeypatch.context() as broken:
        _break(broken, kit.data.elder_keys, "replace")
        assert sign_up(kit).status_code == 503

    retry = sign_up(kit)

    assert retry.status_code == 200
    assert retry.json()["status"] == "unlinked"


def test_a_failed_share_agreement_rolls_the_signup_back_so_a_retry_works(monkeypatch):
    kit = make_app_kit()
    with monkeypatch.context() as broken:
        _break(broken, kit.data.content, "agree_share")
        assert sign_up(kit).status_code == 503

    assert sign_up(kit).status_code == 200


def test_a_rolled_back_signup_leaves_no_row_and_logs_only_the_id(monkeypatch, caplog):
    kit = make_app_kit()
    before = set(kit.data.elders._entries)
    with monkeypatch.context() as broken, caplog.at_level(logging.DEBUG):
        _break(broken, kit.data.elder_keys, "replace")
        assert sign_up(kit).status_code == 503

    assert set(kit.data.elders._entries) == before
    for secret in (PHONE, "01099991111", "홍길동"):
        assert secret not in caplog.text
