"""앱 화면용 조회 모음 — 어르신 요약, 주간 통계, 어르신의 통화 기록 (설계: 앱 화면을 실제 데이터로).

"통화"는 어르신이 받아서 끝난(completed) 통화다. 안 받음·실패는 통화가 아니라서 횟수와
평균에 들어가지 않는다(통화 기록 줄에는 보인다). 날짜는 모두 한국시간 기준이고 한 주는
일요일부터다 — UTC로 세면 일요일 오전 9시 전 통화가 전주로 샌다.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Protocol

from app.api.alerts import AlertStore
from app.api.elder_directory import ElderDirectory
from app.scheduler import KST

_FINISHED = ("completed", "no_answer", "failed")


def sunday_on_or_before(day: date) -> date:
    return day - timedelta(days=(day.weekday() + 1) % 7)  # 월=0 … 일=6


def kst_week_start(now: float) -> date:
    return sunday_on_or_before(datetime.fromtimestamp(now, KST).date())


def week_bounds(week_start: date) -> tuple[float, float]:
    """그 주의 [시작, 끝) 유닉스 시각 (한국시간 일요일 0시 ~ 다음 일요일 0시)."""
    start = datetime(week_start.year, week_start.month, week_start.day, tzinfo=KST)
    return start.timestamp(), (start + timedelta(days=7)).timestamp()


@dataclass(frozen=True)
class ElderSummary:
    elder_id: int
    name: str
    last_call_at: float | None
    last_status: str | None
    week_calls: int
    week_avg_score: float | None
    week_alerts: int


@dataclass(frozen=True)
class DayStat:
    date: str
    calls: int
    avg_score: float | None


@dataclass(frozen=True)
class CallLine:
    call_id: int
    started_at: float
    duration_s: int | None
    status: str


class Reports(Protocol):
    def elder_summaries(self, guardian_id: int, week_start: date) -> list[ElderSummary]: ...

    def weekly(self, elder_id: int, week_start: date) -> list[DayStat]:
        """항상 7개, 일요일부터."""
        ...

    def call_lines(self, elder_id: int, limit: int) -> list[CallLine]:
        """끝난 통화(completed, no_answer, failed)만, 최신순."""
        ...


def _mean(values: list[int]) -> float | None:
    return None if not values else sum(values) / len(values)


class InMemoryReports:
    """메모리 모드와 엔드포인트 테스트용. 통화는 `add_call`로 심는다."""

    def __init__(self, elders: ElderDirectory, alerts: AlertStore) -> None:
        self._elders = elders
        self._alerts = alerts
        self._lock = threading.Lock()
        self._calls: list[dict] = []

    def add_call(
        self,
        *,
        call_id: int,
        elder_id: int,
        status: str,
        created_at: float,
        trigger_type: str = "scheduled",
        score: int | None = None,
        duration_ms: int | None = None,
    ) -> None:
        with self._lock:
            self._calls.append(
                {
                    "call_id": call_id,
                    "elder_id": elder_id,
                    "status": status,
                    "created_at": created_at,
                    "score": score,
                    "duration_ms": duration_ms,
                }
            )

    def _of(self, elder_id: int) -> list[dict]:
        with self._lock:
            return sorted(
                (c for c in self._calls if c["elder_id"] == elder_id), key=lambda c: c["call_id"]
            )

    def elder_summaries(self, guardian_id: int, week_start: date) -> list[ElderSummary]:
        lo, hi = week_bounds(week_start)
        out = []
        for ref in self._elders.elders_of(guardian_id):
            calls = self._of(ref.elder_id)
            last = calls[-1] if calls else None
            week = [c for c in calls if c["status"] == "completed" and lo <= c["created_at"] < hi]
            out.append(
                ElderSummary(
                    elder_id=ref.elder_id,
                    name=ref.name,
                    last_call_at=None if last is None else last["created_at"],
                    last_status=None if last is None else last["status"],
                    week_calls=len(week),
                    week_avg_score=_mean([c["score"] for c in week if c["score"] is not None]),
                    week_alerts=self._alerts.count_since(ref.elder_id, lo),
                )
            )
        return out

    def weekly(self, elder_id: int, week_start: date) -> list[DayStat]:
        calls = [c for c in self._of(elder_id) if c["status"] == "completed"]
        days = []
        for offset in range(7):
            day = week_start + timedelta(days=offset)
            same = [
                c
                for c in calls
                if datetime.fromtimestamp(c["created_at"], KST).date() == day
            ]
            days.append(
                DayStat(
                    date=day.isoformat(),
                    calls=len(same),
                    avg_score=_mean([c["score"] for c in same if c["score"] is not None]),
                )
            )
        return days

    def call_lines(self, elder_id: int, limit: int) -> list[CallLine]:
        finished = [c for c in self._of(elder_id) if c["status"] in _FINISHED]
        finished.sort(key=lambda c: c["call_id"], reverse=True)
        return [
            CallLine(
                call_id=c["call_id"],
                started_at=c["created_at"],
                duration_s=None if c["duration_ms"] is None else c["duration_ms"] // 1000,
                status=c["status"],
            )
            for c in finished[:limit]
        ]
