"""보호자 계정 — 가입, 로그인, 로그아웃, 내 정보, 비밀번호 변경 (설계: 보호자 계정)."""

from __future__ import annotations

import logging

from app.api.guardian_auth import hash_key, parse_bearer
from app.api.passwords import NO_LOGIN, verify_password
from app.api.rate_limit import FailureLimiter
from tests.app_data_helpers import make_app_kit as _make_app_kit

SIGNUP = "/v1/guardian/signup"
LOGIN = "/v1/guardian/login"
BAD_LOGIN = {"detail": "이메일이나 비밀번호를 확인해 주세요"}
GOOD = {"name": "김보호", "email": "Kim@Example.com", "phone": "010-1111-2222", "password": "correct-horse-1"}


def make_app_kit():
    """도우미 열쇠가 보호자 1번을 쓰므로, 새 계정이 1번을 받지 않게 자리를 채운다."""
    kit = _make_app_kit()
    for n in (1, 2):  # 도우미의 보호자 1·2번 자리
        kit.data.accounts.create("자리", f"placeholder{n}@no-login.invalid", "010-0", NO_LOGIN)
    return kit


def bearer(key):
    return {"Authorization": f"Bearer {key}"}


def sign_up(kit, **override):
    return kit.client.post(SIGNUP, json={**GOOD, **override})


# ------------------------------------------------ 가입


def test_signup_creates_an_account_and_logs_in_at_once():
    kit = make_app_kit()
    r = sign_up(kit)
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "김보호" and body["email"] == "kim@example.com" and body["phone"] == "010-1111-2222"
    # 받은 열쇠로 바로 보호자 주소를 쓸 수 있다 — 어르신은 아직 없다
    elders = kit.client.get("/v1/guardian/elders", headers=bearer(body["key"]))
    assert elders.status_code == 200 and elders.json()["elders"] == []


def test_signup_stores_a_hash_never_the_password():
    kit = make_app_kit()
    sign_up(kit)
    stored = kit.data.accounts.find_by_email("kim@example.com").password_hash
    assert stored != GOOD["password"] and GOOD["password"] not in stored
    assert verify_password(GOOD["password"], stored) is True


def test_signup_rejects_bad_input():
    kit = make_app_kit()
    assert sign_up(kit, password="short").status_code == 422
    assert sign_up(kit, email="not-an-email").status_code == 422
    assert sign_up(kit, phone="abc").status_code == 422
    assert sign_up(kit, name="").status_code == 422
    assert kit.data.accounts.find_by_email("kim@example.com") is None


def test_signup_with_a_taken_email_is_409_even_in_other_case():
    kit = make_app_kit()
    assert sign_up(kit).status_code == 200
    r = sign_up(kit, email="  KIM@example.COM ")
    assert r.status_code == 409 and r.json() == {"detail": "이미 가입된 이메일이에요"}


def test_signup_is_limited_per_minute():
    kit = make_app_kit()
    kit.data.signup_attempts = FailureLimiter(limit=2, window_seconds=60, clock=lambda: 1.0)
    assert sign_up(kit, email="a@example.com").status_code == 200
    assert sign_up(kit, email="b@example.com").status_code == 200
    assert sign_up(kit, email="c@example.com").status_code == 429


# ------------------------------------------------ 로그인


def test_login_with_the_right_password_gives_a_working_key():
    kit = make_app_kit()
    sign_up(kit)
    r = kit.client.post(LOGIN, json={"email": " kim@EXAMPLE.com", "password": GOOD["password"]})
    assert r.status_code == 200
    assert kit.client.get("/v1/guardian/elders", headers=bearer(r.json()["key"])).status_code == 200


