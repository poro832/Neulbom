"""보호자 비밀번호 해시 — 표준 라이브러리 scrypt (설계: 보호자 계정).

저장 모양: `scrypt$<N>$<r>$<p>$<salt(base64)>$<해시(base64)>`. 원문은 어디에도 남기지 않는다.
운영 도구가 만든 보호자의 `password_hash`는 `NO_LOGIN`이라 어떤 비밀번호로도 맞지 않는다.
검증은 어떤 입력에도 예외를 내지 않고 False만 돌려준다 — 깨진 행 하나가 로그인 오류로 번지지 않게.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

NO_LOGIN = "not-a-login"

_N = 2**14
_R = 8
_P = 1
_SALT_BYTES = 16
_KEY_BYTES = 32
_SCHEME = "scrypt"


def _derive(password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    return hashlib.scrypt(password.encode("utf-8"), salt=salt, n=n, r=r, p=p, dklen=_KEY_BYTES)


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(_SALT_BYTES)
    digest = _derive(password, salt, _N, _R, _P)
    return "$".join(
        [
            _SCHEME,
            str(_N),
            str(_R),
            str(_P),
            base64.b64encode(salt).decode("ascii"),
            base64.b64encode(digest).decode("ascii"),
        ]
    )


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt_b64, digest_b64 = stored.split("$")
        if scheme != _SCHEME:
            return False
        salt = base64.b64decode(salt_b64, validate=True)
        expected = base64.b64decode(digest_b64, validate=True)
        actual = _derive(password, salt, int(n), int(r), int(p))
    except Exception:
        return False
    return hmac.compare_digest(actual, expected)


# 없는 이메일도 같은 시간이 걸리게 하려고 비교할 가짜 해시를 하나 만들어 둔다.
DUMMY_HASH = hash_password("dummy-for-timing")
