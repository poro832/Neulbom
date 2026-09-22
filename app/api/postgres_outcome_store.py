"""분석 결과 저장소 — Postgres (설계 5장).

`InMemoryOutcomeStore`와 같은 `OutcomeStore` 규약을 구현한다. 둘이 갈라지지
않도록 `tests/test_outcome_store_contract.py`가 같은 테스트를 양쪽에 돌린다.

**`CallOutcome` 하나가 `call_metrics` 한 행이다.** 중첩된 것 둘을 편다 —
`metrics`(CallMetrics)와 `risk`(RiskAssessment | None). 근거가 부족한 통화는
`risk`가 None이고, 그때 `risk_score`·`risk_level`이 함께 NULL이 된다. 스키마의
`metrics_score_and_level_together` 제약이 "하나만 NULL"인 행을 막는다.

**NULL과 0을 구분해서 넣는다.** `avg_response_delay_ms`가 NULL이면 "어르신이
한 번도 응답하지 않았다"이고, 0이면 "즉시 응답했다"다. 0으로 뭉개면 평균이
왜곡되고 나중에 되돌릴 수 없다. `baseline_*`도 같다 — NULL은 "표본이 모자라
기준선을 못 만들었다"이지 "기준선이 0이었다"가 아니다.
"""

from __future__ import annotations

import logging

from app.analysis.metrics_calculator import BaselineDelta, CallMetrics, RiskAssessment
from app.analysis.outcome import CallOutcome

logger = logging.getLogger(__name__)

# 읽는 열 순서. 한 군데만 두어 조회마다 어긋나지 않게 한다 — 순서가 밀리면
# speech_ratio 자리에 silence_ratio가 들어가고도 둘 다 0~1이라 아무 오류가
# 안 난다. 조용히 틀린 점수가 나가는 경로다.
_COLUMNS = """
    m.call_id, c.elder_id,
    m.speech_ratio, m.silence_ratio, m.turn_count, m.negative_word_count,
    m.avg_response_delay_ms,
    m.elder_speech_ms, m.ai_speech_ms, m.silence_ms, m.response_delays_ms,
    m.risk_score, m.risk_level, m.baseline_speech_delta, m.baseline_delay_delta_ms,
    m.no_answer_recent_7, m.baseline_n,
    m.baseline_speech_ratio, m.baseline_avg_response_delay_ms,
    m.clipped_ms, m.filled_gap_ms, m.call_duration_ms,
    m.degraded, m.degraded_reasons, m.calculator_version, m.transcription_enabled
"""


def _outcome(row) -> CallOutcome:
    (
        call_id, elder_id,
        speech_ratio, silence_ratio, turn_count, negative_word_count,
        avg_response_delay_ms,
        elder_speech_ms, ai_speech_ms, silence_ms, response_delays_ms,
        risk_score, risk_level, speech_delta, delay_delta,
        no_answer_recent_7, baseline_n,
        baseline_speech_ratio, baseline_avg_response_delay_ms,
        clipped_ms, filled_gap_ms, call_duration_ms,
        degraded, degraded_reasons, calculator_version, transcription_enabled,
    ) = row

    # 점수가 없는 통화다. 스키마가 둘을 함께 NULL로 묶으므로 하나만 보면 된다.
    risk = None
    if risk_score is not None:
        delta = None
        if speech_delta is not None:
            delta = BaselineDelta(
                speech_ratio=speech_delta, avg_response_delay_ms=delay_delta
            )
        risk = RiskAssessment(
            risk_score=risk_score, risk_level=risk_level, baseline_delta=delta
        )

    return CallOutcome(
        call_id=call_id,
        elder_id=elder_id,
        metrics=CallMetrics(
            speech_ratio=speech_ratio,
            silence_ratio=silence_ratio,
            turn_count=turn_count,
            negative_word_count=negative_word_count,
            avg_response_delay_ms=avg_response_delay_ms,
            elder_speech_ms=elder_speech_ms,
            ai_speech_ms=ai_speech_ms,
            silence_ms=silence_ms,
            # dataclass가 tuple이라 그대로 맞춘다. 리스트로 돌려주면 같은
            # 판정을 두 저장소에서 읽었을 때 == 가 거짓이 된다.
            response_delays_ms=tuple(response_delays_ms or ()),
        ),
        risk=risk,
        no_answer_recent_7=no_answer_recent_7,
        baseline_n=baseline_n,
        baseline_speech_ratio=baseline_speech_ratio,
        baseline_avg_response_delay_ms=baseline_avg_response_delay_ms,
        clipped_ms=clipped_ms,
        filled_gap_ms=filled_gap_ms,
        call_duration_ms=call_duration_ms,
        degraded=degraded,
        degraded_reasons=tuple(degraded_reasons or ()),
        calculator_version=calculator_version,
        transcription_enabled=transcription_enabled,
    )


