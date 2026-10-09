"""보호자 개인 코드 — 어르신이 이 코드로 가입한다 (설계: 보호자 코드로 어르신 가입).

코드는 문자열로 다룬다. 앞자리가 0인 코드("00001234")가 숫자로 바뀌면 "1234"가 된다.
8자리라 1억 가지이고, 대입은 가입 주소의 분당 시도 한도(app/api/rate_limit.py)가 막는다.
DB에는 SHA-256 지문만 둔다. 보호자당 활성 코드는 하나이고 새로 발급하면 이전 코드는
쓸 수 없다. 코드는 재사용할 수 있다(어르신이 여럿일 수 있다) — 가입마다 보호자 승인이 따른다.
"""

from __future__ import annotations

import hashlib
import secrets
import threading
from typing import Protocol

INVITE_DIGITS = 8


def new_invite_code() -> str:
    return f"{secrets.randbelow(10**INVITE_DIGITS):0{INVITE_DIGITS}d}"


def hash_invite_code(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


class InviteStore(Protocol):
    def issue(self, guardian_id: int, code_hash: str) -> None:
        """새 코드를 등록한다. 그 보호자의 이전 활성 코드는 모두 폐기된다. 같은 지문이면 예외."""
        ...

    def find_guardian(self, code_hash: str) -> int | None:
        """활성 코드의 보호자. 폐기됐거나 모르는 코드면 None."""
        ...


class InMemoryInviteStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._rows: dict[str, dict] = {}

    def issue(self, guardian_id: int, code_hash: str) -> None:
        with self._lock:
            if code_hash in self._rows:
                raise ValueError("이미 있는 코드 지문이다")
            for row in self._rows.values():
                if row["guardian_id"] == guardian_id and not row["revoked"]:
                    row["revoked"] = True
            self._rows[code_hash] = {"guardian_id": guardian_id, "revoked": False}

    def find_guardian(self, code_hash: str) -> int | None:
        with self._lock:
            row = self._rows.get(code_hash)
            if row is None or row["revoked"]:
                return None
            return row["guardian_id"]
