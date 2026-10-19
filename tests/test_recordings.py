"""녹음 삭제기 — 탈퇴한 어르신의 녹음을 S3에서 지운다.

네트워크를 타지 않는다. S3 클라이언트는 가짜를 주입한다(boto3를 부르는 경로도 가짜 모듈로 바꿔 끼운다).
"""

from __future__ import annotations

import logging
import sys
import types

from app.recordings import MAX_KEYS_PER_REQUEST, S3RecordingDeleter, recording_deleter_from_env


class FakeS3:
    """delete_objects만 흉내 낸다. fail_keys는 S3가 거절하는 키, explode_on은 요청 자체가 터지는 몇 번째 호출(1부터)."""

    def __init__(self, fail_keys=(), explode_on=()):
        self.fail_keys = set(fail_keys)
        self.explode_on = set(explode_on)
        self.calls: list[dict] = []

    def delete_objects(self, **kwargs):
        self.calls.append(kwargs)
        if len(self.calls) in self.explode_on:
            raise ConnectionError("S3에 닿지 못했다")
        errors = [
            {"Key": o["Key"], "Code": "AccessDenied", "Message": "Access Denied"}
            for o in kwargs["Delete"]["Objects"]
            if o["Key"] in self.fail_keys
        ]
        return {"Errors": errors} if errors else {}


def keys_of(call):
    return [o["Key"] for o in call["Delete"]["Objects"]]


def test_the_keys_are_deleted_from_the_bucket_quietly_and_nothing_failed():
    s3 = FakeS3()

    failed = S3RecordingDeleter("sgu-pj-03-nulbom-recordings", client=s3).delete_many(["12-a.wav", "12-b.wav"])

    assert failed == 0
    (call,) = s3.calls
    assert call["Bucket"] == "sgu-pj-03-nulbom-recordings"
    assert keys_of(call) == ["12-a.wav", "12-b.wav"]
    assert call["Delete"]["Quiet"] is True  # 응답에 실패한 것만 온다


def test_many_keys_go_in_batches_of_a_thousand():
    s3 = FakeS3()
    keys = [f"12-{n}.wav" for n in range(2500)]

    assert S3RecordingDeleter("b", client=s3).delete_many(keys) == 0

    assert MAX_KEYS_PER_REQUEST == 1000
    assert [len(keys_of(c)) for c in s3.calls] == [1000, 1000, 500]
    assert [k for c in s3.calls for k in keys_of(c)] == keys


def test_no_keys_means_no_request():
    s3 = FakeS3()

    assert S3RecordingDeleter("b", client=s3).delete_many([]) == 0

    assert s3.calls == []


def test_the_same_key_twice_is_sent_once():
    s3 = FakeS3()

    assert S3RecordingDeleter("b", client=s3).delete_many(["a.wav", "a.wav", "b.wav"]) == 0

    assert keys_of(s3.calls[0]) == ["a.wav", "b.wav"]


def test_keys_the_bucket_refuses_are_counted_as_failed():
    s3 = FakeS3(fail_keys={"12-b.wav"})

    assert S3RecordingDeleter("b", client=s3).delete_many(["12-a.wav", "12-b.wav"]) == 1


def test_a_failed_request_counts_its_whole_batch_and_the_next_batch_still_goes():
    s3 = FakeS3(explode_on={1})
    keys = [f"12-{n}.wav" for n in range(1500)]

    failed = S3RecordingDeleter("b", client=s3).delete_many(keys)

    assert failed == 1000
    assert len(s3.calls) == 2  # 두 번째 묶음은 그대로 보냈다


def test_errors_never_escape_and_keys_never_reach_the_log(caplog):
    s3 = FakeS3(fail_keys={"12-20261001T000000Z-secret.wav"}, explode_on={2})
    keys = ["12-20261001T000000Z-secret.wav"] + [f"12-{n}-hidden.wav" for n in range(1000)]

    with caplog.at_level(logging.DEBUG):
        failed = S3RecordingDeleter("b", client=s3).delete_many(keys)

    assert failed == 1 + 1  # 첫 묶음에서 거절 1개, 둘째 묶음(1개)은 요청이 터졌다
    assert "secret" not in caplog.text and "hidden" not in caplog.text


def test_a_client_that_cannot_be_built_counts_everything_as_failed(monkeypatch):
    broken = types.ModuleType("boto3")

    def client(*args, **kwargs):
        raise RuntimeError("자격 증명이 없다")

    broken.client = client
    monkeypatch.setitem(sys.modules, "boto3", broken)

    assert S3RecordingDeleter("b").delete_many(["a.wav", "b.wav"]) == 2


def test_the_boto3_client_is_built_only_when_deleting_and_in_seoul(monkeypatch):
    """서버가 켜질 때나 운영 도구가 뜰 때는 S3에 아무것도 하지 않는다. 지울 때 처음 만든다."""
    made = []
    fake_s3 = FakeS3()
    fake = types.ModuleType("boto3")

    def client(name, region_name=None):
        made.append((name, region_name))
        return fake_s3

    fake.client = client
    monkeypatch.setitem(sys.modules, "boto3", fake)

    deleter = S3RecordingDeleter("b")
    assert made == []

    deleter.delete_many(["a.wav"])
    deleter.delete_many(["b.wav"])

    assert made == [("s3", "ap-northeast-2")]
    assert len(fake_s3.calls) == 2


# ------------------------------------------------------------ 환경에서 조립


def test_no_bucket_means_no_deleter(monkeypatch):
    monkeypatch.delenv("RECORDINGS_BUCKET", raising=False)

    assert recording_deleter_from_env() is None
    assert recording_deleter_from_env({"RECORDINGS_BUCKET": "  "}) is None


def test_a_bucket_gets_an_s3_deleter_in_seoul_by_default(monkeypatch):
    monkeypatch.setenv("RECORDINGS_BUCKET", "sgu-pj-03-nulbom-recordings")
    monkeypatch.delenv("AWS_REGION", raising=False)

    deleter = recording_deleter_from_env()

    assert isinstance(deleter, S3RecordingDeleter)
    assert deleter.bucket == "sgu-pj-03-nulbom-recordings"
    assert deleter.region == "ap-northeast-2"
    assert recording_deleter_from_env({"RECORDINGS_BUCKET": "b", "AWS_REGION": "us-east-1"}).region == "us-east-1"


def test_app_data_carries_the_deleter_it_was_given():
    from app.api.elder_directory import InMemoryElderDirectory
    from app.api.guardian_auth import InMemoryGuardianKeyStore, KeyAuth
    from app.main import app_data_for

    deleter = S3RecordingDeleter("b", client=FakeS3())
    auth = KeyAuth(InMemoryGuardianKeyStore())

    data, _ = app_data_for(None, guardian_auth=auth, elders=InMemoryElderDirectory(), recording_deleter=deleter)
    plain, _ = app_data_for(None, guardian_auth=auth, elders=InMemoryElderDirectory())

    assert data.recording_deleter is deleter
    assert plain.recording_deleter is None


def test_the_server_builds_no_deleter_without_a_bucket():
    """시험 환경에는 버킷이 없다(conftest가 지운다) — 서버 조립이 진짜 S3 삭제기를 만들지 않는다."""
    import app.main as main

    assert main._app_data.recording_deleter is None
