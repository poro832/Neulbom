"""탈퇴를 진짜 Postgres 저장소로 — CASCADE가 실제로 무엇을 지우고 무엇을 남기는지 DB에서 센다.

보호자 탈퇴는 어르신을 남기고(연결 전), 어르신 탈퇴는 그 어르신의 통화·점수·요약·언급·연락처·열쇠·코드를
모두 지운다. 다른 사람의 행은 하나도 바뀌지 않는다. S3는 가짜 삭제기다.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.app_data import add_app_routes
from app.api.elder_auth import generate_elder_key
from app.api.guardian_auth import KeyAuth, generate_key
from app.api.passwords import hash_password
from tests.pg_helpers import DATABASE_URL

pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL이 없다")

PASSWORD = "correct-horse-1"


class FakeDeleter:
    def __init__(self):
        self.calls = []

    def delete_many(self, keys):
        self.calls.append(list(keys))
        return 0


def bearer(key):
    return {"Authorization": f"Bearer {key}"}


def make():
    from app.api.postgres_elder_directory import PostgresElderDirectory
    from app.api.postgres_guardian_keys import PostgresGuardianKeyStore
    from app.main import app_data_for
    from tests.pg_helpers import pg_pool, seed_world

    pool = pg_pool()
    seed_world(pool)  # 보호자 1(어르신 12·13), 보호자 2(어르신 14)
    keys = PostgresGuardianKeyStore(pool=pool)
    guardian_keys = {}
    for guardian_id in (1, 2):
        new = generate_key()
        keys.add(guardian_id=guardian_id, label="t", key_prefix=new.key_prefix, key_hash=new.key_hash)
        guardian_keys[guardian_id] = bearer(new.key)
    deleter = FakeDeleter()
    data, _ = app_data_for(
        pool, guardian_auth=KeyAuth(keys), elders=PostgresElderDirectory(pool=pool), recording_deleter=deleter
    )
    data.accounts.set_password(1, hash_password(PASSWORD))
    elder_keys = {}
    for elder_id in (12, 13, 14):
        new = generate_elder_key()
        data.elder_keys.replace(elder_id=elder_id, key_prefix=new.key_prefix, key_hash=new.key_hash)
        elder_keys[elder_id] = bearer(new.key)
    app = FastAPI()
    add_app_routes(app, data)
    return TestClient(app), pool, data, guardian_keys, elder_keys, deleter


def seed_everything(pool):
    """어르신 12·13·14마다 통화·점수·대화·요약·복용·언급·전사·열람·알림·연락처·연결 코드, 보호자마다 폰·개인 코드."""
    with pool.connection() as conn:
        for call_id, elder_id, guardian_id in ((1, 12, 1), (2, 13, 1), (3, 14, 2)):
            conn.execute(
                "INSERT INTO calls (call_id, elder_id, status, audio_key, requested_by_guardian_id, trigger_type) "
                "VALUES (%s, %s, 'completed', %s, %s, 'requested')",
                (call_id, elder_id, f"{elder_id}-a.wav", guardian_id),
            )
            conn.execute(
                "INSERT INTO call_metrics (call_id, risk_score, risk_level, calculator_version) "
                "VALUES (%s, 10, 'normal', '2.0.0')",
                (call_id,),
            )
            conn.execute("INSERT INTO call_transcripts (call_id, text) VALUES (%s, '허리가 아파요')", (call_id,))
            conn.execute(
                "INSERT INTO call_turns (call_id, seq, speaker, text) VALUES (%s, 0, 'elder', '허리가 아파요')",
                (call_id,),
            )
            conn.execute("INSERT INTO call_reports (call_id, summary, model_id) VALUES (%s, '요약', 'm')", (call_id,))
            conn.execute("INSERT INTO call_medication (call_id, status, model_id) VALUES (%s, 'taken', 'm')", (call_id,))
            conn.execute(
                "INSERT INTO call_mentions (call_id, category, said, quote, model_id) "
                "VALUES (%s, 'body', 'bad', '허리가 아파요', 'm')",
                (call_id,),
            )
            conn.execute("INSERT INTO transcript_views (call_id, guardian_id) VALUES (%s, %s)", (call_id, guardian_id))
            conn.execute(
                "INSERT INTO alerts (elder_id, guardian_id, call_id, alert_type, severity, message) "
                "VALUES (%s, %s, %s, 'risk_rise', 'warning', 'm')",
                (elder_id, guardian_id, call_id),
            )
            conn.execute(
                "INSERT INTO contacts (elder_id, name, phone_number) VALUES (%s, '이웃', '010-2222-3333')", (elder_id,)
            )
            conn.execute(
                "INSERT INTO elder_pairings (elder_id, code_hash, expires_at) VALUES (%s, %s, now() + interval '1 hour')",
                (elder_id, f"pair-{elder_id}"),
            )
            conn.execute(
                "INSERT INTO elder_link_codes (elder_id, code_hash, expires_at) VALUES (%s, %s, now() + interval '1 hour')",
                (elder_id, f"link-{elder_id}"),
            )
        # 어르신 12에게는 이미 쓴 연결 코드도 하나 있다(기록 — 보호자 탈퇴가 지우지 않는다)
        conn.execute(
            "INSERT INTO elder_pairings (elder_id, code_hash, expires_at, used_at) "
            "VALUES (12, 'pair-12-used', now(), now())"
        )
        for guardian_id in (1, 2):
            conn.execute(
                "INSERT INTO guardian_devices (token, guardian_id, key_hash) VALUES (%s, %s, 'h')",
                (f"token-{guardian_id}-aaaaaaaaaaaaaaaa", guardian_id),
            )
            conn.execute(
                "INSERT INTO guardian_invites (guardian_id, code_hash) VALUES (%s, %s)", (guardian_id, f"inv-{guardian_id}")
            )


PER_ELDER = {
    "calls": "SELECT count(*) FROM calls WHERE elder_id = %s",
    "call_metrics": "SELECT count(*) FROM call_metrics m JOIN calls c USING (call_id) WHERE c.elder_id = %s",
    "contacts": "SELECT count(*) FROM contacts WHERE elder_id = %s",
    "elder_keys": "SELECT count(*) FROM elder_keys WHERE elder_id = %s",
    "elder_pairings": "SELECT count(*) FROM elder_pairings WHERE elder_id = %s",
    "elder_link_codes": "SELECT count(*) FROM elder_link_codes WHERE elder_id = %s",
    "alerts": "SELECT count(*) FROM alerts WHERE elder_id = %s",
}
PER_CALL = ("call_metrics", "call_transcripts", "call_turns", "call_reports", "call_medication", "call_mentions",
            "transcript_views")
PER_GUARDIAN = ("guardian_keys", "guardian_devices", "guardian_invites", "alerts", "transcript_views")


def counts_for_elder(pool, elder_id):
    with pool.connection() as conn:
        return {name: conn.execute(sql, (elder_id,)).fetchone()[0] for name, sql in PER_ELDER.items()}


def counts_for_call(pool, call_id):
    with pool.connection() as conn:
        return {t: conn.execute(f"SELECT count(*) FROM {t} WHERE call_id = %s", (call_id,)).fetchone()[0] for t in PER_CALL}


def counts_for_guardian(pool, guardian_id):
    with pool.connection() as conn:
        return {
            t: conn.execute(f"SELECT count(*) FROM {t} WHERE guardian_id = %s", (guardian_id,)).fetchone()[0]
            for t in PER_GUARDIAN
        }


def unused_pairings(pool, elder_id):
    with pool.connection() as conn:
        return conn.execute(
            "SELECT count(*) FROM elder_pairings WHERE elder_id = %s AND used_at IS NULL", (elder_id,)
        ).fetchone()[0]


def elder_row(pool, elder_id):
    with pool.connection() as conn:
        return conn.execute(
            "SELECT guardian_id, consent_at IS NOT NULL, name, phone_number FROM elders WHERE elder_id = %s",
            (elder_id,),
        ).fetchone()


# ------------------------------------------------ 보호자 탈퇴


def test_a_guardian_withdrawal_keeps_every_elder_row_and_its_data():
    client, pool, data, guardian_keys, elder_keys, deleter = make()
    seed_everything(pool)
    before = {elder_id: counts_for_elder(pool, elder_id) for elder_id in (12, 13, 14)}

    r = client.request("DELETE", "/v1/guardian/me", json={"password": PASSWORD}, headers=guardian_keys[1])

    assert r.status_code == 204
    with pool.connection() as conn:
        assert conn.execute("SELECT count(*) FROM guardians WHERE guardian_id = 1").fetchone()[0] == 0
        # 통화를 누가 눌렀는지는 비워지고 통화는 남는다
        assert conn.execute("SELECT requested_by_guardian_id FROM calls WHERE call_id = 1").fetchone() == (None,)
    assert counts_for_guardian(pool, 1) == dict.fromkeys(PER_GUARDIAN, 0)
    # 어르신 12·13은 연결 전으로 남고, 그 데이터도 남는다. 보호자에게 간 알림과, 그 보호자가 내준 안 쓴 연결 코드만
    # 지워진다(이미 쓴 코드는 기록으로 남는다).
    assert elder_row(pool, 12) == (None, False, "어르신 12", "070-1111-2222")
    assert elder_row(pool, 13) == (None, False, "어르신 13", "070-3333-4444")
    assert before[12]["elder_pairings"] == 2 and before[13]["elder_pairings"] == 1
    for elder_id, used in ((12, 1), (13, 0)):
        assert counts_for_elder(pool, elder_id) == {**before[elder_id], "alerts": 0, "elder_pairings": used}
        assert unused_pairings(pool, elder_id) == 0
    assert unused_pairings(pool, 14) == 1
    assert counts_for_call(pool, 1) == {**dict.fromkeys(PER_CALL, 1), "transcript_views": 0}
    # 다른 보호자와 그 어르신은 그대로다
    assert elder_row(pool, 14) == (2, True, "어르신 14", "070-5555-6666")
    assert counts_for_elder(pool, 14) == before[14]
    assert counts_for_guardian(pool, 2) == {**dict.fromkeys(PER_GUARDIAN, 1)}
    assert client.get("/v1/guardian/elders", headers=guardian_keys[2]).status_code == 200
    # 안부 전화 명부에서 빠졌다
    from app.api.postgres_store import PostgresRoster

    assert [e.elder_id for e in PostgresRoster(pool=pool).entries()] == [14]
    # 어르신 폰은 그대로 열린다 — 연결 전 상태를 본다
    assert client.get("/v1/me/status", headers=elder_keys[12]).json()["status"] == "unlinked"
    assert deleter.calls == []
    pool.close()


def test_the_operator_tool_deletes_a_guardian_without_touching_the_elders():
    from app.admin import run
    from app.api.postgres_devices import PostgresDeviceStore
    from app.api.postgres_guardian_keys import PostgresGuardianKeyStore
    from app.api.postgres_invites import PostgresInviteStore
    from app.api.postgres_pairing import PostgresPairingStore

    client, pool, data, guardian_keys, elder_keys, deleter = make()
    seed_everything(pool)
    lines = []

    code = run(
        ["guardian", "delete", "1", "--yes"], keys=PostgresGuardianKeyStore(pool=pool), directory=data.elders,
        accounts=data.accounts, devices=PostgresDeviceStore(pool=pool), invites=PostgresInviteStore(pool=pool),
        pairings=PostgresPairingStore(pool=pool), out=lines.append, err=lines.append,
    )

    assert code == 0, lines
    assert elder_row(pool, 12)[0] is None and elder_row(pool, 13)[0] is None
    assert counts_for_elder(pool, 12)["calls"] == 1
    assert counts_for_guardian(pool, 1) == dict.fromkeys(PER_GUARDIAN, 0)
    assert unused_pairings(pool, 12) == 0 and unused_pairings(pool, 13) == 0 and unused_pairings(pool, 14) == 1
    assert elder_row(pool, 14) == (2, True, "어르신 14", "070-5555-6666")
    pool.close()


def test_a_pairing_code_issued_before_the_withdrawal_cannot_pair_a_phone_afterwards():
    client, pool, data, guardian_keys, elder_keys, deleter = make()
    code = client.post("/v1/elders/12/pairing-code", headers=guardian_keys[1]).json()["code"]

    assert client.request("DELETE", "/v1/guardian/me", json={"password": PASSWORD}, headers=guardian_keys[1]).status_code == 204

    assert client.post("/v1/pair", json={"code": code, "phone": "070-1111-2222"}).status_code == 401
    assert unused_pairings(pool, 12) == 0
    pool.close()


# ------------------------------------------------ 어르신 탈퇴


def test_an_elder_withdrawal_cascades_to_every_table_and_nothing_else():
    client, pool, data, guardian_keys, elder_keys, deleter = make()
    seed_everything(pool)
    others_before = {elder_id: counts_for_elder(pool, elder_id) for elder_id in (13, 14)}

    asked = client.post("/v1/me/withdrawal", json={"confirm": True}, headers=elder_keys[12])
    assert asked.status_code == 202
    r = client.post("/v1/elders/12/withdrawal/approve", headers=guardian_keys[1])

    assert r.status_code == 200 and r.json() == {"status": "deleted"}
    assert deleter.calls == [["12-a.wav"]]
    assert elder_row(pool, 12) is None
    assert counts_for_elder(pool, 12) == dict.fromkeys(PER_ELDER, 0)
    assert counts_for_call(pool, 1) == dict.fromkeys(PER_CALL, 0)
    for elder_id in (13, 14):
        assert counts_for_elder(pool, elder_id) == others_before[elder_id]
    assert counts_for_call(pool, 2) == dict.fromkeys(PER_CALL, 1)
    assert data.elders.audio_keys_of(13) == ["13-a.wav"]
    # 보호자는 그대로다(그 어르신에 대한 알림만 같이 지워졌다)
    with pool.connection() as conn:
        assert conn.execute("SELECT count(*) FROM guardians").fetchone()[0] == 2
    assert counts_for_guardian(pool, 1)["guardian_keys"] == 1
    assert client.get("/v1/me/status", headers=elder_keys[12]).status_code == 401
    assert client.get("/v1/me/status", headers=elder_keys[13]).status_code == 200
    # 같은 번호로 다시 가입할 수 있다
    again = client.post("/v1/elders/signup", json={"name": "다시", "phone": "070-1111-2222", "agreed": True})
    assert again.status_code == 200
    pool.close()
