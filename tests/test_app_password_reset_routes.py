"""비밀번호 재설정 — 열쇠 없이, 방금 새 비밀번호로 Firebase에 로그인한 증명서로 서버 비밀번호를 바꾼다.

흐름: 앱이 Firebase 재설정 메일을 보내고, 보호자가 메일의 링크에서 새 비밀번호를 정한 뒤, 앱이 같은 새 비밀번호로
Firebase에 로그인해 받은 증명서와 새 비밀번호를 이 주소로 보낸다. 서버는 그 증명서의 이메일 계정 비밀번호를 바꾸고
그 보호자의 열쇠를 모두 폐기한다(모든 폰에서 로그아웃).

재설정은 이미 이메일 인증을 마친 계정만 된다. 앱은 이메일 인증이 끝나면 Firebase 비밀번호를 아무도 모르는 값으로
바꾸므로, 재설정에 쓸 증명서는 메일의 링크(메일함 주인)로만 다시 얻을 수 있다.
"""

from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import replace

import pytest

from app.api.devices import InMemoryDeviceStore
from app.api.passwords import NO_LOGIN
from app.api.rate_limit import FailureLimiter
from app.firebase_verify import VerifiedEmail
from tests.app_data_helpers import make_app_kit

RESET = "/v1/guardian/password/reset"
SIGNUP = "/v1/guardian/signup"
LOGIN = "/v1/guardian/login"
ME = "/v1/guardian/me"
NOT_CONFIRMED = {"detail": "비밀번호 재설정을 확인하지 못했어요"}
TRY_LATER = {"detail": "잠시 뒤에 다시 해 주세요"}
OFF = {"detail": "이메일 인증을 아직 쓸 수 없어요"}
UNAVAILABLE = {"detail": "인증을 확인할 수 없습니다"}
GOOD = {"name": "김보호", "email": "kim@example.com", "phone": "010-1111-2222", "password": "correct-horse-1"}
OTHER = {**GOOD, "name": "이보호", "email": "lee@example.com", "password": "other-horse-2"}
NEW_PASSWORD = "brand-new-pass-3"
PROOF = "p" * 40
UNKNOWN_PROOF = "q" * 40


class FakeVerifier:
    """증명서 문자열 → (이메일, auth_time) 표. 모르는 문자열은 None(확인 실패)."""

    def __init__(self, table=None):
        self.table = dict(table or {})
        self.calls = 0

    def verify(self, id_token):
        self.calls += 1
        entry = self.table.get(id_token)
        return None if entry is None else VerifiedEmail(email=entry[0], auth_time=entry[1])


def bearer(key):
    return {"Authorization": f"Bearer {key}"}


def now(kit) -> int:
    return int(kit.clock.now)


def signed_up_kit(*, verified=True):
    """앱에서 가입한 보호자의 kit과 가입 때 받은 열쇠 머리글. 확인기는 비어 있다.

    재설정은 이메일 인증을 마친 계정만 되므로 기본은 인증을 마친 보호자다(verified=False면 인증 전 그대로).
    """
    kit = make_app_kit()
    for n in (1, 2):  # kit의 열쇠가 보호자 1·2를 쓰므로 번호를 비켜 간다
        kit.data.accounts.create("자리", f"placeholder{n}@no-login.invalid", "010-0", NO_LOGIN)
    kit.data.email_verifier = FakeVerifier()
    body = kit.client.post(SIGNUP, json=GOOD).json()
    if verified:
        kit.data.accounts.mark_email_verified(guardian_id_of(kit))
    return kit, bearer(body["key"])


def guardian_id_of(kit, email=GOOD["email"]):
    return kit.data.accounts.find_by_email(email).guardian_id


def verified_flag(kit, email=GOOD["email"]):
    return kit.data.accounts.profile(guardian_id_of(kit, email)).email_verified


class RecordingAccounts:
    """계정 저장소를 감싸 이메일 인증 기록 호출을 적어 둔다. 나머지는 그대로 넘긴다."""

    def __init__(self, inner):
        self._inner = inner
        self.marked = []

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def mark_email_verified(self, guardian_id):
        self.marked.append(guardian_id)
        return self._inner.mark_email_verified(guardian_id)


