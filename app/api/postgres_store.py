"""통화 상태 저장소 — Postgres (설계 6장).

`InMemoryCallStore`와 같은 `CallStore` 규약을 구현한다. 둘이 갈라지지 않도록
`tests/test_call_store_contract.py`가 같은 테스트를 양쪽에 돌린다.

**메모리 구현과 달라지는 것 셋.**

`call_id`가 재시작해도 1로 돌아가지 않는다. `BIGSERIAL`이 이어 준다. 녹음 파일
이름이 `{call_id}-{UTC시각}-{난수}.wav`인 이유가 그 문제였고, 전사 워커가 버린
목록을 `call_id`로 남기는 것도 재시작 뒤엔 어느 통화인지 알 수 없었다.

**어르신당 활성 통화 하나를 DB가 막는다.** 부분 유니크 인덱스
`calls_one_active_per_elder`가 지킨다. 메모리 구현은 Python 락으로 지키는데
락은 한 프로세스 안에서만 유효하다. 그래서 여기서는 "넣어 보고 충돌하면 기존
것을 읽는다"로 쓴다 — 확인하고 넣는 순서였다면 그 사이에 끼어들 수 있다.

**바닥 시간이 재시작을 견딘다.** 메모리 구현은 재시작하면 통화가 통째로
사라져서 "끝을 못 본 통화"가 남을 일이 없었다. 여기서는 `ringing`으로 굳은
행이 살아남으므로, 언제부터 활성이었는지를 실제로 알아야 한다.

**시계를 주입받는 이유.** 규약 테스트가 바닥 시간을 가짜 시계로 시험한다.
기본값은 `time.time()`이다 — 메모리 구현은 `time.monotonic()`을 쓰지만, 그건
재시작하면 0으로 돌아가는 값이라 DB에 남길 수 없다. 저장할 때
`to_timestamp()`로 진짜 시각이 되므로 사람이 읽을 수도 있다.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable

from app.api.store import (
    ACTIVE_STATUSES,
    FINISHED_STATUSES,
    MAX_ACTIVE_SECONDS,
    CallRecord,
)
from app.scheduler import RosterEntry

from app.api.db import assert_local

logger = logging.getLogger(__name__)

# SELECT가 CallRecord를 만들 때 쓰는 열 순서. 한 군데만 두어 조회마다
# 어긋나지 않게 한다 — 순서가 밀리면 elder_id 자리에 call_id가 들어가고도
# 타입이 같아서 아무 오류가 안 난다.
_COLUMNS = (
    "call_id, elder_id, trigger_type, status, provider_call_sid, audio_key, "
    "extract(epoch from created_at)::float8 AS created_at, "
    "requested_by_guardian_id"
)


def _record(row) -> CallRecord:
    return CallRecord(
        call_id=row[0],
        elder_id=row[1],
        trigger_type=row[2],
        status=row[3],
        provider_call_sid=row[4],
        audio_key=row[5],
        created_at=row[6],
        requested_by=row[7],
    )


class PostgresCallStore:
    def __init__(
        self,
        *,
        pool,
        phones: dict[int, str],
        clock: Callable[[], float] = time.time,
        max_active_seconds: float = MAX_ACTIVE_SECONDS,
    ) -> None:
        self._pool = pool
        # 어르신 명부는 아직 환경 변수에서 온다. elders 테이블이 채워지면
        # 여기가 그 조회로 바뀐다 — 지금은 메모리 구현과 같은 자리에 둔다.
        self._phones = phones
        self._clock = clock
        self._max_active_seconds = max_active_seconds
        self._expiry_listeners: list[Callable[[CallRecord], None]] = []

    # ------------------------------------------------------------ 조회

    def find_elder(self, elder_id: int) -> str | None:
        return self._phones.get(elder_id)

    def get(self, call_id: int) -> CallRecord:
        with self._pool.connection() as conn:
            row = conn.execute(
                f"SELECT {_COLUMNS} FROM calls WHERE call_id = %s", (call_id,)
            ).fetchone()
        if row is None:
            raise KeyError(call_id)
        return _record(row)

    def find_active(self, elder_id: int) -> CallRecord | None:
        with self._pool.connection() as conn:
            row = conn.execute(
                f"SELECT {_COLUMNS} FROM calls "
                "WHERE elder_id = %s AND status = ANY(%s) "
                "ORDER BY call_id DESC LIMIT 1",
                (elder_id, list(ACTIVE_STATUSES)),
            ).fetchone()
        return _record(row) if row else None

    def find_by_sid(self, sid: str) -> CallRecord | None:
        """사업자 식별자로 통화를 찾는다. 웹훅은 이 식별자만 들고 온다."""
        with self._pool.connection() as conn:
            row = conn.execute(
                f"SELECT {_COLUMNS} FROM calls WHERE provider_call_sid = %s", (sid,)
            ).fetchone()
        return _record(row) if row else None

    def recent_scheduled(
        self, elder_id: int, limit: int, before_call_id: int | None = None
    ) -> list[CallRecord]:
        """끝난 예약 통화를 최신순으로 (설계 3.3).

        요청 통화는 세지 않는다 — 그 미응답은 어르신이 버튼을 누르고 전화기를
        못 찾은 것일 뿐이라, 위험 신호로 세면 활발한 분이 오히려 감점된다.

        before_call_id는 자기 자신과 미래 통화를 함께 막는다. 잘라내기가
        먼저고 LIMIT이 나중이다 — 반대로 하면 표본이 limit보다 적어진다.
        """
        with self._pool.connection() as conn:
            rows = conn.execute(
                f"SELECT {_COLUMNS} FROM calls "
                "WHERE elder_id = %s AND trigger_type = 'scheduled' "
                "  AND status = ANY(%s) "
                "  AND (%s::bigint IS NULL OR call_id < %s::bigint) "
                "ORDER BY call_id DESC LIMIT %s",
                (
                    elder_id,
                    list(FINISHED_STATUSES),
                    before_call_id,
                    before_call_id,
                    limit,
                ),
            ).fetchall()
        return [_record(row) for row in rows]

    # ------------------------------------------------------------ 생성

    def create(
        self, elder_id: int, trigger_type: str, requested_by: int | None = None
    ) -> CallRecord:
        with self._pool.connection() as conn:
            row = conn.execute(
                "INSERT INTO calls (elder_id, trigger_type, status, created_at, "
                "                   requested_by_guardian_id) "
                "VALUES (%s, %s, 'scheduled', to_timestamp(%s), %s) "
                f"RETURNING {_COLUMNS}",
                (elder_id, trigger_type, self._clock(), requested_by),
            ).fetchone()
        return _record(row)

    def count_requested_since(self, elder_id: int, since: float) -> int:
        with self._pool.connection() as conn:
            row = conn.execute(
                "SELECT count(*) FROM calls "
                "WHERE elder_id = %s AND trigger_type = 'requested' "
                "  AND created_at >= to_timestamp(%s)",
                (elder_id, since),
            ).fetchone()
        return row[0]

    def find_active_or_create(
        self, elder_id: int, trigger_type: str, requested_by: int | None = None
    ) -> tuple[CallRecord, bool]:
        """활성 통화를 찾거나, 없으면 만든다 — 검사와 생성을 한 덩어리로.

        먼저 넣어 보고 유니크 위반이면 기존 것을 읽는다. 확인하고 넣는
        순서였다면 그 사이에 다른 요청이 끼어들어 한 어르신에게 두 통이
        나갈 수 있다. 여기서는 DB의 부분 유니크 인덱스가 그걸 막는다.
        """
        self._expire_stale(elder_id)

        from psycopg import errors

        try:
            return self.create(elder_id, trigger_type, requested_by), True
        except errors.UniqueViolation:
            existing = self.find_active(elder_id)
            if existing is not None:
                return existing, False
            # 유니크 위반인데 활성 통화가 없다 — provider_call_sid 쪽 충돌일
            # 수 있다. 삼키면 원인이 사라지므로 올린다.
            raise

    # ------------------------------------------------------------ 상태 전이

    def attach_sid(self, call_id: int, sid: str) -> None:
        """사업자 식별자를 붙이고 '울리는 중'으로 옮긴다.

        활성일 때만 옮긴다. 이 검사가 없으면 이미 끝난(예: 바닥 시간에
        failed로 접힌) 기록을 ringing으로 되살릴 수 있고, 되살아난 기록은
        어르신을 다시 409로 잠근다.
        """
        with self._pool.connection() as conn:
            updated = conn.execute(
                "UPDATE calls SET provider_call_sid = %s, status = 'ringing' "
                "WHERE call_id = %s AND status = ANY(%s)",
                (sid, call_id, list(ACTIVE_STATUSES)),
            ).rowcount
        if not updated:
            logger.warning(
                "활성이 아닌 통화에 사업자 식별자를 붙이려 했다 call_id=%s", call_id
            )

    def mark_answered(self, call_id: int) -> None:
        """우리 스트림이 이 통화에 붙었다 — 어르신이 실제로 받았다는 증거다."""
        with self._pool.connection() as conn:
            conn.execute(
                "UPDATE calls SET status = 'answered' "
                "WHERE call_id = %s AND status = ANY(%s)",
                (call_id, list(ACTIVE_STATUSES)),
            )

    def mark_failed(self, call_id: int) -> None:
        self._finish(call_id, "failed")

    def mark_no_answer(self, call_id: int) -> None:
        """전화는 걸렸지만 오디오가 한 번도 붙지 않았다."""
        self._finish(call_id, "no_answer")

    def mark_completed(self, call_id: int, audio_key: str) -> None:
        """통화가 정상적으로 끝났다. 녹음이 있어야 끝난 것이다."""
        self._finish(call_id, "completed", audio_key=audio_key)

    def _finish(self, call_id: int, status: str, audio_key: str | None = None) -> None:
        """활성 상태일 때만 종료 상태로 옮긴다.

        스트림 종료와 사업자 웹훅은 둘 다 올 수 있고 순서도 보장되지 않는다.
        멱등하지 않으면 늦게 온 웹훅이 방금 completed로 끝난 통화를
        no_answer로 되돌려 지표가 조용히 틀린다.
        """
        with self._pool.connection() as conn:
            updated = conn.execute(
                "UPDATE calls SET status = %s, "
                "       audio_key = COALESCE(%s, audio_key), "
                "       ended_at = now() "
                "WHERE call_id = %s AND status = ANY(%s)",
                (status, audio_key, call_id, list(ACTIVE_STATUSES)),
            ).rowcount
        if not updated:
            # KeyError를 던지면 호출부(lifecycle.stream_finished)가 토큰을
            # 폐기하기도 전에 끊긴다 — 모르는 통화 하나가 토큰을 흘린다.
            logger.debug(
                "이미 끝났거나 모르는 통화다 — 그대로 둔다 call_id=%s", call_id
            )

    # ------------------------------------------------------------ 바닥 시간

    def add_expiry_listener(self, listener: Callable[[CallRecord], None]) -> None:
        """바닥 시간이 통화를 접을 때 부를 콜백을 건다.

        상태만 옮기고 끝내면 그 통화의 스트림 토큰이 계속 살아 있다 —
        인증 없는 /v1/voiceml에서 꺼내진다. 접은 기록을 넘겨 lifecycle이
        토큰까지 닫게 한다.
        """
        self._expiry_listeners.append(listener)

    def _expire_stale(self, elder_id: int) -> None:
        """끝을 확인하지 못한 채 너무 오래된 활성 기록을 정리한다.

        끝을 모르는 통화는 completed가 아니라 failed다 — 지어내지 않는다.
        """
        cutoff = self._clock() - self._max_active_seconds
        with self._pool.connection() as conn:
            rows = conn.execute(
                "UPDATE calls SET status = 'failed', ended_at = now() "
                "WHERE elder_id = %s AND status = ANY(%s) "
                "  AND created_at < to_timestamp(%s) "
                f"RETURNING {_COLUMNS}",
                (elder_id, list(ACTIVE_STATUSES), cutoff),
            ).fetchall()

        for row in rows:
            call = _record(row)
            logger.warning(
                "끝을 확인하지 못한 통화를 정리한다 call_id=%s", call.call_id
            )
            for listener in self._expiry_listeners:
                try:
                    listener(call)
                except Exception:
                    # 리스너 하나가 터져도 나머지 정리는 끝나야 한다 —
                    # 여기서 멈추면 어르신이 영구 잠금으로 돌아간다.
                    logger.exception("만료 통보 실패 call_id=%s", call.call_id)

    # ------------------------------------------------------------ 테스트용

    def reset_for_tests(self) -> None:
        """규약 테스트가 매번 빈 상태에서 시작하도록 비운다.

        운영 경로에서는 절대 불리지 않는다. 이름에 그렇게 적어 둔다.
        calls를 지우면 call_metrics와 call_transcripts는 CASCADE로 따라간다.
        """
        # 원격 DB에서 부르면 실통화 기록이 전부 사라진다(app/api/db.py 참고).
        assert_local()

        with self._pool.connection() as conn:
            conn.execute("TRUNCATE calls RESTART IDENTITY CASCADE")
            # 어르신 행이 없으면 FK 때문에 통화를 못 넣는다. 명부는 아직
            # 환경 변수에서 오므로, 테스트에 필요한 최소 행만 만든다.
            conn.execute(
                "INSERT INTO guardians "
                "  (guardian_id, name, email, password_hash, phone_number) "
                "VALUES (1, '테스트 보호자', 'test@example.invalid', 'x', "
                "        '010-0000-0000') "
                "ON CONFLICT (guardian_id) DO NOTHING"
            )
            for elder_id, phone in self._phones.items():
                conn.execute(
                    "INSERT INTO elders (elder_id, guardian_id, name, phone_number) "
                    "VALUES (%s, 1, %s, %s) "
                    "ON CONFLICT (elder_id) DO NOTHING",
                    (elder_id, f"테스트 어르신 {elder_id}", phone),
                )


class PostgresRoster:
    """스케줄러가 볼 명부 — 동의한 어르신과 마지막 예약 통화 시각.

    **동의가 없으면 여기 나오지 않는다.** `consent_at IS NOT NULL`이 유일한
    발신 자격 조건이고, `elders_due_idx`가 그 조건으로 걸려 있다. 동의를
    코드 여러 곳에서 확인하면 언젠가 한 곳이 빠지므로, 명부를 읽는 이
    질의 하나에만 둔다.

    **판정은 여기서 하지 않는다.** "지금 걸 시각인가"는 app/scheduler.py의
    순수 함수가 정한다 — SQL에 시간 논리를 넣으면 DB 없이 테스트할 수 없고,
    스케줄러에서 가장 틀리기 쉬운 부분이 바로 거기다.
    """

    def __init__(self, *, pool) -> None:
        self._pool = pool

    def entries(self) -> list[RosterEntry]:
        with self._pool.connection() as conn:
            rows = conn.execute(
                """
                SELECT e.elder_id,
                       e.call_time,
                       (SELECT max(c.created_at)
                          FROM calls c
                         WHERE c.elder_id = e.elder_id
                           AND c.trigger_type = 'scheduled') AS last_scheduled_at
                  FROM elders e
                 WHERE e.consent_at IS NOT NULL
                 ORDER BY e.elder_id
                """
            ).fetchall()
        return [
            RosterEntry(elder_id=row[0], call_time=row[1], last_scheduled_at=row[2])
            for row in rows
        ]
