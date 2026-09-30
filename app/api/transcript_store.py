"""전사 원문 저장소 — 통화 한 통에 한 행.

**왜 남기는가.** 부정어 사전은 아직 실제 발화로 검증된 적이 없고 고칠 일이
거의 확실하다. 원문이 없으면 사전을 고쳐도 과거 통화의 점수를 다시 낼 수
없다 — 녹음은 30일 뒤 지워지고, 그 뒤로는 옛 사전으로 센 숫자만 남는다.
(2026-09-22에 "저장한다"로 정했다.)

**대신 녹음과 같은 무게로 다룬다.** 어르신의 사적인 대화 전문이다. 30일이
지나면 지운다(app/archiver.py가 녹음과 같이 치운다). 로그에 원문을 찍지 않는다.

**빈 문자열도 저장한다.** 사업자가 "인식은 성공했는데 말이 없었다"고 답한
통화다. 행이 없는 것("전사를 안 했다")과 빈 원문("말을 안 했다")은 다르고,
뒤쪽이 가장 위험한 통화다.

**다시 저장해도 보관 시계는 처음 저장한 때에 고정된다.** 재분석 한 번으로
30일이 연장되면 안 된다.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Protocol


class TranscriptStore(Protocol):
    def save(self, call_id: int, text: str) -> None: ...

    def get(self, call_id: int) -> str | None: ...

    def purge_older_than(self, cutoff: float) -> int:
        """cutoff(유닉스 시각)보다 먼저 저장된 원문을 지운다. 지운 수를 돌려준다."""
        ...


class InMemoryTranscriptStore:
    def __init__(self, *, clock: Callable[[], float] = time.time) -> None:
        self._clock = clock
        self._rows: dict[int, tuple[str, float]] = {}
        self._lock = threading.Lock()

    def save(self, call_id: int, text: str) -> None:
        with self._lock:
            saved_at = self._rows[call_id][1] if call_id in self._rows else self._clock()
            self._rows[call_id] = (text, saved_at)

    def get(self, call_id: int) -> str | None:
        with self._lock:
            row = self._rows.get(call_id)
        return None if row is None else row[0]

    def purge_older_than(self, cutoff: float) -> int:
        with self._lock:
            old = [cid for cid, (_, saved_at) in self._rows.items() if saved_at < cutoff]
            for cid in old:
                del self._rows[cid]
        return len(old)
