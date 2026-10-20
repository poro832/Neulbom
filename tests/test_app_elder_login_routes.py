"""새 폰 로그인 — 보호자가 어르신 번호를 고치면 새 폰이 24시간 안에 번호만으로 한 번 들어올 수 있다."""

from __future__ import annotations

import logging

from app.api.app_data import PHONE_CLAIM_SECONDS
from app.api.rate_limit import FailureLimiter
from tests.app_data_helpers import make_app_kit

LOGIN = "/v1/elders/login"
BAD = {"detail": "이 폰으로는 로그인할 수 없어요. 보호자에게 어르신 관리에서 번호를 확인해 달라고 부탁해 주세요"}
NEW_PHONE = "010-7777-1212"


def change_phone(kit, phone=NEW_PHONE, elder_id=12):
    return kit.client.put(
        f"/v1/elders/{elder_id}/phone", json={"phone": phone}, headers=kit.guardian_headers
    )


def login(kit, phone=NEW_PHONE):
    return kit.client.post(LOGIN, json={"phone": phone})


def test_after_the_guardian_changes_the_number_the_new_phone_gets_a_key_with_the_number_alone():
    kit = make_app_kit()
    assert change_phone(kit).status_code == 200

    response = login(kit)

    assert response.status_code == 200
    body = response.json()
    assert body["elder_name"] == "어르신 12"
    headers = {"Authorization": f"Bearer {body['elder_key']}"}
    assert kit.client.get("/v1/me/status", headers=headers).status_code == 200


def test_the_window_closes_after_the_first_login():
    kit = make_app_kit()
    change_phone(kit)
    first = login(kit)

    second = login(kit)

    assert first.status_code == 200
    assert second.status_code == 401 and second.json() == BAD
    # 첫 로그인으로 받은 열쇠는 계속 쓴다
    headers = {"Authorization": f"Bearer {first.json()['elder_key']}"}
    assert kit.client.get("/v1/me/status", headers=headers).status_code == 200


def test_the_window_closes_after_24_hours():
    kit = make_app_kit()
    change_phone(kit)
    kit.clock.now += PHONE_CLAIM_SECONDS + 1

    response = login(kit)

    assert response.status_code == 401 and response.json() == BAD


def test_still_open_just_before_24_hours():
    kit = make_app_kit()
    change_phone(kit)
    kit.clock.now += PHONE_CLAIM_SECONDS - 60

    assert login(kit).status_code == 200


def test_a_number_the_guardian_never_changed_cannot_log_in():
    kit = make_app_kit()

    # 어르신 13의 번호는 그대로이고 열린 적이 없다
    response = login(kit, "070-3333-4444")

    assert response.status_code == 401 and response.json() == BAD


def test_unknown_numbers_and_closed_windows_get_the_same_answer():
    kit = make_app_kit()
    change_phone(kit)
    login(kit)  # 창을 닫는다

    unknown = login(kit, "010-1234-5678")
    closed = login(kit)

    assert (unknown.status_code, unknown.json()) == (closed.status_code, closed.json()) == (401, BAD)


def test_the_old_number_cannot_log_in_after_it_was_changed():
    kit = make_app_kit()
    change_phone(kit)

    assert login(kit, "070-1111-2222").status_code == 401


def test_changing_to_the_same_number_again_reopens_the_window():
    kit = make_app_kit()
    change_phone(kit)
    login(kit)
    kit.clock.now += 3600

    again = change_phone(kit)  # 같은 번호로 다시 저장 = 새 폰 로그인 다시 열기

    assert again.status_code == 200
    assert login(kit).status_code == 200


def test_the_phone_change_tells_the_guardian_until_when_the_new_phone_can_log_in():
    kit = make_app_kit()

    body = change_phone(kit).json()

    assert body["phone"] == NEW_PHONE
    assert body["new_phone_login_until"].startswith("2026-10-09")  # 시계는 2026-10-08 09:00 KST + 24시간


def test_the_old_phones_key_is_gone_once_the_number_changes():
    kit = make_app_kit()
    old = kit.elder_headers(12)
    assert kit.client.get("/v1/me/status", headers=old).status_code == 200

    change_phone(kit)

    assert kit.client.get("/v1/me/status", headers=old).status_code == 401


def test_login_attempts_are_limited():
    kit = make_app_kit()
    kit.data.elder_login_attempts = FailureLimiter(limit=2)
    change_phone(kit)

    assert login(kit, "010-0000-0001").status_code == 401
    assert login(kit, "010-0000-0002").status_code == 401
    assert login(kit).status_code == 429  # 맞는 번호도 한도에 걸리면 막힌다


def test_bad_number_shapes_are_rejected():
    kit = make_app_kit()

    for phone in ("abc", "123", ""):
        assert login(kit, phone).status_code == 422


def test_another_guardians_elder_cannot_get_a_window():
    kit = make_app_kit()

    response = change_phone(kit, "010-5555-0000", elder_id=14)  # 어르신 14는 보호자 2의 어르신

    assert response.status_code == 404
    assert login(kit, "010-5555-0000").status_code == 401


def test_the_log_has_ids_but_no_numbers(caplog):
    kit = make_app_kit()

    with caplog.at_level(logging.DEBUG):
        change_phone(kit)
        login(kit)
        login(kit)

    for secret in ("7777", "1212", "1111-2222", "어르신 12"):
        assert secret not in caplog.text
