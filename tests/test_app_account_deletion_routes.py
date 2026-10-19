"""탈퇴 — 보호자(DELETE /v1/guardian/me)와 어르신(DELETE /v1/me) (설계: 탈퇴·내 정보 삭제).

보호자가 탈퇴해도 어르신은 지우지 않는다(연결 전으로 돌린다). 어르신이 탈퇴하면 녹음(S3)을 최선으로 지우고
어르신과 그 통화·언급·연락처·열쇠를 지운다. 저장소는 모두 메모리다 — Postgres의 CASCADE는
tests/test_account_deletion_postgres.py가 실제로 확인한다.
"""

from __future__ import annotations

import logging

import pytest

from app.api.call_content import Mention
from app.api.elder_directory import ElderAccess
from app.api.guardian_auth import generate_key, hash_key, parse_bearer
from app.api.invites import hash_invite_code
from app.api.pairing import hash_code, new_code
from app.api.passwords import hash_password
from app.archiver import MARKER_SUFFIX
from tests.app_data_helpers import kst, make_app_kit

ME = "/v1/guardian/me"
LOGIN = "/v1/guardian/login"
EMAIL = "kim@example.com"
PASSWORD = "correct-horse-1"
BAD_PASSWORD = {"detail": "비밀번호를 확인해 주세요"}
NEED_KEY = {"detail": "열쇠가 필요합니다"}
TOKEN = "token-aaaaaaaaaaaaaaaaaaaa"


def bearer(key):
    return {"Authorization": f"Bearer {key}"}


def add_guardian_key(kit, guardian_id):
    new = generate_key()
    kit.data.guardian_auth.store.add(
        guardian_id=guardian_id, label="t", key_prefix=new.key_prefix, key_hash=new.key_hash
    )
    return bearer(new.key)


class GuardianWorld:
    def __init__(self):
        """보호자 1(어르신 12·13 — 계정·열쇠·폰·개인 코드·알림)과 보호자 2(어르신 14)."""
        kit = make_app_kit()
        self.kit = kit
        assert kit.data.accounts.create("보호자1", EMAIL, "010-0000-0001", hash_password(PASSWORD), activated=True) == 1
        assert kit.data.accounts.create(
            "보호자2", "lee@example.com", "010-0000-0002", hash_password("other-pass-2"), activated=True
        ) == 2
        self.other = add_guardian_key(kit, 2)
        kit.reports.add_call(call_id=1, elder_id=12, status="completed", created_at=kst(2026, 10, 5, 9), score=10)
        kit.reports.add_call(call_id=2, elder_id=14, status="completed", created_at=kst(2026, 10, 5, 9), score=20)
        kit.data.contacts.add(12, name="이웃 김씨", relation="이웃", phone="010-2222-3333")
        self.code = kit.issue_invite(1)
        self.other_code = kit.issue_invite(2)
        kit.data.devices.register(1, hash_key(parse_bearer(kit.guardian_headers["Authorization"])), TOKEN)
        for elder_id, guardian_id in ((12, 1), (14, 2)):
            kit.alerts.raise_alert(
                elder_id=elder_id, guardian_id=guardian_id, call_id=None,
                alert_type="no_answer", severity="info", message="오늘 안부 전화를 받지 못하셨어요.",
            )

    def withdraw(self, password=PASSWORD, headers=None):
        return self.kit.client.request(
            "DELETE", ME, json={"password": password}, headers=headers or self.kit.guardian_headers
        )

    def login(self, password=PASSWORD):
        return self.kit.client.post(LOGIN, json={"email": EMAIL, "password": password})


# ------------------------------------------------ 보호자 탈퇴: 거절