class FlaglessAccounts:
    """이메일로 찾은 계정의 인증 칸이 True가 아닌(None) 저장소 — 인증된 것으로 치지 않아야 한다."""

    def __init__(self, inner):
        self._inner = inner

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def find_by_email(self, email):
        account = self._inner.find_by_email(email)
        return None if account is None else replace(account, email_verified=None)


def login(kit, password, email=GOOD["email"]):
    return kit.client.post(LOGIN, json={"email": email, "password": password})


def reset(kit, token=PROOF, new_password=NEW_PASSWORD, headers=None):
    return kit.client.post(RESET, json={"id_token": token, "new_password": new_password}, headers=headers)


def fresh_proof(kit, email=GOOD["email"], age=10, token=PROOF):
    """방금(age초 전) 새 비밀번호로 Firebase에 로그인해 받은 증명서를 확인기에 적는다."""
    kit.data.email_verifier.table[token] = (email, now(kit) - age)
    return token


# ------------------------------------------------ 성공


def test_a_fresh_proof_resets_the_password_and_logs_every_phone_out():
    kit, first_phone = signed_up_kit()
    second_phone = bearer(login(kit, GOOD["password"]).json()["key"])
    fresh_proof(kit)

    response = reset(kit)

    assert (response.status_code, response.json()) == (200, {"reset": True})
    # 그 보호자의 열쇠는 모두 폐기됐다 — 비밀번호를 잊은 사이 남이 쥔 열쇠도 같이 끊긴다
    assert kit.client.get(ME, headers=first_phone).status_code == 401
    assert kit.client.get(ME, headers=second_phone).status_code == 401
    # 옛 비밀번호는 안 되고 새 비밀번호로 들어간다
    assert login(kit, GOOD["password"]).status_code == 401
    fresh = login(kit, NEW_PASSWORD)
    assert fresh.status_code == 200
    assert kit.client.get(ME, headers=bearer(fresh.json()["key"])).status_code == 200


def test_a_reset_does_not_touch_the_verified_flag():
    """재설정은 이미 인증된 계정만 받으므로 인증 기록을 따로 하지 않는다 — 칸은 그대로 True다."""
    kit, _ = signed_up_kit()
    accounts = RecordingAccounts(kit.data.accounts)
    kit.data.accounts = accounts
    fresh_proof(kit)

    assert reset(kit).status_code == 200

    assert accounts.marked == []
    assert verified_flag(kit) is True
    assert login(kit, NEW_PASSWORD).json()["email_verified"] is True


def test_the_email_in_the_proof_is_matched_without_case_or_spaces():
    kit, _ = signed_up_kit()
    fresh_proof(kit, email="  Kim@Example.COM ")

    assert reset(kit).status_code == 200
    assert login(kit, NEW_PASSWORD).status_code == 200


def test_the_edges_of_the_sign_in_window_are_accepted():
    """정확히 300초 전과 60초 뒤(폰·구글 시계 차이)는 받는다."""
    for age, token in ((300, "edge-old-".ljust(40, "x")), (-60, "edge-new-".ljust(40, "x"))):
        kit, _ = signed_up_kit()
        fresh_proof(kit, age=age, token=token)

        assert reset(kit, token=token).status_code == 200, age


def test_a_locked_out_email_can_log_in_with_the_new_password_right_after_a_reset():
    kit, _ = signed_up_kit()
    for _ in range(5):
        login(kit, "wrong-password-0")
    assert login(kit, GOOD["password"]).status_code == 429  # 이메일 잠금
    fresh_proof(kit)

    assert reset(kit).status_code == 200

    assert login(kit, NEW_PASSWORD).status_code == 200


