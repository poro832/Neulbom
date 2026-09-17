"""통화 기록 저장소 (전화망 설계 5장).

DB가 붙기 전까지 메모리 구현을 쓴다. 규약이 같으므로 PostgreSQL 구현으로
갈아끼울 때 API 코드는 바뀌지 않는다.
"""

from __future__ import annotations

import itertools
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Protocol

logger = logging.getLogger(__name__)

# 통화가 아직 끝나지 않았다고 보는 상태들. 이 동안 재요청은 409다.
#
# 'answered'는 우리 스트림 소켓이 실제로 붙은 통화다. 이 상태를 아무도 쓰지
# 않던 동안 종료 처리는 "여기까지 활성이면 오디오가 안 붙은 것"이라고
# 추론할 수밖에 없었는데, 그 추론이 틀렸다 — 사업자 웹훅과 우리 소켓 종료는
# 서로 다른 경로라 통화 중에 웹훅이 먼저 도착한다. 그러면 멀쩡히 통화하고
# 녹음까지 남긴 어르신이 '전화를 받지 않은 사람'으로 기록된다. 상태 기계가
# 이 둘을 말로 구분할 수 있어야 추론을 안 한다.
ACTIVE_STATUSES = frozenset({"scheduled", "ringing", "answered"})

# 이 시간이 지나도록 끝을 확인하지 못한 통화는 더 이상 '진행 중'이 아니다.
# 스트림 종료도 사업자 웹훅도 유실될 수 있는데, 그 한 번의 유실이 어르신을
# 영구히 잠가 버리면(다시는 전화를 요청할 수 없다) 복구할 방법이 없다.
# 반대로 너무 짧으면 통화 중에 재요청이 통과해 전화가 한 번 더 걸리는데,
# 그건 어르신이 끊으면 끝나는, 복구 가능한 불편이다. 긴 안부 통화도 10분을
# 넘기지 않으므로 그 배수를 바닥으로 둔다.
MAX_ACTIVE_SECONDS = 20 * 60


@dataclass(frozen=True)
class CallRecord:
    call_id: int
    elder_id: int
    trigger_type: str
    status: str
    provider_call_sid: str | None = None
    # 녹음 파일 이름. 스키마의 calls.audio_key에 대응하며, 그 테이블은
    # status='completed'인데 audio_key가 없는 행을 제약으로 금지한다 —
    # 끝났다고 표시된 통화에 분석할 오디오가 없으면 파이프라인이 조용히 멈춘다.
    audio_key: str | None = None
    # 이 기록이 만들어진 시각(monotonic). 벽시계를 쓰면 시스템 시간이 뒤로
    # 조정될 때 활성 판정이 뒤집힌다.
    created_at: float = 0.0


class CallStore(Protocol):
    def find_elder(self, elder_id: int) -> str | None: ...
    def find_active(self, elder_id: int) -> CallRecord | None: ...
    def get(self, call_id: int) -> CallRecord: ...
    def find_by_sid(self, sid: str) -> CallRecord | None:
        """사업자 식별자로 통화를 찾는다. 웹훅은 이 식별자만 들고 온다."""
        ...

    def create(self, elder_id: int, trigger_type: str) -> CallRecord: ...
    def find_active_or_create(
        self, elder_id: int, trigger_type: str
    ) -> tuple[CallRecord, bool]:
        """활성 통화를 찾거나, 없으면 만든다 — 검사와 생성을 한 덩어리로.

        FastAPI가 sync 라우트를 스레드풀에서 돌리므로, 이 둘을 따로 부르면
        두 스레드가 모두 find_active를 통과한 뒤에야 create가 불려 전화가
        두 번 걸릴 수 있다. 두 번째 값은 새로 만들었으면 True다.
        """
        ...

    def attach_sid(self, call_id: int, sid: str) -> None: ...
    def mark_answered(self, call_id: int) -> None:
        """우리 스트림이 이 통화에 붙었다 — 어르신이 실제로 받았다는 증거다."""
        ...

    def mark_failed(self, call_id: int) -> None: ...
    def mark_completed(self, call_id: int, audio_key: str) -> None:
        """통화가 정상적으로 끝났다. 녹음이 있어야 끝난 것이다."""
        ...

    def mark_no_answer(self, call_id: int) -> None:
        """전화는 걸렸지만 오디오가 한 번도 붙지 않았다."""
        ...


