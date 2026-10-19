"""어르신 본인이 "통화하기"로 안부 전화를 요청하는 주소(POST /v1/me/call-request)."""

import pytest
from fastapi.testclient import TestClient

from app.api.calls import build_app
from app.api.elder_auth import ElderKeyAuth, InMemoryElderKeyStore, generate_elder_key
from app.api.elder_directory import ElderAccess, InMemoryElderDirectory
from app.api.store import InMemoryCallStore
from app.media.stream_server import InMemoryCallRegistry
from app.telephony.client import FakeTelephony


def make(elders=None, manual_calls_per_day=3):
    store = InMemoryCallStore(phones={12: "010-1111-2222", 13: "010-3333-4444"})
    telephony = FakeTelephony()
    keys = InMemoryElderKeyStore()
    issued = {}
    for elder_id in (12, 13):
        new = generate_elder_key()
        keys.replace(elder_id=elder_id, key_prefix=new.key_prefix, key_hash=new.key_hash)
        issued[elder_id] = {"Authorization": f"Bearer {new.key}"}
    directory = InMemoryElderDirectory(
        elders
        if elders is not None
        else {12: ElderAccess(1, True), 13: ElderAccess(None, False)}
    )
    app = build_app(
        store=store,
        telephony=telephony,
        registry=InMemoryCallRegistry(),
        public_base_url="https://api.example.com",
        stream_base_url="wss://api.example.com",
        elders=directory,
        elder_auth=ElderKeyAuth(keys),
        manual_calls_per_day=manual_calls_per_day,
        guardian_auth=None,
    )
    return TestClient(app), issued, store, telephony


def test_a_linked_elder_can_ask_for_a_call_to_their_own_number():
    client, keys, store, telephony = make()
    response = client.post("/v1/me/call-request", headers=keys[12])

    assert response.status_code == 202
    assert [to for to, _ in telephony.placed] == ["010-1111-2222"]
    call = store.get(response.json()["call_id"])
    assert call.elder_id == 12
    assert call.trigger_type == "requested"


def test_pressing_twice_does_not_dial_twice():
    client, keys, _, telephony = make()
    first = client.post("/v1/me/call-request", headers=keys[12])
    second = client.post("/v1/me/call-request", headers=keys[12])

    assert second.status_code == 409
    assert second.json()["call_id"] == first.json()["call_id"]
    assert len(telephony.placed) == 1


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer nope"}])
def test_without_a_valid_elder_key_nothing_is_dialed(headers):
    client, _, _, telephony = make()
    assert client.post("/v1/me/call-request", headers=headers).status_code == 401
    assert telephony.placed == []


def test_an_elder_who_is_not_linked_yet_cannot_trigger_a_call():
    client, keys, _, telephony = make()
    response = client.post("/v1/me/call-request", headers=keys[13])

    assert response.status_code == 403
    assert telephony.placed == []


def test_an_elder_whose_guardian_has_not_approved_cannot_trigger_a_call():
    elders = {12: ElderAccess(1, False, agreed=True), 13: ElderAccess(None, False)}
    client, keys, _, telephony = make(elders)

    assert client.post("/v1/me/call-request", headers=keys[12]).status_code == 403
    assert telephony.placed == []


def test_the_daily_limit_applies_to_elder_requests():
    client, keys, _, telephony = make(manual_calls_per_day=1)
    first = client.post("/v1/me/call-request", headers=keys[12])
    assert first.status_code == 202
    # 한도 검사는 활성 통화 검사(409)보다 앞이라 두 번째는 429다.
    second = client.post("/v1/me/call-request", headers=keys[12])

    assert second.status_code == 429
    assert len(telephony.placed) == 1


def test_one_elders_key_never_dials_another_elders_number():
    client, keys, _, telephony = make()
    client.post("/v1/me/call-request", headers=keys[12])

    assert [to for to, _ in telephony.placed] == ["010-1111-2222"]