def test_phones_registered_for_push_stop_getting_alerts_after_a_reset():
    """폰 등록은 열쇠에 묶여 있고 읽을 때 폐기된 열쇠의 폰을 거른다 — 재설정은 따로 지우지 않아도 된다."""
    kit, phone = signed_up_kit()
    gid = guardian_id_of(kit)
    kit.data.accounts.activate(gid)
    kit.data.devices = InMemoryDeviceStore(is_key_active=kit.data.guardian_auth.store.is_active)
    assert kit.client.post("/v1/guardian/devices", json={"token": "t" * 30}, headers=phone).status_code == 204
    assert kit.data.devices.tokens_for(gid) == ["t" * 30]
    fresh_proof(kit)

    assert reset(kit).status_code == 200

    assert kit.data.devices.tokens_for(gid) == []


def test_only_the_guardian_named_in_the_proof_is_changed_whatever_key_is_sent():
    """열쇠 없이 부르는 주소다 — 머리글에 다른 보호자의 열쇠가 실려 와도 무시하고 증명서의 이메일만 본다."""
    kit, kim_phone = signed_up_kit()
    lee_phone = bearer(kit.client.post(SIGNUP, json=OTHER).json()["key"])
    kit.data.accounts.mark_email_verified(guardian_id_of(kit, OTHER["email"]))
    fresh_proof(kit, email=OTHER["email"])

    response = reset(kit, headers=kim_phone)

    assert response.status_code == 200
    assert kit.client.get(ME, headers=lee_phone).status_code == 401
    assert login(kit, NEW_PASSWORD, email=OTHER["email"]).status_code == 200
    # 김보호는 그대로다
    assert kit.client.get(ME, headers=kim_phone).status_code == 200
    assert login(kit, GOOD["password"]).status_code == 200
    assert login(kit, NEW_PASSWORD).status_code == 401


def test_the_legacy_key_only_guardian_is_untouched():
    kit, _ = signed_up_kit()
    fresh_proof(kit)

    reset(kit)

    assert kit.client.get("/v1/guardian/elders", headers=kit.guardian_headers).status_code == 200


# ------------------------------------------------ 실패는 모두 같은 401


def _stale(kit):
    return fresh_proof(kit, age=301)


def _future(kit):
    return fresh_proof(kit, age=-61)


def _no_auth_time(kit):
    kit.data.email_verifier.table[PROOF] = (GOOD["email"], None)
    return PROOF


def _unknown_email(kit):
    return fresh_proof(kit, email="nobody@example.com")


def _bad_proof(kit):
    return UNKNOWN_PROOF  # 확인기가 None을 준다(서명·만료·인증 전 이메일 등)


@pytest.mark.parametrize(
    ("verified", "make_token"),
    [
        (True, _stale),
        (True, _future),
        (True, _no_auth_time),
        (True, _unknown_email),
        (True, _bad_proof),
        (False, fresh_proof),  # 증명서는 맞지만 이 서버에서 이메일 인증을 마치지 않은 계정
    ],
    ids=["301초 전 로그인", "61초 뒤 로그인", "auth_time 없음", "없는 이메일", "확인 실패", "인증 전 계정"],
)
def test_every_kind_of_failure_gets_the_same_401_and_counts_toward_the_limit(verified, make_token):
    kit, phone = signed_up_kit(verified=verified)
    kit.data.password_reset_failures = FailureLimiter(limit=1)
    token = make_token(kit)
    assert kit.data.password_reset_failures.blocked() is False

    response = reset(kit, token=token)

    assert (response.status_code, response.json()) == (401, NOT_CONFIRMED)
    assert kit.data.password_reset_failures.blocked() is True
    # 아무것도 바뀌지 않았다
    assert kit.client.get(ME, headers=phone).status_code == 200
    assert login(kit, GOOD["password"]).status_code == 200
    assert verified_flag(kit) is verified


def test_an_unverified_account_stays_unverified_and_keeps_its_password():
    """인증 전 계정은 운영 도구로 되찾는다(재설정으로 인증까지 끝내게 두지 않는다)."""
    kit, _ = signed_up_kit(verified=False)
    accounts = RecordingAccounts(kit.data.accounts)
    kit.data.accounts = accounts
    fresh_proof(kit)

    response = reset(kit)

    assert (response.status_code, response.json()) == (401, NOT_CONFIRMED)
    assert accounts.marked == []
    assert verified_flag(kit) is False
    assert login(kit, NEW_PASSWORD).status_code == 401


