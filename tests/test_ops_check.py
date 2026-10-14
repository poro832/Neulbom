"""서버 반영 점검 — 비밀은 말하지 않고, 빠진 SQL을 짚어 준다."""

from __future__ import annotations

import os

import pytest

from app.admin import run
from app.api.elder_directory import ElderAccess, InMemoryElderDirectory
from app.api.guardian_auth import InMemoryGuardianKeyStore
from app.ops_check import (
    COLUMN_MIGRATIONS,
    FAIL,
    OK,
    TABLE_MIGRATIONS,
    WARN,
    check_database,
    check_environment,
    format_checks,
)

GOOD_ENV = {
    "DATABASE_URL": "postgresql://x",
    "CLOVA_STUDIO_BASE_URL": "https://example.invalid",
    "CLOVA_STUDIO_API_KEY": "SECRET-STUDIO",
    "CLAWOPS_ACCOUNT_SID": "sid",
    "CLAWOPS_API_KEY": "SECRET-CLAWOPS",
    "CLAWOPS_FROM_NUMBER": "070",
    "PUBLIC_BASE_URL": "https://a",
    "STREAM_BASE_URL": "wss://a",
    "RECORDINGS_BUCKET": "b",
}


def by_name(checks):
    return {c.name: c for c in checks}


def test_a_complete_environment_has_no_failures_and_push_is_a_warning_without_a_key_file():
    checks = by_name(check_environment(GOOD_ENV))
    assert all(c.level in (OK, WARN) for c in checks.values())
    assert checks["푸시(FCM)"].level == WARN


def test_missing_settings_fail_and_name_what_breaks():
    env = {k: v for k, v in GOOD_ENV.items() if k != "CLOVA_STUDIO_API_KEY"}
    checks = by_name(check_environment(env))
    c = checks["대화·요약·복용 확인(CLOVA Studio)"]
    assert c.level == FAIL and "CLOVA_STUDIO_API_KEY" in c.detail


def test_push_key_file_states():
    env = {**GOOD_ENV, "FCM_SERVICE_ACCOUNT_FILE": "/etc/nulbom/fcm.json"}
    missing = by_name(check_environment(env, path_exists=lambda p: False))["푸시(FCM)"]
    unreadable = by_name(check_environment(env, path_exists=lambda p: True, sender_factory=lambda e: None))["푸시(FCM)"]
    ok = by_name(check_environment(env, path_exists=lambda p: True, sender_factory=lambda e: object()))["푸시(FCM)"]
    assert (missing.level, unreadable.level, ok.level) == (FAIL, FAIL, OK)


def test_secrets_never_appear_in_the_output():
    env = {**GOOD_ENV, "FCM_SERVICE_ACCOUNT_FILE": "/etc/nulbom/fcm.json"}
    lines, _ = format_checks(check_environment(env, path_exists=lambda p: True, sender_factory=lambda e: object()))
    text = "\n".join(lines)
    for secret in ("SECRET-STUDIO", "SECRET-CLAWOPS", "postgresql://x"):
        assert secret not in text


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None


class FakePool:
    """information_schema 두 질문과 보호자 개수 질문에만 답한다."""

    def __init__(self, tables, columns, counts=(1, 0), error=None):
        self.tables, self.columns, self.counts, self.error = tables, columns, counts, error

    def connection(self):
        pool = self

        class Ctx:
            def __enter__(self_inner):
                if pool.error:
                    raise pool.error
                return self_inner

            def __exit__(self_inner, *a):
                return False

            def execute(self_inner, sql, params=None):
                if "information_schema.tables" in sql:
                    return _Result([(t,) for t in pool.tables])
                if "information_schema.columns" in sql:
                    return _Result(list(pool.columns))
                return _Result([pool.counts])

        return Ctx()


FULL_TABLES = set(TABLE_MIGRATIONS)
FULL_COLUMNS = set(COLUMN_MIGRATIONS)


def test_a_complete_database_passes():
    checks = by_name(check_database(FakePool(FULL_TABLES, FULL_COLUMNS)))
    assert checks["DB 표·칸"].level == OK
    assert checks["로그인 보호자"].level == OK


def test_a_missing_table_and_column_name_the_migration_to_run():
    pool = FakePool(FULL_TABLES - {"guardian_devices"}, FULL_COLUMNS - {("guardians", "activated_at")})
    checks = by_name(check_database(pool))
    assert checks["표 guardian_devices"].level == FAIL
    assert "2026-10-13-guardian-devices.sql" in checks["표 guardian_devices"].detail
    assert checks["칸 guardians.activated_at"].level == FAIL
    assert "2026-10-13-guardian-activation.sql" in checks["칸 guardians.activated_at"].detail
    assert "DB 표·칸" not in checks


def test_a_missing_elder_link_table_names_its_migration():
    checks = by_name(check_database(FakePool(FULL_TABLES - {"elder_link_codes"}, FULL_COLUMNS)))
    assert checks["표 elder_link_codes"].level == FAIL
    assert "2026-10-14-elder-link.sql" in checks["표 elder_link_codes"].detail


def test_no_guardian_with_a_login_is_a_warning():
    checks = by_name(check_database(FakePool(FULL_TABLES, FULL_COLUMNS, counts=(0, 2))))
    assert checks["로그인 보호자"].level == WARN
    assert "2명" in checks["운영자 확인 대기"].detail


def test_a_database_error_is_a_failure_without_leaking_the_message():
    checks = check_database(FakePool(set(), set(), error=RuntimeError("password=hunter2")))
    assert checks[0].level == FAIL and "hunter2" not in checks[0].detail


def test_the_admin_command_exits_nonzero_on_failure_and_zero_when_fine(monkeypatch):
    lines = []
    keys, directory = InMemoryGuardianKeyStore(), InMemoryElderDirectory({12: ElderAccess(1, True)})

    for k in list(os.environ):
        if k in GOOD_ENV or k == "FCM_SERVICE_ACCOUNT_FILE":
            monkeypatch.delenv(k)
    for k, v in GOOD_ENV.items():
        monkeypatch.setenv(k, v)

    ok = run(["check"], keys=keys, directory=directory, out=lines.append, err=lines.append,
             pool=FakePool(FULL_TABLES, FULL_COLUMNS))
    bad = run(["check"], keys=keys, directory=directory, out=lines.append, err=lines.append,
              pool=FakePool(FULL_TABLES - {"call_medication"}, FULL_COLUMNS))
    assert ok == 0 and bad == 1
    assert any("call_medication" in str(line) for line in lines)


@pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="DATABASE_URL이 없다")
def test_the_local_database_passes_the_real_check():
    from tests.pg_helpers import pg_pool

    pool = pg_pool()
    try:
        checks = by_name(check_database(pool))
    finally:
        pool.close()
    assert checks["DB 표·칸"].level == OK, [c for c in checks.values() if c.level == FAIL]
