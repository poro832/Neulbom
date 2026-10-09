"""앱 데이터 주소 테스트가 쓰는 도우미. 모든 저장소는 메모리다."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.alerts import InMemoryAlertStore
from app.api.app_data import AppData, add_app_routes
from app.api.contacts import InMemoryContactStore
from app.api.elder_auth import ElderKeyAuth, InMemoryElderKeyStore, generate_elder_key
from app.api.elder_directory import ElderAccess, GuardianProfile, InMemoryElderDirectory
from app.api.guardian_auth import InMemoryGuardianKeyStore, KeyAuth, generate_key
from app.api.invites import InMemoryInviteStore
from app.api.pairing import InMemoryPairingStore, hash_code, new_code
from app.api.reports import InMemoryReports
from app.scheduler import KST


class WallClock:
    def __init__(self, now: float):
        self.now = now

    def __call__(self):
        return self.now


def kst(*args) -> float:
    return datetime(*args, tzinfo=KST).timestamp()


@dataclass
class AppKit:
    client: TestClient
    data: AppData
    guardian_headers: dict
    clock: WallClock
    reports: InMemoryReports
    alerts: InMemoryAlertStore

    def elder_headers(self, elder_id: int = 12) -> dict:
        """연결을 거치지 않고 어르신 열쇠를 바로 심는다. 연결 흐름은 따로 시험한다."""
        new = generate_elder_key()
        self.data.elder_keys.replace(elder_id=elder_id, key_prefix=new.key_prefix, key_hash=new.key_hash)
        return {"Authorization": f"Bearer {new.key}"}


    def issue_invite(self, guardian_id: int = 1) -> str:
        """보호자 개인 코드를 직접 심는다. 발급 주소는 따로 시험한다."""
        from app.api.invites import hash_invite_code, new_invite_code

        code = new_invite_code()
        self.data.invites.issue(guardian_id, hash_invite_code(code))
        return code

    def new_pairing(self, elder_id: int = 12) -> str:
        code = new_code()
        self.data.pairings.issue(elder_id, hash_code(code))
        return code


def make_app_kit(now: float | None = None) -> AppKit:
    clock = WallClock(now if now is not None else kst(2026, 10, 8, 9, 0, 0))
    key_store = InMemoryGuardianKeyStore()
    new = generate_key()
    key_store.add(guardian_id=1, label="test", key_prefix=new.key_prefix, key_hash=new.key_hash)

    directory = InMemoryElderDirectory(
        {
            12: ElderAccess(1, True, "어르신 12"),
            13: ElderAccess(1, True, "어르신 13"),
            14: ElderAccess(2, True, "어르신 14"),
        },
        phones={12: "070-1111-2222", 13: "070-3333-4444", 14: "070-5555-6666"},
        guardians={1: GuardianProfile("보호자1", "010-0000-0001"), 2: GuardianProfile("보호자2", "010-0000-0002")},
    )
    alerts = InMemoryAlertStore(clock=clock)
    reports = InMemoryReports(directory, alerts)
    data = AppData(
        guardian_auth=KeyAuth(key_store),
        elder_auth=ElderKeyAuth(InMemoryElderKeyStore(wall_clock=clock)),
        elders=directory,
        pairings=InMemoryPairingStore(clock=clock),
        elder_keys=None,  # 아래에서 인증기와 같은 저장소로 맞춘다
        contacts=InMemoryContactStore(),
        reports=reports,
        alerts=alerts,
        invites=InMemoryInviteStore(),
        wall_clock=clock,
    )
    elder_store = InMemoryElderKeyStore(wall_clock=clock)
    data.elder_keys = elder_store
    data.elder_auth = ElderKeyAuth(elder_store)

    app = FastAPI()
    add_app_routes(app, data)
    return AppKit(
        client=TestClient(app),
        data=data,
        guardian_headers={"Authorization": f"Bearer {new.key}"},
        clock=clock,
        reports=reports,
        alerts=alerts,
    )
