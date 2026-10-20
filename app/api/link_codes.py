"""어르신 연결 코드 — 어르신마다 하나뿐인 고정 8자리 코드 (설계: 어르신 먼저 가입).

어르신이 가입하면 코드가 하나 정해지고, 어르신 앱에서 언제든 다시 볼 수 있다. 보호자가 이 코드를 입력하면 연결된다.
코드는 만료되지 않고 쓴다고 사라지지도 않는다 — 어르신이 "새 코드 만들기"로 바꿀 때만 이전 코드가 못 쓰게 된다.

코드 자체는 `app.api.invites`의 8자리 숫자를 쓴다. 찾기 위한 지문(SHA-256)과, 어르신 앱에 다시 보여 주기 위한 원문을
함께 둔다. 원문만으로는 연결할 수 없다(이메일 인증과 운영자 확인을 마친 보호자 계정이 있어야 하고, 대입은 보호자 쪽 주소의
분당 실패 한도가 막는다).
"""

from __future__ import annotations

import threading
from typing import Protocol


class CodeCollision(Exception):
    """다른 어르신이 같은 지문의 코드를 이미 갖고 있다 — 새 코드로 다시 시도한다."""


class LinkCodeStore(Protocol):
    def issue(self, elder_id: int, code_hash: str, code: str) -> None:
        """그 어르신의 코드를 정한다(고정). 이전 코드는 무효가 된다. 같은 지문을 다른 어르신이 갖고 있으면 CodeCollision."""
        ...

    def find(self, code_hash: str) -> int | None:
        """코드의 어르신. 모르면 None. 코드는 그대로 둔다(고정 코드라 연결에 써도 사라지지 않는다)."""
        ...

    def code_of(self, elder_id: int) -> str | None:
        """그 어르신의 코드 원문. 아직 정해지지 않았으면 None."""
        ...


class InMemoryLinkCodeStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._rows: dict[int, tuple[str, str]] = {}  # elder_id -> (지문, 원문)

    def issue(self, elder_id: int, code_hash: str, code: str) -> None:
        with self._lock:
            for other, (stored, _) in self._rows.items():
                if stored == code_hash and other != elder_id:
                    raise CodeCollision(code_hash[:8])
            self._rows[elder_id] = (code_hash, code)

    def find(self, code_hash: str) -> int | None:
        with self._lock:
            for elder_id, (stored, _) in self._rows.items():
                if stored == code_hash:
                    return elder_id
            return None

    def code_of(self, elder_id: int) -> str | None:
        with self._lock:
            row = self._rows.get(elder_id)
            return None if row is None else row[1]
