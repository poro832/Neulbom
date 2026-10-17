"""Firebase ID 토큰 확인 — 서명 검사는 라이브러리에 맡기고, 우리가 정한 조건을 시험한다."""

from __future__ import annotations

import logging

from app import firebase_verify
from app.firebase_verify import FirebaseEmailVerifier, VerifiedEmail, verifier_from_env

PROJECT = "demo-project"


def claims(**over):
    base = {
        "iss": f"https://securetoken.google.com/{PROJECT}",
        "aud": PROJECT,
        "sub": "uid-1",
        "email": "Kim@Example.com",
        "email_verified": True,
        "firebase": {"sign_in_provider": "password"},  # 앱은 이메일+비밀번호로 Firebase에 로그인한다
    }
    base.update(over)
    return base


def verifier_returning(value):
    return FirebaseEmailVerifier(PROJECT, decode=lambda token: value)


def test_a_valid_verified_token_gives_the_email():
    assert verifier_returning(claims()).verify("tok") == VerifiedEmail(email="Kim@Example.com")


def test_each_broken_condition_is_refused():
    for broken in (
        claims(iss="https://securetoken.google.com/other-project"),
        claims(aud="other-project"),
        claims(email_verified=False),
        claims(email_verified="true"),  # 문자열 "true"는 인정하지 않는다
        claims(sub=""),
        claims(email=""),
        claims(email=None),
        {},
        None,
    ):
        assert verifier_returning(broken).verify("tok") is None, broken


def test_a_missing_claim_is_refused():
    for key in ("iss", "aud", "sub", "email", "email_verified", "firebase"):
        data = claims()
        del data[key]
        assert verifier_returning(data).verify("tok") is None, key


def test_only_an_email_and_password_sign_in_is_accepted():
    """다른 로그인 방식(직접 만든 토큰·익명·구글 등)은 우리 앱이 받은 증명서가 아니다."""
    for firebase in (
        {"sign_in_provider": "custom"},
        {"sign_in_provider": "anonymous"},
        {"sign_in_provider": "google.com"},
        {"sign_in_provider": "Password"},  # 대소문자가 다르면 다른 값이다
        {"sign_in_provider": ""},
        {"sign_in_provider": None},
        {},
        {"identities": {"email": ["kim@example.com"]}},
        None,
        "password",
        ["password"],
    ):
        assert verifier_returning(claims(firebase=firebase)).verify("tok") is None, firebase


def test_the_subject_must_be_a_non_empty_string():
    for sub in (None, "", 0, 1, 12345, True, ["uid-1"], {"uid": "uid-1"}):
        assert verifier_returning(claims(sub=sub)).verify("tok") is None, sub


def test_an_integer_auth_time_is_passed_on():
    """비밀번호 재설정은 방금 로그인했는지(auth_time)를 본다. 이메일 인증은 이 값을 쓰지 않는다."""
    assert verifier_returning(claims(auth_time=1_800_000_000)).verify("tok") == VerifiedEmail(
        email="Kim@Example.com", auth_time=1_800_000_000
    )


def test_a_missing_or_non_integer_auth_time_is_none_and_the_email_still_verifies():
    for over in ({}, {"auth_time": "1800000000"}, {"auth_time": True}, {"auth_time": False},
                 {"auth_time": 1_800_000_000.5}, {"auth_time": None}, {"auth_time": [1]}):
        assert verifier_returning(claims(**over)).verify("tok") == VerifiedEmail(email="Kim@Example.com"), over


def test_a_decode_failure_is_none_and_the_token_is_never_logged(caplog):
    def boom(token):
        raise ValueError("Token expired: " + token)

    verifier = FirebaseEmailVerifier(PROJECT, decode=boom)

    with caplog.at_level(logging.DEBUG):
        assert verifier.verify("SECRET-TOKEN-VALUE") is None

    assert "SECRET-TOKEN-VALUE" not in caplog.text


def test_the_factory_reads_the_project_id_and_stays_off_without_it():
    assert verifier_from_env({}) is None
    assert verifier_from_env({"FIREBASE_PROJECT_ID": "   "}) is None
    assert isinstance(verifier_from_env({"FIREBASE_PROJECT_ID": PROJECT}), FirebaseEmailVerifier)


def test_the_google_transport_the_real_decoder_needs_is_installed():
    """배포 때 `requests`가 빠지면 실서버에서만 인증이 전부 실패한다 — 여기서 먼저 잡는다."""
    from google.auth.transport import requests as google_requests
    from google.oauth2 import id_token

    assert google_requests.Request and id_token.verify_firebase_token


class FakeSession:
    """구글에 실제로 닿지 않고, 통로가 보낸 요청의 시간 제한만 적어 둔다."""

    def __init__(self):
        self.sent = []

    def request(self, method, url, **kwargs):
        self.sent.append({"method": method, "url": url, **kwargs})
        return type("FakeResponse", (), {"status_code": 200, "headers": {}, "content": b"{}", "text": "{}"})()

    def close(self):
        pass


def test_the_real_decoder_asks_google_with_our_project_and_a_short_timeout(monkeypatch):
    """구글 기본값은 120초다 — 공개키가 느리게 오면 작업 스레드가 2분씩 묶인다. 5초면 그만둔다."""
    from google.oauth2 import id_token

    seen = {}

    def fake_verify_firebase_token(token, request, audience=None, clock_skew_in_seconds=0):
        seen.update(token=token, request=request, audience=audience)
        return claims()

    monkeypatch.setattr(id_token, "verify_firebase_token", fake_verify_firebase_token)

    assert FirebaseEmailVerifier(PROJECT).verify("tok") == VerifiedEmail(email="Kim@Example.com")
    assert seen["token"] == "tok"
    assert seen["audience"] == PROJECT

    # 라이브러리는 공개키를 받을 때 시간 제한을 주지 않는다 — 통로의 기본값이 그대로 쓰인다.
    transport = seen["request"]
    transport.session = FakeSession()
    transport("https://www.googleapis.com/robot/v1/metadata/x509/securetoken@system.gserviceaccount.com")
    assert transport.session.sent[0]["timeout"] == 5
    assert firebase_verify.CERT_FETCH_TIMEOUT_SECONDS == 5

    # 부르는 쪽이 시간 제한을 직접 주면 그 값을 쓴다.
    transport("https://example.invalid/certs", timeout=1)
    assert transport.session.sent[1]["timeout"] == 1
