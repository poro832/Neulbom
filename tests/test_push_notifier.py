import logging

from app.api.devices import InMemoryDeviceStore
from app.api.elder_directory import ElderAccess, InMemoryElderDirectory
from app.push import FAILED, INVALID_TOKEN, SENT, PushNotifier

T1, T2, T3 = "token-aaaaaaaaaaaaaaaaaaaa", "token-bbbbbbbbbbbbbbbbbbbb", "token-cccccccccccccccccccc"


class FakeSender:
    def __init__(self, results=None, raises=()):
        self.results = results or {}
        self.raises = set(raises)
        self.sent = []

    def send(self, token, title, body, data):
        self.sent.append((token, title, body, data))
        if token in self.raises:
            raise RuntimeError("boom")
        return self.results.get(token, SENT)


def run_now(job):
    job()


def make(sender, tokens=(T1, T2), name="김할머니"):
    devices = InMemoryDeviceStore()
    for t in tokens:
        devices.register(1, "k", t)
    elders = InMemoryElderDirectory({12: ElderAccess(1, True, name)})
    return PushNotifier(devices=devices, elders=elders, sender=sender, spawn=run_now), devices


def test_every_phone_of_the_guardian_gets_a_neutral_push():
    sender = FakeSender()
    notifier, _ = make(sender)
    notifier.notify(1, 12)
    assert [s[0] for s in sender.sent] == [T1, T2]
    token, title, body, data = sender.sent[0]
    assert (title, body, data) == ("늘봄", "김할머니 어르신 확인이 필요해요", {"elder_id": "12"})


def test_a_missing_name_still_reads_naturally():
    sender = FakeSender()
    notifier, _ = make(sender, name="")
    notifier.notify(1, 12)
    assert sender.sent[0][2] == "어르신 확인이 필요해요"


def test_an_invalid_token_is_removed_and_others_still_get_the_push():
    sender = FakeSender(results={T1: INVALID_TOKEN})
    notifier, devices = make(sender)
    notifier.notify(1, 12)
    assert [s[0] for s in sender.sent] == [T1, T2]
    assert devices.tokens_for(1) == [T2]


def test_a_failed_send_keeps_the_token():
    sender = FakeSender(results={T1: FAILED})
    notifier, devices = make(sender)
    notifier.notify(1, 12)
    assert sorted(devices.tokens_for(1)) == sorted([T1, T2])


def test_one_phone_raising_does_not_stop_the_rest_and_nothing_escapes(caplog):
    sender = FakeSender(raises={T1})
    notifier, _ = make(sender)
    with caplog.at_level(logging.INFO):
        notifier.notify(1, 12)
    assert [s[0] for s in sender.sent] == [T1, T2]
    assert T1 not in caplog.text and "김할머니" not in caplog.text


def test_without_a_sender_nothing_happens_and_nothing_is_spawned():
    spawned = []
    devices = InMemoryDeviceStore()
    devices.register(1, "k", T1)
    elders = InMemoryElderDirectory({12: ElderAccess(1, True, "김할머니")})
    notifier = PushNotifier(devices=devices, elders=elders, sender=None, spawn=spawned.append)
    notifier.notify(1, 12)
    assert spawned == []


def test_store_errors_are_swallowed(caplog):
    class BrokenDevices:
        def tokens_for(self, guardian_id):
            raise RuntimeError("db down")

        def remove_token(self, token):
            raise RuntimeError("db down")

    elders = InMemoryElderDirectory({12: ElderAccess(1, True, "김할머니")})
    notifier = PushNotifier(devices=BrokenDevices(), elders=elders, sender=FakeSender(), spawn=run_now)
    notifier.notify(1, 12)  # 예외 없이 끝나야 한다


def test_a_withdrawal_request_push_says_approval_is_needed():
    sender = FakeSender()
    notifier, _ = make(sender)

    notifier.notify_withdrawal(1, 12)

    assert [s[0] for s in sender.sent] == [T1, T2]
    _, title, body, data = sender.sent[0]
    assert (title, body, data) == ("늘봄", "김할머니 어르신 탈퇴를 요청했어요. 승인이 필요해요", {"elder_id": "12"})


def test_a_withdrawal_request_push_without_a_name_and_without_a_sender():
    sender = FakeSender()
    notifier, _ = make(sender, name="")
    notifier.notify_withdrawal(1, 12)
    assert sender.sent[0][2] == "어르신 탈퇴를 요청했어요. 승인이 필요해요"

    spawned = []
    off = PushNotifier(devices=InMemoryDeviceStore(), elders=InMemoryElderDirectory({}), sender=None, spawn=spawned.append)
    off.notify_withdrawal(1, 12)
    assert spawned == []
