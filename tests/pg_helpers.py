"""Postgres 규약 테스트가 함께 쓰는 도우미. 로컬 Docker DB 전용이다(assert_local)."""

from __future__ import annotations

import os

DATABASE_URL = os.getenv("DATABASE_URL")

WORLD_ELDERS = {
    12: (1, "어르신 12", "070-1111-2222"),
    13: (1, "어르신 13", "070-3333-4444"),
    14: (2, "어르신 14", "070-5555-6666"),
}


def pg_pool():
    from app.api.db import assert_local, connect

    assert_local()
    return connect(DATABASE_URL)


def seed_world(pool) -> None:
    """보호자 1·2와 어르신 12·13(보호자 1), 14(보호자 2)만 남기고 모두 비운다."""
    with pool.connection() as conn:
        conn.execute(
            "TRUNCATE alerts, contacts, elder_keys, elder_pairings, guardian_invites, call_metrics, "
            "calls, elders, guardians RESTART IDENTITY CASCADE"
        )
        for guardian_id, name in ((1, "보호자1"), (2, "보호자2")):
            conn.execute(
                "INSERT INTO guardians (guardian_id, name, email, password_hash, phone_number) "
                "VALUES (%s, %s, %s, 'not-a-login', %s)",
                (guardian_id, name, f"g{guardian_id}@example.invalid", f"010-0000-000{guardian_id}"),
            )
        for elder_id, (guardian_id, name, phone) in WORLD_ELDERS.items():
            conn.execute(
                "INSERT INTO elders (elder_id, guardian_id, name, phone_number, consent_at) "
                "VALUES (%s, %s, %s, %s, now())",
                (elder_id, guardian_id, name, phone),
            )


def insert_call(
    pool,
    *,
    call_id: int,
    elder_id: int,
    status: str,
    created_at: float,
    trigger_type: str = "scheduled",
    score: int | None = None,
    level: str | None = None,
    duration_ms: int | None = None,
) -> None:
    """끝난 통화 한 건을 직접 심는다. 점수를 주면 call_metrics도 심는다."""
    audio_key = "t.wav" if status == "completed" else None
    with pool.connection() as conn:
        conn.execute(
            "INSERT INTO calls (call_id, elder_id, trigger_type, status, audio_key, created_at) "
            "VALUES (%s, %s, %s, %s, %s, to_timestamp(%s))",
            (call_id, elder_id, trigger_type, status, audio_key, created_at),
        )
        if score is not None or duration_ms is not None:
            conn.execute(
                "INSERT INTO call_metrics (call_id, risk_score, risk_level, call_duration_ms, "
                "calculator_version) VALUES (%s, %s, %s, %s, '2.0.0')",
                (call_id, score, level if score is not None else None, duration_ms),
            )
