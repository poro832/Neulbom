"""어르신 연결 주소 — 코드 발급(보호자)과 폰 연결(열쇠 없이)."""

from __future__ import annotations

import logging

import pytest

from app.api.pairing import MAX_FAILED_ATTEMPTS
from tests.app_data_helpers import kst, make_app_kit

ISSUE = "/v1/elders/{}/pairing-code"
PAIR = "/v1/pair"
BAD_PAIR = {"detail": "연결 코드를 확인해 주세요"}


# ------------------------------------------------ 코드 발급 (보호자)


def test_a_guardian_gets_a_six_digit_code_with_an_expiry():
    kit = make_app_kit()

    response = kit.client.post(ISSUE.format(12), headers=kit.guardian_headers)

    assert response.status_code == 200
    body = response.json()
    assert len(body["code"]) == 6 and body["code"].isdigit()
    assert body["expires_at"] == "2026-10-09T09:00:00+09:00"


def test_issuing_requires_a_guardian_key():
    kit = make_app_kit()

    assert kit.client.post(ISSUE.format(12)).status_code == 401
    assert kit.client.post(ISSUE.format(12), headers=kit.elder_headers(12)).status_code == 401


def test_issuing_for_someone_elses_or_a_missing_elder_is_404_with_the_same_body():
    kit = make_app_kit()

    theirs = kit.client.post(ISSUE.format(14), headers=kit.guardian_headers)
    missing = kit.client.post(ISSUE.format(999), headers=kit.guardian_headers)

    assert theirs.status_code == missing.status_code == 404
    assert theirs.json() == missing.json() == {"detail": "등록되지 않은 어르신입니다"}


def test_issuing_never_logs_the_code(caplog):
    kit = make_app_kit()

    with caplog.at_level(logging.DEBUG):
        code = kit.client.post(ISSUE.format(12), headers=kit.guardian_headers).json()["code"]

    assert code not in caplog.text


# ------------------------------------------------ 폰 연결


def test_the_right_code_and_phone_give_an_elder_key():
    kit = make_app_kit()
    code = kit.new_pairing(12)

    response = kit.client.post(PAIR, json={"code": code, "phone": "070-1111-2222"})

    assert response.status_code == 200
    body = response.json()
    assert body["elder_name"] == "어르신 12"
    assert body["elder_key"].startswith("nle_") and len(body["elder_key"]) == 47
    # 받은 열쇠로 어르신 주소를 부를 수 있다
    me = kit.client.get("/v1/me/calls", headers={"Authorization": f"Bearer {body['elder_key']}"})
    assert me.status_code == 200


def test_the_phone_may_be_typed_without_hyphens():
    kit = make_app_kit()
    code = kit.new_pairing(12)

    assert kit.client.post(PAIR, json={"code": code, "phone": "07011112222"}).status_code == 200


def test_a_code_with_leading_zeros_works():
    kit = make_app_kit()
    from app.api.pairing import hash_code

    kit.data.pairings.issue(12, hash_code("000123"))

    assert kit.client.post(PAIR, json={"code": "000123", "phone": "070-1111-2222"}).status_code == 200


def test_a_wrong_phone_and_a_wrong_code_look_exactly_the_same():
    """다르면 '이 번호는 등록돼 있다'가 새어 나간다."""
    kit = make_app_kit()
    code = kit.new_pairing(12)
    wrong_code = "000000" if code != "000000" else "111111"

    unknown_phone = kit.client.post(PAIR, json={"code": code, "phone": "070-9999-9999"})
    wrong_code_response = kit.client.post(PAIR, json={"code": wrong_code, "phone": "070-1111-2222"})
    other_elders_phone = kit.client.post(PAIR, json={"code": code, "phone": "070-3333-4444"})

    for response in (unknown_phone, wrong_code_response, other_elders_phone):
        assert response.status_code == 401
        assert response.json() == BAD_PAIR


def test_a_used_code_cannot_be_used_again():
    kit = make_app_kit()
    code = kit.new_pairing(12)
    assert kit.client.post(PAIR, json={"code": code, "phone": "070-1111-2222"}).status_code == 200

    again = kit.client.post(PAIR, json={"code": code, "phone": "070-1111-2222"})

    assert again.status_code == 401 and again.json() == BAD_PAIR


def test_five_wrong_codes_lock_even_the_right_one_and_a_new_code_unlocks():
    kit = make_app_kit()
    code = kit.new_pairing(12)
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(MAX_FAILED_ATTEMPTS):
        assert kit.client.post(PAIR, json={"code": wrong, "phone": "070-1111-2222"}).status_code == 401

    locked = kit.client.post(PAIR, json={"code": code, "phone": "070-1111-2222"})
    assert locked.status_code == 401 and locked.json() == BAD_PAIR

    fresh = kit.new_pairing(12)
    assert kit.client.post(PAIR, json={"code": fresh, "phone": "070-1111-2222"}).status_code == 200


def test_an_expired_code_is_refused():
    kit = make_app_kit()
    code = kit.new_pairing(12)

    kit.clock.now += 24 * 3600 + 1

    assert kit.client.post(PAIR, json={"code": code, "phone": "070-1111-2222"}).status_code == 401


def test_connecting_again_revokes_the_previous_phones_key():
    kit = make_app_kit()
    first = kit.client.post(PAIR, json={"code": kit.new_pairing(12), "phone": "070-1111-2222"}).json()["elder_key"]
    second = kit.client.post(PAIR, json={"code": kit.new_pairing(12), "phone": "070-1111-2222"}).json()["elder_key"]

    old = kit.client.get("/v1/me/calls", headers={"Authorization": f"Bearer {first}"})
    new = kit.client.get("/v1/me/calls", headers={"Authorization": f"Bearer {second}"})

    assert old.status_code == 401
    assert new.status_code == 200


@pytest.mark.parametrize(
    "body",
    [
        {"code": "12345", "phone": "070-1111-2222"},
        {"code": "1234567", "phone": "070-1111-2222"},
        {"code": "12a456", "phone": "070-1111-2222"},
        {"code": "123456", "phone": ""},
        {"code": 123456, "phone": "070-1111-2222"},
        {},
    ],
)
def test_a_malformed_pair_request_is_422_never_500(body):
    kit = make_app_kit()

    assert kit.client.post(PAIR, json=body).status_code == 422


def test_pairing_never_logs_the_code_or_the_full_key(caplog):
    kit = make_app_kit()
    code = kit.new_pairing(12)

    with caplog.at_level(logging.DEBUG):
        key = kit.client.post(PAIR, json={"code": code, "phone": "070-1111-2222"}).json()["elder_key"]

    assert code not in caplog.text and key not in caplog.text
    assert "070-1111-2222" not in caplog.text and "07011112222" not in caplog.text


class ExplodingPairings:
    def issue(self, elder_id, code_hash):
        raise RuntimeError("DB 끊김")

    def redeem(self, elder_id, code_hash):
        raise RuntimeError("DB 끊김")


def test_a_broken_pairing_store_is_503_not_open():
    kit = make_app_kit()
    kit.data.pairings = ExplodingPairings()

    assert kit.client.post(ISSUE.format(12), headers=kit.guardian_headers).status_code == 503
    assert kit.client.post(PAIR, json={"code": "123456", "phone": "070-1111-2222"}).status_code == 503
