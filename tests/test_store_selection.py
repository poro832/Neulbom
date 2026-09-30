"""조립부가 저장소를 고르는 규칙 (app/main.py의 stores_from_env).

여기가 틀리면 아무것도 터지지 않는다. 서버는 멀쩡히 뜨고 전화도 걸리고
점수도 나온다 — 다만 재시작하면 다 사라진다. 그래서 "떴다"로는 확인이
안 되고, 고른 저장소가 무엇인지를 직접 봐야 한다.

마지막 테스트 하나는 진짜 Postgres 위에서 통화를 처음부터 끝까지 돌린다.
규약 테스트는 저장소를 직접 부르므로, 서버가 그 저장소를 실제로 쓰는지는
거기서 알 수 없다.
"""

from __future__ import annotations

import os
import re

import pytest
from fastapi.testclient import TestClient

from app.api.outcome_store import InMemoryOutcomeStore
from app.api.store import InMemoryCallStore
from app.main import build_server, stores_from_env
from app.telephony.client import FakeTelephony
from tests.test_server_wiring import _Beep, run_stream

DATABASE_URL = os.getenv("DATABASE_URL")

needs_postgres = pytest.mark.skipif(
    not DATABASE_URL,
    reason="DATABASE_URL이 없다 — 조립부의 Postgres 갈래를 건너뛴다.",
)


def test_no_database_url_gives_memory_stores(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)

    store, outcomes, pool = stores_from_env()

    assert isinstance(store, InMemoryCallStore)
    # 결과 저장소는 None으로 넘기고 build_server가 메모리로 채운다.
    assert outcomes is None
    assert pool is None


def test_a_blank_database_url_is_the_same_as_none(monkeypatch):
    """공백만 있는 값은 "설정했다"가 아니다. 이걸 참으로 읽으면 psycopg가
    빈 문자열로 접속을 시도하고, 서버가 뜨지 않는 이유가 한참 안 보인다."""
    monkeypatch.setenv("DATABASE_URL", "   ")

    store, outcomes, pool = stores_from_env()

    assert isinstance(store, InMemoryCallStore)
    assert pool is None


def test_the_memory_fallback_says_so_in_the_log(monkeypatch, caplog):
    """조용히 메모리로 도는 것이 가장 위험하다 — 데이터가 남는다고 믿게 된다."""
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with caplog.at_level("INFO", logger="app.main"):
        stores_from_env()

    assert "메모리 저장소" in caplog.text


def test_elder_phones_still_reach_the_postgres_store(monkeypatch):
    """명부는 아직 환경 변수에 있다(app/seed_elders.py의 임시 다리). 저장소를
    바꾸면서 이걸 빠뜨리면 전화번호가 없어 발신이 통째로 실패한다."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("ELDER_PHONES", "12:070-1111-2222")

    store, _, _ = stores_from_env()

    assert store.find_elder(12) == "070-1111-2222"


@needs_postgres
def test_a_database_url_gives_postgres_stores_on_one_pool(monkeypatch):
    """저장소 둘이 한 풀을 나눠 쓴다. 각자 열면 연결이 두 배로 늘고,
    RDS Free Tier의 연결 한도가 우리가 먼저 만나는 벽이다."""
    from app.api.postgres_outcome_store import PostgresOutcomeStore
    from app.api.postgres_store import PostgresCallStore

    monkeypatch.setenv("DATABASE_URL", DATABASE_URL)

    store, outcomes, pool = stores_from_env()
    try:
        assert isinstance(store, PostgresCallStore)
        assert isinstance(outcomes, PostgresOutcomeStore)
        assert store._pool is pool is outcomes._pool
    finally:
        pool.close()


@needs_postgres
def test_a_whole_call_runs_on_postgres_and_survives_the_stores(tmp_path, monkeypatch):
    """통화 하나를 트리거부터 종료까지 실제 경로로 돌리고, 그 결과를 새로
    만든 저장소에서 다시 읽는다.

    새로 읽는 것이 요점이다. 같은 객체에서 읽으면 메모리에 남은 것을 보는
    것과 구분되지 않는다 — 재시작 뒤에도 보호자에게 보여줄 점수가 있는지가
    이 작업의 목적이었다.
    """
    from app.api.db import connect
    from app.api.postgres_outcome_store import PostgresOutcomeStore
    from app.api.postgres_store import PostgresCallStore

    monkeypatch.setenv("DATABASE_URL", DATABASE_URL)
    monkeypatch.setenv("ELDER_PHONES", "12:070-1111-2222")

    store, outcomes, pool = stores_from_env()
    # 앞선 테스트가 남긴 행을 치우고 어르신 12를 심는다.
    outcomes.reset_for_tests()

    try:
        app = build_server(
            store=store,
            outcomes=outcomes,
            telephony=FakeTelephony(),
            public_base_url="https://api.example.com",
            stream_base_url="wss://api.example.com",
            responder_factory=_Beep,
            recordings_dir=tmp_path,
        )
        client = TestClient(app)

        call_id = client.post(
            "/v1/calls/request", json={"elder_id": 12}
        ).json()["call_id"]
        sid = store.get(call_id).provider_call_sid
        xml = client.post("/v1/voiceml", data={"CallId": sid}).text
        token = re.search(r'name="token" value="([^"]+)"', xml).group(1)

        run_stream(client, token)

        assert store.get(call_id).status == "completed"
    finally:
        pool.close()

    fresh_pool = connect(DATABASE_URL)
    try:
        fresh_calls = PostgresCallStore(pool=fresh_pool, phones={})
        fresh_outcomes = PostgresOutcomeStore(pool=fresh_pool)

        assert fresh_calls.get(call_id).status == "completed"
        got = fresh_outcomes.recent(12, 14)
        assert [o.call_id for o in got] == [call_id]
        # 녹음에서 실제로 잰 값이다. 발화 절반, 침묵 절반을 보냈다.
        assert 0.3 < got[0].metrics.speech_ratio < 0.7
    finally:
        fresh_pool.close()


def test_without_a_database_transcripts_live_in_memory():
    from app.api.transcript_store import InMemoryTranscriptStore
    from app.main import transcripts_for

    assert isinstance(transcripts_for(None), InMemoryTranscriptStore)


def test_with_a_database_transcripts_go_to_postgres():
    from app.api.postgres_transcript_store import PostgresTranscriptStore
    from app.main import transcripts_for

    assert isinstance(transcripts_for(object()), PostgresTranscriptStore)


def test_the_worker_and_the_archiver_share_one_transcript_store():
    """저장하는 쪽과 30일에 지우는 쪽이 다른 저장소면 약속이 조용히 깨진다."""
    import app.main as main

    assert main._transcripts is not None
    # 모듈 조립에서 보관기에 넘긴 것이 같은 객체인지 본다.
    archivers = [
        h.__self__
        for h in main.app.router.on_startup
        if getattr(h, "__self__", None).__class__.__name__ == "RecordingArchiver"
    ]
    assert archivers and archivers[0].transcripts is main._transcripts
