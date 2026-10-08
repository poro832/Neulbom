"""보호자 요청 인증 — 개인 열쇠 (설계: 노션 「설계 — 보호자 요청 인증」).

**왜 열쇠인가.** `/v1/calls/request`는 누구나 부를 수 있어 아무나 어르신께 전화를
걸게 할 수 있었다. 보호자마다 다른 열쇠를 주고, 서버가 요청마다 "누구의
요청인가"를 알아낸다. 지금은 열쇠로, 나중에는 로그인으로 — 신원을 알아내는
한 곳(`GuardianAuth`)만 바뀌고 나머지는 그대로다.

**열쇠는 DB에 지문으로만 둔다.** 열쇠가 256비트 무작위라 느린 해시가 필요 없다.
SHA-256 지문으로 바로 찾는다. 전체 열쇠는 발급할 때 한 번 보이고 어디에도
남지 않는다 — 로그와 목록에는 앞 12글자(`key_prefix`)만 나온다.
"""

from __future__ import annotations

import hashlib
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

KEY_PREFIX = "nlb_"
_RANDOM_CHARS = 43  # secrets.token_urlsafe(32)는 항상 43글자다
KEY_LENGTH = len(KEY_PREFIX) + _RANDOM_CHARS  # 47
PREFIX_RANDOM_CHARS = 8
# 폐기할 때 받는 앞부분의 최소 길이. 너무 짧으면 엉뚱한 열쇠를 폐기한다.
MIN_REVOKE_PREFIX = len(KEY_PREFIX) + 4
_UNREADABLE = "(형식 오류)"


class AmbiguousPrefix(Exception):
    """앞부분이 여러 열쇠와 겹친다. 하나만 가리킬 때까지 늘려서 다시 할 것."""


@dataclass(frozen=True)
class KeyInfo:
    key_id: int
    guardian_id: int
    key_prefix: str
    label: str
    created_at: float
    revoked_at: float | None
    last_used_at: float | None


@dataclass(frozen=True)
class NewKey:
    key: str  # 전체 열쇠 — 만든 순간에만 존재한다
    key_prefix: str
    key_hash: str


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def generate_key() -> NewKey:
    key = KEY_PREFIX + secrets.token_urlsafe(32)
    return NewKey(
        key=key,
        key_prefix=key[: len(KEY_PREFIX) + PREFIX_RANDOM_CHARS],
        key_hash=hash_key(key),
    )


def parse_bearer(authorization: str | None) -> str | None:
    """`Authorization: Bearer <열쇠>`에서 열쇠를 꺼낸다. 아니면 None."""
    if not authorization:
        return None
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    return parts[1]


def looks_like_key(candidate: str) -> bool:
    return candidate.startswith(KEY_PREFIX) and len(candidate) == KEY_LENGTH


def attempt_label(authorization: str | None) -> str:
    """틀린 시도를 로그에 남길 때 쓰는 이름. 앞 12글자까지만 보인다."""
    key = parse_bearer(authorization)
    if key is None or not looks_like_key(key):
        return _UNREADABLE
    return key[: len(KEY_PREFIX) + PREFIX_RANDOM_CHARS]


def check_prefix(prefix: str) -> None:
    if len(prefix) < MIN_REVOKE_PREFIX:
        raise ValueError(
            f"앞부분이 너무 짧다 — 최소 {MIN_REVOKE_PREFIX}글자 "
            f"(예: {KEY_PREFIX}xxxxxxxx). 엉뚱한 열쇠를 폐기하지 않으려는 제한이다"
        )


class GuardianKeyStore(Protocol):
    def add(self, *, guardian_id: int, label: str, key_prefix: str, key_hash: str) -> int:
        """열쇠의 지문을 저장한다. 같은 지문이 있으면 예외."""
        ...

    def find_guardian(self, key_hash: str) -> int | None:
        """폐기되지 않은 열쇠의 주인. 찾으면 마지막 사용 시각을 갱신한다."""
        ...

    def list_keys(self) -> list[KeyInfo]: ...

    def revoke(self, prefix: str) -> int:
        """앞부분이 일치하는 열쇠를 폐기하고 폐기한 수(0 또는 1)를 돌려준다.

        둘 이상과 겹치면 AmbiguousPrefix, 너무 짧으면 ValueError.
        """
        ...


class InMemoryGuardianKeyStore:
    def __init__(self, wall_clock: Callable[[], float] = time.time) -> None:
        self._clock = wall_clock
        self._lock = threading.Lock()
        self._rows: dict[int, dict] = {}
        self._next_id = 1

    def add(self, *, guardian_id: int, label: str, key_prefix: str, key_hash: str) -> int:
        with self._lock:
            if any(row["key_hash"] == key_hash for row in self._rows.values()):
                raise ValueError("이미 있는 열쇠 지문이다")
            key_id = self._next_id
            self._next_id += 1
            self._rows[key_id] = {
                "key_id": key_id,
                "guardian_id": guardian_id,
                "key_prefix": key_prefix,
                "key_hash": key_hash,
                "label": label,
                "created_at": self._clock(),
                "revoked_at": None,
                "last_used_at": None,
            }
            return key_id

    def find_guardian(self, key_hash: str) -> int | None:
        with self._lock:
            for row in self._rows.values():
                if row["key_hash"] == key_hash and row["revoked_at"] is None:
                    row["last_used_at"] = self._clock()
                    return row["guardian_id"]
        return None

    def list_keys(self) -> list[KeyInfo]:
        with self._lock:
            return [
                KeyInfo(
                    key_id=row["key_id"],
                    guardian_id=row["guardian_id"],
                    key_prefix=row["key_prefix"],
                    label=row["label"],
                    created_at=row["created_at"],
                    revoked_at=row["revoked_at"],
                    last_used_at=row["last_used_at"],
                )
                for row in self._rows.values()
            ]

    def revoke(self, prefix: str) -> int:
        check_prefix(prefix)
        with self._lock:
            hits = [
                row
                for row in self._rows.values()
                if row["revoked_at"] is None and row["key_prefix"].startswith(prefix)
            ]
            if len(hits) > 1:
                raise AmbiguousPrefix(prefix)
            if not hits:
                return 0
            hits[0]["revoked_at"] = self._clock()
            return 1


class GuardianAuth(Protocol):
    def authenticate(self, authorization: str | None) -> int | None:
        """요청 머리의 Authorization 값으로 보호자 번호를 알아낸다. 모르면 None.

        **갈아 끼우는 자리다.** 나중에 로그인 출입증을 쓰게 되면 이 규약을 지키는
        다른 구현으로 바꾸고, 나머지(소유, 동의, 횟수)는 그대로 둔다.
        """
        ...


class KeyAuth:
    def __init__(self, store: GuardianKeyStore) -> None:
        self._store = store

    def authenticate(self, authorization: str | None) -> int | None:
        key = parse_bearer(authorization)
        if key is None or not looks_like_key(key):
            # 형식이 틀리면 저장소를 보지 않는다. 열쇠를 찍어 보는 요청이
            # DB를 두드리게 두지 않는다.
            return None
        return self._store.find_guardian(hash_key(key))
