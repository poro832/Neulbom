"""통화 기록 저장소 (전화망 설계 5장).

DB가 붙기 전까지 메모리 구현을 쓴다. 규약이 같으므로 PostgreSQL 구현으로
갈아끼울 때 API 코드는 바뀌지 않는다.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, replace
from typing import Protocol

# 통화가 아직 끝나지 않았다고 보는 상태들. 이 동안 재요청은 409다.
ACTIVE_STATUSES = frozenset({"scheduled", "ringing", "answered"})


@dataclass(frozen=True)
class CallRecord:
    call_id: int
    elder_id: int
    trigger_type: str
    status: str
    provider_call_sid: str | None = None


class CallStore(Protocol):
    def find_elder(self, elder_id: int) -> str | None: ...
    def find_active(self, elder_id: int) -> CallRecord | None: ...
    def get(self, call_id: int) -> CallRecord: ...
    def create(self, elder_id: int, trigger_type: str) -> CallRecord: ...
    def attach_sid(self, call_id: int, sid: str) -> None: ...
    def mark_failed(self, call_id: int) -> None: ...


class InMemoryCallStore:
    def __init__(self, phones: dict[int, str]) -> None:
        self._phones = phones
        self._calls: dict[int, CallRecord] = {}
        self._ids = itertools.count(1)

    def find_elder(self, elder_id: int) -> str | None:
        return self._phones.get(elder_id)

    def find_active(self, elder_id: int) -> CallRecord | None:
        for call in self._calls.values():
            if call.elder_id == elder_id and call.status in ACTIVE_STATUSES:
                return call
        return None

    def get(self, call_id: int) -> CallRecord:
        return self._calls[call_id]

    def create(self, elder_id: int, trigger_type: str) -> CallRecord:
        call = CallRecord(
            call_id=next(self._ids),
            elder_id=elder_id,
            trigger_type=trigger_type,
            status="scheduled",
        )
        self._calls[call.call_id] = call
        return call

    def attach_sid(self, call_id: int, sid: str) -> None:
        self._calls[call_id] = replace(
            self._calls[call_id], provider_call_sid=sid, status="ringing"
        )

    def mark_failed(self, call_id: int) -> None:
        # 실패한 통화가 '진행 중'으로 남으면 그 어르신은 영원히 409를 받는다.
        self._calls[call_id] = replace(self._calls[call_id], status="failed")
