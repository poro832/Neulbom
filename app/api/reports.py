"""앱 화면용 조회 모음 — 어르신 요약, 주간 통계, 어르신의 통화 기록 (설계: 앱 화면을 실제 데이터로).

"통화"는 어르신이 받아서 끝난(completed) 통화다. 안 받음·실패는 통화가 아니라서 횟수와
평균에 들어가지 않는다(통화 기록 줄에는 보인다). 날짜는 모두 한국시간 기준이고 한 주는
일요일부터다 — UTC로 세면 일요일 오전 9시 전 통화가 전주로 샌다.
"""

from __future__ import annotations

import calendar
import threading
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Protocol

from app.analysis.baseline import BASELINE_WINDOW
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


def month_week_starts(first: date) -> list[date]:
    """그 달(first는 1일)에 걸친 주의 일요일들, 오래된 순. 한 달은 4~6주에 걸친다.

    마지막 주의 다음 일요일까지 계산하므로, 그 주들을 날짜로 다룰 수 없는 달(0001-01, 9999-12)은
    여기서 OverflowError가 난다 — 저장소에 닿기 전에 막는다.
    """
    last = first.replace(day=calendar.monthrange(first.year, first.month)[1])
    weeks = []
    cursor = sunday_on_or_before(first)
    while cursor <= last:
        weeks.append(cursor)
        cursor += timedelta(days=7)
    return weeks


@dataclass(frozen=True)
class ElderSummary:
    elder_id: int
    name: str
    last_call_at: float | None
    last_status: str | None
    week_calls: int
    week_avg_score: float | None
    week_alerts: int
    status: str = "active"
    # 승인 대기일 때만 채운다. 보호자가 번호를 보고 승인한다.
    phone: str | None = None
    # 이 어르신을 함께 보는 보호자 수(나 포함).
    guardian_count: int = 1


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

    def baseline_calls(self, elder_id: int) -> int:
        """평소 기준에 쓸 수 있는 통화 수(0~BASELINE_WINDOW).

        받은(completed) 통화를 최신순으로 BASELINE_WINDOW통까지 자른 뒤, 그중 지표가 있고 degraded가 아닌
        통화를 센다. 창을 먼저 자르고 거르는 순서는 기준선(app/analysis/baseline.py)과 같다.
        """
        ...

    def remove_for_elder(self, elder_id: int) -> int:
        """그 어르신의 통화를 모두 지운다(탈퇴). 지운 통화 수.

        Postgres에서는 통화의 점수·전사·대화·요약·언급도 CASCADE로 같이 지워지고, 어르신 행을 지우면 이 통화들도
        CASCADE로 지워진다 — 메모리 모드에서도 결과가 같도록 둔다.
        """
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
        degraded: bool = False,
    ) -> None:
        """점수·길이를 주거나 degraded면 지표(call_metrics)가 있는 통화다 — tests/pg_helpers.insert_call과 같다."""
        with self._lock:
            self._calls.append(
                {
                    "call_id": call_id,
                    "elder_id": elder_id,
                    "status": status,
                    "created_at": created_at,
                    "score": score,
                    "duration_ms": duration_ms,
                    "has_metrics": score is not None or duration_ms is not None or degraded,
                    "degraded": degraded,
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
                    status=ref.status,
                    phone=ref.phone,
                    guardian_count=ref.guardian_count,
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

    def baseline_calls(self, elder_id: int) -> int:
        completed = [c for c in self._of(elder_id) if c["status"] == "completed"]
        window = sorted(completed, key=lambda c: c["call_id"], reverse=True)[:BASELINE_WINDOW]
        return sum(1 for c in window if c["has_metrics"] and not c["degraded"])

    def remove_for_elder(self, elder_id: int) -> int:
        with self._lock:
            before = len(self._calls)
            self._calls = [c for c in self._calls if c["elder_id"] != elder_id]
            return before - len(self._calls)