def test_wrong_password_unknown_email_and_no_login_accounts_look_identical():
    kit = make_app_kit()
    sign_up(kit)
    gid = kit.data.accounts.create("운영자", "op@no-login.invalid", "010-0", NO_LOGIN)
    cases = [
        {"email": "kim@example.com", "password": "wrong-password"},
        {"email": "nobody@example.com", "password": GOOD["password"]},
        {"email": "op@no-login.invalid", "password": NO_LOGIN},
    ]
    for case in cases:
        r = kit.client.post(LOGIN, json=case)
        assert r.status_code == 401 and r.json() == BAD_LOGIN, case
    assert gid  # 위 세 번 모두 열쇠를 만들지 않았다
    assert not [k for k in kit.data.guardian_auth.store.list_keys() if k.guardian_id == gid]


def test_five_wrong_passwords_lock_that_email_even_for_the_right_one():
    kit = make_app_kit()
    sign_up(kit)
    for _ in range(5):
        kit.client.post(LOGIN, json={"email": "kim@example.com", "password": "wrong-password"})
    r = kit.client.post(LOGIN, json={"email": "kim@example.com", "password": GOOD["password"]})
    assert r.status_code == 429
    # 다른 이메일은 영향이 없다
    sign_up(kit, email="lee@example.com")
    ok = kit.client.post(LOGIN, json={"email": "lee@example.com", "password": GOOD["password"]})
    assert ok.status_code == 200


def test_a_successful_login_resets_the_failure_count():
    kit = make_app_kit()
    sign_up(kit)
    for _ in range(4):
        kit.client.post(LOGIN, json={"email": "kim@example.com", "password": "wrong-password"})
    assert kit.client.post(LOGIN, json={"email": "kim@example.com", "password": GOOD["password"]}).status_code == 200
    kit.client.post(LOGIN, json={"email": "kim@example.com", "password": "wrong-password"})
    assert kit.client.post(LOGIN, json={"email": "kim@example.com", "password": GOOD["password"]}).status_code == 200


def test_unknown_email_failures_throttle_unknown_emails_but_not_real_accounts():
    kit = make_app_kit()
    sign_up(kit)
    kit.data.account_failures = FailureLimiter(limit=2, window_seconds=60, clock=lambda: 1.0)
    for n in range(2):
        kit.client.post(LOGIN, json={"email": f"x{n}@example.com", "password": "whatever-1"})
    # 없는 이메일을 더 찍어 보는 요청은 막히지만
    assert kit.client.post(LOGIN, json={"email": "x9@example.com", "password": "whatever-1"}).status_code == 429
    # 맞는 계정의 로그인과 비밀번호 변경은 남이 막지 못한다
    ok = kit.client.post(LOGIN, json={"email": "kim@example.com", "password": GOOD["password"]})
    assert ok.status_code == 200
    changed = kit.client.post(
        "/v1/guardian/password",
        json={"current": GOOD["password"], "new": "brand-new-pass-2"},
        headers=bearer(ok.json()["key"]),
    )
    assert changed.status_code == 200


def test_a_login_started_with_the_old_password_gets_no_key_after_the_password_changed(monkeypatch):
    from app.api import app_data

    kit = make_app_kit()
    sign_up(kit)
    real = app_data.verify_password
    calls = []

    def verify_then_change_password(password, stored):
        ok = real(password, stored)
        if not calls:  # 첫 호출(로그인의 비밀번호 검사) 직후에 다른 폰이 비밀번호를 바꾼다
            calls.append(1)
            gid = kit.data.accounts.find_by_email("kim@example.com").guardian_id
            kit.data.accounts.set_password(gid, app_data.hash_password("brand-new-pass-2"))
        return ok

    monkeypatch.setattr(app_data, "verify_password", verify_then_change_password)
    r = kit.client.post(LOGIN, json={"email": "kim@example.com", "password": GOOD["password"]})

    assert r.status_code == 401 and r.json() == BAD_LOGIN
    assert len(kit.data.guardian_auth.store.list_keys()) == 2  # 도우미 열쇠 + 가입 때 열쇠뿐, 새 열쇠 없음


# ------------------------------------------------ 로그아웃·내 정보


