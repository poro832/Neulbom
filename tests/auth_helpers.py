"""엔드포인트 테스트가 쓰는 시험용 열쇠 세트.

기본은 보호자 1번이 12번 어르신(동의 있음)을 가진 상태다. 테스트는 이 세트의
`headers`를 기본 헤더로 쓰는 TestClient로 /v1/calls/request를 부른다.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.api.elder_directory import ElderAccess, ElderDirectory, InMemoryElderDirectory
from app.api.guardian_auth import (
    GuardianAuth,
    InMemoryGuardianKeyStore,
    KeyAuth,
    generate_key,
)

GUARDIAN = 1


@dataclass
class Kit:
    auth: GuardianAuth
    directory: ElderDirectory
    headers: dict
    store: InMemoryGuardianKeyStore
    key: str


def auth_kit(*, elders: dict[int, ElderAccess] | None = None, guardian_id: int = GUARDIAN) -> Kit:
    store = InMemoryGuardianKeyStore()
    new = generate_key()
    store.add(
        guardian_id=guardian_id, label="test", key_prefix=new.key_prefix, key_hash=new.key_hash
    )
    directory = InMemoryElderDirectory(
        elders if elders is not None else {12: ElderAccess(guardian_id, True)}
    )
    return Kit(
        auth=KeyAuth(store),
        directory=directory,
        headers={"Authorization": f"Bearer {new.key}"},
        store=store,
        key=new.key,
    )
