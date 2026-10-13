"""보호자 계정 흐름을 실제 Postgres로 — 가입, 로그인, 비밀번호 변경, 로그아웃."""

from __future__ import annotations

import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

pytestmark = pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="DATABASE_URL이 없다")

GOOD = {"name": "김보호", "email": "Kim@Example.com", "phone": "010-1111-2222", "password": "correct-horse-1"}


def make_client():
    from app.api.app_data import add_app_routes
    from app.api.elder_directory import InMemoryElderDirectory
    from app.api.guardian_auth import KeyAuth
    from app.api.postgres_guardian_keys import PostgresGuardianKeyStore
    from app.main import app_data_for
    from tests.pg_helpers import pg_pool, seed_world

    pool = pg_pool()
    seed_world(pool)
    auth = KeyAuth(PostgresGuardianKeyStore(pool=pool))
    data, _ = app_data_for(pool, guardian_auth=auth, elders=InMemoryElderDirectory())
    app = FastAPI()
    add_app_routes(app, data)
    return TestClient(app)


def bearer(key):
    return {"Authorization": f"Bearer {key}"}


def test_account_flow_against_postgres():
    client = make_client()
    signup = client.post("/v1/guardian/signup", json=GOOD)
    assert signup.status_code == 200
    key1 = signup.json()["key"]
    assert client.post("/v1/guardian/signup", json={**GOOD, "email": " KIM@example.com"}).status_code == 409

    key2 = client.post("/v1/guardian/login", json={"email": "kim@example.com", "password": GOOD["password"]}).json()["key"]
    assert client.get("/v1/guardian/me", headers=bearer(key2)).json()["name"] == "김보호"

    changed = client.post(
        "/v1/guardian/password",
        json={"current": GOOD["password"], "new": "brand-new-pass-2"},
        headers=bearer(key1),
    )
    assert changed.status_code == 200 and changed.json() == {"revoked_others": 1}
    assert client.get("/v1/guardian/me", headers=bearer(key2)).status_code == 401
    assert client.get("/v1/guardian/me", headers=bearer(key1)).status_code == 200
    assert client.post("/v1/guardian/login", json={"email": "kim@example.com", "password": GOOD["password"]}).status_code == 401

    assert client.post("/v1/guardian/logout", headers=bearer(key1)).status_code == 204
    assert client.get("/v1/guardian/me", headers=bearer(key1)).status_code == 401


def test_parallel_signups_get_distinct_ids():
    from concurrent.futures import ThreadPoolExecutor

    client = make_client()

    def go(n):
        body = {**GOOD, "email": f"user{n}@example.com"}
        return client.post("/v1/guardian/signup", json=body).status_code

    with ThreadPoolExecutor(max_workers=6) as pool:
        codes = list(pool.map(go, range(12)))

    assert codes == [200] * 12
