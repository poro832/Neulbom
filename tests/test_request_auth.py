"""수동 전화 요청의 다섯 개의 문 — 순서가 중요하다."""

from __future__ import annotations

import logging
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from app.api.calls import build_app
from app.api.elder_directory import ElderAccess
from app.api.guardian_auth import KeyAuth, generate_key
from app.api.store import InMemoryCallStore
from app.media.stream_server import InMemoryCallRegistry
from app.scheduler import KST
from app.telephony.client import FakeTelephony
from tests.auth_helpers import auth_kit

URL = "/v1/calls/request"


class WallClock:
    def __init__(self, now: float):
        self.now = now

    def __call__(self):
        return self.now


def kst(*args) -> float:
    return datetime(*args, tzinfo=KST).timestamp()


def make(kit=None, *, limit=3, clock=None, use_auth=True, headers=True):
    kit = kit or auth_kit()
    clock = clock or WallClock(kst(2026, 10, 8, 9, 0, 0))
    store = InMemoryCallStore(phones={12: "070-1111-2222", 13: "070-1313-1313"}, wall_clock=clock)
    telephony = FakeTelephony()
    kwargs = {"guardian_auth": kit.auth, "elders": kit.directory} if use_auth else {}
    app = build_app(
        store=store,
        telephony=telephony,
        registry=InMemoryCallRegistry(),
        public_base_url="https://api.example.com",
        stream_base_url="wss://api.example.com",
        manual_calls_per_day=limit,
        wall_clock=clock,
        **kwargs,
    )
    client = TestClient(app, headers=kit.headers if headers else {})
    return client, store, telephony, kit, clock


# ------------------------------------------------ ①② 열쇠


@pytest.mark.parametrize(
    "header",
    [None, "Bearer", "Basic abc", "Bearer nlb_short", "bearer " + "x" * 5000],
)
def test_a_missing_or_malformed_key_is_401_never_500(header):
    client, _, telephony, _, _ = make(headers=False)
    headers = {} if header is None else {"Authorization": header}

    response = client.post(URL, json={"elder_id": 12}, headers=headers)

    assert response.status_code == 401
    assert response.json() == {"detail": "열쇠가 필요합니다"}
    assert telephony.placed == []


def test_a_well_formed_but_unknown_key_is_401():
    client, _, telephony, _, _ = make(headers=False)

    response = client.post(
        URL, json={"elder_id": 12}, headers={"Authorization": f"Bearer {generate_key().key}"}
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "열쇠가 필요합니다"}
    assert telephony.placed == []


def test_key_header_variants_that_are_still_valid_are_accepted():
    client, _, _, kit, _ = make(headers=False)

    lower = client.post(URL, json={"elder_id": 12}, headers={"Authorization": f"bearer  {kit.key} "})

    assert lower.status_code == 202


def test_a_revoked_key_is_refused_from_the_next_request():
    client, store, _, kit, _ = make()
    first = client.post(URL, json={"elder_id": 12})
    assert first.status_code == 202
    store.mark_failed(first.json()["call_id"])
    (info,) = kit.store.list_keys()

    kit.store.revoke(info.key_prefix)

    assert client.post(URL, json={"elder_id": 12}).status_code == 401


def test_a_failed_attempt_logs_only_the_key_prefix(caplog):
    client, _, _, _, _ = make(headers=False)
    wrong = generate_key()

    with caplog.at_level(logging.WARNING, logger="app.api.calls"):
        client.post(URL, json={"elder_id": 12}, headers={"Authorization": f"Bearer {wrong.key}"})

    assert wrong.key_prefix in caplog.text
    assert wrong.key not in caplog.text
    assert wrong.key_hash not in caplog.text


class ExplodingStore:
    def find_guardian(self, key_hash):
        raise RuntimeError("DB 끊김")


def test_a_broken_key_store_is_503_not_401_and_not_open():
    kit = auth_kit()
    kit.auth = KeyAuth(ExplodingStore())
    client, _, telephony, _, _ = make(kit)

    response = client.post(URL, json={"elder_id": 12})

    assert response.status_code == 503
    assert telephony.placed == []


class ExplodingDirectory:
    def get(self, elder_id):
        raise RuntimeError("DB 끊김")


def test_a_broken_elder_lookup_is_503():
    kit = auth_kit()
    kit.directory = ExplodingDirectory()
    client, _, telephony, _, _ = make(kit)

    assert client.post(URL, json={"elder_id": 12}).status_code == 503
    assert telephony.placed == []


