"""통화 내용 저장소 — 대화 턴, 요약, 열람 기록, 공유 동의 (설계: 통화 요약·원문 공개).

보호자 앱이 읽는 것은 여기뿐이다. 점수·경보를 정하는 쪽(call_metrics)과 섞지 않는다.
**동의 전 공개 금지는 이 저장소가 아니라 주소(app_data.py)가 지킨다** — 저장은 동의와
무관하게 하고(통화·점수는 그대로 돈다) 읽을 때 막는다.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Protocol


# 통화별 약 복용 확인 결과. 어르신이 한 말을 셋으로만 나눈다 (설계: 약 복용 확인).
MEDICATION_STATUSES = ("taken", "not_taken", "unknown")

# 통화 속 건강·기분 언급 (설계: 통화 속 건강·기분 언급 모으기). 어르신이 한 말을 그대로 옮기며 진단이 아니다.
MENTION_CATEGORIES = ("body", "sleep", "meal", "mood", "activity")
MENTION_SAID = ("bad", "ok", "good")
MAX_MENTION_QUOTE = 80


@dataclass(frozen=True)
class Mention:
    category: str  # MENTION_CATEGORIES 중 하나
    said: str  # 어르신이 스스로 한 표현: bad | ok | good
    quote: str  # 어르신 말 그대로(어르신이 한 한 문장, 80자 이하)


def check_mentions(mentions: Sequence[Mention]) -> None:
    for m in mentions:
        if m.category not in MENTION_CATEGORIES:
            raise ValueError(f"알 수 없는 언급 분류: {m.category!r}")
        if m.said not in MENTION_SAID:
            raise ValueError(f"알 수 없는 언급 느낌: {m.said!r}")
        if not m.quote.strip() or len(m.quote) > MAX_MENTION_QUOTE:
            raise ValueError("언급 인용은 1~40자여야 한다")


@dataclass(frozen=True)
class StoredTurn:
    speaker: str  # ai | elder
    text: str


class CallContentStore(Protocol):
    def save_turns(self, call_id: int, turns: Sequence[tuple[str, str]]) -> None: ...

    def turns(self, call_id: int) -> list[StoredTurn]: ...

    def save_summary(self, call_id: int, summary: str, model_id: str) -> None: ...

    def summaries(self, call_ids: Sequence[int]) -> dict[int, str]: ...

    def save_medication(self, call_id: int, status: str, model_id: str) -> None: ...

    def medication(self, call_ids: Sequence[int]) -> dict[int, str]: ...

    def save_mentions(self, call_id: int, mentions: Sequence[Mention], model_id: str) -> None:
        """그 통화의 건강·기분 언급을 통째로 바꾼다(빈 목록이면 지운다). 값이 규칙 밖이면 ValueError."""
        ...

    def mentions(self, call_ids: Sequence[int]) -> dict[int, list[Mention]]: ...

    def calls_with_turns(self, call_ids: Sequence[int]) -> set[int]: ...

    def elder_of_call(self, call_id: int) -> int | None: ...

    def record_view(self, call_id: int, guardian_id: int) -> None: ...

    def view_count(self, call_id: int) -> int: ...

    def share_agreed(self, elder_id: int) -> bool: ...

    def agree_share(self, elder_id: int) -> None: ...

    def purge_older_than(self, cutoff: float) -> int:
        """cutoff(유닉스 시각)보다 먼저 저장된 턴·요약을 지운다. 지운 행 수를 돌려준다."""
        ...


class InMemoryCallContent:
    def __init__(self, *, clock: Callable[[], float] = time.time) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._turns: dict[int, tuple[list[StoredTurn], float]] = {}
        self._summaries: dict[int, tuple[str, float]] = {}
        self._medication: dict[int, tuple[str, float]] = {}
        self._mentions: dict[int, tuple[list[Mention], float]] = {}
        self._owners: dict[int, int] = {}
        self._views: dict[int, int] = {}
        self._shared: set[int] = set()

    def set_owner(self, call_id: int, elder_id: int) -> None:
        """테스트용. 운영의 메모리 모드는 모든 주소가 401이라 쓰이지 않는다."""
        self._owners[call_id] = elder_id

    def save_turns(self, call_id: int, turns: Sequence[tuple[str, str]]) -> None:
        with self._lock:
            self._turns[call_id] = ([StoredTurn(s, t) for s, t in turns], self._clock())

    def turns(self, call_id: int) -> list[StoredTurn]:
        with self._lock:
            row = self._turns.get(call_id)
        return [] if row is None else list(row[0])

    def save_summary(self, call_id: int, summary: str, model_id: str) -> None:
        with self._lock:
            self._summaries[call_id] = (summary, self._clock())

    def summaries(self, call_ids: Sequence[int]) -> dict[int, str]:
        with self._lock:
            return {c: self._summaries[c][0] for c in call_ids if c in self._summaries}

    def save_medication(self, call_id: int, status: str, model_id: str) -> None:
        if status not in MEDICATION_STATUSES:
            raise ValueError(f"알 수 없는 복용 확인 값: {status!r}")
        with self._lock:
            self._medication[call_id] = (status, self._clock())

    def medication(self, call_ids: Sequence[int]) -> dict[int, str]:
        with self._lock:
            return {c: self._medication[c][0] for c in call_ids if c in self._medication}

    def save_mentions(self, call_id: int, mentions: Sequence[Mention], model_id: str) -> None:
        check_mentions(mentions)
        with self._lock:
            if mentions:
                self._mentions[call_id] = (list(mentions), self._clock())
            else:
                self._mentions.pop(call_id, None)

    def mentions(self, call_ids: Sequence[int]) -> dict[int, list[Mention]]:
        with self._lock:
            return {c: list(self._mentions[c][0]) for c in call_ids if c in self._mentions}

    def calls_with_turns(self, call_ids: Sequence[int]) -> set[int]:
        with self._lock:
            return {c for c in call_ids if c in self._turns and self._turns[c][0]}

    def elder_of_call(self, call_id: int) -> int | None:
        return self._owners.get(call_id)

    def record_view(self, call_id: int, guardian_id: int) -> None:
        with self._lock:
            self._views[call_id] = self._views.get(call_id, 0) + 1

    def view_count(self, call_id: int) -> int:
        return self._views.get(call_id, 0)

    def share_agreed(self, elder_id: int) -> bool:
        return elder_id in self._shared

    def agree_share(self, elder_id: int) -> None:
        with self._lock:
            self._shared.add(elder_id)

    def purge_older_than(self, cutoff: float) -> int:
        removed = 0
        with self._lock:
            for call_id in [c for c, (_, at) in self._turns.items() if at < cutoff]:
                removed += len(self._turns.pop(call_id)[0])
            for call_id in [c for c, (_, at) in self._summaries.items() if at < cutoff]:
                del self._summaries[call_id]
                removed += 1
            for call_id in [c for c, (_, at) in self._medication.items() if at < cutoff]:
                del self._medication[call_id]
                removed += 1
            for call_id in [c for c, (_, at) in self._mentions.items() if at < cutoff]:
                removed += len(self._mentions.pop(call_id)[0])
        return removed
