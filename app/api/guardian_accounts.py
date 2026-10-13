"""보호자 계정 저장소 — 이메일·비밀번호 해시·전화번호 (설계: 보호자 계정).

이메일은 소문자·앞뒤 공백 제거로 정규화해 저장하고 조회한다. 비밀번호 원문은 이 계층에
오지 않는다 — 해시(passwords.py)만 받는다.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, replace
from typing import Protocol


class EmailTaken(Exception):
    """이미 쓰는 이메일이다."""


@dataclass(frozen=True)
class Account:
    guardian_id: int
    name: str
    email: str
    phone: str
    password_hash: str


def normalize_email(email: str) -> str:
    return email.strip().lower()


class GuardianAccounts(Protocol):
    def create(self, name: str, email: str, phone: str, password_hash: str) -> int:
        """새 보호자를 만든다. 이메일이 이미 있으면 EmailTaken."""
        ...

    def find_by_email(self, email: str) -> Account | None: ...

    def profile(self, guardian_id: int) -> Account | None: ...

    def set_password(self, guardian_id: int, password_hash: str) -> None: ...

    def set_login(self, guardian_id: int, email: str, password_hash: str) -> bool:
        """운영 도구가 만든 보호자에게 이메일과 비밀번호를 붙인다. 보호자가 없으면 False."""
        ...


class InMemoryGuardianAccounts:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._rows: dict[int, Account] = {}
        self._next = 1

    def create(self, name: str, email: str, phone: str, password_hash: str) -> int:
        email = normalize_email(email)
        with self._lock:
            if any(a.email == email for a in self._rows.values()):
                raise EmailTaken(email)
            gid = self._next
            self._next += 1
            self._rows[gid] = Account(gid, name, email, phone, password_hash)
            return gid

    def find_by_email(self, email: str) -> Account | None:
        email = normalize_email(email)
        with self._lock:
            return next((a for a in self._rows.values() if a.email == email), None)

    def profile(self, guardian_id: int) -> Account | None:
        with self._lock:
            return self._rows.get(guardian_id)

    def set_password(self, guardian_id: int, password_hash: str) -> None:
        with self._lock:
            if guardian_id in self._rows:
                self._rows[guardian_id] = replace(self._rows[guardian_id], password_hash=password_hash)

    def set_login(self, guardian_id: int, email: str, password_hash: str) -> bool:
        email = normalize_email(email)
        with self._lock:
            if guardian_id not in self._rows:
                return False
            if any(a.email == email and a.guardian_id != guardian_id for a in self._rows.values()):
                raise EmailTaken(email)
            self._rows[guardian_id] = replace(
                self._rows[guardian_id], email=email, password_hash=password_hash
            )
            return True
