"""어르신이 폰을 바꿨을 때 보호자가 새 전화번호로 고친다(어르신 열쇠는 모두 폐기된다)."""

from __future__ import annotations

import logging

from app.api.elder_auth import generate_elder_key
from tests.app_data_helpers import make_app_kit

PHONE = "/v1/elders/{}/phone"
NO_ELDER = {"detail": "등록되지 않은 어르신입니다"}
NEED_KEY = {"detail": "열쇠가 필요합니다"}
PHONE_USED = {"detail": "이미 등록된 번호예요"}


def put(kit, phone, elder_id=12, headers=None):
    return kit.client.put(
        PHONE.format(elder_id),
        json={"phone": phone},
        headers=kit.guardian_headers if headers is None else headers,
    )


def test_the_guardian_reads_and_changes_the_elders_phone():
    kit = make_app_kit()

    assert kit.client.get(PHONE.format(12), headers=kit.guardian_headers).json() == {"phone": "070-1111-2222"}
    response = put(kit, "010-7777-1212")

    assert response.status_code == 200 and response.json()["phone"] == "010-7777-1212"
    assert kit.client.get(PHONE.format(12), headers=kit.guardian_headers).json() == {"phone": "010-7777-1212"}
    assert kit.data.elders.find_by_phone("070-1111-2222") is None
    assert kit.data.elders.phone_of(13) == "070-3333-4444"


def test_the_old_phones_key_stops_working_after_the_number_changes():
    kit = make_app_kit()
    new = generate_elder_key()
    kit.data.elder_keys.replace(elder_id=12, key_prefix=new.key_prefix, key_hash=new.key_hash)
    elder_headers = {"Authorization": f"Bearer {new.key}"}
    assert kit.client.get("/v1/me/status", headers=elder_headers).status_code == 200

    assert put(kit, "010-7777-1212").status_code == 200

    assert kit.client.get("/v1/me/status", headers=elder_headers).status_code == 401


def test_a_number_another_elder_uses_is_refused_and_nothing_changes():
    kit = make_app_kit()

    response = put(kit, "070-3333-4444")

    assert response.status_code == 409 and response.json() == PHONE_USED
    assert kit.data.elders.phone_of(12) == "070-1111-2222"


def test_another_guardians_elder_is_not_found():
    kit = make_app_kit()

    response = put(kit, "010-7777-1212", elder_id=14)

    assert response.status_code == 404 and response.json() == NO_ELDER
    assert kit.client.get(PHONE.format(14), headers=kit.guardian_headers).status_code == 404
    assert kit.data.elders.phone_of(14) == "070-5555-6666"


def test_without_a_key_nothing_is_read_or_changed():
    kit = make_app_kit()

    assert kit.client.get(PHONE.format(12)).status_code == 401
    response = kit.client.put(PHONE.format(12), json={"phone": "010-7777-1212"})
    assert response.status_code == 401 and response.json() == NEED_KEY
    assert kit.data.elders.phone_of(12) == "070-1111-2222"


def test_a_malformed_number_is_refused():
    kit = make_app_kit()

    for bad in ["abc", "123", "010-12-3"]:
        assert put(kit, bad).status_code == 422
    assert kit.data.elders.phone_of(12) == "070-1111-2222"


def test_the_log_has_ids_and_counts_but_no_phone_number(caplog):
    kit = make_app_kit()

    with caplog.at_level(logging.INFO):
        put(kit, "010-7777-1212")

    text = " ".join(record.getMessage() for record in caplog.records)
    assert "어르신 전화번호를 바꿨다" in text
    assert "7777" not in text and "1111-2222" not in text
