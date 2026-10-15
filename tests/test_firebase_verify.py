"""Firebase ID 토큰 확인 — 서명 검사는 라이브러리에 맡기고, 우리가 정한 조건을 시험한다."""

from __future__ import annotations

import logging

from app.firebase_verify import FirebaseEmailVerifier, VerifiedEmail, verifier_from_env

PROJECT = "demo-project"


def claims(**over):
    base = {
        "iss": f"https://securetoken.google.com/{PROJECT}",
        "aud": PROJECT,
        "sub": "uid-1",
        "email": "Kim@Example.com",
        "email_verified": True,
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
    for key in ("iss", "aud", "sub", "email", "email_verified"):
        data = claims()
        del data[key]
        assert verifier_returning(data).verify("tok") is None, key


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