# ------------------------------------------------ ③ 소유


def test_someone_elses_elder_is_404_exactly_like_a_missing_one():
    kit = auth_kit(elders={12: ElderAccess(guardian_id=2, consenting=True)})
    client, _, telephony, _, _ = make(kit)

    theirs = client.post(URL, json={"elder_id": 12})
    missing = client.post(URL, json={"elder_id": 999})

    assert theirs.status_code == missing.status_code == 404
    assert theirs.json() == missing.json() == {"detail": "등록되지 않은 어르신입니다"}
    assert telephony.placed == []


def test_someone_elses_elder_without_consent_is_404_not_403():
    """남의 부모님의 동의 여부를 알아내지 못하게, 소유 확인이 동의 확인보다 먼저다."""
    kit = auth_kit(elders={12: ElderAccess(guardian_id=2, consenting=False)})
    client, _, _, _, _ = make(kit)

    assert client.post(URL, json={"elder_id": 12}).status_code == 404


@pytest.mark.parametrize("elder_id", [0, -1, 10**30])
def test_an_out_of_range_elder_id_is_422(elder_id):
    client, _, _, _, _ = make()

    assert client.post(URL, json={"elder_id": elder_id}).status_code == 422


# ------------------------------------------------ ④ 동의


def test_no_consent_is_403():
    kit = auth_kit(elders={12: ElderAccess(guardian_id=1, consenting=False)})
    client, _, telephony, _, _ = make(kit)

    response = client.post(URL, json={"elder_id": 12})

    assert response.status_code == 403
    assert response.json() == {"detail": "어르신의 동의가 없습니다"}
    assert telephony.placed == []


def test_consent_is_checked_before_the_daily_limit():
    kit = auth_kit(elders={12: ElderAccess(guardian_id=1, consenting=False)})
    client, _, _, _, _ = make(kit, limit=0)

    assert client.post(URL, json={"elder_id": 12}).status_code == 403


# ------------------------------------------------ ⑤ 오늘 횟수


def press_and_finish(client, store, elder_id=12):
    response = client.post(URL, json={"elder_id": elder_id})
    if response.status_code == 202:
        store.mark_failed(response.json()["call_id"])
    return response


def test_the_fourth_request_in_a_day_is_429():
    client, store, telephony, _, _ = make()

    codes = [press_and_finish(client, store).status_code for _ in range(4)]

    assert codes == [202, 202, 202, 429]
    assert len(telephony.placed) == 3
    assert client.post(URL, json={"elder_id": 12}).json() == {"detail": "오늘 요청 횟수를 넘었습니다"}


def test_the_limit_resets_at_midnight_korea_time():
    clock = WallClock(kst(2026, 10, 7, 23, 59, 50))
    client, store, _, _, _ = make(clock=clock)
    for _ in range(3):
        assert press_and_finish(client, store).status_code == 202
    assert press_and_finish(client, store).status_code == 429

    clock.now = kst(2026, 10, 8, 0, 0, 10)

    assert press_and_finish(client, store).status_code == 202


def test_a_call_already_in_progress_is_still_409():
    client, _, _, _, _ = make()
    first = client.post(URL, json={"elder_id": 12})
    second = client.post(URL, json={"elder_id": 12})

    assert (first.status_code, second.status_code) == (202, 409)
    assert second.json()["status"] == "in_progress"


def test_the_guardian_who_pressed_the_button_is_recorded():
    client, store, _, kit, _ = make()

    call_id = client.post(URL, json={"elder_id": 12}).json()["call_id"]

    assert store.get(call_id).requested_by == 1
    assert store.get(call_id).trigger_type == "requested"


# ------------------------------------------------ 닫힌 쪽이 기본


def test_without_an_authenticator_the_route_does_not_exist():
    client, _, telephony, _, _ = make(use_auth=False)

    assert client.post(URL, json={"elder_id": 12}).status_code == 404
    assert telephony.placed == []


def test_building_with_auth_but_no_directory_is_a_configuration_error():
    kit = auth_kit()

    with pytest.raises(ValueError):
        build_app(
            store=InMemoryCallStore(phones={}),
            telephony=FakeTelephony(),
            registry=InMemoryCallRegistry(),
            public_base_url="https://x",
            stream_base_url="wss://x",
            guardian_auth=kit.auth,
        )
