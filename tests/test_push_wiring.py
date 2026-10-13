"""조립: 알림 규칙이 푸시 발송기에 이어져 있다 (설계: 푸시 알림)."""

from __future__ import annotations

import time

from app.api.elder_directory import ElderAccess, InMemoryElderDirectory
from app.api.guardian_auth import InMemoryGuardianKeyStore, KeyAuth, generate_key
from app.main import app_data_for
from app.push import SENT


class FakeSender:
    def __init__(self):
        self.sent = []

    def send(self, token, title, body, data):
        self.sent.append((token, title, body, data))
        return SENT


def wait_for(predicate, seconds=2.0):
    end = time.time() + seconds
    while time.time() < end:
        if predicate():
            return True
        time.sleep(0.02)
    return predicate()


def _world(sender):
    keys = InMemoryGuardianKeyStore()
    new = generate_key()
    keys.add(guardian_id=1, label="t", key_prefix=new.key_prefix, key_hash=new.key_hash)
    elders = InMemoryElderDirectory({12: ElderAccess(1, True, "김할머니")})
    data, rules = app_data_for(None, guardian_auth=KeyAuth(keys), elders=elders, push_sender=sender)
    return data, rules, new, keys


def test_a_new_alert_pushes_to_the_registered_phone():
    sender = FakeSender()
    data, rules, new, _ = _world(sender)
    data.devices.register(1, new.key_hash, "token-aaaaaaaaaaaaaaaaaaaa")

    rules.on_risk(call_id=1, elder_id=12, risk_level="alert")

    assert wait_for(lambda: len(sender.sent) == 1)
    token, title, body, payload = sender.sent[0]
    assert (token, title, body, payload) == (
        "token-aaaaaaaaaaaaaaaaaaaa", "늘봄", "김할머니 어르신 확인이 필요해요", {"elder_id": "12"},
    )


def test_a_revoked_key_gets_no_push():
    sender = FakeSender()
    data, rules, new, keys = _world(sender)
    data.devices.register(1, new.key_hash, "token-aaaaaaaaaaaaaaaaaaaa")
    keys.revoke_hash(new.key_hash)

    rules.on_risk(call_id=1, elder_id=12, risk_level="alert")

    time.sleep(0.2)
    assert sender.sent == []


def test_without_a_sender_alerts_still_work_and_nothing_is_pushed():
    data, rules, new, _ = _world(None)
    data.devices.register(1, new.key_hash, "token-aaaaaaaaaaaaaaaaaaaa")
    rules.on_risk(call_id=1, elder_id=12, risk_level="alert")  # 예외 없이 끝나야 한다
