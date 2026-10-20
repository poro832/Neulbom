"""한 어르신을 여러 보호자가 함께 본다 — 연결, 권한, 알림, 탈퇴 승인, 보호자가 떠날 때."""

from __future__ import annotations

from app.api.alert_rules import AlertRules
from app.api.alerts import InMemoryAlertStore
from app.api.elder_directory import ElderAccess, InMemoryElderDirectory
from app.api.guardian_auth import generate_key
from app.api.passwords import hash_password
from app.api.invites import hash_invite_code
from tests.app_data_helpers import make_app_kit

PREVIEW = "/v1/guardian/link/preview"
LINK = "/v1/guardian/link"
LINK_CODE = "/v1/me/link-code"
ELDERS = "/v1/guardian/elders"


def add_guardian_key(kit, guardian_id: int) -> dict:
    """보호자 한 명의 열쇠를 심고 머리글을 돌려준다."""
    new = generate_key()
    kit.data.guardian_auth.store.add(
        guardian_id=guardian_id, label="test", key_prefix=new.key_prefix, key_hash=new.key_hash
    )
    return {"Authorization": f"Bearer {new.key}"}


def code_of(kit, elder_id: int = 12) -> str:
    """어르신 한 분의 고정 연결 코드."""
    response = kit.client.get(LINK_CODE, headers=kit.elder_headers(elder_id))
    assert response.status_code == 200, response.text
    return response.json()["code"]


class RecordingNotifier:
    def __init__(self):
        self.linked, self.alerts = [], []

    def notify_linked(self, guardian_id, elder_id):
        self.linked.append((guardian_id, elder_id))

    def notify(self, guardian_id, elder_id):
        self.alerts.append((guardian_id, elder_id))


def kit_with_two_guardians():
    """어르신 12를 보호자 1이 보고 있고, 보호자 2의 열쇠가 있다."""
    kit = make_app_kit()
    # 어르신 12는 가입 때 동의했다(운영자가 등록만 한 어르신은 연결 코드가 없다).
    kit.data.elders._entries[12] = ElderAccess(1, True, "어르신 12", agreed=True)
    second = add_guardian_key(kit, 2)
    return kit, second


# ------------------------------------------------ 연결


def test_a_second_guardian_links_with_the_fixed_code_and_both_see_the_elder():
    kit, second = kit_with_two_guardians()
    code = code_of(kit)

    response = kit.client.post(LINK, json={"code": code}, headers=second)

    assert response.status_code == 200 and response.json()["elder_id"] == 12
    assert kit.data.elders.guardians_of(12) == [1, 2]
    for headers in (kit.guardian_headers, second):
        listed = kit.client.get(ELDERS, headers=headers).json()["elders"]
        mine = next(e for e in listed if e["elder_id"] == 12)
        assert mine["status"] == "active" and mine["guardian_count"] == 2
    # 처음 보호자의 전화 동의와 대표는 그대로다
    access = kit.data.elders.get(12)
    assert access.guardian_id == 1 and access.consenting


def test_preview_tells_how_many_guardians_already_watch_but_not_who():
    kit, second = kit_with_two_guardians()

    response = kit.client.post(PREVIEW, json={"code": code_of(kit)}, headers=second)

    assert response.status_code == 200
    assert response.json() == {"name": "어르신 12", "phone_masked": "070-****-2222", "other_guardians": 1}


def test_the_existing_guardians_are_told_by_push_when_another_links():
    kit, second = kit_with_two_guardians()
    kit.data.notifier = notifier = RecordingNotifier()

    kit.client.post(LINK, json={"code": code_of(kit)}, headers=second)

    assert notifier.linked == [(1, 12)]  # 새로 들어온 보호자 본인에게는 보내지 않는다


