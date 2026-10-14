"""보호자 폰 등록 저장소 (설계: 푸시 알림).

토큰은 폰 하나를 가리킨다. 로그인한 열쇠(key_hash)에 묶어 두고, 읽을 때 폐기된 열쇠의 폰은
뺀다 — 로그아웃한 폰이나 다른 폰에서 비밀번호를 바꿔 쫓겨난 폰의 잠금 화면에 알림이 계속
뜨면 안 된다.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Protocol


class DeviceStore(Protocol):
    def register(self, guardian_id: int, key_hash: str, token: str) -> None:
        """폰을 등록한다. 같은 토큰이 이미 있으면(다른 보호자 것이어도) 주인과 열쇠를 바꾼다."""
        ...

    def unregister(self, guardian_id: int, token: str) -> bool:
        """그 보호자의 토큰만 지운다. 지웠으면 True, 없거나 남의 것이면 False."""
        ...

    def remove_for_key(self, key_hash: str) -> int:
        """그 열쇠에 묶인 토큰을 모두 지운다(로그아웃). 지운 수."""
        ...

    def tokens_for(self, guardian_id: int) -> list[str]:
        """푸시를 보낼 토큰. 폐기되지 않은 열쇠에 묶인 것만."""
        ...

    def remove_token(self, token: str) -> None:
        """푸시 서버가 없는 토큰이라고 했을 때 지운다. 없어도 조용히 넘어간다."""
        ...


class InMemoryDeviceStore:
    def __init__(self, *, is_key_active: Callable[[str], bool] = lambda _h: True) -> None:
        self._is_key_active = is_key_active
        self._lock = threading.Lock()
        self._rows: dict[str, tuple[int, str]] = {}  # token -> (guardian_id, key_hash)

    def register(self, guardian_id: int, key_hash: str, token: str) -> None:
        with self._lock:
            self._rows[token] = (guardian_id, key_hash)
            # 이 보호자의 폐기된 열쇠에 묶인 옛 등록을 같이 치운다 — 따로 청소하는 곳이 없어도 쌓이지 않게.
            stale = [
                t for t, (g, h) in self._rows.items()
                if g == guardian_id and t != token and not self._is_key_active(h)
            ]
            for t in stale:
                del self._rows[t]

    def unregister(self, guardian_id: int, token: str) -> bool:
        with self._lock:
            row = self._rows.get(token)
            if row is None or row[0] != guardian_id:
                return False
            del self._rows[token]
            return True

    def remove_for_key(self, key_hash: str) -> int:
        with self._lock:
            gone = [t for t, (_, h) in self._rows.items() if h == key_hash]
            for token in gone:
                del self._rows[token]
            return len(gone)

    def tokens_for(self, guardian_id: int) -> list[str]:
        with self._lock:
            rows = [(t, h) for t, (g, h) in self._rows.items() if g == guardian_id]
        return [t for t, h in rows if self._is_key_active(h)]

    def remove_token(self, token: str) -> None:
        with self._lock:
            self._rows.pop(token, None)
