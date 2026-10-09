"""어르신이 직접 추가한 비상 연락처 (설계: 앱 화면을 실제 데이터로).

보호자(DB의 guardians)는 여기에 넣지 않는다. 비상 연락 화면이 보호자 목록은 DB에서
자동으로 채우고, 어르신이 추가한 것만 이 저장소에서 읽는다.
"""

from __future__ import annotations

import itertools
import threading
from dataclasses import dataclass
from typing import Protocol

MAX_CONTACTS = 20


class TooManyContacts(Exception):
    """어르신 한 명이 둘 수 있는 연락처 수를 넘었다."""


@dataclass(frozen=True)
class Contact:
    contact_id: int
    name: str
    relation: str
    phone: str


class ContactStore(Protocol):
    def list(self, elder_id: int) -> list[Contact]:
        """추가한 순서대로(contact_id 오름차순)."""
        ...

    def add(self, elder_id: int, *, name: str, relation: str, phone: str) -> Contact:
        """MAX_CONTACTS개를 넘으면 TooManyContacts."""
        ...

    def remove(self, elder_id: int, contact_id: int) -> bool:
        """그 어르신의 연락처일 때만 지우고 True. 남의 것이거나 없으면 False."""
        ...


class InMemoryContactStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._ids = itertools.count(1)
        self._rows: dict[int, list[Contact]] = {}

    def list(self, elder_id: int) -> list[Contact]:
        with self._lock:
            return list(self._rows.get(elder_id, []))

    def add(self, elder_id: int, *, name: str, relation: str, phone: str) -> Contact:
        with self._lock:
            rows = self._rows.setdefault(elder_id, [])
            if len(rows) >= MAX_CONTACTS:
                raise TooManyContacts(elder_id)
            contact = Contact(next(self._ids), name, relation, phone)
            rows.append(contact)
            return contact

    def remove(self, elder_id: int, contact_id: int) -> bool:
        with self._lock:
            rows = self._rows.get(elder_id, [])
            for index, contact in enumerate(rows):
                if contact.contact_id == contact_id:
                    del rows[index]
                    return True
            return False