class InMemoryCallStore:
    def __init__(
        self,
        phones: dict[int, str],
        clock: Callable[[], float] = time.monotonic,
        max_active_seconds: float = MAX_ACTIVE_SECONDS,
    ) -> None:
        self._phones = phones
        self._calls: dict[int, CallRecord] = {}
        self._ids = itertools.count(1)
        self._clock = clock
        self._max_active_seconds = max_active_seconds
        # find_active + create를 한 스레드가 끝낼 때까지 다른 스레드를 세운다.
        # 상태 전이(mark_*)도 읽고-고쳐-쓰기라 같은 락으로 묶는다. 전이가
        # find_active_or_create 안에서 다시 불릴 수 있어 재진입 가능해야 한다.
        self._lock = threading.RLock()

    def find_elder(self, elder_id: int) -> str | None:
        return self._phones.get(elder_id)

    def find_active(self, elder_id: int) -> CallRecord | None:
        now = self._clock()
        for call in self._calls.values():
            if call.elder_id != elder_id or call.status not in ACTIVE_STATUSES:
                continue
            if now - call.created_at > self._max_active_seconds:
                # 끝을 알리는 신호가 하나도 오지 않은 기록이다. 계속 활성으로
                # 세면 유실된 웹훅 하나가 영구 잠금이 된다(위 상수 참고).
                continue
            return call
        return None

    def get(self, call_id: int) -> CallRecord:
        return self._calls[call_id]

    def find_by_sid(self, sid: str) -> CallRecord | None:
        for call in self._calls.values():
            if call.provider_call_sid == sid:
                return call
        return None

    def create(self, elder_id: int, trigger_type: str) -> CallRecord:
        call = CallRecord(
            call_id=next(self._ids),
            elder_id=elder_id,
            trigger_type=trigger_type,
            status="scheduled",
            created_at=self._clock(),
        )
        self._calls[call.call_id] = call
        return call

    def find_active_or_create(
        self, elder_id: int, trigger_type: str
    ) -> tuple[CallRecord, bool]:
        # 락 없이 find_active와 create를 따로 부르면, 두 스레드가 모두
        # "없다"를 보고 동시에 만들어 실제 전화가 두 번 걸릴 수 있다.
        with self._lock:
            self._expire_stale(elder_id)
            active = self.find_active(elder_id)
            if active is not None:
                return active, False
            return self.create(elder_id, trigger_type), True

    def _expire_stale(self, elder_id: int) -> None:
        """끝을 확인하지 못한 채 너무 오래된 활성 기록을 정리한다.

        find_active가 이미 걸러 주므로 재요청은 이것 없이도 통과한다. 그래도
        상태를 실제로 옮기는 이유는, 'ringing'으로 굳은 기록이 남아 있으면
        나중에 미응답 통계나 운영 화면이 그 거짓말을 그대로 읽기 때문이다.
        끝을 모르는 통화는 completed가 아니라 failed다 — 지어내지 않는다.
        """
        now = self._clock()
        for call_id, call in list(self._calls.items()):
            if call.elder_id != elder_id or call.status not in ACTIVE_STATUSES:
                continue
            if now - call.created_at <= self._max_active_seconds:
                continue
            logger.warning(
                "끝을 확인하지 못한 통화를 정리한다 call_id=%s status=%s",
                call_id,
                call.status,
            )
            self._calls[call_id] = replace(call, status="failed")

    def attach_sid(self, call_id: int, sid: str) -> None:
        with self._lock:
            self._calls[call_id] = replace(
                self._calls[call_id], provider_call_sid=sid, status="ringing"
            )

    def mark_answered(self, call_id: int) -> None:
        """우리 스트림이 붙었다. 아직 진행 중이지만 '받은' 통화다.

        종료 상태가 아니므로 _finish가 아니다. 이 전이가 있어야 종료 처리가
        "받았는데 웹훅이 먼저 왔다"와 "아예 받지 않았다"를 추론이 아니라
        기록으로 구분한다(ACTIVE_STATUSES 주석 참고).
        """
        with self._lock:
            call = self._calls.get(call_id)
            if call is None:
                logger.error("모르는 통화가 스트림에 붙었다 call_id=%s", call_id)
                return
            if call.status not in ACTIVE_STATUSES:
                # 이미 끝난 통화를 되살리지 않는다. 늦게 붙은 스트림 하나가
                # 종료된 기록을 활성으로 돌려놓으면 어르신이 다시 잠긴다.
                logger.warning(
                    "이미 끝난 통화에 스트림이 붙었다 call_id=%s status=%s",
                    call_id,
                    call.status,
                )
                return
            self._calls[call_id] = replace(call, status="answered")

    def mark_failed(self, call_id: int) -> None:
        # 실패한 통화가 '진행 중'으로 남으면 그 어르신은 영원히 409를 받는다.
        self._finish(call_id, "failed")

    def mark_completed(self, call_id: int, audio_key: str) -> None:
        self._finish(call_id, "completed", audio_key=audio_key)

    def mark_no_answer(self, call_id: int) -> None:
        self._finish(call_id, "no_answer")

    def _finish(self, call_id: int, status: str, audio_key: str | None = None) -> None:
        """활성 상태일 때만 종료 상태로 옮긴다.

        스트림 종료와 사업자 웹훅은 둘 다 올 수 있고 순서도 보장되지 않는다.
        멱등하지 않으면 늦게 온 웹훅이 방금 completed로 끝난 통화를
        no_answer로 되돌려 지표가 조용히 틀린다.
        """
        with self._lock:
            call = self._calls[call_id]
            if call.status not in ACTIVE_STATUSES:
                return
            self._calls[call_id] = replace(
                call, status=status, audio_key=audio_key or call.audio_key
            )
