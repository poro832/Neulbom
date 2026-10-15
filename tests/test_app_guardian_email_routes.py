"""보호자 이메일 인증 — Firebase 증명서를 받아 인증을 기록하고, 인증 전에는 어르신 연결을 막는다."""

from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager

import anyio.to_thread

from app.api.passwords import NO_LOGIN
from app.api.rate_limit import FailureLimiter
from app.firebase_verify import VerifiedEmail
from tests.app_data_helpers import make_app_kit

VERIFY = "/v1/guardian/email/verify"
SIGNUP = "/v1/guardian/signup"
ME = "/v1/guardian/me"
BAD_PROOF = {"detail": "이메일 인증을 확인하지 못했어요"}
NEEDS_EMAIL = {"detail": "이메일 인증 후 사용할 수 있어요"}
NEEDS_OPERATOR = {"detail": "운영자 확인 후 사용할 수 있어요"}
TRY_LATER = {"detail": "잠시 뒤에 다시 해 주세요"}
UNAVAILABLE = {"detail": "인증을 확인할 수 없습니다"}
GOOD = {"name": "김보호", "email": "kim@example.com", "phone": "010-1111-2222", "password": "correct-horse-1"}
PROOF = "p" * 40


class FakeVerifier:
    """주어진 증명서 문자열 → 이메일 표. 모르는 문자열은 None."""

    def __init__(self, table=None):
        self.table = table or {}
        self.calls = 0

    def verify(self, id_token):
        self.calls += 1
        email = self.table.get(id_token)
        return None if email is None else VerifiedEmail(email=email)


def bearer(key):
    return {"Authorization": f"Bearer {key}"}


def signed_up_kit(verifier=None):
    """앱에서 가입만 한 보호자(이메일 인증 전·운영자 확인 전)의 kit과 머리글."""
    kit = make_app_kit()
    for n in (1, 2):  # kit의 열쇠가 보호자 1·2를 쓰므로 번호를 비켜 간다
        kit.data.accounts.create("자리", f"placeholder{n}@no-login.invalid", "010-0", NO_LOGIN)
    kit.data.email_verifier = verifier
    body = kit.client.post(SIGNUP, json=GOOD).json()
    return kit, body, bearer(body["key"])


def guardian_id_of(kit):
    return kit.data.accounts.find_by_email(GOOD["email"]).guardian_id


def test_a_new_signup_is_unverified_everywhere_it_is_reported():
    kit, body, headers = signed_up_kit(FakeVerifier())

    assert body["email_verified"] is False
    assert kit.client.get(ME, headers=headers).json()["email_verified"] is False
    login = kit.client.post("/v1/guardian/login", json={"email": GOOD["email"], "password": GOOD["password"]})
    assert login.json()["email_verified"] is False


def test_a_matching_proof_verifies_the_account():
    kit, body, headers = signed_up_kit(FakeVerifier({PROOF: "Kim@Example.com"}))  # 대소문자가 달라도 같은 이메일

    response = kit.client.post(VERIFY, json={"id_token": PROOF}, headers=headers)

    assert response.status_code == 200 and response.json() == {"email_verified": True}
    assert kit.client.get(ME, headers=headers).json()["email_verified"] is True


def test_someone_elses_email_and_unknown_proofs_get_the_same_401():
    verifier = FakeVerifier({PROOF: "other@example.com"})
    kit, _, headers = signed_up_kit(verifier)

    other = kit.client.post(VERIFY, json={"id_token": PROOF}, headers=headers)
    unknown = kit.client.post(VERIFY, json={"id_token": "q" * 40}, headers=headers)

    assert (other.status_code, other.json()) == (401, BAD_PROOF)
    assert (unknown.status_code, unknown.json()) == (401, BAD_PROOF)
    assert kit.data.accounts.profile(guardian_id_of(kit)).email_verified is False


def test_failed_proofs_are_limited_server_wide():
    kit, _, headers = signed_up_kit(FakeVerifier())
    kit.data.email_verify_failures = FailureLimiter(limit=2)
    for _ in range(2):
        kit.client.post(VERIFY, json={"id_token": "q" * 40}, headers=headers)

    assert kit.client.post(VERIFY, json={"id_token": "q" * 40}, headers=headers).status_code == 429


def test_without_a_configured_verifier_the_endpoint_is_closed_with_503():
    kit, _, headers = signed_up_kit(None)

    response = kit.client.post(VERIFY, json={"id_token": PROOF}, headers=headers)

    assert response.status_code == 503
    assert response.json() == {"detail": "이메일 인증을 아직 쓸 수 없어요"}


def test_an_already_verified_guardian_gets_200_without_calling_firebase():
    verifier = FakeVerifier()
    kit, _, headers = signed_up_kit(verifier)
    kit.data.accounts.mark_email_verified(guardian_id_of(kit))

    response = kit.client.post(VERIFY, json={"id_token": PROOF}, headers=headers)

    assert response.status_code == 200 and response.json() == {"email_verified": True}
    assert verifier.calls == 0