def test_the_first_guardian_linking_an_unlinked_elder_sends_no_push():
    kit = make_app_kit()
    kit.data.elders._entries[12] = ElderAccess(1, True, "어르신 12", agreed=True)
    kit.data.notifier = notifier = RecordingNotifier()
    kit.data.elders.detach_all_from(1)  # 어르신 12, 13이 연결 전이 된다
    code = code_of(kit)

    assert kit.client.post(LINK, json={"code": code}, headers=kit.guardian_headers).status_code == 200
    assert notifier.linked == []


def test_a_guardian_who_already_watches_gets_a_clear_answer_not_a_failure_count():
    kit = make_app_kit()
    kit.data.elders._entries[12] = ElderAccess(1, True, "어르신 12", agreed=True)
    code = code_of(kit)

    preview = kit.client.post(PREVIEW, json={"code": code}, headers=kit.guardian_headers)
    link = kit.client.post(LINK, json={"code": code}, headers=kit.guardian_headers)

    assert preview.status_code == 409 and link.status_code == 409
    assert preview.json() == {"detail": "이미 연결된 어르신이에요"}
    assert kit.data.elders.guardians_of(12) == [1]


def test_a_full_elder_refuses_one_more_guardian_and_keeps_the_code():
    kit, second = kit_with_two_guardians()
    code = code_of(kit)
    for guardian_id in (3, 4, 5):
        assert kit.data.elders.link(12, guardian_id) is True
    assert len(kit.data.elders.guardians_of(12)) == 4
    assert kit.data.elders.link(12, 6) is True  # 다섯 번째는 들어간다
    assert len(kit.data.elders.guardians_of(12)) == 5

    preview = kit.client.post(PREVIEW, json={"code": code}, headers=second)
    link = kit.client.post(LINK, json={"code": code}, headers=second)

    assert preview.status_code == 409 and link.status_code == 409
    assert preview.json() == {"detail": "이 어르신은 보호자가 가득 찼어요"}
    assert kit.data.links.find(hash_invite_code(code)) is not None


def test_a_waiting_elder_cannot_be_joined_through_a_code():
    kit, second = kit_with_two_guardians()
    kit.data.elders._entries[13] = ElderAccess(1, False, "어르신 13", agreed=True)

    code = code_of(kit, 13)
    response = kit.client.post(LINK, json={"code": code}, headers=second)

    assert response.status_code == 401
    assert kit.data.elders.guardians_of(13) == [1]


# ------------------------------------------------ 권한

def test_every_guardian_of_the_elder_can_read_and_change_but_a_stranger_cannot():
    kit, second = kit_with_two_guardians()
    stranger = add_guardian_key(kit, 9)
    kit.client.post(LINK, json={"code": code_of(kit)}, headers=second)

    assert kit.client.get("/v1/elders/12/call-time", headers=second).status_code == 200
    assert kit.client.put("/v1/elders/12/call-time", json={"call_time": "07:30"}, headers=second).status_code == 200
    assert kit.client.get("/v1/elders/12/weekly", headers=second).status_code == 200
    phone = kit.client.put("/v1/elders/12/phone", json={"phone": "010-8888-7777"}, headers=second)
    assert phone.status_code == 200
    # 처음 보호자도 바뀐 시각을 본다
    assert kit.client.get("/v1/elders/12/call-time", headers=kit.guardian_headers).json() == {"call_time": "07:30"}

    for path in ("/v1/elders/12/call-time", "/v1/elders/12/weekly", "/v1/elders/12/phone"):
        assert kit.client.get(path, headers=stranger).status_code == 404
    assert kit.client.put("/v1/elders/12/call-time", json={"call_time": "08:00"}, headers=stranger).status_code == 404


def test_the_elder_sees_every_guardian_in_the_contacts():
    kit, second = kit_with_two_guardians()
    kit.client.post(LINK, json={"code": code_of(kit)}, headers=second)

    guardians = kit.client.get("/v1/me/contacts", headers=kit.elder_headers(12)).json()["guardians"]

    assert [g["name"] for g in guardians] == ["보호자1", "보호자2"]


