"""매일 아침 발신 스케줄러 — 예약 통화를 만드는 유일한 곳.

**미응답 20점이 여기 달려 있다.** `trigger_type="scheduled"` 통화를 만드는
코드가 이것뿐이라, 이게 없으면 "안 받았다"가 발생할 수 없고 그 축은 영원히
0이다. 위험 점수의 실질 만점이 80에 머물러 있던 이유다.

**시계를 쓰는 유일한 자리.** 이 프로젝트는 "시계가 점수에 닿으면 안 된다"를
지켜 왔다. 그 규칙은 **점수 계산**에 대한 것이다 — 언제 전화를 걸지 정하는
데 시계를 쓰는 건 당연하다. 대신 여기서 읽은 시각이 점수 계산으로 흘러가지
않게 경계를 지킨다. 스케줄러가 하는 일은 "통화를 만든다"까지이고, 그 뒤는
기존 경로와 완전히 같다.

**왜 유예를 두는가.** 서버가 09:00~09:40 꺼져 있었다면 09:40에 걸어야 할까.
둘 다 문제가 있다 — 안 걸면 그날 데이터가 없고, 걸면 어르신이 예고 없이 늦은
전화를 받는다. 아침 안부 전화가 11시에 오면 그건 다른 제품이다. 그래서
30분까지는 걸고, 넘으면 건너뛴다.

**건너뛴 날은 미응답이 아니다.** 통화를 아예 만들지 않으므로 `recent_scheduled`
집계에 잡히지 않는다. 안 받은 게 아니라 **우리가 안 건** 것이라, 섞으면 서버
장애가 어르신 위험 점수를 올린다.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from typing import Callable, Protocol

logger = logging.getLogger(__name__)

# 한국은 서머타임이 없어 고정 오프셋으로 충분하다. zoneinfo를 쓰면 배포
# 서버에 tzdata가 깔려 있어야 하는데, 그게 없으면 런타임에 죽는다.
KST = timezone(timedelta(hours=9))

# 발신 시각이 지난 뒤 이만큼까지는 건다. 넘으면 그날은 건너뛴다.
DEFAULT_GRACE_SECONDS = 1800

# 얼마나 자주 명부를 확인하는가. 1분이면 유예 30분 안에 서른 번 본다 —
# 한 번 놓쳐도 다음 틱이 잡는다.
DEFAULT_TICK_SECONDS = 60.0


@dataclass(frozen=True)
class RosterEntry:
    """동의한 어르신 한 명과, 그분께 마지막으로 예약 통화를 만든 시각."""

    elder_id: int
    call_time: time
    last_scheduled_at: datetime | None


class Roster(Protocol):
    def entries(self) -> list[RosterEntry]:
        """동의한 어르신 전부. 동의가 없으면 여기 나오지 않는다."""
        ...


def due_elders(
    entries: list[RosterEntry], now: datetime, *, grace: timedelta
) -> list[int]:
    """지금 전화를 걸어야 할 어르신 번호들.

    순수 함수다 — DB도 스레드도 없이 판정만 한다. 스케줄러에서 가장 틀리기
    쉬운 부분이라 따로 떼어 시계를 주입받고 테스트한다.

    세 조건을 모두 만족해야 건다.
      1. 발신 시각이 지났다
      2. 유예를 넘지 않았다
      3. 오늘 아직 안 걸었다
    """
    local_now = now.astimezone(KST)
    today = local_now.date()
    due: list[int] = []

    for item in entries:
        due_at = datetime.combine(today, item.call_time, tzinfo=KST)
        if local_now < due_at:
            continue
        if local_now - due_at > grace:
            continue

        last = item.last_scheduled_at
        # 날짜 비교는 반드시 한국시간으로 한다. UTC로 세면 한국 자정 직후
        # 통화가 "어제"로 잡혀 하루 두 번 걸리는 날이 생긴다.
        if last is not None and last.astimezone(KST).date() == today:
            continue

        due.append(item.elder_id)

    return due


class Scheduler:
    """명부를 주기적으로 보고 걸 사람이 있으면 발신을 시킨다.

    발신 자체는 하지 않는다 — `place`로 받은 것에 넘긴다. 그래야 트리거
    API와 **완전히 같은 경로**로 나간다. 발신 뒤처리(토큰 발급 실패 시
    복구)가 까다로워서, 여기서 베껴 쓰면 언젠가 갈라진다.
    """

    def __init__(
        self,
        *,
        roster: Roster,
        place: Callable[[int], None],
        clock: Callable[[], datetime] = lambda: datetime.now(KST),
        grace_seconds: float = DEFAULT_GRACE_SECONDS,
        tick_seconds: float = DEFAULT_TICK_SECONDS,
    ) -> None:
        self._roster = roster
        self._place = place
        self._clock = clock
        self._grace = timedelta(seconds=grace_seconds)
        self._tick_seconds = tick_seconds
        self._stopping = threading.Event()
        self._thread: threading.Thread | None = None

    def tick(self) -> int:
        """한 번 확인하고 걸 사람에게 건다. 실제로 건 수를 돌려준다."""
        try:
            entries = self._roster.entries()
        except Exception:
            # 여기서 예외가 올라가면 루프 스레드가 죽고, 그날 남은 어르신
            # 전부가 조용히 통화 없이 지나간다. DB가 잠깐 끊긴 것뿐일 수도
            # 있으므로 다음 틱을 기다린다.
            logger.exception("명부를 읽지 못했다 — 이번 틱을 건너뛴다")
            return 0

        placed = 0
        for elder_id in due_elders(entries, self._clock(), grace=self._grace):
            try:
                self._place(elder_id)
            except Exception:
                # 한 어르신 발신 실패가 뒤에 있는 어르신들의 그날 통화를
                # 통째로 없애면 안 된다.
                logger.exception("예약 발신 실패 elder_id=%s — 다음 어르신으로", elder_id)
                continue
            placed += 1
            logger.info("예약 통화를 걸었다 elder_id=%s", elder_id)

        return placed

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stopping.clear()
        self._thread = threading.Thread(
            target=self._run, name="scheduler", daemon=True
        )
        self._thread.start()
        logger.info(
            "스케줄러를 켠다 — %.0f초마다 확인, 유예 %.0f분",
            self._tick_seconds,
            self._grace.total_seconds() / 60,
        )

    def stop(self, timeout: float = 5.0) -> None:
        self._stopping.set()
        thread = self._thread
        if thread is None:
            return
        thread.join(timeout=timeout)
        # 살아 있으면 참조를 지우지 않는다. 지우면 다음 start()가 같은
        # 명부를 보는 두 번째 스레드를 만든다 — 전사 워커에서 겪은 것과
        # 같은 형태다.
        if not thread.is_alive():
            self._thread = None

    def _run(self) -> None:
        while not self._stopping.is_set():
            self.tick()
            self._stopping.wait(self._tick_seconds)
