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
    # 근거가 부족한 통화(degraded)에는 점수를 내지 않는다 — None이다.
    # 보호자는 숫자만 보므로, 옆에 "근거 부족"을 적어도 그 숫자가 머리에
    # 남는다. 지표(metrics)는 그대로 남기므로 근거가 채워지면 다시 판정할 수
    # 있다. db/schema.sql도 risk_score와 risk_level이 함께 NULL인 행을
    # 허용한다(metrics_score_and_level_together).
    risk: RiskAssessment | None
    no_answer_recent_7: int
    # 이 판정의 기준선을 과거 몇 통으로 만들었나(degraded 제외). 0이면
    # 기준선 없이 절대 기준으로 낸 점수다.
    #
    # "몇 통부터 믿을 만한 기준선인가"는 지금 알 수 없다. 3이든 7이든 14든
    # 근거가 없기는 마찬가지라, 경계를 지어내는 대신 실제 표본 수를 남긴다 —
    # 실통 데이터가 쌓이면 분포를 보고 정할 수 있다.
    baseline_n: int
    # 이 판정이 실제로 쓴 기준선. 기준선은 저장하지 않고 매번 과거에서 다시
    # 계산하므로(설계 3.1), 당시 값을 남겨 두지 않으면 나중에 이 판정을
    # 재현할 수 없다 — 이력이 한 줄만 늘어도 기준선이 달라진다.
    baseline_speech_ratio: float | None
    baseline_avg_response_delay_ms: int | None
    clipped_ms: int
    filled_gap_ms: int
    call_duration_ms: int
    degraded: bool
    # 왜 근거가 부족한가. 에코(우리 알고리즘) / 유실(통신) / 표식 불일치
    # (사업자)는 고쳐야 할 곳이 전혀 다른데 bool 하나로는 구분이 안 된다.
    degraded_reasons: tuple[str, ...]
    # 어느 가중치로 낸 점수인지. 없으면 나중에 점수끼리 비교할 수 없다.
    calculator_version: str
