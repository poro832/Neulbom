"""어르신 조회 — 누구의 어르신인가, 동의했는가, 전화번호로 누구인가, 가입·승인.

수동 요청의 세 번째, 네 번째 문(소유, 동의)과 앱 연결, 보호자 화면의 어르신 목록,
보호자 코드 가입이 쓴다. 통화 저장소와 따로 둔 이유: 보호자와 동의는 DB의 `elders`
표에만 있다.

**상태는 컬럼 조합이다.** 새 상태 컬럼을 두지 않는다.
- active      consent_at이 있다 — 보호자가 승인했거나 운영자가 동의를 기록했다.
- pending     agreed_at만 있다 — 어르신이 가입하며 동의에 체크했고 보호자 승인을 기다린다.
- unconsented 둘 다 없다 — 운영자가 등록한 어르신. 앱에서 승인할 수 없다.
`consent_at`을 채우는 곳은 `approve` 하나다. 가입(`create_pending`)은 절대 채우지 않는다.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, replace
from typing import Protocol

STATUS_ACTIVE = "active"
STATUS_PENDING = "pending"
STATUS_UNCONSENTED = "unconsented"


class PhoneTaken(Exception):
    """이미 등록된 전화번호다(숫자만 비교한다)."""


class PendingLimit(Exception):
    """그 보호자의 승인 대기가 한도에 닿았다."""


@dataclass(frozen=True)
class ElderAccess:
    guardian_id: int
    consenting: bool
    name: str = ""
    agreed: bool = False

    @property
    def status(self) -> str:
        if self.consenting:
            return STATUS_ACTIVE
        return STATUS_PENDING if self.agreed else STATUS_UNCONSENTED


@dataclass(frozen=True)
class ElderRef:
    elder_id: int
    name: str
    status: str = STATUS_ACTIVE
    # 승인 대기일 때만 채운다. 보호자가 "내 부모님 번호가 맞나"를 보고 승인하는 데 쓴다.
    phone: str | None = None


@dataclass(frozen=True)
class GuardianProfile:
    name: str
    phone: str


def digits_of(phone: str) -> str:
    return "".join(ch for ch in phone if ch.isdigit())


class ElderDirectory(Protocol):
    def get(self, elder_id: int) -> ElderAccess | None: ...

    def find_by_phone(self, phone: str) -> int | None:
        """전화번호의 숫자만 비교해 어르신을 찾는다. 하이픈·공백은 무시한다."""
        ...

    def elders_of(self, guardian_id: int) -> list[ElderRef]:
        """그 보호자의 어르신들, elder_id 오름차순."""
        ...

    def guardian_profile(self, guardian_id: int) -> GuardianProfile | None: ...

    def create_pending(
        self, *, guardian_id: int, name: str, phone: str, max_pending: int
    ) -> int:
        """승인 대기 어르신을 만든다. consent_at은 비워 둔다 — 전화가 나가지 않는다.

        번호가 이미 있으면 PhoneTaken, 그 보호자의 대기가 max_pending 이상이면 PendingLimit.
        """
        ...

    def approve(self, elder_id: int, guardian_id: int) -> bool:
        """그 보호자의 승인 대기 어르신일 때만 consent_at을 지금으로 채우고 True."""
        ...

    def reject(self, elder_id: int, guardian_id: int) -> bool:
        """그 보호자의 승인 대기 어르신일 때만 행을 지우고 True."""
        ...


class DirectoryAdmin(Protocol):
    """운영 도구(`python -m app.admin`)가 쓴다. 동의는 여기서 바꾸지 않는다."""

    def add_guardian(self, name: str, phone: str) -> int: ...
    def assign_elder(self, elder_id: int, guardian_id: int) -> bool: ...
    def guardian_exists(self, guardian_id: int) -> bool: ...


class InMemoryElderDirectory:
    def __init__(
        self,
        entries: dict[int, ElderAccess] | None = None,
        *,
        phones: dict[int, str] | None = None,
        guardians: dict[int, GuardianProfile] | None = None,
    ) -> None:
        self._entries = dict(entries or {})
        self._phone_text = dict(phones or {})
        self._phones = {elder_id: digits_of(phone) for elder_id, phone in self._phone_text.items()}
        self._profiles = dict(guardians or {})
        self._guardians = {access.guardian_id for access in self._entries.values()} | set(
            self._profiles
        )
        self._lock = threading.Lock()
        self._next_guardian = max(self._guardians, default=0) + 1

    def get(self, elder_id: int) -> ElderAccess | None:
        return self._entries.get(elder_id)

    def find_by_phone(self, phone: str) -> int | None:
        wanted = digits_of(phone)
        if not wanted:
            return None
        for elder_id, digits in self._phones.items():
            if digits == wanted:
                return elder_id
        return None

    def elders_of(self, guardian_id: int) -> list[ElderRef]:
        return [
            ElderRef(
                elder_id=elder_id,
                name=access.name,
                status=access.status,
                phone=self._phone_text.get(elder_id) if access.status == STATUS_PENDING else None,
            )
            for elder_id, access in sorted(self._entries.items())
            if access.guardian_id == guardian_id
        ]

    def guardian_profile(self, guardian_id: int) -> GuardianProfile | None:
        return self._profiles.get(guardian_id)

    def create_pending(
        self, *, guardian_id: int, name: str, phone: str, max_pending: int
    ) -> int:
        with self._lock:
            wanted = digits_of(phone)
            if any(digits == wanted for digits in self._phones.values()):
                raise PhoneTaken(wanted)
            pending = sum(
                1
                for access in self._entries.values()
                if access.guardian_id == guardian_id and access.status == STATUS_PENDING
            )
            if pending >= max_pending:
                raise PendingLimit(guardian_id)
            elder_id = max(self._entries, default=0) + 1
            self._entries[elder_id] = ElderAccess(guardian_id, False, name, agreed=True)
            self._phone_text[elder_id] = phone
            self._phones[elder_id] = wanted
            self._guardians.add(guardian_id)
            return elder_id

    def _pending_of(self, elder_id: int, guardian_id: int) -> ElderAccess | None:
        access = self._entries.get(elder_id)
        if access is None or access.guardian_id != guardian_id or access.status != STATUS_PENDING:
            return None
        return access

    def approve(self, elder_id: int, guardian_id: int) -> bool:
        with self._lock:
            access = self._pending_of(elder_id, guardian_id)
            if access is None:
                return False
            self._entries[elder_id] = replace(access, consenting=True)
            return True

    def reject(self, elder_id: int, guardian_id: int) -> bool:
        with self._lock:
            if self._pending_of(elder_id, guardian_id) is None:
                return False
            del self._entries[elder_id]
            self._phone_text.pop(elder_id, None)
            self._phones.pop(elder_id, None)
            return True

    def add_guardian(self, name: str, phone: str) -> int:
        with self._lock:
            guardian_id = self._next_guardian
            self._next_guardian += 1
            self._guardians.add(guardian_id)
            self._profiles[guardian_id] = GuardianProfile(name=name, phone=phone)
            return guardian_id

    def guardian_exists(self, guardian_id: int) -> bool:
        return guardian_id in self._guardians

    def assign_elder(self, elder_id: int, guardian_id: int) -> bool:
        with self._lock:
            old = self._entries.get(elder_id)
            if old is None or guardian_id not in self._guardians:
                return False
            self._entries[elder_id] = replace(old, guardian_id=guardian_id)
            return True