def test_a_wrong_password_is_401_and_nothing_changes():
    w = GuardianWorld()

    r = w.withdraw(password="wrong-password")

    assert r.status_code == 401 and r.json() == BAD_PASSWORD
    assert w.kit.data.accounts.profile(1) is not None
    assert w.kit.data.elders.get(12) == ElderAccess(1, True, "어르신 12")
    assert w.kit.client.get("/v1/guardian/elders", headers=w.kit.guardian_headers).status_code == 200
    assert w.kit.data.devices.tokens_for(1) == [TOKEN]


def test_repeated_wrong_passwords_lock_the_email_even_for_the_right_one():
    w = GuardianWorld()
    for _ in range(5):
        assert w.withdraw(password="wrong-password").status_code == 401

    r = w.withdraw()

    assert r.status_code == 429 and r.json() == {"detail": "잠시 뒤에 다시 해 주세요"}
    assert w.kit.data.accounts.profile(1) is not None
    assert w.kit.data.elders.get(12).guardian_id == 1
    assert w.login().status_code == 429  # 로그인과 같은 이메일 한도다


def test_withdrawal_needs_a_key_and_a_password_of_sane_length():
    w = GuardianWorld()
    no_key = w.kit.client.request("DELETE", ME, json={"password": PASSWORD})
    assert no_key.status_code == 401
    assert w.withdraw(password="").status_code == 422
    assert w.withdraw(password="x" * 129).status_code == 422
    assert w.kit.client.request("DELETE", ME, headers=w.kit.guardian_headers).status_code == 422
    assert w.withdraw(headers=w.kit.elder_headers(12)).status_code == 401  # 어르신 열쇠로는 안 된다
    assert w.kit.data.accounts.profile(1) is not None


def test_a_key_only_guardian_has_no_account_to_delete():
    kit = make_app_kit()  # 보호자 1은 열쇠만 있고 계정 표에 없다

    r = kit.client.request("DELETE", ME, json={"password": PASSWORD}, headers=kit.guardian_headers)

    assert r.status_code == 404 and r.json() == {"detail": "삭제할 계정이 없어요"}
    assert kit.data.elders.get(12).guardian_id == 1
    assert kit.client.get("/v1/guardian/elders", headers=kit.guardian_headers).status_code == 200


def test_a_password_changed_while_checking_stops_the_withdrawal(monkeypatch):
    """검사한 뒤 잠금 안에서 다시 본다 — 그 사이 재설정·다른 폰의 변경이 있었으면 아무것도 지우지 않는다."""
    from app.api import app_data

    w = GuardianWorld()
    real = app_data.verify_password

    def verify_then_reset(password, stored):
        ok = real(password, stored)
        w.kit.data.accounts.set_password(1, app_data.hash_password("reset-by-owner-9"))
        return ok

    monkeypatch.setattr(app_data, "verify_password", verify_then_reset)

    r = w.withdraw()

    assert r.status_code == 401 and r.json() == NEED_KEY
    assert w.kit.data.accounts.profile(1) is not None
    assert w.kit.data.elders.get(12).guardian_id == 1
    assert w.kit.data.devices.tokens_for(1) == [TOKEN]


# ------------------------------------------------ 보호자 탈퇴: 성공


def test_withdrawing_removes_the_account_and_signs_out_every_phone():
    w = GuardianWorld()
    second_phone = bearer(w.login().json()["key"])

    r = w.withdraw()

    assert r.status_code == 204 and r.content == b""
    assert w.kit.data.accounts.profile(1) is None
    assert w.login().status_code == 401
    for headers in (w.kit.guardian_headers, second_phone):
        assert w.kit.client.get("/v1/guardian/elders", headers=headers).status_code == 401
        assert w.kit.client.get(ME, headers=headers).status_code == 401
    active = [k for k in w.kit.data.guardian_auth.store.list_keys() if k.guardian_id == 1 and k.revoked_at is None]
    assert active == []


