"""가입 → 승인 전 통화 거절 → 승인 → 통화 — 진짜 Postgres 저장소로 처음부터 끝까지."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api.app_data import add_app_routes
from app.api.calls import build_app
from app.api.elder_directory import ElderAccess  # noqa: F401
from app.api.guardian_auth import InMemoryGuardianKeyStore, KeyAuth, generate_key
from app.main import app_data_for
from app.media.stream_server import InMemoryCallRegistry
from app.telephony.client import FakeTelephony
from tests.pg_helpers import DATABASE_URL

pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL이 없다")


def make():
    from app.api.postgres_elder_directory import PostgresElderDirectory
    from app.api.postgres_store import PostgresCallStore
    from tests.pg_helpers import pg_pool, seed_world

    pool = pg_pool()
    seed_world(pool)
    keys = InMemoryGuardianKeyStore()
    new = generate_key()
    keys.add(guardian_id=1, label="t", key_prefix=new.key_prefix, key_hash=new.key_hash)
    auth = KeyAuth(keys)
    directory = PostgresElderDirectory(pool=pool)
    data, _ = app_data_for(pool, guardian_auth=auth, elders=directory)
    telephony = FakeTelephony()
    store = PostgresCallStore(pool=pool, phones={})
    app = build_app(
        store=store,
        telephony=telephony,
        registry=InMemoryCallRegistry(),
        public_base_url="https://api.example.com",
        stream_base_url="wss://api.example.com",
        guardian_auth=auth,
        elders=directory,
    )
    add_app_routes(app, data)
    return TestClient(app), {"Authorization": f"Bearer {new.key}"}, telephony, store, pool


def test_a_signed_up_elder_is_called_only_after_the_guardian_approves():
    client, guardian, telephony, store, pool = make()
    code = client.post("/v1/guardian/invite", headers=guardian).json()["code"]

    signup = client.post(
        "/v1/signup",
        json={"code": code, "name": "새 어르신", "phone": "010-9999-1111", "agreed": True},
    )
    assert signup.status_code == 200
    elders = client.get("/v1/guardian/elders", headers=guardian).json()["elders"]
    pending = next(e for e in elders if e["status"] == "pending")
    elder_id = pending["elder_id"]
    assert pending["phone"] == "010-9999-1111" and pending["name"] == "새 어르신"

    # 1) 승인 전: DB에 consent_at이 없고, 통화 요청은 거절되고, 스케줄러 명부에도 없다.
    with pool.connection() as conn:
        consent = conn.execute(
            "SELECT consent_at, agreed_at FROM elders WHERE elder_id = %s", (elder_id,)
        ).fetchone()
        assert consent[0] is None and consent[1] is not None
        roster_ids = [r[0] for r in conn.execute(
            "SELECT e.elder_id FROM elders e WHERE e.consent_at IS NOT NULL"
        ).fetchall()]
    assert elder_id not in roster_ids
    refused = client.post("/v1/calls/request", json={"elder_id": elder_id}, headers=guardian)
    assert refused.status_code == 403
    assert telephony.placed == []

    # 2) 승인 후: 같은 요청이 통과하고, 그 어르신의 DB 번호로 전화가 걸린다.
    assert client.post(f"/v1/elders/{elder_id}/approve", headers=guardian).status_code == 200
    placed = client.post("/v1/calls/request", json={"elder_id": elder_id}, headers=guardian)
    assert placed.status_code == 202
    assert store.find_elder(elder_id) == "010-9999-1111"
    assert [to for to, _ in telephony.placed] == ["010-9999-1111"]


def test_rejecting_removes_the_elder_the_keys_and_frees_the_number():
    client, guardian, telephony, store, pool = make()
    code = client.post("/v1/guardian/invite", headers=guardian).json()["code"]
    key = client.post(
        "/v1/signup",
        json={"code": code, "name": "새 어르신", "phone": "010-9999-1111", "agreed": True},
    ).json()["elder_key"]
    elders = client.get("/v1/guardian/elders", headers=guardian).json()["elders"]
    elder_id = next(e["elder_id"] for e in elders if e["status"] == "pending")

    assert client.post(f"/v1/elders/{elder_id}/reject", headers=guardian).status_code == 200

    me = client.get("/v1/me/status", headers={"Authorization": f"Bearer {key}"})
    assert me.status_code == 401
    with pool.connection() as conn:
        assert conn.execute("SELECT count(*) FROM elder_keys WHERE elder_id = %s", (elder_id,)).fetchone()[0] == 0
    again = client.post(
        "/v1/signup",
        json={"code": code, "name": "다시", "phone": "010-9999-1111", "agreed": True},
    )
    assert again.status_code == 200  # 같은 번호로 다시 가입할 수 있다
