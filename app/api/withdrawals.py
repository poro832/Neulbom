"""어르신 탈퇴 요청 — 보호자 전원이 승인해야 탈퇴된다 (설계: 탈퇴·내 정보 삭제).

어르신이 탈퇴를 누르면 요청이 하나 생기고, 그 어르신의 보호자가 모두 승인해야 어르신이 지워진다. 한 명이라도 거절하면
요청이 거절 상태가 되어 어르신 앱에 보이고, 어르신은 나중에 다시 요청할 수 있다. 요청은 WITHDRAWAL_TTL_SECONDS가
지나면 저절로 없어진 것으로 본다(읽을 때 지운다).

어르신 한 명당 요청은 하나다. 새 요청(`open`)은 이전 요청과 승인 기록을 모두 지우고 새로 시작한다.

**요청마다 번호(request_id)가 있다.** 보호자가 화면에서 본 요청과 승인·거절이 닿는 요청이 같아야 한다 — 보호자가
옛 카드를 보고 있는 사이 어르신이 취소하고 다시 요청했는데 그 승인이 새 요청에 붙으면, 보호자가 보지 못한 요청이
승인된다. 그래서 승인·거절은 본 요청의 번호를 함께 보내고, 번호가 다르면 아무것도 바꾸지 않는다.

**마지막 승인은 요청을 잠근다(`lock`).** 전원이 승인한 순간부터는 어르신이 취소하거나 다시 요청해도 삭제를 막을 수 없다 —
승인과 삭제 사이에 취소·재요청이 끼어들면 옛 승인으로 새 요청의 어르신이 지워지거나(재요청), 반대로 이미 승인한
보호자의 결정이 뒤집힌다. 잠그는 것은 요청 번호가 같을 때만 되므로, 취소 뒤 다시 요청된 새 요청은 잠기지 않고 삭제도 일어나지
않는다. 잠긴 요청은 삭제가 끝날 때까지 남아 이어서 지운다.
"""

from __future__ import annotations

import itertools
import threading
from dataclasses import dataclass, field
from typing import Protocol

WITHDRAWAL_TTL_SECONDS = 7 * 24 * 3600


@dataclass(frozen=True)
class WithdrawalRequest:
    elder_id: int
    request_id: int
    requested_at: float
    rejected_at: float | None = None
    locked_at: float | None = None
    approved_by: frozenset[int] = field(default_factory=frozenset)

    @property
    def rejected(self) -> bool:
        return self.rejected_at is not None

    @property
    def locked(self) -> bool:
        return self.locked_at is not None


class WithdrawalStore(Protocol):
    def open(self, elder_id: int, now: float) -> WithdrawalRequest:
        """새 탈퇴 요청을 시작한다. 이전 요청(거절된 것 포함)과 승인 기록은 지운다.
        이미 잠긴(전원이 승인한) 요청이 있으면 바꾸지 않고 그 요청을 돌려준다."""
        ...

    def get(self, elder_id: int) -> WithdrawalRequest | None:
        """그 어르신의 요청. 없으면 None. 만료는 호출부가 requested_at으로 판단한다."""
        ...

    def approve(self, elder_id: int, guardian_id: int, request_id: int) -> WithdrawalRequest | None:
        """보호자가 본 요청(request_id)이 지금도 열려 있을 때만 이 보호자의 승인을 더한다. 같은 보호자가 또 해도 한 번이다.
        요청이 없거나, 거절됐거나, 번호가 다른(취소 뒤 다시 요청된) 요청이면 None."""
        ...

    def reject(self, elder_id: int, now: float, request_id: int) -> bool:
        """보호자가 본 요청(request_id)이 지금도 열려 있고 잠기지 않았을 때만 거절 상태로 바꾼다. 바꿨으면 True."""
        ...

    def lock(self, elder_id: int, request_id: int, now: float) -> bool:
        """전원이 승인한 요청(request_id)을 잠근다 — 이제 취소·재요청·거절이 닿지 않고 삭제만 남는다.
        그 번호의 거절되지 않은 요청이 지금도 있으면 True(이미 잠겨 있어도 True). 없거나 번호가 다르면 False."""
        ...

    def cancel(self, elder_id: int) -> bool:
        """요청을 지운다(어르신이 취소했거나 만료). 잠긴 요청은 지우지 않는다. 지웠으면 True."""
        ...

    def remove_for_elder(self, elder_id: int) -> int:
        """어르신이 지워진 뒤 요청 기록을 정리한다(메모리 저장소용). Postgres에서는 CASCADE도 같은 일을 한다."""
        ...


class InMemoryWithdrawalStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._rows: dict[int, WithdrawalRequest] = {}
        self._ids = itertools.count(1)

    def open(self, elder_id: int, now: float) -> WithdrawalRequest:
        with self._lock:
            existing = self._rows.get(elder_id)
            if existing is not None and existing.locked:
                return existing
            request = WithdrawalRequest(elder_id=elder_id, request_id=next(self._ids), requested_at=now)
            self._rows[elder_id] = request
            return request

    def get(self, elder_id: int) -> WithdrawalRequest | None:
        with self._lock:
            return self._rows.get(elder_id)

    def approve(self, elder_id: int, guardian_id: int, request_id: int) -> WithdrawalRequest | None:
        with self._lock:
            request = self._rows.get(elder_id)
            if request is None or request.rejected or request.request_id != request_id:
                return None
            updated = WithdrawalRequest(
                elder_id=elder_id,
                request_id=request.request_id,
                requested_at=request.requested_at,
                rejected_at=None,
                locked_at=request.locked_at,
                approved_by=request.approved_by | {guardian_id},
            )
            self._rows[elder_id] = updated
            return updated

    def reject(self, elder_id: int, now: float, request_id: int) -> bool:
        with self._lock:
            request = self._rows.get(elder_id)
            if request is None or request.rejected or request.locked or request.request_id != request_id:
                return False
            self._rows[elder_id] = WithdrawalRequest(
                elder_id=elder_id,
                request_id=request.request_id,
                requested_at=request.requested_at,
                rejected_at=now,
                approved_by=request.approved_by,
            )
            return True

    def lock(self, elder_id: int, request_id: int, now: float) -> bool:
        with self._lock:
            request = self._rows.get(elder_id)
            if request is None or request.rejected or request.request_id != request_id:
                return False
            if not request.locked:
                self._rows[elder_id] = WithdrawalRequest(
                    elder_id=elder_id,
                    request_id=request.request_id,
                    requested_at=request.requested_at,
                    rejected_at=None,
                    locked_at=now,
                    approved_by=request.approved_by,
                )
            return True

    def cancel(self, elder_id: int) -> bool:
        with self._lock:
            request = self._rows.get(elder_id)
            if request is None or request.locked:
                return False
            del self._rows[elder_id]
            return True

    def remove_for_elder(self, elder_id: int) -> int:
        # 어르신이 지워진 뒤 정리다 — 잠긴 요청도 함께 지운다.
        with self._lock:
            return 1 if self._rows.pop(elder_id, None) is not None else 0