# ------------------------------------------------ 동시에 몰려온 확인 (Firebase는 작업 스레드 안의 느린 바깥 호출이다)


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
        email = self.table.get(id_token)
        return None if email is None else VerifiedEmail(email=email)

    def wait_for_calls(self, count, timeout=5):
        with self._entered:
            return self._entered.wait_for(lambda: self.calls >= count, timeout)


class RaisingVerifier:
    def __init__(self):
        self.calls = 0

    def verify(self, id_token):
        self.calls += 1
        raise RuntimeError("Firebase 쪽 오류")


def another_guardian(kit, verifier, n):
    """같은 서버에 앱으로 가입한 n번째 보호자(인증 전)의 머리글과, 그 보호자 이메일이 적힌 증명서."""
    email = f"guardian{n}@example.com"
    token = f"proof-{n}-".ljust(40, "x")
    verifier.table[token] = email
    body = kit.client.post(SIGNUP, json={**GOOD, "email": email}).json()
    return bearer(body["key"]), token


def _set_worker_threads(count):
    anyio.to_thread.current_default_thread_limiter().total_tokens = count


@contextmanager
def one_server(kit, verifier, *, worker_threads=None):
    """요청을 한 서버(이벤트 루프 하나·작업 스레드 묶음 하나)에 동시에 보낸다 — 실서버(uvicorn)와 같은 모양.

    끝날 때는 붙잡힌 확인을 모두 풀어 준다(실패한 시험이 스레드를 남기지 않게).
    """
    with kit.client as client, ThreadPoolExecutor(max_workers=32) as pool:
        if worker_threads is not None:
            client.portal.call(_set_worker_threads, worker_threads)

        def send(headers, token=PROOF):
            return pool.submit(client.post, VERIFY, json={"id_token": token}, headers=headers)

        def get(path, headers):
            return pool.submit(client.get, path, headers=headers)

        try:
            yield send, get
        finally:
            verifier.release.set()


def test_concurrent_proofs_from_one_guardian_enter_firebase_one_at_a_time():
    """끝난 실패만 세는 한도로는 한꺼번에 보낸 요청을 막지 못한다 — 두 번째부터는 확인기에 들어가지 않고 곧바로 429다."""
    verifier = BlockingVerifier({PROOF: GOOD["email"]})
    kit, _, headers = signed_up_kit(verifier)

    with one_server(kit, verifier) as (send, _):
        first = send(headers)
        assert verifier.wait_for_calls(1)

        rest = [send(headers) for _ in range(9)]
        for response in (future.result(timeout=5) for future in rest):
            assert (response.status_code, response.json()) == (429, TRY_LATER)
        assert verifier.calls == 1  # 나머지는 확인기를 기다리지 않고 돌아왔다

        verifier.release.set()
        assert first.result(timeout=5).json() == {"email_verified": True}

    assert kit.data.email_verify_slots.in_flight() == 0


def test_at_most_four_proofs_are_checked_at_once_and_the_slots_come_back_after_success():
    verifier = BlockingVerifier({PROOF: GOOD["email"]})
    kit, _, headers = signed_up_kit(verifier)
    guardians = [(headers, PROOF)] + [another_guardian(kit, verifier, n) for n in range(1, 6)]  # 6명

    with one_server(kit, verifier) as (send, _):
        inside = [send(h, token) for h, token in guardians[:4]]
        assert verifier.wait_for_calls(4)

        turned_away = [send(h, token).result(timeout=5) for h, token in guardians[4:]]
        assert [(r.status_code, r.json()) for r in turned_away] == [(429, TRY_LATER)] * 2
        assert verifier.calls == 4

        verifier.release.set()
        assert [future.result(timeout=5).status_code for future in inside] == [200] * 4

        # 성공한 확인이 자리를 돌려줬다 — 돌려보냈던 보호자도 이제 들어간다.
        late = [send(h, token).result(timeout=5) for h, token in guardians[4:]]
        assert [r.status_code for r in late] == [200, 200]

    assert verifier.calls == 6
    assert kit.data.email_verify_slots.in_flight() == 0


def test_waiting_on_firebase_never_ties_up_every_worker_thread():
    """작업 스레드가 6개뿐인 서버에 27개를 한꺼번에 보내도, 붙잡히는 것은 4개까지라 다른 주소가 답한다."""
    verifier = BlockingVerifier({PROOF: GOOD["email"]})
    kit, _, headers = signed_up_kit(verifier)
    guardians = [(headers, PROOF)] + [another_guardian(kit, verifier, n) for n in range(1, 9)]  # 9명

    with one_server(kit, verifier, worker_threads=6) as (send, get):
        flood = [send(h, token) for h, token in guardians for _ in range(3)]
        assert verifier.wait_for_calls(4)

        me = get(ME, headers).result(timeout=5)

        assert me.status_code == 200
        verifier.release.set()
        statuses = sorted(future.result(timeout=5).status_code for future in flood)

    assert verifier.calls <= 9  # 한 보호자는 한 번에 하나만 확인기에 들어간다
    assert 200 in statuses and set(statuses) <= {200, 429}


