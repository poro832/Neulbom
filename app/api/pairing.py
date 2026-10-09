"""연결 코드 — 보호자가 어르신 폰을 잇는 6자리 코드 (설계: 앱 화면을 실제 데이터로).

코드는 문자열로 다룬다. 앞자리가 0인 코드("000123")가 숫자로 바뀌면 "123"이 된다.
DB에는 SHA-256 지문만 둔다. 코드가 6자리뿐이라 지문만으로는 막지 못하는 대입 공격은
(1) 전화번호가 맞아야 하고 (2) 틀리게 5번이면 그 코드를 잠그는 것으로 막는다.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
import time
from collections.abc import Callable
from typing import Protocol

CODE_DIGITS = 6
CODE_TTL_SECONDS = 24 * 3600
MAX_FAILED_ATTEMPTS = 5


def new_code() -> str:
    return f"{secrets.randbelow(10**CODE_DIGITS):0{CODE_DIGITS}d}"


def hash_code(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


class PairingStore(Protocol):
    def issue(self, elder_id: int, code_hash: str) -> float:
        """새 코드를 등록하고 만료 시각(유닉스 시각)을 돌려준다. 이전 코드는 모두 무효가 된다."""
        ...

    def redeem(self, elder_id: int, code_hash: str) -> bool:
        """맞으면 코드를 소진하고 True. 틀리면 False이고 활성 코드의 실패 횟수를 올린다.

        만료됐거나, 이미 썼거나, 틀린 횟수가 한도에 닿은 코드는 맞아도 False다.
        """
        ...


class InMemoryPairingStore:
    def __init__(
        self,
        clock: Callable[[], float] = time.time,
        ttl_seconds: float = CODE_TTL_SECONDS,
        max_failed: int = MAX_FAILED_ATTEMPTS,
    ) -> None:
        self._clock = clock
        self._ttl = ttl_seconds
        self._max_failed = max_failed
        self._lock = threading.Lock()
        self._rows: dict[int, list[dict]] = {}

    def issue(self, elder_id: int, code_hash: str) -> float:
        with self._lock:
            rows = self._rows.setdefault(elder_id, [])
            for row in rows:
                row["used"] = True
            expires_at = self._clock() + self._ttl
            rows.append(
                {"code_hash": code_hash, "expires_at": expires_at, "failed": 0, "used": False}
            )
            return expires_at

    def redeem(self, elder_id: int, code_hash: str) -> bool:
        with self._lock:
            active = None
            for row in reversed(self._rows.get(elder_id, [])):
                if (
                    not row["used"]
                    and row["expires_at"] > self._clock()
                    and row["failed"] < self._max_failed
                ):
                    active = row
                    break
            if active is None:
                return False
            if hmac.compare_digest(active["code_hash"], code_hash):
                active["used"] = True
                return True
            active["failed"] += 1
            return False
