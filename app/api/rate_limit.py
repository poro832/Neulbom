"""틀린 시도 한도 — 가입 코드를 찍어 보는 요청을 늦춘다.

서버가 하나라 프로세스 안 카운터로 충분하다(재시작하면 초기화된다). 틀린 시도가 최근
`window_seconds` 안에 `limit`개 이상이면 `blocked()`가 True다. 이 한도는 서버 전체에
걸린다 — 공격자가 가입을 잠시 막을 수 있다는 한계를 알고 둔 선택이다. 8자리 코드는
분당 20번이면 1억 가지를 훑는 데 9년이 걸린다.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable


class FailureLimiter:
    def __init__(
        self,
        *,
        limit: int = 20,
        window_seconds: float = 60,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._limit = limit
        self._window = window_seconds
        self._clock = clock
        self._lock = threading.Lock()
        self._failures: deque[float] = deque()

    def _trim(self, now: float) -> None:
        while self._failures and now - self._failures[0] >= self._window:
            self._failures.popleft()

    def record_failure(self) -> None:
        with self._lock:
            now = self._clock()
            self._trim(now)
            self._failures.append(now)

    def blocked(self) -> bool:
        with self._lock:
            self._trim(self._clock())
            return len(self._failures) >= self._limit
