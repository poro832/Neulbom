"""서버 반영 점검 — `python -m app.admin check` (서버에서 사람이 실행한다).

반영한 뒤 한 번에 본다: 필요한 DB 표·칸이 다 있는지, 푸시 열쇠 파일을 읽을 수 있는지, 통화·대화
설정이 있는지, 로그인할 수 있는 보호자가 있는지. SQL 순서 하나가 틀려도 조용히 오류가 나는
구조라서 만들었다. **비밀 값은 출력하지 않는다** — 설정이 있는지와 파일을 읽었는지만 말한다.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass

OK, WARN, FAIL = "ok", "warn", "fail"


@dataclass(frozen=True)
class Check:
    name: str
    level: str  # ok | warn | fail
    detail: str


# 표 -> 그 표를 만드는 SQL 파일 (db/migrations/ 아래)
TABLE_MIGRATIONS = {
    "guardian_keys": "2026-10-08-guardian-keys.sql",
    "guardian_invites": "2026-10-09-guardian-invites.sql",
    "alerts": "2026-10-09-app-data.sql",
    "contacts": "2026-10-09-app-data.sql",
    "elder_keys": "2026-10-09-app-data.sql",
    "elder_pairings": "2026-10-09-app-data.sql",
    "call_reports": "2026-10-10-transcript-sharing.sql",
    "call_turns": "2026-10-10-transcript-sharing.sql",
    "transcript_views": "2026-10-10-transcript-sharing.sql",
    "call_medication": "2026-10-13-call-medication.sql",
    "call_mentions": "2026-10-15-call-mentions.sql",
    "guardian_devices": "2026-10-13-guardian-devices.sql",
    "elder_link_codes": "2026-10-14-elder-link.sql",
}

# (표, 칸) -> 그 칸을 더하는 SQL 파일
COLUMN_MIGRATIONS = {
    ("calls", "requested_by_guardian_id"): "2026-10-08-guardian-keys.sql",
    ("elders", "share_agreed_at"): "2026-10-10-transcript-sharing.sql",
    ("guardians", "activated_at"): "2026-10-13-guardian-activation.sql",
    ("guardians", "email_verified_at"): "2026-10-15-email-verified.sql",
}

NO_LOGIN_SUFFIX = "@no-login.invalid"


def check_database(pool) -> list[Check]:
    checks: list[Check] = []
    try:
        with pool.connection() as conn:
            tables = {
                r[0]
                for r in conn.execute(
                    "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
                ).fetchall()
            }
            columns = {
                (r[0], r[1])
                for r in conn.execute(
                    "SELECT table_name, column_name FROM information_schema.columns "
                    "WHERE table_schema = 'public'"
                ).fetchall()
            }
            missing_tables = {t: f for t, f in TABLE_MIGRATIONS.items() if t not in tables}
            missing_columns = {c: f for c, f in COLUMN_MIGRATIONS.items() if c not in columns}
            counts = None
            if ("guardians", "activated_at") in columns:
                counts = conn.execute(
                    "SELECT count(*) FILTER (WHERE email NOT LIKE %s), "
                    "count(*) FILTER (WHERE activated_at IS NULL) FROM guardians",
                    ("%" + NO_LOGIN_SUFFIX,),
                ).fetchone()
    except Exception as exc:
        return [Check("DB 연결", FAIL, f"DB를 읽지 못했다 ({type(exc).__name__})")]

    checks.append(Check("DB 연결", OK, "읽었다"))
    if not missing_tables and not missing_columns:
        checks.append(Check("DB 표·칸", OK, f"필요한 표 {len(TABLE_MIGRATIONS)}개와 칸 {len(COLUMN_MIGRATIONS)}개가 있다"))
    for table, file in sorted(missing_tables.items()):
        checks.append(Check(f"표 {table}", FAIL, f"없다 — db/migrations/{file}을 실행한다"))
    for (table, column), file in sorted(missing_columns.items()):
        checks.append(Check(f"칸 {table}.{column}", FAIL, f"없다 — db/migrations/{file}을 실행한다"))
    if counts is not None:
        with_login, pending = counts
        if with_login == 0:
            checks.append(
                Check("로그인 보호자", WARN, "이메일로 로그인할 수 있는 보호자가 없다 — `guardian set-login <번호> --email ...`")
            )
        else:
            checks.append(Check("로그인 보호자", OK, f"{with_login}명"))
        checks.append(Check("운영자 확인 대기", OK, f"{pending}명" + (" — `guardian pending`으로 확인한다" if pending else "")))
    return checks


def check_environment(
    env: Mapping[str, str],
    *,
    path_exists: Callable[[str], bool] = os.path.exists,
    sender_factory: Callable[[Mapping[str, str]], object | None] | None = None,
) -> list[Check]:
    if sender_factory is None:
        from app.push import sender_from_env

        sender_factory = sender_from_env

    def has(name: str) -> bool:
        return bool(env.get(name, "").strip())

    checks: list[Check] = []

    def need(names: tuple[str, ...], label: str, consequence: str, level: str = FAIL) -> None:
        missing = [n for n in names if not has(n)]
        if missing:
            checks.append(Check(label, level, f"{', '.join(missing)}이 없다 — {consequence}"))
        else:
            checks.append(Check(label, OK, "설정돼 있다"))

    need(("DATABASE_URL",), "DB 주소", "서버가 메모리 모드로 떠서 모든 보호자 주소가 401이다")
    need(("CLOVA_STUDIO_BASE_URL", "CLOVA_STUDIO_API_KEY"), "대화·요약·복용 확인(CLOVA Studio)", "AI 대화와 요약·복용 확인이 꺼진다")
    need(("CLAWOPS_ACCOUNT_SID", "CLAWOPS_API_KEY", "CLAWOPS_FROM_NUMBER"), "전화(ClawOps)", "전화를 걸 수 없다")
    need(("PUBLIC_BASE_URL", "STREAM_BASE_URL"), "공개 주소", "전화 연결 주소를 만들 수 없다")
    need(("FIREBASE_PROJECT_ID",), "이메일 인증(Firebase)", "새 보호자가 이메일 인증을 못 해 어르신을 연결할 수 없다")
    need(("RECORDINGS_BUCKET",), "녹음 보관(S3)", "녹음이 보관되지 않는다", level=WARN)

    path = env.get("FCM_SERVICE_ACCOUNT_FILE", "").strip()
    if not path:
        checks.append(Check("푸시(FCM)", WARN, "FCM_SERVICE_ACCOUNT_FILE이 없다 — 푸시가 꺼져 있다"))
    elif not path_exists(path):
        checks.append(Check("푸시(FCM)", FAIL, "열쇠 파일이 그 경로에 없다 (경로를 확인한다)"))
    elif sender_factory(env) is None:
        checks.append(Check("푸시(FCM)", FAIL, "열쇠 파일을 읽지 못했다 — JSON이 맞는지, 권한이 맞는지 확인한다"))
    else:
        checks.append(Check("푸시(FCM)", OK, "열쇠 파일을 읽었다(실제 발송은 따로 시험한다)"))
    return checks


def run_checks(pool, env: Mapping[str, str] | None = None) -> list[Check]:
    env = os.environ if env is None else env
    checks = check_environment(env)
    checks += check_database(pool) if pool is not None else [Check("DB 연결", FAIL, "DATABASE_URL이 없다")]
    return checks


def format_checks(checks: list[Check]) -> tuple[list[str], int]:
    """(출력 줄들, 실패 수)."""
    mark = {OK: "OK  ", WARN: "주의", FAIL: "실패"}
    lines = [f"{mark[c.level]} {c.name} — {c.detail}" for c in checks]
    failed = sum(1 for c in checks if c.level == FAIL)
    warned = sum(1 for c in checks if c.level == WARN)
    lines.append("")
    lines.append(f"실패 {failed}개 · 주의 {warned}개" + (" — 위 실패를 고친 뒤 다시 실행한다." if failed else " — 반영 상태가 맞다."))
    return lines, failed
