"""어르신 연결 코드 — 어르신이 화면에 띄우고 보호자가 입력하는 8자리 코드 (설계: 어르신 먼저 가입).

코드 자체는 `app.api.invites`의 8자리 숫자와 지문(SHA-256)을 쓴다. DB에는 지문만 둔다.
어르신당 활성 코드는 하나이고 새로 발급하면 이전 코드는 쓸 수 없다. 24시간 뒤 만료되고
연결에 쓰면(`consume`) 사라진다. 대입은 보호자 쪽 주소의 분당 실패 한도가 막는다.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Protocol

LINK_CODE_TTL_SECONDS = 24 * 3600


class CodeCollision(Exception):
    """다른 어르신이 같은 지문의 코드를 이미 갖고 있다 — 새 코드로 다시 시도한다."""


class LinkCodeStore(Protocol):
    def issue(self, elder_id: int, code_hash: str) -> float:
        """새 코드를 등록하고 만료 시각(유닉스 시각)을 돌려준다. 그 어르신의 이전 코드는 무효가 된다."""
        ...

    def find(self, code_hash: str) -> int | None:
        """만료되지 않은 코드의 어르신. 모르거나 만료됐으면 None. 코드는 그대로 둔다."""
        ...

    def consume(self, code_hash: str) -> int | None:
        """만료되지 않은 코드면 코드를 지우고 어르신 번호를 돌려준다. 동시에 와도 한 쪽만 얻는다."""
        ...


class InMemoryLinkCodeStore:
    def __init__(
        self,
        clock: Callable[[], float] = time.time,
        ttl_seconds: float = LINK_CODE_TTL_SECONDS,
    ) -> None:
        self._clock = clock
        self._ttl = ttl_seconds
        self._lock = threading.Lock()
        self._rows: dict[int, tuple[str, float]] = {}  # elder_id -> (지문, 만료 시각)

    def issue(self, elder_id: int, code_hash: str) -> float:
        with self._lock:
            for other, (stored, _) in self._rows.items():
                if stored == code_hash and other != elder_id:
                    raise CodeCollision(code_hash[:8])
            expires_at = self._clock() + self._ttl
            self._rows[elder_id] = (code_hash, expires_at)
            return expires_at

    def _live(self, code_hash: str) -> int | None:
        now = self._clock()
        for elder_id, (stored, expires_at) in self._rows.items():
            if stored == code_hash and expires_at > now:
                return elder_id
        return None

    def find(self, code_hash: str) -> int | None:
        with self._lock:
            return self._live(code_hash)

    def consume(self, code_hash: str) -> int | None:
        with self._lock:
            elder_id = self._live(code_hash)
            if elder_id is not None:
                del self._rows[elder_id]
            return elder_id
