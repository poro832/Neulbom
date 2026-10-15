"""Firebase ID 토큰(로그인 증명서) 확인 — 보호자 이메일 인증 (설계: 보호자 이메일 인증).

앱이 Firebase에서 이메일을 인증한 뒤 받은 ID 토큰을 서버로 보내면, 서버는 그 토큰이
**우리 Firebase 프로젝트가 서명한 것이고, 이메일이 인증된 상태**인지 확인한다. 서명·만료는
구글 인증 라이브러리가 공개키로 검사하고, 발급자·대상·이메일·로그인 방식 조건은 여기서 따로 검사한다
(라이브러리가 발급자까지 확인해 주지 않는다). 이유가 무엇이든 실패는 None이다 — 어느 조건이
깨졌는지 알려 주지 않고, 토큰은 로그에 남기지 않는다.
"""

from __future__ import annotations

import functools
import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Protocol

logger = logging.getLogger(__name__)

# 구글 공개키를 받아 올 때 기다리는 시간. 라이브러리 기본값(120초)이면 구글 응답이 느릴 때
# 확인 하나가 작업 스레드를 2분씩 붙잡는다. 5초가 넘으면 그만두고 확인 실패로 본다.
CERT_FETCH_TIMEOUT_SECONDS = 5

# 앱은 이메일+비밀번호로 Firebase에 로그인한다. 다른 방식(직접 만든 토큰·익명·구글 등)의 증명서는 받지 않는다.
SIGN_IN_PROVIDER = "password"


@functools.cache
def _short_timeout_request_class():
    # requests를 늦게 불러온다: 없어도 서버는 뜨고, 확인할 때만 실패한다(test가 설치를 따로 지킨다).
    from google.auth.transport import requests as google_requests

    class ShortTimeoutRequest(google_requests.Request):
        """시간 제한을 주지 않은 요청(공개키 받기)에 120초 대신 5초를 쓴다."""

        def __call__(self, url, method="GET", body=None, headers=None, timeout=CERT_FETCH_TIMEOUT_SECONDS, **kwargs):
            return super().__call__(url, method=method, body=body, headers=headers, timeout=timeout, **kwargs)

    return ShortTimeoutRequest


@dataclass(frozen=True)
class VerifiedEmail:
    email: str  # 토큰에 적힌 그대로. 비교는 부르는 쪽이 정규화해서 한다.


class EmailVerifier(Protocol):
    def verify(self, id_token: str) -> VerifiedEmail | None: ...


class FirebaseEmailVerifier:
    def __init__(self, project_id: str, *, decode: Callable[[str], dict] | None = None) -> None:
        self._project_id = project_id
        self._decode = decode or self._google_decode

    def _google_decode(self, token: str) -> dict:
        from google.oauth2 import id_token as google_id_token

        return google_id_token.verify_firebase_token(
            token, _short_timeout_request_class()(), audience=self._project_id, clock_skew_in_seconds=10
        )

    def verify(self, id_token: str) -> VerifiedEmail | None:
        try:
            claims = self._decode(id_token)
        except Exception:
            # 만료·변조·공개키 수신 실패가 모두 여기로 온다. 이유와 토큰은 남기지 않는다.
            logger.warning("Firebase 증명서를 확인하지 못했다")
            return None
        if not isinstance(claims, dict):
            return None
        if claims.get("iss") != f"https://securetoken.google.com/{self._project_id}":
            return None
        if claims.get("aud") != self._project_id:
            return None
        if claims.get("email_verified") is not True:
            return None
        sub = claims.get("sub")
        if not isinstance(sub, str) or not sub:
            return None
        firebase = claims.get("firebase")
        if not isinstance(firebase, dict) or firebase.get("sign_in_provider") != SIGN_IN_PROVIDER:
            return None
        email = claims.get("email")
        if not isinstance(email, str) or not email.strip():
            return None
        return VerifiedEmail(email=email)


def verifier_from_env(env: Mapping[str, str]) -> EmailVerifier | None:
    """FIREBASE_PROJECT_ID(비밀이 아니다)가 없으면 None — 이메일 인증 주소만 닫히고 서버는 정상으로 뜬다."""
    project_id = env.get("FIREBASE_PROJECT_ID", "").strip()
    return FirebaseEmailVerifier(project_id) if project_id else None