def test_the_guardians_elders_are_unlinked_and_keep_their_data():
    w = GuardianWorld()

    assert w.withdraw().status_code == 204

    for elder_id, name in ((12, "어르신 12"), (13, "어르신 13")):
        access = w.kit.data.elders.get(elder_id)
        assert access is not None and access.name == name
        assert access.status == "unlinked" and access.consenting is False  # 안부 전화 대상이 아니다
    assert w.kit.data.elders.phone_of(12) == "070-1111-2222"
    assert [line.call_id for line in w.kit.reports.call_lines(12, 10)] == [1]
    assert [c.name for c in w.kit.data.contacts.list(12)] == ["이웃 김씨"]
    # 어르신 폰의 열쇠는 그대로다 — 앱이 연결 전 상태를 보고 새 연결 코드를 만들 수 있다
    status = w.kit.client.get("/v1/me/status", headers=w.kit.elder_headers(12))
    assert status.status_code == 200 and status.json()["status"] == "unlinked"


def test_other_guardians_and_their_elders_are_untouched():
    w = GuardianWorld()

    assert w.withdraw().status_code == 204

    assert w.kit.data.elders.get(14) == ElderAccess(2, True, "어르신 14")
    listed = w.kit.client.get("/v1/guardian/elders", headers=w.other).json()["elders"]
    assert [(e["elder_id"], e["status"]) for e in listed] == [(14, "active")]
    assert w.kit.data.accounts.profile(2).email == "lee@example.com"
    assert [line.call_id for line in w.kit.reports.call_lines(14, 10)] == [2]
    assert [a.elder_id for a in w.kit.alerts.recent_for_guardian(2, 10)] == [14]
    assert w.kit.data.invites.find_guardian(hash_invite_code(w.other_code)) == 2


def test_the_personal_code_the_phones_and_the_alerts_go_with_the_account():
    w = GuardianWorld()

    assert w.withdraw().status_code == 204

    assert w.kit.data.invites.find_guardian(hash_invite_code(w.code)) is None
    assert w.kit.data.devices.tokens_for(1) == []
    assert w.kit.data.devices.unregister(1, TOKEN) is False  # 등록 행이 없다
    assert w.kit.alerts.recent_for_guardian(1, 10) == []
    signup = w.kit.client.post(
        "/v1/signup", json={"code": w.code, "name": "가", "phone": "010-5555-1111", "agreed": True}
    )
    assert signup.status_code == 401  # 그 코드로는 더 이상 가입할 수 없다


def test_pairing_codes_the_guardian_issued_stop_working_after_withdrawal():
    """탈퇴 전에 내준 연결 코드(6자리)로 어르신 폰을 잇지 못한다 — 남은 코드를 가진 사람이 어르신 열쇠를 받지 못하게."""
    w = GuardianWorld()
    mine = w.kit.client.post("/v1/elders/12/pairing-code", headers=w.kit.guardian_headers).json()["code"]
    theirs = w.kit.client.post("/v1/elders/14/pairing-code", headers=w.other).json()["code"]

    assert w.withdraw().status_code == 204

    voided = w.kit.client.post("/v1/pair", json={"code": mine, "phone": "070-1111-2222"})
    assert voided.status_code == 401 and voided.json() == {"detail": "연결 코드를 확인해 주세요"}
    # 다른 보호자가 내준 코드는 그대로다
    assert w.kit.client.post("/v1/pair", json={"code": theirs, "phone": "070-5555-6666"}).status_code == 200


def test_the_same_email_can_sign_up_again_as_a_fresh_account():
    w = GuardianWorld()
    assert w.withdraw().status_code == 204

    r = w.kit.client.post(
        "/v1/guardian/signup",
        json={"name": "김보호", "email": EMAIL, "phone": "010-0000-0001", "password": "brand-new-pass-2"},
    )

    assert r.status_code == 200
    elders = w.kit.client.get("/v1/guardian/elders", headers=bearer(r.json()["key"])).json()["elders"]
    assert elders == []  # 옛 어르신은 새 계정에 다시 붙지 않는다


