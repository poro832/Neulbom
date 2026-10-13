"""통화 요약·원문 공개 — 진짜 Postgres 저장소로 동의 전/후, 남의 통화, 열람 기록까지."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.app_data import add_app_routes
from app.api.guardian_auth import InMemoryGuardianKeyStore, KeyAuth, generate_key
from app.main import app_data_for
from tests.pg_helpers import DATABASE_URL, insert_call

pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL이 없다")

START = 1_800_000_000.0


def make():
    from app.api.postgres_elder_directory import PostgresElderDirectory
    from tests.pg_helpers import pg_pool, seed_world

    pool = pg_pool()
    seed_world(pool)
    keys = InMemoryGuardianKeyStore()
    mine, theirs = generate_key(), generate_key()
    keys.add(guardian_id=1, label="t", key_prefix=mine.key_prefix, key_hash=mine.key_hash)
    keys.add(guardian_id=2, label="t", key_prefix=theirs.key_prefix, key_hash=theirs.key_hash)
    data, _ = app_data_for(
        pool, guardian_auth=KeyAuth(keys), elders=PostgresElderDirectory(pool=pool)
    )
    app = FastAPI()
    add_app_routes(app, data)
    return (
        TestClient(app),
        {"Authorization": f"Bearer {mine.key}"},
        {"Authorization": f"Bearer {theirs.key}"},
        data,
        pool,
    )


def test_content_is_hidden_until_the_elder_agrees_and_every_view_is_logged():
    client, mine, theirs, data, pool = make()
    insert_call(pool, call_id=1, elder_id=12, status="completed", created_at=START)
    data.content.save_turns(1, [("ai", "안녕하세요"), ("elder", "네 안녕하세요")])
    data.content.save_summary(1, "안부를 나누셨어요.", "m")

    # 동의 전: DB에 내용이 있어도 목록은 비고 원문은 404, 열람 기록도 없다.
    assert client.get("/v1/elders/12/calls", headers=mine).json() == {
        "share_agreed": False,
        "calls": [],
    }
    assert client.get("/v1/calls/1/turns", headers=mine).status_code == 404
    assert data.content.view_count(1) == 0

    # 약 복용 확인 값이 저장돼 있어도 동의 전에는 나가지 않는다.
    data.content.save_medication(1, "taken", "m")
    before = client.get("/v1/elders/12/calls", headers=mine)
    assert before.json() == {"share_agreed": False, "calls": []}
    assert "taken" not in before.text

    # 어르신이 동의한다.
    data.content.agree_share(12)
    calls = client.get("/v1/elders/12/calls", headers=mine).json()["calls"]
    assert calls[0]["summary"] == "안부를 나누셨어요." and calls[0]["has_turns"] is True
    assert calls[0]["medication"] == "taken"
    turns = client.get("/v1/calls/1/turns", headers=mine).json()["turns"]
    assert [t["text"] for t in turns] == ["안녕하세요", "네 안녕하세요"]
    assert data.content.view_count(1) == 1
    with pool.connection() as conn:
        rows = conn.execute("SELECT guardian_id FROM transcript_views WHERE call_id = 1").fetchall()
    assert rows == [(1,)]

    # 다른 보호자는 존재 여부도 알 수 없다.
    assert client.get("/v1/elders/12/calls", headers=theirs).status_code == 404
    assert client.get("/v1/calls/1/turns", headers=theirs).status_code == 404
    assert data.content.view_count(1) == 1


def test_a_signup_through_the_real_stores_records_the_agreement():
    client, mine, _, data, pool = make()
    code = client.post("/v1/guardian/invite", headers=mine).json()["code"]
    key = client.post(
        "/v1/signup",
        json={"code": code, "name": "새 어르신", "phone": "010-9999-1111", "agreed": True},
    ).json()["elder_key"]

    status = client.get("/v1/me/status", headers={"Authorization": f"Bearer {key}"}).json()
    assert status["share_agreed"] is True
    with pool.connection() as conn:
        row = conn.execute(
            "SELECT share_agreed_at IS NOT NULL, consent_at IS NULL FROM elders WHERE name = '새 어르신'"
        ).fetchone()
    assert row == (True, True)  # 공유 동의는 있어도 consent_at(전화 동의)은 승인 전까지 비어 있다