def test_a_failed_proof_gives_the_slot_back():
    verifier = FakeVerifier()
    kit, _, headers = signed_up_kit(verifier)

    first = kit.client.post(VERIFY, json={"id_token": "q" * 40}, headers=headers)
    second = kit.client.post(VERIFY, json={"id_token": "q" * 40}, headers=headers)

    assert (first.status_code, first.json()) == (401, BAD_PROOF)
    assert (second.status_code, second.json()) == (401, BAD_PROOF)  # 429가 아니다 — 자리가 돌아왔다
    assert verifier.calls == 2
    assert kit.data.email_verify_slots.in_flight() == 0


def test_a_verifier_error_closes_with_503_and_gives_the_slot_back():
    verifier = RaisingVerifier()
    kit, _, headers = signed_up_kit(verifier)

    first = kit.client.post(VERIFY, json={"id_token": PROOF}, headers=headers)
    second = kit.client.post(VERIFY, json={"id_token": PROOF}, headers=headers)

    assert (first.status_code, first.json()) == (503, UNAVAILABLE)
    assert (second.status_code, second.json()) == (503, UNAVAILABLE)
    assert verifier.calls == 2
    assert kit.data.email_verify_slots.in_flight() == 0


def test_verifying_needs_a_guardian_key_and_a_plausible_proof():
    kit, _, headers = signed_up_kit(FakeVerifier())

    assert kit.client.post(VERIFY, json={"id_token": PROOF}).status_code == 401
    assert kit.client.post(VERIFY, json={"id_token": PROOF}, headers=kit.elder_headers(12)).status_code == 401
    assert kit.client.post(VERIFY, json={"id_token": "short"}, headers=headers).status_code == 422
    assert kit.client.post(VERIFY, json={"id_token": "x" * 5000}, headers=headers).status_code == 422


# ------------------------------------------------ 게이트


def test_an_unverified_guardian_is_blocked_even_after_the_operator_opened_them():
    kit, _, headers = signed_up_kit(FakeVerifier())
    kit.data.accounts.activate(guardian_id_of(kit))

    for response in (
        kit.client.post("/v1/guardian/invite", headers=headers),
        kit.client.post("/v1/elders/12/approve", headers=headers),
        kit.client.post("/v1/guardian/link/preview", json={"code": "12345678"}, headers=headers),
        kit.client.post("/v1/guardian/link", json={"code": "12345678"}, headers=headers),
        kit.client.post("/v1/guardian/devices", json={"token": "t" * 30}, headers=headers),
    ):
        assert response.status_code == 403 and response.json() == NEEDS_EMAIL


def test_the_email_message_comes_first_and_the_operator_message_second():
    kit, _, headers = signed_up_kit(FakeVerifier({PROOF: GOOD["email"]}))

    assert kit.client.post("/v1/guardian/invite", headers=headers).json() == NEEDS_EMAIL

    kit.client.post(VERIFY, json={"id_token": PROOF}, headers=headers)  # 이메일은 인증, 운영자는 아직

    refused = kit.client.post("/v1/guardian/invite", headers=headers)
    assert refused.status_code == 403 and refused.json() == NEEDS_OPERATOR


def test_both_checks_are_needed_neither_stands_in_for_the_other():
    kit, _, headers = signed_up_kit(FakeVerifier({PROOF: GOOD["email"]}))
    kit.client.post(VERIFY, json={"id_token": PROOF}, headers=headers)
    assert kit.client.post("/v1/guardian/invite", headers=headers).status_code == 403  # 인증만으로는 안 된다

    kit.data.accounts.activate(guardian_id_of(kit))

    assert kit.client.post("/v1/guardian/invite", headers=headers).status_code == 200


def test_unverified_guardians_can_still_log_in_and_read_their_own_list():
    kit, _, headers = signed_up_kit(FakeVerifier())

    assert kit.client.get("/v1/guardian/elders", headers=headers).status_code == 200
    assert kit.client.get(ME, headers=headers).status_code == 200


def test_the_legacy_and_key_only_guardians_are_not_affected():
    kit = make_app_kit()  # 보호자 1은 계정 표에 없는 열쇠 전용 보호자다

    assert kit.client.post("/v1/guardian/invite", headers=kit.guardian_headers).status_code == 200


def test_the_whole_flow_never_logs_the_proof_or_the_email(caplog):
    kit, _, headers = signed_up_kit(FakeVerifier({PROOF: GOOD["email"]}))

    with caplog.at_level(logging.DEBUG):
        kit.client.post(VERIFY, json={"id_token": "q" * 40}, headers=headers)
        kit.client.post(VERIFY, json={"id_token": PROOF}, headers=headers)

    assert PROOF not in caplog.text and "q" * 40 not in caplog.text
    assert GOOD["email"] not in caplog.text