def test_an_unlinked_elder_who_agreed_can_be_taken_over_with_a_new_link_code():
    w = GuardianWorld()
    signed = w.kit.client.post(
        "/v1/elders/signup", json={"name": "홍길동", "phone": "010-7777-8888", "agreed": True}
    ).json()
    elder = bearer(signed["elder_key"])
    code = w.kit.client.post("/v1/me/link-code", headers=elder).json()["code"]
    assert w.kit.client.post("/v1/guardian/link", json={"code": code}, headers=w.kit.guardian_headers).status_code == 200

    assert w.withdraw().status_code == 204

    assert w.kit.client.get("/v1/me/status", headers=elder).json()["status"] == "unlinked"
    again = w.kit.client.post("/v1/me/link-code", headers=elder).json()["code"]
    taken = w.kit.client.post("/v1/guardian/link", json={"code": again}, headers=w.other)
    assert taken.status_code == 200 and taken.json()["status"] == "active"


def test_the_steps_run_in_order_and_the_elders_are_unlinked_before_the_account_goes():
    w = GuardianWorld()
    order = []
    data = w.kit.data

    def spy(store, name):
        real = getattr(store, name)

        def wrapper(*args, **kwargs):
            order.append(name if name != "remove_for_guardian" else type(store).__name__)
            return real(*args, **kwargs)

        setattr(store, name, wrapper)

    spy(data.elders, "detach_all_from")
    spy(data.guardian_auth.store, "revoke_all")
    spy(data.devices, "remove_for_guardian")
    spy(data.invites, "remove_for_guardian")
    spy(data.accounts, "delete")

    assert w.withdraw().status_code == 204

    assert order == ["detach_all_from", "revoke_all", "InMemoryDeviceStore", "InMemoryInviteStore", "delete"]


def test_an_elder_attached_at_the_last_moment_is_unlinked_too_never_deleted():
    """Postgres는 어르신이 남아 있으면 계정을 지우지 않는다(CASCADE가 어르신을 지우지 않게). 그때 한 번 더 풀고 지운다."""
    w = GuardianWorld()
    data = w.kit.data
    real_delete = data.accounts.delete
    late = {}

    def refuse_once(guardian_id):
        if not late:
            late["id"] = data.elders.create_pending(
                guardian_id=1, name="늦게 온 어르신", phone="010-4444-5555", max_pending=5
            )
            late["code"] = new_code()
            data.pairings.issue(late["id"], hash_code(late["code"]))
            return False
        return real_delete(guardian_id)

    data.accounts.delete = refuse_once

    assert w.withdraw().status_code == 204

    assert data.accounts.profile(1) is None
    access = data.elders.get(late["id"])
    assert access is not None and access.status == "unlinked"
    # 다시 푼 어르신의 안 쓴 연결 코드도 지워졌다
    paired = w.kit.client.post("/v1/pair", json={"code": late["code"], "phone": "010-4444-5555"})
    assert paired.status_code == 401


def test_an_account_that_still_cannot_be_deleted_is_a_503_not_a_success():
    w = GuardianWorld()
    w.kit.data.accounts.delete = lambda guardian_id: False

    r = w.withdraw()

    assert r.status_code == 503
    assert w.kit.data.accounts.profile(1) is not None
    assert w.kit.data.elders.get(12).status == "unlinked"  # 어르신은 지워지지 않았다


def test_the_guardian_withdrawal_log_has_numbers_only(caplog):
    w = GuardianWorld()
    stored = w.kit.data.accounts.profile(1).password_hash

    with caplog.at_level(logging.DEBUG):
        w.withdraw(password="wrong-password")
        assert w.withdraw().status_code == 204

    assert "보호자가 탈퇴했다 guardian_id=1 어르신 연결 해제=2" in caplog.text
    for secret in (EMAIL, PASSWORD, "wrong-password", stored, "보호자1", "010-0000-0001", "어르신 12"):
        assert secret not in caplog.text, secret


