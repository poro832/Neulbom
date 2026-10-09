"""어르신 열쇠 — 연결 코드로 받은 폰 전용 열쇠 (설계: 앱 화면을 실제 데이터로).

보호자 열쇠(`guardian_auth.py`)와 같은 방식이다: 256비트 무작위, DB에는 SHA-256 지문만,
목록과 로그에는 앞 12글자만. 접두어가 달라서(`nle_`) 어르신 열쇠를 보호자 주소에 내밀면
형식 검사에서 바로 떨어진다. 어르신 한 명에게 열쇠는 하나만 산다 — 새로 연결하면 이전
폰의 열쇠가 폐기된다(분실한 폰을 끊는 방법이다).
"""

from __future__ import annotations

import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from app.api.guardian_auth import hash_key, parse_bearer

ELDER_KEY_PREFIX = "nle_"
ELDER_KEY_LENGTH = len(ELDER_KEY_PREFIX) + 43  # token_urlsafe(32)는 항상 43글자다
_SHOWN = len(ELDER_KEY_PREFIX) + 8
_UNREADABLE = "(형식 오류)"


@dataclass(frozen=True)
class NewElderKey:
    key: str  # 전체 열쇠 — 만든 순간에만 존재한다
    key_prefix: str
    key_hash: str


def generate_elder_key() -> NewElderKey:
    key = ELDER_KEY_PREFIX + secrets.token_urlsafe(32)
    return NewElderKey(key=key, key_prefix=key[:_SHOWN], key_hash=hash_key(key))


def _looks_like_elder_key(candidate: str) -> bool:
    return candidate.startswith(ELDER_KEY_PREFIX) and len(candidate) == ELDER_KEY_LENGTH


def elder_key_label(authorization: str | None) -> str:
    """틀린 시도를 로그에 남길 때 쓰는 이름. 앞 12글자까지만 보인다."""
    key = parse_bearer(authorization)
    if key is None or not _looks_like_elder_key(key):
        return _UNREADABLE
    return key[:_SHOWN]


class ElderKeyStore(Protocol):
    def replace(self, *, elder_id: int, key_prefix: str, key_hash: str) -> None:
        """그 어르신의 사용 중인 열쇠를 모두 폐기하고 새 열쇠를 넣는다. 같은 지문이면 예외."""
        ...

    def find_elder(self, key_hash: str) -> int | None:
        """폐기되지 않은 열쇠의 주인. 찾으면 마지막 사용 시각을 갱신한다."""
        ...

    def last_used_at(self, key_hash: str) -> float | None: ...


class InMemoryElderKeyStore:
    def __init__(self, wall_clock: Callable[[], float] = time.time) -> None:
        self._clock = wall_clock
        self._lock = threading.Lock()
        self._rows: dict[str, dict] = {}

    def replace(self, *, elder_id: int, key_prefix: str, key_hash: str) -> None:
        with self._lock:
            if key_hash in self._rows:
                raise ValueError("이미 있는 열쇠 지문이다")
            for row in self._rows.values():
                if row["elder_id"] == elder_id and row["revoked_at"] is None:
                    row["revoked_at"] = self._clock()
            self._rows[key_hash] = {
                "elder_id": elder_id,
                "key_prefix": key_prefix,
                "revoked_at": None,
                "last_used_at": None,
            }

    def find_elder(self, key_hash: str) -> int | None:
        with self._lock:
            row = self._rows.get(key_hash)
            if row is None or row["revoked_at"] is not None:
                return None
            row["last_used_at"] = self._clock()
            return row["elder_id"]

    def last_used_at(self, key_hash: str) -> float | None:
        with self._lock:
            row = self._rows.get(key_hash)
            return None if row is None else row["last_used_at"]


class ElderAuth(Protocol):
    def authenticate(self, authorization: str | None) -> int | None:
        """요청 머리의 Authorization 값으로 어르신 번호를 알아낸다. 모르면 None."""
        ...


class ElderKeyAuth:
    def __init__(self, store: ElderKeyStore) -> None:
        self._store = store

    def authenticate(self, authorization: str | None) -> int | None:
        key = parse_bearer(authorization)
        if key is None or not _looks_like_elder_key(key):
            # 형식이 틀리면 저장소를 보지 않는다. 열쇠를 찍어 보는 요청이 DB를 두드리게 두지 않는다.
            return None
        return self._store.find_elder(hash_key(key))
