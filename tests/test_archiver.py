"""녹음 보관기 — 로컬 녹음을 S3로 올리고, 로컬은 정해진 때에 지운다.

**30일 삭제는 어르신께 드린 약속이다.** S3 버킷에는 수명주기 규칙이 걸려
있지만 서버 디스크에는 아무것도 없었다 — 보관기가 붙기 전까지 로컬 녹음은
영원히 남았다. 그래서 30일 규칙은 버킷 설정과 무관하게 항상 돈다.

네트워크를 타지 않는다. 업로더와 시계를 주입받는다.
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path

from app.archiver import (
    DEFAULT_KEEP_LOCAL_SECONDS,
    DEFAULT_MAX_AGE_SECONDS,
    MARKER_SUFFIX,
    RecordingArchiver,
    S3Uploader,
)

NOW = 1_800_000_000.0
HOUR = 3600.0
DAY = 24 * HOUR


class FakeUploader:
    def __init__(self, fail=False, check_ok=True):
        self.fail = fail
        self.check_ok = check_ok
        self.puts: list[tuple[str, bytes]] = []

    def put(self, key: str, path: Path) -> None:
        if self.fail:
            raise RuntimeError("S3 거부")
        self.puts.append((key, path.read_bytes()))

    def check(self) -> None:
        if not self.check_ok:
            raise RuntimeError("AccessDenied")


def recording(directory: Path, name: str, *, age: float) -> Path:
    path = directory / name
    path.write_bytes(b"RIFF....WAVE")
    stamp = NOW - age
    os.utime(path, (stamp, stamp))
    return path


def archiver(directory, uploader, **over):
    return RecordingArchiver(
        directory=directory, uploader=uploader, clock=lambda: NOW, **over
    )


# ------------------------------------------------------------ 올리기


def test_a_new_recording_goes_up_under_its_own_name(tmp_path):
    """S3 키는 파일 이름 그대로다. audio_key가 이미 파일 이름이라,
    DB의 의미가 'S3 객체 키'가 될 뿐 아무것도 안 바뀐다."""
    uploader = FakeUploader()
    wav = recording(tmp_path, "12-20260930T000000Z-abc123.wav", age=10)

    archiver(tmp_path, uploader).sweep()

    assert uploader.puts == [(wav.name, wav.read_bytes())]
    assert (tmp_path / (wav.name + MARKER_SUFFIX)).exists()


def test_an_uploaded_recording_is_not_uploaded_again(tmp_path):
    uploader = FakeUploader()
    recording(tmp_path, "1-a.wav", age=10)
    keeper = archiver(tmp_path, uploader)

    keeper.sweep()
    keeper.sweep()

    assert len(uploader.puts) == 1


def test_a_failed_upload_keeps_the_local_file_and_retries(tmp_path, caplog):
    """못 올렸으면 로컬이 유일한 사본이다. 지우면 녹음이 사라진다."""
    uploader = FakeUploader(fail=True)
    wav = recording(tmp_path, "1-a.wav", age=2 * DAY)

    with caplog.at_level(logging.ERROR, logger="app.archiver"):
        archiver(tmp_path, uploader).sweep()

    assert wav.exists()
    assert not (tmp_path / (wav.name + MARKER_SUFFIX)).exists()
    assert "올리지 못했다" in caplog.text

    uploader.fail = False
    archiver(tmp_path, uploader).sweep()
    assert [key for key, _ in uploader.puts] == [wav.name]


def test_files_that_are_not_recordings_are_left_alone(tmp_path):
    uploader = FakeUploader()
    other = tmp_path / "notes.txt"
    other.write_text("x")
    os.utime(other, (NOW - 40 * DAY, NOW - 40 * DAY))

    archiver(tmp_path, uploader).sweep()

    assert other.exists()
    assert uploader.puts == []


# ------------------------------------------------------------ 로컬 지우기


def test_an_uploaded_recording_stays_local_while_transcription_may_need_it(tmp_path):
    """전사 워커가 이 파일을 읽는다. 아침에 어르신이 몰리면 줄이 몇 시간
    길어질 수 있어서, 올렸다고 바로 지우면 전사가 파일을 못 찾는다."""
    uploader = FakeUploader()
    wav = recording(tmp_path, "1-a.wav", age=DEFAULT_KEEP_LOCAL_SECONDS - HOUR)

    archiver(tmp_path, uploader).sweep()

    assert wav.exists()


def test_an_uploaded_recording_is_removed_locally_after_a_day(tmp_path):
    uploader = FakeUploader()
    wav = recording(tmp_path, "1-a.wav", age=DEFAULT_KEEP_LOCAL_SECONDS + HOUR)
    marker = tmp_path / (wav.name + MARKER_SUFFIX)

    keeper = archiver(tmp_path, uploader)
    keeper.sweep()  # 올리고
    keeper.sweep()  # 지운다

    assert not wav.exists()
    assert not marker.exists()


def test_an_old_recording_that_never_reached_s3_is_still_deleted(tmp_path, caplog):
    """30일은 어르신께 드린 약속이다. 'S3가 고장 나서 못 지켰다'는 변명이
    안 된다. 대신 녹음이 사라진다는 사실을 크게 남긴다."""
    uploader = FakeUploader(fail=True)
    wav = recording(tmp_path, "1-a.wav", age=DEFAULT_MAX_AGE_SECONDS + HOUR)

    with caplog.at_level(logging.ERROR, logger="app.archiver"):
        archiver(tmp_path, uploader).sweep()

    assert not wav.exists()
    assert "S3에 못 간 채" in caplog.text


def test_without_a_bucket_nothing_goes_up_but_thirty_days_still_holds(tmp_path):
    """약속이 환경 변수 하나에 달려 있으면 안 된다. 버킷 설정을 빠뜨려도
    30일 삭제는 지켜진다."""
    young = recording(tmp_path, "1-a.wav", age=2 * DAY)
    old = recording(tmp_path, "2-b.wav", age=DEFAULT_MAX_AGE_SECONDS + HOUR)

    archiver(tmp_path, None).sweep()

    assert young.exists()  # 올린 적이 없으니 24시간 규칙은 안 걸린다
    assert not old.exists()


def test_a_marker_without_its_recording_is_cleaned_up(tmp_path):
    orphan = tmp_path / ("1-a.wav" + MARKER_SUFFIX)
    orphan.write_text("")

    archiver(tmp_path, FakeUploader()).sweep()

    assert not orphan.exists()


def test_a_missing_directory_is_not_an_error(tmp_path):
    """녹음이 한 번도 안 생긴 새 서버에는 폴더가 없다."""
    archiver(tmp_path / "없음", FakeUploader()).sweep()


def test_an_unexpected_error_in_one_file_does_not_stop_the_sweep(tmp_path, caplog):
    """한 파일에서 예상 못 한 오류가 나도 나머지는 처리해야 한다. 특히
    30일 삭제가 앞 파일 하나 때문에 멈추면 안 된다."""

    class Exploding(FakeUploader):
        def put(self, key, path):
            raise TypeError("예상 못 한 오류")

    recording(tmp_path, "1-a.wav", age=10)
    old = recording(tmp_path, "2-b.wav", age=DEFAULT_MAX_AGE_SECONDS + HOUR)

    with caplog.at_level(logging.ERROR, logger="app.archiver"):
        archiver(tmp_path, Exploding()).sweep()

    assert not old.exists()


# ------------------------------------------------------------ 시작할 때 확인


def test_a_broken_bucket_is_said_out_loud_at_startup(tmp_path, caplog):
    """권한이나 버킷 이름이 틀렸을 때 30일 뒤가 아니라 배포하는 그 순간
    알아야 한다. 서버는 멈추지 않는다 — 통화는 녹음 보관과 별개다."""
    keeper = archiver(tmp_path, FakeUploader(check_ok=False), tick_seconds=60)

    with caplog.at_level(logging.ERROR, logger="app.archiver"):
        keeper.start()
    keeper.stop()

    assert "S3에 쓸 수 없다" in caplog.text


def test_without_a_bucket_the_startup_says_so(tmp_path, caplog):
    keeper = archiver(tmp_path, None, tick_seconds=60)

    with caplog.at_level(logging.WARNING, logger="app.archiver"):
        keeper.start()
    keeper.stop()

    assert "버킷이 없다" in caplog.text


def test_start_and_stop_are_idempotent(tmp_path):
    keeper = archiver(tmp_path, FakeUploader(), tick_seconds=60)

    keeper.start()
    keeper.start()
    keeper.stop()
    keeper.stop()


# ------------------------------------------------------------ 루프


def test_notify_uploads_without_waiting_for_the_next_tick(tmp_path):
    """통화가 끝나자마자 올린다. 인스턴스가 죽으면 그 사이 녹음이 사라지니,
    그 창을 몇 초로 줄인다."""
    uploader = FakeUploader()
    keeper = RecordingArchiver(directory=tmp_path, uploader=uploader, tick_seconds=3600)
    keeper.start()
    try:
        time.sleep(0.1)  # 첫 틱이 지나가게 둔다
        wav = tmp_path / "9-z.wav"
        wav.write_bytes(b"RIFF")
        keeper.notify()

        deadline = time.monotonic() + 2.0
        while not uploader.puts and time.monotonic() < deadline:
            time.sleep(0.01)
    finally:
        keeper.stop()

    assert [key for key, _ in uploader.puts] == ["9-z.wav"]


# ------------------------------------------------------------ S3


class FakeS3:
    def __init__(self):
        self.put_calls = []
        self.deleted = []

    def put_object(self, **kwargs):
        body = kwargs.pop("Body")
        kwargs["Body"] = body.read() if hasattr(body, "read") else body
        self.put_calls.append(kwargs)

    def delete_object(self, **kwargs):
        self.deleted.append(kwargs)


def test_s3_upload_is_encrypted_and_typed(tmp_path):
    """어르신 육성이다. 서버 측 암호화를 명시하고, 형식을 wav로 적는다."""
    client = FakeS3()
    wav = tmp_path / "1-a.wav"
    wav.write_bytes(b"RIFFdata")

    S3Uploader(bucket="b", client=client).put("1-a.wav", wav)

    call = client.put_calls[0]
    assert call["Bucket"] == "b"
    assert call["Key"] == "1-a.wav"
    assert call["Body"] == b"RIFFdata"
    assert call["ContentType"] == "audio/wav"
    assert call["ServerSideEncryption"] == "AES256"


def test_the_startup_check_writes_and_removes_a_probe():
    """실제로 한 번 써 봐야 권한을 안다. 읽기만 되고 쓰기가 막힌 경우를
    잡으려면 쓰기를 해야 한다."""
    client = FakeS3()

    S3Uploader(bucket="b", client=client).check()

    assert len(client.put_calls) == 1
    key = client.put_calls[0]["Key"]
    assert key.startswith("_selfcheck/")
    assert client.deleted == [{"Bucket": "b", "Key": key}]


# ------------------------------------------------------------ 환경에서 조립


def test_no_bucket_means_local_only(monkeypatch, tmp_path):
    from app.archiver import archiver_from_env

    monkeypatch.delenv("RECORDINGS_BUCKET", raising=False)

    assert archiver_from_env(tmp_path).uploader is None


def test_a_bucket_gets_an_s3_uploader_in_seoul_by_default(monkeypatch, tmp_path):
    """리전을 환경에 맡기면 개발 PC의 ~/.aws/config를 읽는다. 09-29에 그
    차이로 테스트가 로컬은 통과, EC2는 실패했다. 기본값을 코드에 둔다."""
    from app.archiver import archiver_from_env

    monkeypatch.setenv("RECORDINGS_BUCKET", "sgu-pj-03-nulbom-recordings")
    monkeypatch.delenv("AWS_REGION", raising=False)

    keeper = archiver_from_env(tmp_path)

    assert isinstance(keeper.uploader, S3Uploader)
    assert keeper.uploader.bucket == "sgu-pj-03-nulbom-recordings"
    assert keeper.uploader.region == "ap-northeast-2"


# ------------------------------------------------------------ 반쪽 녹음


def test_a_half_written_recording_is_never_picked_up(tmp_path):
    """wave는 헤더의 길이를 닫을 때 고쳐 쓴다. 쓰는 도중의 파일을 올리면
    헤더가 틀린 반쪽이 S3에 가고, '올림' 표시가 붙어 다시는 안 올린다.
    세션은 .part로 쓰고 이름을 바꾼다 — 보관기는 그 이름을 안 본다."""
    uploader = FakeUploader()
    (tmp_path / "1-a.wav.part").write_bytes(b"RIFF\x00\x00\x00\x00half")

    archiver(tmp_path, uploader).sweep()

    assert uploader.puts == []


def test_the_session_leaves_only_a_finished_recording(tmp_path):
    """세션이 쓰고 나면 .part가 남지 않고, 남은 wav는 온전히 읽힌다."""
    import wave

    from app.media.session import CallSession
    from tests.test_server_wiring import _Beep

    session = CallSession(call_id="7", sample_rate=8000, responder=_Beep())
    session.push_audio(bytes(3200), timestamp_ms=0)  # 무음 1600샘플

    path = session.finish(tmp_path)

    assert list(tmp_path.glob("*.part")) == []
    with wave.open(str(path), "rb") as wav:
        assert wav.getnframes() == 1600


# ------------------------------------------------------------ 조립부 배선


class FakeArchiver:
    def __init__(self):
        self.started = 0
        self.stopped = 0
        self.notified = 0

    def start(self):
        self.started += 1

    def stop(self):
        self.stopped += 1

    def notify(self):
        self.notified += 1


def _server(tmp_path, keeper):
    from app.api.store import InMemoryCallStore
    from app.main import build_server
    from app.telephony.client import FakeTelephony
    from tests.test_server_wiring import _Beep

    store = InMemoryCallStore(phones={12: "070-1111-2222"})
    app = build_server(
        store=store,
        telephony=FakeTelephony(),
        public_base_url="https://api.example.com",
        stream_base_url="wss://api.example.com",
        responder_factory=_Beep,
        recordings_dir=tmp_path,
        archiver=keeper,
    )
    return app, store


def test_the_archiver_starts_with_the_server_not_on_import(tmp_path):
    """import만으로 켜지면 테스트가 개발 PC의 recordings/를 훑고 30일 지난
    파일을 지운다. 서버가 실제로 뜰 때만 켜진다."""
    from fastapi.testclient import TestClient

    keeper = FakeArchiver()
    app, _ = _server(tmp_path, keeper)

    assert keeper.started == 0

    with TestClient(app):
        assert keeper.started == 1

    assert keeper.stopped == 1


def test_a_finished_call_wakes_the_archiver(tmp_path):
    """통화가 끝나면 바로 올리게 깨운다. 다음 틱까지 기다리는 동안
    인스턴스가 죽으면 그 녹음이 사라진다."""
    from fastapi.testclient import TestClient

    from tests.test_server_wiring import place_call, run_stream

    keeper = FakeArchiver()
    app, store = _server(tmp_path, keeper)

    with TestClient(app) as client:
        _, _, token = place_call(client, store)
        run_stream(client, token, frames=5)

    assert keeper.notified == 1


# ------------------------------------------------------------ 전사 원문 30일


def test_old_transcripts_are_purged_with_the_recordings(tmp_path):
    """원문은 녹음을 글로 옮긴 것이라 같은 30일 약속이 걸린다."""
    from app.api.transcript_store import InMemoryTranscriptStore

    saved_at = {"now": NOW - DEFAULT_MAX_AGE_SECONDS - HOUR}
    store = InMemoryTranscriptStore(clock=lambda: saved_at["now"])
    store.save(1, "오래된 통화")
    saved_at["now"] = NOW - HOUR
    store.save(2, "최근 통화")

    archiver(tmp_path, FakeUploader(), transcripts=store).sweep()

    assert store.get(1) is None
    assert store.get(2) == "최근 통화"


def test_transcripts_are_purged_even_before_any_recording_exists(tmp_path):
    """새 서버라 녹음 폴더가 없어도 원문 30일은 지킨다."""
    from app.api.transcript_store import InMemoryTranscriptStore

    store = InMemoryTranscriptStore(clock=lambda: NOW - DEFAULT_MAX_AGE_SECONDS - HOUR)
    store.save(1, "오래된 통화")

    archiver(tmp_path / "없음", None, transcripts=store).sweep()

    assert store.get(1) is None


def test_a_failing_purge_does_not_stop_the_recording_rules(tmp_path, caplog):
    class Broken:
        def purge_older_than(self, cutoff):
            raise RuntimeError("DB 끊김")

    old = recording(tmp_path, "1-a.wav", age=DEFAULT_MAX_AGE_SECONDS + HOUR)

    with caplog.at_level(logging.ERROR, logger="app.archiver"):
        archiver(tmp_path, None, transcripts=Broken()).sweep()

    assert not old.exists()
    assert "전사 원문을 지우지 못했다" in caplog.text