# ------------------------------------------------ 어르신 탈퇴


class FakeDeleter:
    def __init__(self, *, failed=0, explode=False):
        self.failed = failed
        self.explode = explode
        self.calls: list[list[str]] = []

    def delete_many(self, keys):
        self.calls.append(list(keys))
        if self.explode:
            raise RuntimeError("S3 거부 12-20261005T090000Z-a.wav")
        return self.failed


A = "12-20261005T090000Z-a.wav"
B = "12-20261006T090000Z-b.wav"
C = "13-20261005T090000Z-c.wav"


class ElderWorld:
    def __init__(self, deleter=None):
        """어르신 12(통화 1·2, 녹음 A·B, 연락처, 언급, 알림)와 어르신 13(통화 3, 녹음 C, 연락처). 보호자는 1."""
        kit = make_app_kit()
        self.kit = kit
        self.deleter = deleter
        kit.data.recording_deleter = deleter
        content = kit.data.content
        for call_id, elder_id in ((1, 12), (2, 12), (3, 13)):
            kit.reports.add_call(
                call_id=call_id, elder_id=elder_id, status="completed",
                created_at=kst(2026, 10, 5, 8 + call_id), score=10, duration_ms=60_000,
            )
            content.set_owner(call_id, elder_id)
            content.save_turns(call_id, [("ai", "안녕하세요"), ("elder", "허리가 아파요")])
            content.save_summary(call_id, "허리가 아프다고 하셨어요.", "m")
            content.save_mentions(call_id, [Mention("body", "bad", "허리가 아파요")], "m")
        content.agree_share(12)
        content.agree_share(13)
        for elder_id, key in ((12, A), (12, B), (13, C)):
            kit.data.elders.add_audio_key(elder_id, key)
        kit.data.contacts.add(12, name="이웃 김씨", relation="이웃", phone="010-2222-3333")
        kit.data.contacts.add(13, name="딸", relation="가족", phone="010-4444-5555")
        kit.alerts.raise_alert(
            elder_id=12, guardian_id=1, call_id=1, alert_type="risk_rise", severity="warning", message="m"
        )
        self.headers = kit.elder_headers(12)
        self.other_headers = kit.elder_headers(13)

    def withdraw(self, body=None, headers=None):
        return self.kit.client.request(
            "DELETE", "/v1/me", json={"confirm": True} if body is None else body, headers=headers or self.headers
        )


def test_withdrawing_deletes_the_elder_and_the_key_stops_working():
    w = ElderWorld(FakeDeleter())

    r = w.withdraw()

    assert r.status_code == 204 and r.content == b""
    assert w.kit.data.elders.get(12) is None
    assert w.kit.client.get("/v1/me/status", headers=w.headers).status_code == 401
    assert w.withdraw().status_code == 401  # 이미 지워진 어르신의 열쇠는 그대로 401이다


def test_the_calls_mentions_contacts_and_alerts_are_gone():
    w = ElderWorld(FakeDeleter())

    assert w.withdraw().status_code == 204

    content = w.kit.data.content
    assert w.kit.reports.call_lines(12, 100) == []
    assert content.mentions([1, 2]) == {} and content.summaries([1, 2]) == {}
    assert content.turns(1) == [] and content.turns(2) == []
    assert content.share_agreed(12) is False
    assert w.kit.data.contacts.list(12) == []
    assert w.kit.alerts.count_since(12, 0) == 0
    assert w.kit.data.elders.audio_keys_of(12) == []
    listed = w.kit.client.get("/v1/guardian/elders", headers=w.kit.guardian_headers).json()["elders"]
    assert [e["elder_id"] for e in listed] == [13]
    assert w.kit.client.get("/v1/elders/12/calls", headers=w.kit.guardian_headers).status_code == 404


