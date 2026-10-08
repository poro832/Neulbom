"""어르신 조회 — 누구의 어르신인가, 동의했는가.

수동 요청의 세 번째, 네 번째 문(소유, 동의)이 쓴다. 통화 저장소와 따로 둔
이유: 통화 저장소의 `find_elder`는 전화번호를 환경 변수 명부에서 읽고, 보호자와
동의는 DB의 `elders` 표에만 있다. 둘은 출처가 다르다.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ElderAccess:
    guardian_id: int
    consenting: bool


class ElderDirectory(Protocol):
    def get(self, elder_id: int) -> ElderAccess | None: ...


class DirectoryAdmin(Protocol):
    """운영 도구(`python -m app.admin`)가 쓴다. 동의는 여기서 바꾸지 않는다."""

    def add_guardian(self, name: str, phone: str) -> int: ...
    def assign_elder(self, elder_id: int, guardian_id: int) -> bool: ...
    def guardian_exists(self, guardian_id: int) -> bool: ...


class InMemoryElderDirectory:
    def __init__(self, entries: dict[int, ElderAccess] | None = None) -> None:
        self._entries = dict(entries or {})
        self._guardians = {access.guardian_id for access in self._entries.values()}
        self._lock = threading.Lock()
        self._next_guardian = max(self._guardians, default=0) + 1

    def get(self, elder_id: int) -> ElderAccess | None:
        return self._entries.get(elder_id)

    def add_guardian(self, name: str, phone: str) -> int:
        with self._lock:
            guardian_id = self._next_guardian
            self._next_guardian += 1
            self._guardians.add(guardian_id)
            return guardian_id

    def guardian_exists(self, guardian_id: int) -> bool:
        return guardian_id in self._guardians

    def assign_elder(self, elder_id: int, guardian_id: int) -> bool:
        with self._lock:
            old = self._entries.get(elder_id)
            if old is None or guardian_id not in self._guardians:
                return False
            self._entries[elder_id] = ElderAccess(guardian_id, old.consenting)
            return True
