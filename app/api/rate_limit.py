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


class KeyedFailureLimiter:
    """키(이메일)마다 따로 세는 실패 한도 — 한 계정만 잠그고 나머지는 열어 둔다.

    `window_seconds` 안에 `limit`번 이상 틀리면 그 키만 `blocked()`. 맞게 로그인하면 `clear`로 지운다.
    키가 무한히 늘지 않게 오래된 것부터 버린다(`max_keys`) — 없는 이메일을 마구 넣어 메모리를
    채우는 공격을 막는다.
    """

    def __init__(
        self,
        *,
        limit: int = 5,
        window_seconds: float = 900,
        clock: Callable[[], float] = time.time,
        max_keys: int = 10_000,
    ) -> None:
        self._limit = limit
        self._window = window_seconds
        self._clock = clock
        self._max_keys = max_keys
        self._lock = threading.Lock()
        self._failures: dict[str, deque[float]] = {}

    def _trim(self, key: str, now: float) -> deque[float] | None:
        entries = self._failures.get(key)
        if entries is None:
            return None
        while entries and now - entries[0] >= self._window:
            entries.popleft()
        if not entries:
            del self._failures[key]
            return None
        return entries

    def record_failure(self, key: str) -> None:
        with self._lock:
            now = self._clock()
            entries = self._trim(key, now)
            if entries is None:
                if len(self._failures) >= self._max_keys:
                    # 가장 먼저 들어온 키 하나를 버린다(딕셔너리는 넣은 순서를 지킨다).
                    del self._failures[next(iter(self._failures))]
                entries = self._failures.setdefault(key, deque())
            entries.append(now)

    def blocked(self, key: str) -> bool:
        with self._lock:
            entries = self._trim(key, self._clock())
            return entries is not None and len(entries) >= self._limit

    def clear(self, key: str) -> None:
        with self._lock:
            self._failures.pop(key, None)

    def tracked(self) -> int:
        with self._lock:
            return len(self._failures)