def test_other_elders_are_untouched():
    w = ElderWorld(FakeDeleter())

    assert w.withdraw().status_code == 204

    content = w.kit.data.content
    assert [line.call_id for line in w.kit.reports.call_lines(13, 100)] == [3]
    assert content.mentions([3]) == {3: [Mention("body", "bad", "허리가 아파요")]}
    assert len(content.turns(3)) == 2 and content.share_agreed(13) is True
    assert [c.name for c in w.kit.data.contacts.list(13)] == ["딸"]
    assert w.kit.data.elders.audio_keys_of(13) == [C]
    assert w.kit.client.get("/v1/me/status", headers=w.other_headers).json()["status"] == "active"
    assert w.kit.data.elders.get(14) == ElderAccess(2, True, "어르신 14")


def test_the_same_number_can_sign_up_again_as_a_new_elder():
    w = ElderWorld(FakeDeleter())
    assert w.withdraw().status_code == 204

    r = w.kit.client.post("/v1/elders/signup", json={"name": "어르신 12", "phone": "070-1111-2222", "agreed": True})

    assert r.status_code == 200
    again = w.kit.data.elders.find_by_phone("070-1111-2222")
    assert again is not None and again != 12  # 새 번호 — 옛 기록이 붙지 않는다
    assert w.kit.data.contacts.list(again) == [] and w.kit.reports.call_lines(again, 10) == []


def test_the_deleter_gets_exactly_that_elders_recording_keys():
    deleter = FakeDeleter()
    w = ElderWorld(deleter)

    assert w.withdraw().status_code == 204

    assert deleter.calls == [[A, B]]


@pytest.mark.parametrize("deleter", [FakeDeleter(failed=2), FakeDeleter(explode=True)], ids=["refused", "exploded"])
def test_a_deleter_failure_or_error_never_stops_the_deletion(deleter, caplog):
    w = ElderWorld(deleter)

    with caplog.at_level(logging.DEBUG):
        r = w.withdraw()

    assert r.status_code == 204
    assert w.kit.data.elders.get(12) is None and w.kit.data.contacts.list(12) == []
    assert "어르신이 탈퇴했다 elder_id=12 녹음=2개 삭제시도 실패=2" in caplog.text
    assert "20261005T090000Z" not in caplog.text and "20261006T090000Z" not in caplog.text  # 키는 남기지 않는다


def test_without_a_deleter_the_elder_is_still_deleted(caplog):
    w = ElderWorld(deleter=None)

    with caplog.at_level(logging.DEBUG):
        assert w.withdraw().status_code == 204

    assert w.kit.data.elders.get(12) is None
    assert "어르신이 탈퇴했다 elder_id=12 녹음=2개 삭제시도 실패=2" in caplog.text
    assert "RECORDINGS_BUCKET" in caplog.text  # 왜 지우지 않았는지 남긴다


def test_an_elder_with_no_recordings_does_not_call_the_deleter(caplog):
    deleter = FakeDeleter()
    w = ElderWorld(deleter)
    signed = w.kit.client.post(
        "/v1/elders/signup", json={"name": "홍길동", "phone": "010-7777-8888", "agreed": True}
    ).json()

    with caplog.at_level(logging.DEBUG):
        r = w.withdraw(headers=bearer(signed["elder_key"]))  # 연결 전 어르신도 탈퇴할 수 있다

    assert r.status_code == 204
    assert deleter.calls == []
    assert "녹음=0개 삭제시도 실패=0" in caplog.text