# ------------------------------------------------ 알림

def test_an_alert_goes_to_every_guardian_once_each_and_counts_once():
    directory = InMemoryElderDirectory({12: ElderAccess(1, True, "어르신 12", co_guardians=(2, 3))})
    alerts = InMemoryAlertStore()
    notifier = RecordingNotifier()
    rules = AlertRules(alerts=alerts, elders=directory, notifier=notifier)

    rules.on_risk(call_id=7, elder_id=12, risk_level="alert")
    rules.on_risk(call_id=7, elder_id=12, risk_level="alert")  # 웹훅 재전송

    for guardian_id in (1, 2, 3):
        assert len(alerts.recent_for_guardian(guardian_id, 10)) == 1
    assert sorted(notifier.alerts) == [(1, 12), (2, 12), (3, 12)]
    assert alerts.count_since(12, 0.0) == 1  # 보호자가 셋이어도 알림은 한 건으로 센다


# ------------------------------------------------ 탈퇴 승인

def test_the_elder_leaves_only_when_every_guardian_approves():
    kit, second = kit_with_two_guardians()
    kit.client.post(LINK, json={"code": code_of(kit)}, headers=second)
    elder = kit.elder_headers(12)
    assert kit.client.post("/v1/me/withdrawal", json={"confirm": True}, headers=elder).status_code == 202
    request_id = kit.data.withdrawals.get(12).request_id

    first = kit.client.post(
        "/v1/elders/12/withdrawal/approve", json={"request_id": request_id}, headers=kit.guardian_headers
    )
    assert first.status_code == 200 and first.json()["status"] == "waiting"
    assert kit.data.elders.get(12) is not None

    last = kit.client.post(
        "/v1/elders/12/withdrawal/approve", json={"request_id": request_id}, headers=second
    )
    assert last.status_code == 200 and last.json() == {"status": "deleted"}
    assert kit.data.elders.get(12) is None


def test_every_guardian_gets_the_withdrawal_push():
    kit, second = kit_with_two_guardians()
    kit.client.post(LINK, json={"code": code_of(kit)}, headers=second)
    pushed = []

    class Spy:
        def notify_withdrawal(self, guardian_id, elder_id):
            pushed.append((guardian_id, elder_id))

    kit.data.notifier = Spy()
    kit.client.post("/v1/me/withdrawal", json={"confirm": True}, headers=kit.elder_headers(12))

    assert sorted(pushed) == [(1, 12), (2, 12)]


# ------------------------------------------------ 보호자가 떠날 때

PASSWORD = "correct-horse-1"


def leave(kit, headers):
    return kit.client.request("DELETE", "/v1/guardian/me", json={"password": PASSWORD}, headers=headers)


def kit_with_two_accounts():
    kit, second = kit_with_two_guardians()
    for name, email in (("보호자1", "a@example.com"), ("보호자2", "b@example.com")):
        kit.data.accounts.create(name, email, "010-0000-0001", hash_password(PASSWORD), activated=True)
    return kit, second


def test_one_guardian_deleting_the_account_leaves_the_elder_with_the_others():
    kit, second = kit_with_two_accounts()
    kit.client.post(LINK, json={"code": code_of(kit)}, headers=second)

    response = leave(kit, second)

    assert response.status_code in (200, 204), response.text
    access = kit.data.elders.get(12)
    assert access.guardian_ids == (1,) and access.consenting and access.status == "active"
    assert kit.client.get("/v1/elders/12/call-time", headers=kit.guardian_headers).status_code == 200


def test_the_last_guardian_deleting_the_account_unlinks_the_elder():
    kit, second = kit_with_two_accounts()
    kit.client.post(LINK, json={"code": code_of(kit)}, headers=second)
    leave(kit, second)

    response = leave(kit, kit.guardian_headers)

    assert response.status_code in (200, 204), response.text
    access = kit.data.elders.get(12)
    assert access.status == "unlinked" and not access.consenting
