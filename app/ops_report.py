"""일일 운영 리포트 — `python -m app.admin report` (서버에서 사람이 아침에 한 번 돌려 본다).

"어제 전화가 제대로 나갔나"를 DB 한 번 읽어 알려 준다. 읽기만 한다 — 아무것도 바꾸지 않는다.
이름·전화번호·대화 내용은 싣지 않는다(어르신 번호와 개수만). 터미널에 남는 기록이라서다.

보는 것:
  통화      기간 안의 통화를 예약/요청 × 상태로 센다. 실패한 통화는 이유(error_code)별로 센다.
  스케줄 누락 오늘 통화 시각이 지났는데(유예 30분 포함) 예약 통화가 한 건도 만들어지지 않은 어르신.
              서버가 꺼져 있었거나 스케줄러가 멈췄다는 신호다. 미응답과는 다르다(미응답은 건 뒤에 안 받은 것).
  알림      종류별 개수.
  AI 채팅   대화 덩이·어르신이 보낸 말·위급 표현 분류별 개수.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta

from app.scheduler import DEFAULT_GRACE_SECONDS, KST

_STATUS_ORDER = ("completed", "no_answer", "failed", "answered", "ringing", "scheduled")
_TRIGGER_LABEL = {"scheduled": "예약", "requested": "요청"}
_STATUS_LABEL = {
    "completed": "완료",
    "no_answer": "미응답",
    "failed": "실패",
    "answered": "통화 중",
    "ringing": "울리는 중",
    "scheduled": "걸기 전",
}
_ALERT_LABEL = {"risk_rise": "평소와 다름", "no_answer": "미응답", "emergency_keyword": "위급 표현"}
_URGENT_LABEL = {"medical": "몸 불편", "fall": "낙상", "self_harm": "극단적 표현", "help": "도움 요청"}


def period_start(now: datetime, days: int) -> datetime:
    """한국 시간 기준 오늘 0시에서 (days-1)일 앞. days=1이면 오늘 0시부터."""
    local = now.astimezone(KST)
    midnight = local.replace(hour=0, minute=0, second=0, microsecond=0)
    return midnight - timedelta(days=days - 1)


def build_report(pool, now: datetime, days: int = 1) -> list[str]:
    """리포트 줄들. DB를 읽기만 한다."""
    since = period_start(now, days)
    local_now = now.astimezone(KST)
    lines = [
        f"운영 리포트 — {since:%Y-%m-%d %H:%M} ~ {local_now:%Y-%m-%d %H:%M} (한국 시간, {days}일)",
        "",
    ]
    with pool.connection() as conn:
        lines += _calls(conn, since, local_now)
        lines += _missing_schedules(conn, local_now)
        lines += _alerts(conn, since)
        lines += _chat(conn, since)
    return lines


def _calls(conn, since: datetime, local_now: datetime) -> list[str]:
    rows = conn.execute(
        "SELECT trigger_type, status, count(*) FROM calls WHERE created_at >= %s GROUP BY 1, 2", (since,)
    ).fetchall()
    out = ["[통화]"]
    if not rows:
        return out + ["  기간 안에 통화가 없다.", ""]
    counts = {(r[0], r[1]): r[2] for r in rows}
    for trigger in ("scheduled", "requested"):
        parts = [
            f"{_STATUS_LABEL.get(s, s)} {counts[(trigger, s)]}"
            for s in _STATUS_ORDER
            if counts.get((trigger, s))
        ]
        if parts:
            out.append(f"  {_TRIGGER_LABEL[trigger]}: " + ", ".join(parts))
    failures = conn.execute(
        "SELECT coalesce(error_code, '(이유 없음)'), count(*) FROM calls "
        "WHERE created_at >= %s AND status = 'failed' GROUP BY 1 ORDER BY 2 DESC",
        (since,),
    ).fetchall()
    if failures:
        out.append("  실패 이유: " + ", ".join(f"{code} {n}" for code, n in failures))
    stuck = conn.execute(
        "SELECT count(*) FROM calls WHERE created_at >= %s AND status IN ('scheduled', 'ringing', 'answered') "
        "AND created_at < %s",
        (since, local_now - timedelta(hours=2)),
    ).fetchone()[0]
    if stuck:
        out.append(f"  주의: 두 시간이 넘도록 끝나지 않은 통화 {stuck}건 (서버가 중간에 멈췄을 수 있다)")
    return out + [""]


def _missing_schedules(conn, local_now: datetime) -> list[str]:
    """오늘 통화 시각 + 유예가 지났는데 오늘 예약 통화가 없는 어르신(동의한 어르신만)."""
    today_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    deadline = (local_now - timedelta(seconds=DEFAULT_GRACE_SECONDS)).time()
    rows = conn.execute(
        "SELECT e.elder_id, e.call_time FROM elders e "
        "WHERE e.consent_at IS NOT NULL AND e.guardian_id IS NOT NULL AND e.call_time <= %s "
        "AND NOT EXISTS (SELECT 1 FROM calls c WHERE c.elder_id = e.elder_id "
        "                AND c.trigger_type = 'scheduled' AND c.created_at >= %s) "
        "ORDER BY e.call_time, e.elder_id",
        (deadline, today_start),
    ).fetchall()
    out = ["[스케줄 누락]"]
    if not rows:
        return out + ["  없다 — 통화 시각이 지난 어르신은 모두 오늘 예약 통화가 만들어졌다.", ""]
    ids = ", ".join(f"{r[0]}번({r[1]:%H:%M})" for r in rows)
    return out + [f"  오늘 통화 시각이 지났는데 예약 통화가 없는 어르신 {len(rows)}명: {ids}", ""]


def _alerts(conn, since: datetime) -> list[str]:
    rows = conn.execute(
        "SELECT alert_type, count(*) FROM alerts WHERE created_at >= %s GROUP BY 1 ORDER BY 2 DESC", (since,)
    ).fetchall()
    out = ["[알림]"]
    if not rows:
        return out + ["  기간 안에 알림이 없다.", ""]
    return out + ["  " + ", ".join(f"{_ALERT_LABEL.get(t, t)} {n}" for t, n in rows), ""]


def _chat(conn, since: datetime) -> list[str]:
    out = ["[AI 채팅]"]
    sessions = conn.execute("SELECT count(*) FROM chat_sessions WHERE started_at >= %s", (since,)).fetchone()[0]
    messages = conn.execute(
        "SELECT count(*) FROM chat_messages WHERE role = 'elder' AND created_at >= %s", (since,)
    ).fetchone()[0]
    if not sessions and not messages:
        return out + ["  기간 안에 채팅이 없다.", ""]
    out.append(f"  대화 {sessions}덩이, 어르신이 보낸 말 {messages}개")
    urgent = conn.execute(
        "SELECT urgent, count(*) FROM chat_messages WHERE urgent IS NOT NULL AND created_at >= %s GROUP BY 1 ORDER BY 2 DESC",
        (since,),
    ).fetchall()
    if urgent:
        out.append("  위급 표현: " + ", ".join(f"{_URGENT_LABEL.get(c, c)} {n}" for c, n in urgent))
    return out + [""]


def health(check_database: Callable[[], bool] | None) -> tuple[int, dict]:
    """(HTTP 상태, 본문). 본문에는 상태 말고 아무것도 싣지 않는다 — 인증 없는 주소다."""
    if check_database is None:
        return 200, {"status": "ok"}
    try:
        ok = bool(check_database())
    except Exception:
        ok = False
    return (200, {"status": "ok"}) if ok else (503, {"status": "database_down"})