def test_the_recordings_still_on_the_server_disk_are_removed_too(tmp_path, caplog):
    """보관기는 올린 뒤 24시간(못 올렸으면 30일) 로컬에 둔다. 남겨 두면 안 올린 녹음이 탈퇴 뒤에 S3로 올라간다."""
    deleter = FakeDeleter()
    w = ElderWorld(deleter)
    folder = tmp_path / "recordings"
    folder.mkdir()
    w.kit.data.recordings_dir = folder
    for name in (A, A + MARKER_SUFFIX, B, C, C + MARKER_SUFFIX):  # B는 아직 못 올렸다(표시 없음)
        (folder / name).write_bytes(b"RIFF")

    with caplog.at_level(logging.DEBUG):
        assert w.withdraw().status_code == 204

    assert not (folder / A).exists() and not (folder / (A + MARKER_SUFFIX)).exists() and not (folder / B).exists()
    assert (folder / C).exists() and (folder / (C + MARKER_SUFFIX)).exists()  # 다른 어르신의 녹음은 그대로다
    assert "서버 파일 삭제=2개" in caplog.text
    assert A not in caplog.text and B not in caplog.text


def test_a_recording_key_that_is_not_a_plain_file_name_never_touches_other_paths(tmp_path):
    w = ElderWorld(FakeDeleter())
    folder = tmp_path / "recordings"
    (folder / "sub").mkdir(parents=True)
    w.kit.data.recordings_dir = folder
    outside = tmp_path / "outside.wav"
    nested = folder / "sub" / "x.wav"
    for path in (outside, nested):
        path.write_bytes(b"RIFF")
    for key in ("../outside.wav", "sub/x.wav", "..", "."):
        w.kit.data.elders.add_audio_key(12, key)

    assert w.withdraw().status_code == 204

    assert outside.exists() and nested.exists() and folder.is_dir()
    assert w.kit.data.elders.get(12) is None


def test_a_local_file_that_cannot_be_removed_never_stops_the_deletion(tmp_path, monkeypatch, caplog):
    from pathlib import Path

    w = ElderWorld(FakeDeleter())
    folder = tmp_path / "recordings"
    folder.mkdir()
    w.kit.data.recordings_dir = folder
    (folder / A).write_bytes(b"RIFF")
    real_unlink = Path.unlink

    def refuse(self, *args, **kwargs):
        if self.name == A:
            raise PermissionError(f"거부 {self}")
        return real_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", refuse)

    with caplog.at_level(logging.DEBUG):
        assert w.withdraw().status_code == 204

    assert w.kit.data.elders.get(12) is None
    assert A not in caplog.text  # 파일 이름(키)은 로그에 남기지 않는다


@pytest.mark.parametrize(
    "body", [{"confirm": False}, {}, {"confirm": "true"}, {"confirm": 1}, {"confirm": None}],
    ids=["false", "missing", "string", "one", "null"],
)
def test_anything_but_confirm_true_is_refused(body):
    deleter = FakeDeleter()
    w = ElderWorld(deleter)

    r = w.withdraw(body=body)

    assert r.status_code == 422
    assert w.kit.data.elders.get(12) is not None and deleter.calls == []
    assert w.kit.client.get("/v1/me/status", headers=w.headers).status_code == 200


def test_a_missing_body_is_refused():
    w = ElderWorld(FakeDeleter())

    assert w.kit.client.request("DELETE", "/v1/me", headers=w.headers).status_code == 422
    assert w.kit.data.elders.get(12) is not None


def test_withdrawal_needs_an_elder_key():
    w = ElderWorld(FakeDeleter())

    assert w.kit.client.request("DELETE", "/v1/me", json={"confirm": True}).status_code == 401
    assert w.withdraw(headers=w.kit.guardian_headers).status_code == 401  # 보호자 열쇠로는 안 된다
    assert w.kit.data.elders.get(12) is not None


def test_the_elder_withdrawal_log_has_numbers_only(caplog):
    w = ElderWorld(FakeDeleter())

    with caplog.at_level(logging.DEBUG):
        assert w.withdraw().status_code == 204

    assert "어르신이 탈퇴했다 elder_id=12 녹음=2개 삭제시도 실패=0" in caplog.text
    for secret in ("어르신 12", "070-1111-2222", "이웃 김씨", "010-2222-3333", "허리가 아파요", A, B):
        assert secret not in caplog.text, secret