def test_an_account_whose_verified_flag_is_not_true_is_refused_the_same_way():
    kit, phone = signed_up_kit()
    kit.data.accounts = FlaglessAccounts(kit.data.accounts)
    kit.data.password_reset_failures = FailureLimiter(limit=1)
    fresh_proof(kit)

    response = reset(kit)

    assert (response.status_code, response.json()) == (401, NOT_CONFIRMED)
    assert kit.data.password_reset_failures.blocked() is True
    assert kit.client.get(ME, headers=phone).status_code == 200
    assert login(kit, NEW_PASSWORD).status_code == 401


def test_failures_are_limited_server_wide_and_a_blocked_request_is_not_checked():
    kit, _ = signed_up_kit()
    kit.data.password_reset_failures = FailureLimiter(limit=2)
    for _ in range(2):
        assert reset(kit, token=UNKNOWN_PROOF).status_code == 401
    fresh_proof(kit)
    calls = kit.data.email_verifier.calls

    response = reset(kit)  # 맞는 증명서여도 한도가 풀릴 때까지는 막는다

    assert (response.status_code, response.json()) == (429, TRY_LATER)
    assert kit.data.email_verifier.calls == calls  # Firebase 확인에 들어가지 않았다
    assert login(kit, GOOD["password"]).status_code == 200


def test_a_success_does_not_count_toward_the_failure_limit():
    kit, _ = signed_up_kit()
    kit.data.password_reset_failures = FailureLimiter(limit=1)
    fresh_proof(kit)

    assert reset(kit).status_code == 200
    assert kit.data.password_reset_failures.blocked() is False


def test_without_a_configured_verifier_the_endpoint_is_closed_with_503():
    kit, _ = signed_up_kit()
    kit.data.email_verifier = None

    response = reset(kit)

    assert (response.status_code, response.json()) == (503, OFF)
    assert login(kit, GOOD["password"]).status_code == 200


@pytest.mark.parametrize(
    "body",
    [
        {"id_token": PROOF, "new_password": "seven77"},  # 7자
        {"id_token": PROOF, "new_password": "x" * 129},
        {"id_token": "short", "new_password": NEW_PASSWORD},
        {"id_token": "x" * 4097, "new_password": NEW_PASSWORD},
        {"id_token": PROOF},
        {"new_password": NEW_PASSWORD},
    ],
    ids=["비밀번호 7자", "비밀번호 129자", "짧은 증명서", "긴 증명서", "비밀번호 없음", "증명서 없음"],
)
def test_a_malformed_body_is_422_and_firebase_is_not_asked(body):
    kit, _ = signed_up_kit()
    fresh_proof(kit)

    response = kit.client.post(RESET, json=body)

    assert response.status_code == 422
    assert kit.data.email_verifier.calls == 0
    assert login(kit, GOOD["password"]).status_code == 200


def test_the_minimum_password_length_is_shared_with_signup():
    from app.api.app_data import MIN_PASSWORD

    kit, _ = signed_up_kit()
    fresh_proof(kit)

    assert reset(kit, new_password="a" * (MIN_PASSWORD - 1)).status_code == 422
    assert reset(kit, new_password="a" * MIN_PASSWORD).status_code == 200


# ------------------------------------------------ 기록


def test_the_logs_never_carry_the_email_the_proof_or_either_password(caplog):
    kit, _ = signed_up_kit()
    fresh_proof(kit)

    with caplog.at_level(logging.DEBUG):
        reset(kit, token=UNKNOWN_PROOF)
        reset(kit)

    for secret in (GOOD["email"], PROOF, UNKNOWN_PROOF, NEW_PASSWORD, GOOD["password"]):
        assert secret not in caplog.text, secret
    gid = guardian_id_of(kit)
    assert f"비밀번호를 재설정했다 guardian_id={gid} 폐기=1" in caplog.text