def test_logout_revokes_only_this_phones_key():
    kit = make_app_kit()
    key1 = sign_up(kit).json()["key"]
    key2 = kit.client.post(LOGIN, json={"email": "kim@example.com", "password": GOOD["password"]}).json()["key"]
    assert kit.client.post("/v1/guardian/logout", headers=bearer(key1)).status_code == 204
    assert kit.client.get("/v1/guardian/elders", headers=bearer(key1)).status_code == 401
    assert kit.client.get("/v1/guardian/elders", headers=bearer(key2)).status_code == 200


def test_logout_needs_a_key():
    assert make_app_kit().client.post("/v1/guardian/logout").status_code == 401


def test_me_returns_the_profile_and_needs_a_key():
    kit = make_app_kit()
    key = sign_up(kit).json()["key"]
    r = kit.client.get("/v1/guardian/me", headers=bearer(key))
    assert r.json() == {"name": "김보호", "email": "kim@example.com", "phone": "010-1111-2222", "activated": False, "email_verified": False}
    assert kit.client.get("/v1/guardian/me").status_code == 401


# ------------------------------------------------ 비밀번호 변경


def test_password_change_swaps_the_password_and_signs_out_other_phones():
    kit = make_app_kit()
    this_phone = sign_up(kit).json()["key"]
    other_phone = kit.client.post(LOGIN, json={"email": "kim@example.com", "password": GOOD["password"]}).json()["key"]

    r = kit.client.post(
        "/v1/guardian/password",
        json={"current": GOOD["password"], "new": "brand-new-pass-2"},
        headers=bearer(this_phone),
    )

    assert r.status_code == 200 and r.json() == {"revoked_others": 1}
    assert kit.client.get("/v1/guardian/elders", headers=bearer(this_phone)).status_code == 200
    assert kit.client.get("/v1/guardian/elders", headers=bearer(other_phone)).status_code == 401
    assert kit.client.post(LOGIN, json={"email": "kim@example.com", "password": GOOD["password"]}).status_code == 401
    assert kit.client.post(LOGIN, json={"email": "kim@example.com", "password": "brand-new-pass-2"}).status_code == 200


def test_password_change_needs_the_current_password():
    kit = make_app_kit()
    key = sign_up(kit).json()["key"]
    r = kit.client.post(
        "/v1/guardian/password",
        json={"current": "not-my-password", "new": "brand-new-pass-2"},
        headers=bearer(key),
    )
    assert r.status_code == 403 and r.json() == {"detail": "현재 비밀번호를 확인해 주세요"}
    assert kit.client.post(LOGIN, json={"email": "kim@example.com", "password": GOOD["password"]}).status_code == 200


def test_password_change_rejects_a_short_new_password_and_missing_key():
    kit = make_app_kit()
    key = sign_up(kit).json()["key"]
    short = kit.client.post(
        "/v1/guardian/password", json={"current": GOOD["password"], "new": "short"}, headers=bearer(key)
    )
    assert short.status_code == 422
    nokey = kit.client.post("/v1/guardian/password", json={"current": "a", "new": "brand-new-pass-2"})
    assert nokey.status_code == 401


def test_wrong_current_passwords_count_toward_the_email_lock():
    kit = make_app_kit()
    key = sign_up(kit).json()["key"]
    for _ in range(5):
        kit.client.post(
            "/v1/guardian/password", json={"current": "nope-nope-1", "new": "brand-new-pass-2"}, headers=bearer(key)
        )
    r = kit.client.post(
        "/v1/guardian/password", json={"current": GOOD["password"], "new": "brand-new-pass-2"}, headers=bearer(key)
    )
    assert r.status_code == 429


# ------------------------------------------------ 비밀이 새지 않는다


