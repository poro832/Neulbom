"""일일 운영 리포트와 /healthz."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from app.ops_report import build_report, health, period_start
from app.scheduler import KST
from tests.pg_helpers import DATABASE_URL

pg = pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL이 없다")

NOON = datetime(2026, 11, 10, 12, 0, tzinfo=KST)


def seed(pool):
    from tests.pg_helpers import insert_call, seed_world

    seed_world(pool)  # 보호자 1·2, 어르신 12·13(보호자 1)·14(보호자 2) — 모두 동의, 통화 시각 09:00
    ts = NOON.timestamp()
    insert_call(pool, call_id=1, elder_id=12, status="completed", created_at=ts - 3 * 3600)
    insert_call(pool, call_id=2, elder_id=13, status="no_answer", created_at=ts - 3 * 3600)
    insert_call(pool, call_id=3, elder_id=12, status="failed", created_at=ts - 2 * 3600, trigger_type="requested")
    insert_call(pool, call_id=4, elder_id=13, status="completed", created_at=ts - 30 * 3600)  # 어제 — 오늘 리포트에 안 든다
    with pool.connection() as conn:
        conn.execute("UPDATE calls SET error_code = 'CALL_FAILED' WHERE call_id = 3")


@pg
def test_the_report_counts_calls_by_trigger_and_status_with_failure_reasons():
    from tests.pg_helpers import pg_pool

    pool = pg_pool()
    seed(pool)

    text = "\n".join(build_report(pool, NOON, 1))

    assert "2026-11-10 00:00" in text and "2026-11-10 12:00" in text
    assert "예약: 완료 1, 미응답 1" in text
    assert "요청: 실패 1" in text
    assert "실패 이유: CALL_FAILED 1" in text
    # 어제 통화는 하루 리포트에 들지 않고, 이틀 리포트에는 든다
    assert "완료 2" in "\n".join(build_report(pool, NOON, 2))


@pg
def test_the_report_names_elders_whose_scheduled_call_was_never_created_after_the_grace():
    from tests.pg_helpers import pg_pool

    pool = pg_pool()
    seed(pool)

    late = "\n".join(build_report(pool, NOON, 1))
    assert "예약 통화가 없는 어르신 1명: 14번(09:00)" in late  # 12·13은 오늘 예약 통화가 있다

    # 통화 시각(09:00) + 유예(30분)가 아직 안 지났으면 누락이 아니다
    early = "\n".join(build_report(pool, NOON.replace(hour=9, minute=10), 1))
    assert "스케줄 누락" in early and "예약 통화가 없는 어르신" not in early


@pg
def test_the_report_flags_calls_stuck_for_hours_and_never_prints_names_or_numbers():
    from tests.pg_helpers import insert_call, pg_pool

    pool = pg_pool()
    seed(pool)
    insert_call(pool, call_id=5, elder_id=14, status="answered", created_at=NOON.timestamp() - 5 * 3600)

    text = "\n".join(build_report(pool, NOON, 1))

    assert "두 시간이 넘도록 끝나지 않은 통화 1건" in text
    for secret in ("어르신 12", "070-", "010-", "보호자1"):
        assert secret not in text


@pg
def test_the_report_counts_alerts_and_chat_usage_with_urgent_categories():
    from app.api.postgres_alerts import PostgresAlertStore
    from app.chat.postgres_store import PostgresChatStore
    from tests.pg_helpers import pg_pool

    pool = pg_pool()
    seed(pool)
    ts = NOON.timestamp() - 3600
    alerts = PostgresAlertStore(pool=pool, clock=lambda: ts)
    alerts.raise_alert(elder_id=12, guardian_id=1, call_id=None, alert_type="emergency_keyword", severity="critical", message="x")
    alerts.raise_alert(elder_id=13, guardian_id=1, call_id=None, alert_type="no_answer", severity="info", message="x")
    chat = PostgresChatStore(pool=pool)
    session = chat.session_for(12, ts, 1800)
    chat.add_message(session, "elder", "가슴이 아파요", ts, "medical")
    chat.add_message(session, "ai", "괜찮으세요?", ts + 1)
    chat.add_message(session, "elder", "응", ts + 2)

    text = "\n".join(build_report(pool, NOON, 1))

    assert "위급 표현 1" in text and "미응답 1" in text
    assert "대화 1덩이, 어르신이 보낸 말 2개" in text
    assert "위급 표현: 몸 불편 1" in text
    assert "가슴" not in text  # 말 내용은 리포트에 싣지 않는다


@pg
def test_an_empty_period_says_so_in_every_section():
    from tests.pg_helpers import pg_pool, seed_world

    pool = pg_pool()
    seed_world(pool)

    text = "\n".join(build_report(pool, NOON, 1))

    assert "기간 안에 통화가 없다" in text
    assert "기간 안에 알림이 없다" in text
    assert "기간 안에 채팅이 없다" in text


def test_the_period_starts_at_korean_midnight_and_goes_back_by_days():
    assert period_start(NOON, 1) == datetime(2026, 11, 10, 0, 0, tzinfo=KST)
    assert period_start(NOON, 3) == datetime(2026, 11, 8, 0, 0, tzinfo=KST)
    utc_evening = datetime(2026, 11, 9, 20, 0, tzinfo=KST).astimezone()  # 한국 시간으로는 같은 날 저녁
    assert period_start(utc_evening, 1).day == 9


def run_report(argv, pool):
    from app.admin import run
    from app.api.elder_directory import ElderAccess, InMemoryElderDirectory
    from app.api.guardian_auth import InMemoryGuardianKeyStore

    lines, errors = [], []
    code = run(
        argv,
        keys=InMemoryGuardianKeyStore(),
        directory=InMemoryElderDirectory({12: ElderAccess(1, True)}),
        out=lambda text="": lines.append(str(text)),
        err=lambda text="": errors.append(str(text)),
        pool=pool,
    )
    return code, "\n".join(lines), "\n".join(errors)


@pg
def test_the_admin_report_command_prints_the_report_and_changes_nothing():
    from tests.pg_helpers import pg_pool

    pool = pg_pool()
    seed(pool)
    with pool.connection() as conn:
        before = conn.execute("SELECT count(*) FROM calls").fetchone()[0]

    code, out, _ = run_report(["report"], pool)

    assert code == 0 and "[통화]" in out and "[스케줄 누락]" in out and "[알림]" in out and "[AI 채팅]" in out
    with pool.connection() as conn:
        assert conn.execute("SELECT count(*) FROM calls").fetchone()[0] == before  # 읽기만 한다


def test_the_admin_report_command_refuses_without_a_database_and_with_bad_days():
    code, _, err = run_report(["report"], None)
    assert code == 1 and "DB가 없다" in err

    for days in ("0", "32"):
        code, _, err = run_report(["report", "--days", days], object())
        assert code == 1 and "1~31" in err


# ------------------------------------------------------------------ /healthz


def test_health_is_ok_without_a_check_and_when_the_database_answers():
    assert health(None) == (200, {"status": "ok"})
    assert health(lambda: True) == (200, {"status": "ok"})


def test_health_is_503_when_the_database_is_down_and_says_nothing_else():
    def boom():
        raise TimeoutError("끊김 password=secret host=db.internal")

    assert health(lambda: False) == (503, {"status": "database_down"})
    status, body = health(boom)
    assert status == 503 and body == {"status": "database_down"}  # 오류 내용·주소가 새지 않는다


def test_healthz_answers_without_a_key_and_caddy_opens_it():
    from fastapi.testclient import TestClient

    from app.main import app

    response = TestClient(app).get("/healthz")

    assert response.status_code == 200 and response.json() == {"status": "ok"}
    from pathlib import Path

    caddy = (Path(__file__).resolve().parent.parent / "deploy" / "Caddyfile").read_text(encoding="utf-8")
    assert "/healthz" in caddy