# ------------------------------------------------ 동시에 몰려온 재설정 (Firebase는 작업 스레드 안의 느린 바깥 호출이다)


class BlockingVerifier:
    """확인 중에 멈춰 서는 가짜 Firebase — `release`를 열기 전까지 들어온 요청을 붙잡아 둔다."""

    def __init__(self, table=None):
        self.table = dict(table or {})
        self.release = threading.Event()
        self.calls = 0
        self._entered = threading.Condition()

    def verify(self, id_token):
        with self._entered:
            self.calls += 1
            self._entered.notify_all()
        if not self.release.wait(timeout=10):
            raise RuntimeError("시험이 확인기를 풀어 주지 않았다")
        entry = self.table.get(id_token)
        return None if entry is None else VerifiedEmail(email=entry[0], auth_time=entry[1])

    def wait_for_calls(self, count, timeout=5):
        with self._entered:
            return self._entered.wait_for(lambda: self.calls >= count, timeout)


class RaisingVerifier:
    def __init__(self):
        self.calls = 0

    def verify(self, id_token):
        self.calls += 1
        raise RuntimeError("Firebase 쪽 오류")


@contextmanager
def one_server(kit, verifier):
    """요청을 한 서버(이벤트 루프 하나·작업 스레드 묶음 하나)에 동시에 보낸다. 끝날 때 붙잡힌 확인을 모두 풀어 준다."""
    with kit.client as client, ThreadPoolExecutor(max_workers=16) as pool:

        def send(token):
            return pool.submit(client.post, RESET, json={"id_token": token, "new_password": NEW_PASSWORD})

        try:
            yield send
        finally:
            verifier.release.set()


def test_at_most_four_resets_are_checked_at_once_and_the_fifth_is_turned_away_at_once():
    kit, _ = signed_up_kit()
    verifier = BlockingVerifier()
    kit.data.email_verifier = verifier
    good = fresh_proof(kit)
    tokens = [good] + [f"unknown-{n}-".ljust(40, "x") for n in range(3)]  # 하나는 맞고 셋은 틀린 증명서

    with one_server(kit, verifier) as send:
        inside = [send(token) for token in tokens]
        assert verifier.wait_for_calls(4)

        fifth = send(good).result(timeout=5)  # 확인기가 막혀 있어도 기다리지 않고 돌아온다
        assert (fifth.status_code, fifth.json()) == (429, TRY_LATER)
        assert verifier.calls == 4
        assert kit.data.password_reset_slots.in_flight() == 4

        verifier.release.set()
        assert sorted(f.result(timeout=5).status_code for f in inside) == [200, 401, 401, 401]

    # 성공·실패 모두 자리를 돌려줬다
    assert kit.data.password_reset_slots.in_flight() == 0
    fresh_proof(kit, token="again-".ljust(40, "x"))
    assert reset(kit, token="again-".ljust(40, "x")).status_code == 200


def test_a_verifier_error_closes_with_503_and_gives_the_slot_back():
    kit, _ = signed_up_kit()
    kit.data.email_verifier = RaisingVerifier()

    responses = [reset(kit) for _ in range(5)]  # 자리가 돌아오지 않으면 다섯 번째는 429가 된다

    assert [(r.status_code, r.json()) for r in responses] == [(503, UNAVAILABLE)] * 5
    assert kit.data.email_verifier.calls == 5
    assert kit.data.password_reset_slots.in_flight() == 0
    assert login(kit, GOOD["password"]).status_code == 200


def test_failed_resets_give_the_slot_back():
    kit, _ = signed_up_kit()

    responses = [reset(kit, token=UNKNOWN_PROOF) for _ in range(5)]

    assert [r.status_code for r in responses] == [401] * 5
    assert kit.data.password_reset_slots.in_flight() == 0


def test_email_verification_slots_are_not_shared_with_resets():
    """열쇠 없이 부르는 재설정이 몰려도 로그인한 보호자의 이메일 인증 자리를 빼앗지 않는다."""
    kit, _ = signed_up_kit()

    assert kit.data.password_reset_slots is not kit.data.email_verify_slots