def test_no_password_or_hash_in_responses_or_logs(caplog):
    kit = make_app_kit()
    with caplog.at_level(logging.DEBUG):
        r1 = sign_up(kit)
        r2 = kit.client.post(LOGIN, json={"email": "kim@example.com", "password": "wrong-password"})
        r3 = kit.client.post(LOGIN, json={"email": "kim@example.com", "password": GOOD["password"]})
        kit.client.post(
            "/v1/guardian/password",
            json={"current": GOOD["password"], "new": "brand-new-pass-2"},
            headers=bearer(r3.json()["key"]),
        )
    stored = kit.data.accounts.find_by_email("kim@example.com").password_hash
    everything = caplog.text + r1.text + r2.text + r3.text
    for secret in (GOOD["password"], "wrong-password", "brand-new-pass-2", stored, "kim@example.com"):
        assert secret not in caplog.text, secret
    assert stored not in everything and "scrypt$" not in everything


# ------------------------------------------------ 운영자 활성화


def test_a_new_signup_is_pending_and_cannot_issue_invites_or_approve():
    kit = make_app_kit()
    body = sign_up(kit).json()
    assert body["activated"] is False
    assert kit.client.get("/v1/guardian/me", headers=bearer(body["key"])).json()["activated"] is False
    kit.data.accounts.mark_email_verified(kit.data.accounts.find_by_email("kim@example.com").guardian_id)

    invite = kit.client.post("/v1/guardian/invite", headers=bearer(body["key"]))
    assert invite.status_code == 403 and invite.json() == {"detail": "운영자 확인 후 사용할 수 있어요"}
    approve = kit.client.post("/v1/elders/12/approve", headers=bearer(body["key"]))
    assert approve.status_code == 403


def test_an_activated_guardian_can_issue_invites():
    kit = make_app_kit()
    body = sign_up(kit).json()
    kit.data.accounts.activate(kit.data.accounts.find_by_email("kim@example.com").guardian_id)
    kit.data.accounts.mark_email_verified(kit.data.accounts.find_by_email("kim@example.com").guardian_id)

    assert kit.client.post("/v1/guardian/invite", headers=bearer(body["key"])).status_code == 200
    assert kit.client.get("/v1/guardian/me", headers=bearer(body["key"])).json()["activated"] is True


def test_a_pending_guardian_can_still_log_in_and_read_their_own_list():
    kit = make_app_kit()
    sign_up(kit)
    r = kit.client.post(LOGIN, json={"email": "kim@example.com", "password": GOOD["password"]})
    assert r.status_code == 200 and r.json()["activated"] is False
    assert kit.client.get("/v1/guardian/elders", headers=bearer(r.json()["key"])).status_code == 200


# ------------------------------------------------ 열쇠 상한


def _active_keys(kit, guardian_id):
    return [k for k in kit.data.guardian_auth.store.list_keys() if k.guardian_id == guardian_id and k.revoked_at is None]


def test_logging_in_many_times_keeps_only_the_ten_newest_keys():
    kit = make_app_kit()
    sign_up(kit)
    keys = [kit.client.post(LOGIN, json={"email": GOOD["email"], "password": GOOD["password"]}).json()["key"] for _ in range(12)]

    guardian_id = kit.data.accounts.find_by_email("kim@example.com").guardian_id
    assert len(_active_keys(kit, guardian_id)) == 10
    me = [kit.client.get("/v1/guardian/me", headers=bearer(k)).status_code for k in keys]
    assert me[-10:] == [200] * 10  # 가장 새 열쇠 열 개는 쓸 수 있다
    assert me[:2] == [401, 401]  # 가입 때 받은 열쇠를 포함해 가장 오래된 것은 폐기됐다


def test_signup_also_enforces_the_key_cap_without_touching_other_guardians():
    kit = make_app_kit()
    first = sign_up(kit).json()["key"]
    other = sign_up(kit, email="lee@example.com").json()["key"]
    for _ in range(12):
        kit.client.post(LOGIN, json={"email": GOOD["email"], "password": GOOD["password"]})

    assert kit.client.get("/v1/guardian/me", headers=bearer(first)).status_code == 401
    assert kit.client.get("/v1/guardian/me", headers=bearer(other)).status_code == 200
