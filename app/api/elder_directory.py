"""어르신 조회 — 누구의 어르신인가, 동의했는가, 전화번호로 누구인가, 가입·승인.

수동 요청의 세 번째, 네 번째 문(소유, 동의)과 앱 연결, 보호자 화면의 어르신 목록,
보호자 코드 가입이 쓴다. 통화 저장소와 따로 둔 이유: 보호자와 동의는 DB의 `elders`
표에만 있다.

**상태는 컬럼 조합이다.** 새 상태 컬럼을 두지 않는다.
- active      consent_at이 있다 — 보호자가 승인했거나 운영자가 동의를 기록했다.
- pending     agreed_at만 있다 — 어르신이 가입하며 동의에 체크했고 보호자 승인을 기다린다.
- unconsented 둘 다 없다 — 운영자가 등록한 어르신. 앱에서 승인할 수 없다.
- unlinked   보호자가 아직 없다 — 어르신이 먼저 가입했고 연결 코드를 기다린다. consent_at은 link()만 채운다.
`consent_at`을 채우는 곳은 `approve` 하나다. 가입(`create_pending`)은 절대 채우지 않는다.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, replace
from datetime import time
from typing import Protocol

STATUS_ACTIVE = "active"
STATUS_PENDING = "pending"
STATUS_UNCONSENTED = "unconsented"
STATUS_UNLINKED = "unlinked"

# 한 어르신을 함께 보는 보호자의 최대 수.
MAX_GUARDIANS_PER_ELDER = 5


class PhoneTaken(Exception):
    """이미 등록된 전화번호다(숫자만 비교한다)."""


class PendingLimit(Exception):
    """그 보호자의 승인 대기가 한도에 닿았다."""


@dataclass(frozen=True)
class ElderAccess:
    guardian_id: int | None
    consenting: bool
    name: str = ""
    agreed: bool = False
    # 대표 보호자(guardian_id) 말고 함께 보는 보호자들, 번호 오름차순.
    co_guardians: tuple[int, ...] = ()

    @property
    def guardian_ids(self) -> tuple[int, ...]:
        """이 어르신을 보는 보호자 전원(대표가 맨 앞). 연결 전이면 빈 값."""
        if self.guardian_id is None:
            return ()
        return (self.guardian_id, *self.co_guardians)

    def has_guardian(self, guardian_id: int) -> bool:
        return guardian_id in self.guardian_ids

    @property
    def status(self) -> str:
        if self.guardian_id is None:
            return STATUS_UNLINKED
        if self.consenting:
            return STATUS_ACTIVE
        return STATUS_PENDING if self.agreed else STATUS_UNCONSENTED


@dataclass(frozen=True)
class ElderRef:
    elder_id: int
    name: str
    status: str = STATUS_ACTIVE
    # 승인 대기일 때만 채운다. 보호자가 "내 부모님 번호가 맞나"를 보고 승인하는 데 쓴다.
    phone: str | None = None
    # 이 어르신을 함께 보는 보호자 수(나 포함). 이름은 알리지 않는다.
    guardian_count: int = 1


@dataclass(frozen=True)
class GuardianProfile:
    name: str
    phone: str


# db/schema.sql의 elders.call_time 기본값과 같다.
DEFAULT_CALL_TIME = time(9, 0)


def digits_of(phone: str) -> str:
    return "".join(ch for ch in phone if ch.isdigit())


def mask_phone(phone: str) -> str:
    """보호자가 '내 부모님 번호가 맞나' 볼 수 있을 만큼만 보인다: 010-****-1111."""
    digits = digits_of(phone)
    if len(digits) < 8:
        return "****"
    return f"{digits[:3]}-****-{digits[-4:]}"


class ElderDirectory(Protocol):
    def get(self, elder_id: int) -> ElderAccess | None: ...

    def find_by_phone(self, phone: str) -> int | None:
        """전화번호의 숫자만 비교해 어르신을 찾는다. 하이픈·공백은 무시한다."""
        ...

    def elders_of(self, guardian_id: int) -> list[ElderRef]:
        """그 보호자의 어르신들, elder_id 오름차순."""
        ...

    def guardian_profile(self, guardian_id: int) -> GuardianProfile | None: ...

    def phone_of(self, elder_id: int) -> str | None:
        """어르신이 가입 때 적은 전화번호 원문. 없는 어르신이면 None."""
        ...

    def create_unlinked(self, *, name: str, phone: str) -> int:
        """보호자 없이 가입한 어르신을 만든다(agreed_at만 채운다). consent_at은 비워 둔다.

        번호가 이미 있으면 PhoneTaken.
        """
        ...

    def discard_unlinked(self, elder_id: int) -> bool:
        """가입 직후 실패를 되돌리는 용도. 보호자도 전화 동의(consent_at)도 없는 어르신 행만 지우고 True."""
        ...

    def link(
        self, elder_id: int, guardian_id: int, max_guardians: int = MAX_GUARDIANS_PER_ELDER
    ) -> bool:
        """가입 동의(agreed_at)가 있는 어르신에게 보호자를 잇고 True.

        보호자가 없으면 그 보호자가 대표가 되고 consent_at이 채워진다(consent_at을 채우는 두 곳 중 하나, 다른 하나는
        approve — 보호자가 연결을 확인하는 것이 승인이다). 이미 연결된(동의한) 어르신이면 **추가 보호자**로 들어간다
        (동의는 그대로). 이미 그 어르신의 보호자이거나, 보호자가 max_guardians명이거나, 승인 대기 어르신이면 False.
        """
        ...

    def create_pending(
        self, *, guardian_id: int, name: str, phone: str, max_pending: int
    ) -> int:
        """승인 대기 어르신을 만든다. consent_at은 비워 둔다 — 전화가 나가지 않는다.

        번호가 이미 있으면 PhoneTaken, 그 보호자의 대기가 max_pending 이상이면 PendingLimit.
        """
        ...

    def approve(self, elder_id: int, guardian_id: int) -> bool:
        """그 보호자의 승인 대기 어르신일 때만 consent_at을 지금으로 채우고 True."""
        ...

    def reject(self, elder_id: int, guardian_id: int) -> bool:
        """그 보호자의 승인 대기 어르신일 때만 행을 지우고 True."""
        ...

    def call_time_of(self, elder_id: int) -> time | None:
        """하루 한 번 안부 전화를 거는 시각(한국 시간). 없는 어르신이면 None."""
        ...

    def set_call_time(self, elder_id: int, guardian_id: int, value: time) -> bool:
        """그 보호자의 어르신일 때만 안부 전화 시각을 바꾸고 True. 스케줄러는 이 값을 매분 새로 읽는다."""
        ...

    def set_phone(self, elder_id: int, guardian_id: int, phone: str) -> bool:
        """그 보호자의 어르신일 때만 전화번호를 바꾸고 True. 아니면 False.

        다른 어르신이 이미 쓰는 번호(숫자만 비교)면 PhoneTaken. 같은 어르신의 자기 번호로 다시 바꾸는 것은 허용한다.
        """
        ...

    def guardians_of(self, elder_id: int) -> list[int]:
        """그 어르신을 함께 보는 보호자들(번호 오름차순). 연결 전이거나 없는 어르신이면 빈 목록."""
        ...

    def open_new_phone_login(self, elder_id: int, guardian_id: int, until: float) -> bool:
        """그 보호자의 어르신일 때만, 새 폰이 번호만으로 한 번 로그인할 수 있는 시간을 until(유닉스 시각)까지 연다."""
        ...

    def claim_new_phone(self, phone: str, now: float) -> int | None:
        """열려 있는(만료 전) 번호면 닫고 어르신 번호를 돌려준다. 동시에 와도 한 쪽만 얻는다. 아니면 None."""
        ...

    # ------------------------------------------------ 탈퇴 (app/api/account_deletion.py)

    def detach_all_from(self, guardian_id: int) -> list[int]:
        """보호자 탈퇴: 그 보호자의 어르신을 **지우지 않고** 그 보호자만 뗀다.

        다른 보호자가 남은 어르신은 그대로 이어진다(대표였다면 남은 사람 중 번호가 가장 작은 사람이 대표가 된다).
        마지막 보호자였던 어르신은 연결 전으로 돌아간다(보호자·전화 동의를 비운다). 뗀 어르신 번호를 모두 오름차순으로
        돌려준다 — 호출부가 그 어르신들의 안 쓴 연결 코드(그 보호자가 내준 것)를 지운다. 연결 전이 된 어르신은 안부 전화가 멈춘다. 가입 동의(agreed_at)·공유 동의·통화 시각·통화 기록은 그대로라, 가입 동의가 있는
        어르신은 새 연결 코드로 다른 보호자가 이어받을 수 있다.
        """
        ...

    def delete_elder(self, elder_id: int) -> bool:
        """어르신 탈퇴: 어르신 행을 지우고 True. 없으면 False.

        Postgres에서는 통화·점수·요약·언급·열람 기록·알림·연락처·열쇠·코드가 CASCADE로 같이 지워진다.
        S3 녹음은 지워지지 않는다 — 먼저 audio_keys_of로 키를 읽어 지운다.
        """
        ...

    def audio_keys_of(self, elder_id: int) -> list[str]:
        """그 어르신 통화의 녹음 키(S3 객체 키). 녹음이 없는 통화는 빠진다."""
        ...


class DirectoryAdmin(Protocol):
    """운영 도구(`python -m app.admin`)가 쓴다. 동의는 여기서 바꾸지 않는다."""

    def add_guardian(self, name: str, phone: str) -> int: ...
    def assign_elder(self, elder_id: int, guardian_id: int) -> bool: ...
    def guardian_exists(self, guardian_id: int) -> bool: ...


class InMemoryElderDirectory:
    def __init__(
        self,
        entries: dict[int, ElderAccess] | None = None,
        *,
        phones: dict[int, str] | None = None,
        guardians: dict[int, GuardianProfile] | None = None,
    ) -> None:
        self._entries = dict(entries or {})
        self._phone_text = dict(phones or {})
        self._phones = {elder_id: digits_of(phone) for elder_id, phone in self._phone_text.items()}
        self._profiles = dict(guardians or {})
        # 바꾼 안부 전화 시각만 둔다. 없으면 DEFAULT_CALL_TIME이다(DB의 기본값과 같게).
        self._call_times: dict[int, time] = {}
        # 새 폰 로그인이 열린 어르신과 닫히는 시각.
        self._claims: dict[int, float] = {}
        # 메모리 모드에는 통화 표가 없다. 녹음 키는 시험이 add_audio_key로 심는다.
        self._audio_keys: dict[int, list[str]] = {}
        self._guardians = {
            access.guardian_id for access in self._entries.values() if access.guardian_id is not None
        } | set(self._profiles)
        self._lock = threading.Lock()
        self._next_guardian = max(self._guardians, default=0) + 1
        self._next_elder = max(self._entries, default=0) + 1

    def _new_elder_id(self) -> int:
        """잠금 안에서 부른다. 지운 어르신의 번호는 다시 쓰지 않는다(Postgres의 BIGSERIAL처럼) —
        다시 쓰면 다른 저장소에 남은 옛 기록(연결 코드 등)이 새 어르신에게 붙는다."""
        elder_id = max(self._next_elder, max(self._entries, default=0) + 1)
        self._next_elder = elder_id + 1
        return elder_id

    def _forget(self, elder_id: int) -> None:
        """잠금 안에서 부른다. 어르신 행과 그 번호에 딸린 것을 모두 지운다."""
        del self._entries[elder_id]
        self._phone_text.pop(elder_id, None)
        self._phones.pop(elder_id, None)
        self._call_times.pop(elder_id, None)
        self._claims.pop(elder_id, None)
        self._audio_keys.pop(elder_id, None)

    def get(self, elder_id: int) -> ElderAccess | None:
        return self._entries.get(elder_id)

    def find_by_phone(self, phone: str) -> int | None:
        wanted = digits_of(phone)
        if not wanted:
            return None
        for elder_id, digits in self._phones.items():
            if digits == wanted:
                return elder_id
        return None

    def elders_of(self, guardian_id: int) -> list[ElderRef]:
        return [
            ElderRef(
                elder_id=elder_id,
                name=access.name,
                status=access.status,
                phone=self._phone_text.get(elder_id) if access.status == STATUS_PENDING else None,
                guardian_count=len(access.guardian_ids),
            )
            for elder_id, access in sorted(self._entries.items())
            if access.has_guardian(guardian_id)
        ]

    def guardian_profile(self, guardian_id: int) -> GuardianProfile | None:
        return self._profiles.get(guardian_id)

    def create_pending(
        self, *, guardian_id: int, name: str, phone: str, max_pending: int
    ) -> int:
        with self._lock:
            wanted = digits_of(phone)
            if any(digits == wanted for digits in self._phones.values()):
                raise PhoneTaken(wanted)
            pending = sum(
                1
                for access in self._entries.values()
                if access.guardian_id == guardian_id and access.status == STATUS_PENDING
            )
            if pending >= max_pending:
                raise PendingLimit(guardian_id)
            elder_id = self._new_elder_id()
            self._entries[elder_id] = ElderAccess(guardian_id, False, name, agreed=True)
            self._phone_text[elder_id] = phone
            self._phones[elder_id] = wanted
            self._guardians.add(guardian_id)
            return elder_id

    def _pending_of(self, elder_id: int, guardian_id: int) -> ElderAccess | None:
        access = self._entries.get(elder_id)
        if access is None or access.guardian_id != guardian_id or access.status != STATUS_PENDING:
            return None
        return access

    def phone_of(self, elder_id: int) -> str | None:
        return self._phone_text.get(elder_id)

    def create_unlinked(self, *, name: str, phone: str) -> int:
        with self._lock:
            wanted = digits_of(phone)
            if any(digits == wanted for digits in self._phones.values()):
                raise PhoneTaken(wanted)
            elder_id = self._new_elder_id()
            self._entries[elder_id] = ElderAccess(None, False, name, agreed=True)
            self._phone_text[elder_id] = phone
            self._phones[elder_id] = wanted
            return elder_id

    def discard_unlinked(self, elder_id: int) -> bool:
        with self._lock:
            access = self._entries.get(elder_id)
            if access is None or access.guardian_id is not None or access.consenting:
                return False
            self._forget(elder_id)
            return True

    def link(
        self, elder_id: int, guardian_id: int, max_guardians: int = MAX_GUARDIANS_PER_ELDER
    ) -> bool:
        with self._lock:
            access = self._entries.get(elder_id)
            if access is None or not access.agreed:
                return False
            if access.guardian_id is None:
                self._entries[elder_id] = replace(access, guardian_id=guardian_id, consenting=True)
            else:
                if (
                    not access.consenting
                    or access.has_guardian(guardian_id)
                    or len(access.guardian_ids) >= max_guardians
                ):
                    return False
                co = tuple(sorted((*access.co_guardians, guardian_id)))
                self._entries[elder_id] = replace(access, co_guardians=co)
            self._guardians.add(guardian_id)
            return True

    def approve(self, elder_id: int, guardian_id: int) -> bool:
        with self._lock:
            access = self._pending_of(elder_id, guardian_id)
            if access is None:
                return False
            self._entries[elder_id] = replace(access, consenting=True)
            return True

    def reject(self, elder_id: int, guardian_id: int) -> bool:
        with self._lock:
            if self._pending_of(elder_id, guardian_id) is None:
                return False
            self._forget(elder_id)
            return True

    def call_time_of(self, elder_id: int) -> time | None:
        if elder_id not in self._entries:
            return None
        return self._call_times.get(elder_id, DEFAULT_CALL_TIME)

    def set_call_time(self, elder_id: int, guardian_id: int, value: time) -> bool:
        with self._lock:
            access = self._entries.get(elder_id)
            if access is None or not access.has_guardian(guardian_id):
                return False
            self._call_times[elder_id] = value
            return True

    def set_phone(self, elder_id: int, guardian_id: int, phone: str) -> bool:
        with self._lock:
            access = self._entries.get(elder_id)
            if access is None or not access.has_guardian(guardian_id):
                return False
            wanted = digits_of(phone)
            if any(other != elder_id and digits == wanted for other, digits in self._phones.items()):
                raise PhoneTaken(wanted)
            self._phone_text[elder_id] = phone
            self._phones[elder_id] = wanted
            return True

    def guardians_of(self, elder_id: int) -> list[int]:
        access = self._entries.get(elder_id)
        return [] if access is None else sorted(access.guardian_ids)

    def open_new_phone_login(self, elder_id: int, guardian_id: int, until: float) -> bool:
        with self._lock:
            access = self._entries.get(elder_id)
            if access is None or not access.has_guardian(guardian_id):
                return False
            self._claims[elder_id] = until
            return True

    def claim_new_phone(self, phone: str, now: float) -> int | None:
        wanted = digits_of(phone)
        if not wanted:
            return None
        with self._lock:
            for elder_id, digits in self._phones.items():
                if digits != wanted:
                    continue
                until = self._claims.pop(elder_id, None)
                return elder_id if until is not None and until > now else None
            return None

    def detach_all_from(self, guardian_id: int) -> list[int]:
        with self._lock:
            mine = sorted(eid for eid, access in self._entries.items() if access.has_guardian(guardian_id))
            for eid in mine:
                access = self._entries[eid]
                rest = sorted(g for g in access.guardian_ids if g != guardian_id)
                if not rest:
                    self._entries[eid] = replace(
                        access, guardian_id=None, consenting=False, co_guardians=()
                    )
                else:
                    self._entries[eid] = replace(
                        access, guardian_id=rest[0], co_guardians=tuple(rest[1:])
                    )
            return mine

    def delete_elder(self, elder_id: int) -> bool:
        with self._lock:
            if elder_id not in self._entries:
                return False
            self._forget(elder_id)
            return True

    def add_audio_key(self, elder_id: int, key: str) -> None:
        """시험용. Postgres는 calls.audio_key를 읽는다."""
        with self._lock:
            self._audio_keys.setdefault(elder_id, []).append(key)

    def audio_keys_of(self, elder_id: int) -> list[str]:
        with self._lock:
            return list(self._audio_keys.get(elder_id, []))

    def add_guardian(self, name: str, phone: str) -> int:
        with self._lock:
            guardian_id = self._next_guardian
            self._next_guardian += 1
            self._guardians.add(guardian_id)
            self._profiles[guardian_id] = GuardianProfile(name=name, phone=phone)
            return guardian_id

    def guardian_exists(self, guardian_id: int) -> bool:
        return guardian_id in self._guardians

    def assign_elder(self, elder_id: int, guardian_id: int) -> bool:
        with self._lock:
            old = self._entries.get(elder_id)
            if old is None or guardian_id not in self._guardians:
                return False
            self._entries[elder_id] = replace(old, guardian_id=guardian_id, co_guardians=())
            return True
