"""보호자 폰 등록 — 로그인한 열쇠에 묶이고, 폐기된 열쇠의 폰은 푸시를 못 받는다 (설계: 푸시 알림)."""

from __future__ import annotations

from app.api.devices import InMemoryDeviceStore
from tests.app_data_helpers import make_app_kit

REGISTER = "/v1/guardian/devices"
UNREGISTER = "/v1/guardian/devices/unregister"
T1, T2 = "token-aaaaaaaaaaaaaaaaaaaa", "token-bbbbbbbbbbbbbbbbbbbb"


def kit_with_devices():
    kit = make_app_kit()
    kit.data.devices = InMemoryDeviceStore(is_key_active=kit.data.guardian_auth.store.is_active)
    return kit


def test_register_stores_the_token_for_the_guardian():
    kit = kit_with_devices()
    r = kit.client.post(REGISTER, json={"token": T1}, headers=kit.guardian_headers)
    assert r.status_code == 204
    assert kit.data.devices.tokens_for(1) == [T1]


def test_register_needs_a_key_and_a_plausible_token():
    kit = kit_with_devices()
    assert kit.client.post(REGISTER, json={"token": T1}).status_code == 401
    assert kit.client.post(REGISTER, json={"token": "short"}, headers=kit.guardian_headers).status_code == 422
    assert kit.client.post(REGISTER, json={"token": "x" * 5000}, headers=kit.guardian_headers).status_code == 422
    assert kit.client.post(REGISTER, json={"token": "x" * 513}, headers=kit.guardian_headers).status_code == 422
    assert kit.client.post(REGISTER, json={"token": "x" * 512}, headers=kit.guardian_headers).status_code == 204
    assert kit.data.devices.tokens_for(1) == ["x" * 512]


def test_unregister_removes_only_the_callers_own_token_and_always_204():
    kit = kit_with_devices()
    kit.client.post(REGISTER, json={"token": T1}, headers=kit.guardian_headers)
    from app.api.guardian_auth import generate_key

    other = generate_key()  # 보호자 2의 (폐기되지 않은) 열쇠
    kit.data.guardian_auth.store.add(guardian_id=2, label="폰", key_prefix=other.key_prefix, key_hash=other.key_hash)
    kit.data.devices.register(2, other.key_hash, T2)  # 보호자 2의 폰

    mine = kit.client.post(UNREGISTER, json={"token": T1}, headers=kit.guardian_headers)
    theirs = kit.client.post(UNREGISTER, json={"token": T2}, headers=kit.guardian_headers)
    nobody = kit.client.post(UNREGISTER, json={"token": "token-zzzzzzzzzzzzzzzzzzzz"}, headers=kit.guardian_headers)

    assert (mine.status_code, theirs.status_code, nobody.status_code) == (204, 204, 204)
    assert kit.data.devices.tokens_for(1) == []
    assert kit.data.devices.tokens_for(2) == [T2]  # 남의 토큰은 그대로


def test_unregister_needs_a_key():
    kit = kit_with_devices()
    assert kit.client.post(UNREGISTER, json={"token": T1}).status_code == 401


def test_logout_removes_that_keys_phones_only():
    from app.api.guardian_auth import generate_key, hash_key

    kit = kit_with_devices()
    other = generate_key()
    kit.data.guardian_auth.store.add(guardian_id=1, label="다른 폰", key_prefix=other.key_prefix, key_hash=other.key_hash)
    kit.client.post(REGISTER, json={"token": T1}, headers=kit.guardian_headers)
    kit.client.post(REGISTER, json={"token": T2}, headers={"Authorization": f"Bearer {other.key}"})

    assert kit.client.post("/v1/guardian/logout", headers=kit.guardian_headers).status_code == 204

    assert kit.data.devices.tokens_for(1) == [T2]


def test_a_revoked_key_stops_its_phone_from_being_listed():
    from app.api.guardian_auth import hash_key

    kit = kit_with_devices()
    kit.client.post(REGISTER, json={"token": T1}, headers=kit.guardian_headers)
    key_hash = hash_key(kit.guardian_headers["Authorization"].split()[1])
    kit.data.guardian_auth.store.revoke_hash(key_hash)  # 로그아웃 말고 다른 경로(운영 도구 등)로 폐기
    assert kit.data.devices.tokens_for(1) == []


def test_logout_still_succeeds_when_the_device_store_is_broken():
    class Broken:
        def remove_for_key(self, key_hash):
            raise RuntimeError("db down")

    kit = make_app_kit()
    kit.data.devices = Broken()
    assert kit.client.post("/v1/guardian/logout", headers=kit.guardian_headers).status_code == 204


def test_unregister_accepts_short_tokens_with_204():
    kit = kit_with_devices()
    r = kit.client.post(UNREGISTER, json={"token": "x"}, headers=kit.guardian_headers)
    assert r.status_code == 204



def _pending_kit():
    """가입만 하고 운영자 확인을 못 받은 보호자의 열쇠가 있는 kit."""
    from app.api.passwords import NO_LOGIN

    kit = kit_with_devices()
    for n in (1, 2):
        kit.data.accounts.create("자리", f"placeholder{n}@no-login.invalid", "010-0", NO_LOGIN)
    signup = kit.client.post(
        "/v1/guardian/signup",
        json={"name": "김보호", "email": "kim@example.com", "phone": "010-1111-2222", "password": "correct-horse-1"},
    ).json()
    kit.data.accounts.mark_email_verified(kit.data.accounts.find_by_email("kim@example.com").guardian_id)
    return kit, {"Authorization": f"Bearer {signup['key']}"}


def test_a_pending_account_cannot_register_a_phone_but_can_unregister_and_log_out():
    kit, headers = _pending_kit()

    refused = kit.client.post(REGISTER, json={"token": T1}, headers=headers)

    assert refused.status_code == 403
    assert refused.json() == {"detail": "운영자 확인 후 사용할 수 있어요"}
    assert kit.client.post(UNREGISTER, json={"token": T1}, headers=headers).status_code == 204
    assert kit.client.post("/v1/guardian/logout", headers=headers).status_code == 204


def test_a_sixth_phone_pushes_out_the_oldest_of_that_guardian_only():
    kit = kit_with_devices()
    from app.api.guardian_auth import generate_key

    other = generate_key()
    kit.data.guardian_auth.store.add(guardian_id=2, label="폰", key_prefix=other.key_prefix, key_hash=other.key_hash)
    kit.data.devices.register(2, other.key_hash, T2)
    tokens = [f"token-{i:02d}" + "x" * 14 for i in range(6)]

    for t in tokens:
        assert kit.client.post(REGISTER, json={"token": t}, headers=kit.guardian_headers).status_code == 204

    assert sorted(kit.data.devices.tokens_for(1)) == sorted(tokens[1:])
    assert kit.data.devices.tokens_for(2) == [T2]


def test_the_register_log_says_when_a_token_came_from_another_guardian(caplog):
    import logging

    from app.api.guardian_auth import generate_key

    kit = kit_with_devices()
    other = generate_key()
    kit.data.guardian_auth.store.add(guardian_id=2, label="폰", key_prefix=other.key_prefix, key_hash=other.key_hash)
    kit.data.devices.register(2, other.key_hash, T1)

    with caplog.at_level(logging.INFO, logger="app.api.app_data"):
        kit.client.post(REGISTER, json={"token": T1}, headers=kit.guardian_headers)

    line = [r.getMessage() for r in caplog.records if "폰을 등록" in r.getMessage()][0]
    assert "이전 보호자=2" in line and "guardian_id=1" in line
    assert T1[:8] in line and T1 not in line
