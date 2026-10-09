"""어르신 조회 — 누구의 어르신인가, 동의했는가, 전화번호로 누구인가.

수동 요청의 세 번째, 네 번째 문(소유, 동의)과 앱 연결(전화번호 확인), 보호자 화면의
어르신 목록이 쓴다. 통화 저장소와 따로 둔 이유: 통화 저장소의 `find_elder`는 전화번호를
환경 변수 명부에서 읽고, 보호자와 동의는 DB의 `elders` 표에만 있다. 둘은 출처가 다르다.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, replace
from typing import Protocol


@dataclass(frozen=True)
class ElderAccess:
    guardian_id: int
    consenting: bool
    name: str = ""


@dataclass(frozen=True)
class ElderRef:
    elder_id: int
    name: str


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
        self._phones = {elder_id: digits_of(phone) for elder_id, phone in (phones or {}).items()}
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
            ElderRef(elder_id=elder_id, name=access.name)
            for elder_id, access in sorted(self._entries.items())
            if access.guardian_id == guardian_id
        ]

    def guardian_profile(self, guardian_id: int) -> GuardianProfile | None:
        return self._profiles.get(guardian_id)

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
