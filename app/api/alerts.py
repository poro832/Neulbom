"""알림 저장소와 문구 (설계: 앱 화면을 실제 데이터로).

문구에 진단·의료 용어를 쓰지 않는다. 우리 점수는 말수와 대답 속도의 변화를 잴 뿐
기분이나 병을 판정하지 않는다.
"""

from __future__ import annotations

import itertools
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

RISK_MESSAGES = {
    "watch": "최근 통화에서 평소보다 말수가 줄고 대답이 느려졌어요.",
    "alert": "최근 통화에서 평소와 많이 달랐어요. 한 번 안부를 확인해 보세요.",
}
NO_ANSWER_MESSAGE = "오늘 안부 전화를 받지 못하셨어요."


@dataclass(frozen=True)
class AlertRecord:
    alert_id: int
    elder_id: int
    guardian_id: int
    call_id: int | None
    alert_type: str
    severity: str
    message: str
    created_at: float


class AlertStore(Protocol):
    def raise_alert(
        self,
        *,
        elder_id: int,
        guardian_id: int,
        call_id: int | None,
        alert_type: str,
        severity: str,
        message: str,
    ) -> bool:
        """알림을 남긴다. 같은 (call_id, alert_type)가 이미 있으면 False.

        웹훅은 재전송되므로 같은 통화에서 같은 알림이 두 번 들어올 수 있다. call_id가
        None이면 중복 검사를 하지 않는다.
        """
        ...

    def recent_for_guardian(self, guardian_id: int, limit: int) -> list[AlertRecord]:
        """최신순."""
        ...

    def count_since(self, elder_id: int, since: float) -> int:
        """since(유닉스 시각) 이후 그 어르신께 생긴 알림 수."""
        ...


class InMemoryAlertStore:
    def __init__(self, clock: Callable[[], float] = time.time) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._ids = itertools.count(1)
        self._rows: list[AlertRecord] = []

    def raise_alert(
        self,
        *,
        elder_id: int,
        guardian_id: int,
        call_id: int | None,
        alert_type: str,
        severity: str,
        message: str,
    ) -> bool:
        with self._lock:
            if call_id is not None and any(
                row.call_id == call_id and row.alert_type == alert_type for row in self._rows
            ):
                return False
            self._rows.append(
                AlertRecord(
                    next(self._ids),
                    elder_id,
                    guardian_id,
                    call_id,
                    alert_type,
                    severity,
                    message,
                    self._clock(),
                )
            )
            return True

    def recent_for_guardian(self, guardian_id: int, limit: int) -> list[AlertRecord]:
        with self._lock:
            mine = [row for row in self._rows if row.guardian_id == guardian_id]
        mine.sort(key=lambda row: row.alert_id, reverse=True)
        return mine[:limit]

    def count_since(self, elder_id: int, since: float) -> int:
        with self._lock:
            return sum(1 for row in self._rows if row.elder_id == elder_id and row.created_at >= since)