class PostgresOutcomeStore:
    def __init__(self, *, pool) -> None:
        self._pool = pool

    def record(self, outcome: CallOutcome) -> None:
        """결과를 남긴다. 같은 call_id로 다시 부르면 덮어쓴다.

        call_metrics의 기본키가 call_id다 — 한 통화에 결과가 둘일 수 없다.
        백필이나 재분석이 생기면 그 경로도 이 규칙을 지켜야 한다: 새 행을
        더하는 게 아니라 그 call_id의 행을 교체한다.
        """
        risk = outcome.risk
        delta = risk.baseline_delta if risk else None
        metrics = outcome.metrics

        with self._pool.connection() as conn:
            conn.execute(
                """
                INSERT INTO call_metrics (
                    call_id,
                    speech_ratio, silence_ratio, turn_count, negative_word_count,
                    avg_response_delay_ms,
                    elder_speech_ms, ai_speech_ms, silence_ms, response_delays_ms,
                    risk_score, risk_level,
                    baseline_speech_delta, baseline_delay_delta_ms,
                    no_answer_recent_7, baseline_n,
                    baseline_speech_ratio, baseline_avg_response_delay_ms,
                    clipped_ms, filled_gap_ms, call_duration_ms,
                    degraded, degraded_reasons,
                    calculator_version, transcription_enabled
                ) VALUES (
                    %s,
                    %s, %s, %s, %s,
                    %s,
                    %s, %s, %s, %s,
                    %s, %s,
                    %s, %s,
                    %s, %s,
                    %s, %s,
                    %s, %s, %s,
                    %s, %s,
                    %s, %s
                )
                ON CONFLICT (call_id) DO UPDATE SET
                    speech_ratio = EXCLUDED.speech_ratio,
                    silence_ratio = EXCLUDED.silence_ratio,
                    turn_count = EXCLUDED.turn_count,
                    negative_word_count = EXCLUDED.negative_word_count,
                    avg_response_delay_ms = EXCLUDED.avg_response_delay_ms,
                    elder_speech_ms = EXCLUDED.elder_speech_ms,
                    ai_speech_ms = EXCLUDED.ai_speech_ms,
                    silence_ms = EXCLUDED.silence_ms,
                    response_delays_ms = EXCLUDED.response_delays_ms,
                    risk_score = EXCLUDED.risk_score,
                    risk_level = EXCLUDED.risk_level,
                    baseline_speech_delta = EXCLUDED.baseline_speech_delta,
                    baseline_delay_delta_ms = EXCLUDED.baseline_delay_delta_ms,
                    no_answer_recent_7 = EXCLUDED.no_answer_recent_7,
                    baseline_n = EXCLUDED.baseline_n,
                    baseline_speech_ratio = EXCLUDED.baseline_speech_ratio,
                    baseline_avg_response_delay_ms =
                        EXCLUDED.baseline_avg_response_delay_ms,
                    clipped_ms = EXCLUDED.clipped_ms,
                    filled_gap_ms = EXCLUDED.filled_gap_ms,
                    call_duration_ms = EXCLUDED.call_duration_ms,
                    degraded = EXCLUDED.degraded,
                    degraded_reasons = EXCLUDED.degraded_reasons,
                    calculator_version = EXCLUDED.calculator_version,
                    transcription_enabled = EXCLUDED.transcription_enabled,
                    computed_at = now()
                """,
                (
                    outcome.call_id,
                    metrics.speech_ratio, metrics.silence_ratio,
                    metrics.turn_count, metrics.negative_word_count,
                    metrics.avg_response_delay_ms,
                    metrics.elder_speech_ms, metrics.ai_speech_ms,
                    metrics.silence_ms, list(metrics.response_delays_ms),
                    risk.risk_score if risk else None,
                    risk.risk_level if risk else None,
                    delta.speech_ratio if delta else None,
                    delta.avg_response_delay_ms if delta else None,
                    outcome.no_answer_recent_7, outcome.baseline_n,
                    outcome.baseline_speech_ratio,
                    outcome.baseline_avg_response_delay_ms,
                    outcome.clipped_ms, outcome.filled_gap_ms,
                    outcome.call_duration_ms,
                    outcome.degraded, list(outcome.degraded_reasons),
                    outcome.calculator_version, outcome.transcription_enabled,
                ),
            )

    def recent(
        self, elder_id: int, limit: int, before_call_id: int | None = None
    ) -> list[CallOutcome]:
        """그 어르신의 결과를 최신순(call_id 내림차순)으로 limit개까지.

        최신순은 구현 편의가 아니라 규약이다. 기준선의 창이 이 순서 위에 서
        있어서, 순서가 틀리면 엉뚱한 통화들의 평균이 기준선이 된다 — 아무
        오류 없이 점수만 틀린다(설계 4.6).

        before_call_id를 주면 그 call_id 이상은 빼고 돌려준다. 잘라내기가
        먼저고 LIMIT이 나중이다 — 반대로 하면 표본이 limit보다 적어진다.

        elder_id는 calls를 거쳐 온다. call_metrics에는 그 열이 없다 — 통화
        하나가 두 어르신의 것일 수 없으므로 한 군데만 둔다.
        """
        with self._pool.connection() as conn:
            rows = conn.execute(
                f"SELECT {_COLUMNS} "
                "FROM call_metrics m JOIN calls c USING (call_id) "
                "WHERE c.elder_id = %s "
                "  AND (%s::bigint IS NULL OR m.call_id < %s::bigint) "
                "ORDER BY m.call_id DESC LIMIT %s",
                (elder_id, before_call_id, before_call_id, limit),
            ).fetchall()
        return [_outcome(row) for row in rows]

    def reset_for_tests(self) -> None:
        """규약 테스트가 매번 빈 상태에서 시작하도록 비운다.

        운영 경로에서는 절대 불리지 않는다. 이름에 그렇게 적어 둔다.

        결과는 통화에 매달려 있으므로 통화부터 만든다 — call_metrics.call_id가
        calls를 참조한다. 규약 테스트가 call_id를 직접 고르므로(10, 20, 30…)
        그 번호의 통화 껍데기를 미리 넣어 둔다.
        """
        with self._pool.connection() as conn:
            conn.execute("TRUNCATE calls RESTART IDENTITY CASCADE")
            conn.execute(
                "INSERT INTO guardians "
                "  (guardian_id, name, email, password_hash, phone_number) "
                "VALUES (1, '테스트 보호자', 'test@example.invalid', 'x', "
                "        '010-0000-0000') "
                "ON CONFLICT (guardian_id) DO NOTHING"
            )
            for elder_id in (12, 99):
                conn.execute(
                    "INSERT INTO elders (elder_id, guardian_id, name, phone_number) "
                    "VALUES (%s, 1, %s, %s) ON CONFLICT (elder_id) DO NOTHING",
                    (elder_id, f"테스트 어르신 {elder_id}", f"070-{elder_id:04d}"),
                )
            # 규약 테스트가 쓰는 call_id 범위. 끝난 상태로 넣는다 — 활성으로
            # 두면 어르신당 하나 제약에 걸린다.
            for call_id in range(1, 41):
                for elder_id in (12, 99):
                    conn.execute(
                        "INSERT INTO calls "
                        "  (call_id, elder_id, trigger_type, status, audio_key) "
                        "VALUES (%s, %s, 'scheduled', 'completed', %s) "
                        "ON CONFLICT (call_id) DO NOTHING",
                        (call_id if elder_id == 12 else call_id + 1000,
                         elder_id, f"{call_id}.wav"),
                    )
            # 껍데기의 call_id를 손으로 정했으므로 시퀀스를 그 위로 민다.
            # 안 하면 다음 create()가 nextval로 1을 받아 여기 넣은 행과
            # 부딪힌다 — 조립부 테스트가 실제로 이렇게 터졌다.
            conn.execute(
                "SELECT setval('calls_call_id_seq', "
                "  (SELECT MAX(call_id) FROM calls))"
            )
