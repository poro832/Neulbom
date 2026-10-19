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
    activated: bool = True  # 운영자가 열어 준 보호자만 어르신을 등록·승인할 수 있다
    email_verified: bool = True  # 앱에서 가입한 보호자는 Firebase로 이메일을 증명하기 전까지 False


def normalize_email(email: str) -> str:
    return email.strip().lower()


class GuardianAccounts(Protocol):
    def create(
        self,
        name: str,
        email: str,
        phone: str,
        password_hash: str,
        *,
        activated: bool = False,
        email_verified: bool | None = None,
    ) -> int:
        """새 보호자를 만든다. 이메일이 이미 있으면 EmailTaken. 기본은 운영자 확인 대기·이메일 인증 전이다.

        email_verified를 안 주면 activated를 따른다: 운영 도구가 열어서 만든 보호자는 이메일도 인증된 것으로 본다.
        """
        ...

    def mark_email_verified(self, guardian_id: int) -> bool:
        """이메일 인증을 마친 것으로 기록한다. 보호자가 없으면 False."""
        ...

    def activate(self, guardian_id: int) -> bool:
        """운영자가 보호자를 연다. 보호자가 없으면 False."""
        ...

    def pending(self) -> list[Account]:
        """아직 열리지 않은 보호자(가입 순서대로)."""
        ...

    def find_by_email(self, email: str) -> Account | None: ...

    def profile(self, guardian_id: int) -> Account | None: ...

    def set_password(self, guardian_id: int, password_hash: str) -> None: ...

    def set_login(self, guardian_id: int, email: str, password_hash: str) -> bool:
        """운영 도구가 만든 보호자에게 이메일과 비밀번호를 붙인다(열린 상태가 된다). 보호자가 없으면 False."""
        ...

    def delete(self, guardian_id: int) -> bool:
        """보호자 계정을 지운다(탈퇴). 지웠으면 True, 없으면 False. 이메일은 다시 가입할 수 있게 풀린다.

        **반드시 ElderDirectory.detach_all_from을 먼저 부른다.** Postgres에서는 열쇠·폰 등록·개인 코드·알림이
        CASCADE로 같이 지워지는데, elders.guardian_id도 CASCADE라 연결된 어르신이 남아 있으면 어르신까지 지워진다.
        그래서 Postgres 구현은 어르신이 하나라도 남아 있으면 지우지 않고 False다(안전장치).
        """
        ...


class InMemoryGuardianAccounts:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._rows: dict[int, Account] = {}
        self._next = 1

    def create(
        self,
        name: str,
        email: str,
        phone: str,
        password_hash: str,
        *,
        activated: bool = False,
        email_verified: bool | None = None,
    ) -> int:
        email = normalize_email(email)
        verified = activated if email_verified is None else email_verified
        with self._lock:
            if any(a.email == email for a in self._rows.values()):
                raise EmailTaken(email)
            gid = self._next
            self._next += 1
            self._rows[gid] = Account(gid, name, email, phone, password_hash, activated, verified)
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

    def activate(self, guardian_id: int) -> bool:
        with self._lock:
            if guardian_id not in self._rows:
                return False
            self._rows[guardian_id] = replace(self._rows[guardian_id], activated=True)
            return True

    def mark_email_verified(self, guardian_id: int) -> bool:
        with self._lock:
            if guardian_id not in self._rows:
                return False
            self._rows[guardian_id] = replace(self._rows[guardian_id], email_verified=True)
            return True

    def pending(self) -> list[Account]:
        with self._lock:
            return [a for a in self._rows.values() if not a.activated]

    def set_login(self, guardian_id: int, email: str, password_hash: str) -> bool:
        email = normalize_email(email)
        with self._lock:
            if guardian_id not in self._rows:
                return False
            if any(a.email == email and a.guardian_id != guardian_id for a in self._rows.values()):
                raise EmailTaken(email)
            self._rows[guardian_id] = replace(
                self._rows[guardian_id], email=email, password_hash=password_hash, activated=True, email_verified=True
            )
            return True

    def delete(self, guardian_id: int) -> bool:
        # 메모리 계정 표는 어르신을 모른다(CASCADE가 없다). 그래도 호출 순서는 Postgres와 같게 한다.
        with self._lock:
            return self._rows.pop(guardian_id, None) is not None
