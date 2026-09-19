"""분석 결과 저장소 (설계 4.3).

DB가 붙기 전까지 메모리 구현을 쓴다. 규약이 같으므로 PostgresOutcomeStore로
갈아끼울 때 호출부는 바뀌지 않는다 — CallOutcome은 call_metrics 한 행과
필드가 1:1이다.
"""

from __future__ import annotations

import threading
from typing import Protocol

from app.analysis.outcome import CallOutcome


class OutcomeStore(Protocol):
    def record(self, outcome: CallOutcome) -> None:
        """결과를 남긴다. 같은 call_id로 다시 부르면 덮어쓴다.

        call_metrics의 기본키가 call_id다 — 한 통화에 결과가 둘일 수 없다.
        """
        ...

    def recent(self, elder_id: int, limit: int) -> list[CallOutcome]:
        """그 어르신의 결과를 최신순(call_id 내림차순)으로 limit개까지.

        최신순은 구현 편의가 아니라 규약이다. 기준선의 창이 이 순서 위에 서
        있어서, 순서가 틀리면 엉뚱한 통화들의 평균이 기준선이 된다 — 아무
        오류 없이 점수만 틀린다(설계 4.6).
        """
        ...


class InMemoryOutcomeStore:
    def __init__(self) -> None:
        self._by_call: dict[int, CallOutcome] = {}
        # 분석은 통화마다 스트림 종료 훅에서 돈다. FastAPI가 라우트를
        # 스레드풀에 올리므로 두 통화가 동시에 끝날 수 있다.
        self._lock = threading.Lock()

    def record(self, outcome: CallOutcome) -> None:
        with self._lock:
            self._by_call[outcome.call_id] = outcome

    def recent(self, elder_id: int, limit: int) -> list[CallOutcome]:
        with self._lock:
            mine = [
                outcome
                for outcome in self._by_call.values()
                if outcome.elder_id == elder_id
            ]
        # call_id는 단조 증가하므로 시계 없이 시간 순서가 정해진다(설계 4.6).
        mine.sort(key=lambda outcome: outcome.call_id, reverse=True)
        return mine[:limit]
