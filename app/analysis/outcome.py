"""한 통화의 최종 결과 (설계 4.1).

db/schema.sql의 call_metrics 한 행과 필드가 1:1로 대응한다. DB가 붙을 때
PostgresOutcomeStore가 이 자료형을 그대로 INSERT하면 된다.

저장소도 시계도 없는 순수한 값이다 — 그래야 기준선 계산이 재현된다.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.analysis.metrics_calculator import CallMetrics, RiskAssessment


@dataclass(frozen=True)
class CallOutcome:
    call_id: int
    elder_id: int
    metrics: CallMetrics
    risk: RiskAssessment
    no_answer_recent_7: int
    clipped_ms: int
    degraded: bool
    # 어느 가중치로 낸 점수인지. 없으면 나중에 점수끼리 비교할 수 없다.
    calculator_version: str
